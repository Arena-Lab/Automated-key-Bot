"""Admin key inventory management handlers"""

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from bson import ObjectId
from datetime import datetime

from bot.keyboards.admin import AdminKeyboards
from bot.states.admin import AdminStates
from bot.filters.admin import IsAdminCallbackFilter, IsAdminFilter
from bot.database.repositories import KeyRepository, AdminLogRepository
from bot.database.connection import Database
from bot.inventory.manager import InventoryManager
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

router = Router()
router.callback_query.filter(IsAdminCallbackFilter())
router.message.filter(IsAdminFilter())


@router.callback_query(F.data == "admin_add_key")
async def admin_add_key_start(callback: types.CallbackQuery):
    """Add keys - guided flow: pick product, then plan, then send keys"""
    db = Database.get_db()
    products = await db.products.find({"status": "active"}).sort("display_order", 1).to_list(length=50)

    if not products:
        await callback.message.answer(
            "❌ No active products. Add a product first.",
            reply_markup=AdminKeyboards.back_button("admin_keys")
        )
        await callback.answer()
        return

    keyboard = [[InlineKeyboardButton(text=p["name"], callback_data=f"addkey_prod_{p['_id']}")]
                for p in products]
    keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_keys")])

    await callback.message.answer(
        "➕ ADD KEYS\n\nStep 1/3: Select a product:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("addkey_prod_"))
async def addkey_select_product(callback: types.CallbackQuery):
    """Show plans for selected product"""
    product_id = callback.data.split("_")[2]
    db = Database.get_db()

    product = await db.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        await callback.answer("Product not found", show_alert=True)
        return

    plans = await db.plans.find({
        "product_id": ObjectId(product_id),
        "status": "active"
    }).to_list(length=50)

    if not plans:
        await callback.message.answer(
            f"❌ No active plans for {product['name']}. Add a plan first.",
            reply_markup=AdminKeyboards.back_button(f"edit_product_{product_id}")
        )
        await callback.answer()
        return

    keyboard = [[InlineKeyboardButton(
        text=f"⏱️ {p['name']} - ₹{p['price']}",
        callback_data=f"addkey_plan_{p['_id']}"
    )] for p in plans]
    keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_add_key")])

    await callback.message.answer(
        f"📦 {product['name']}\n\nStep 2/3: Select a plan:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("addkey_plan_"))
async def addkey_select_plan(callback: types.CallbackQuery, state: FSMContext):
    """Plan selected - ask for key values"""
    plan_id = callback.data.split("_")[2]
    db = Database.get_db()

    plan = await db.plans.find_one({"_id": ObjectId(plan_id)})
    if not plan:
        await callback.answer("Plan not found", show_alert=True)
        return

    product = await db.products.find_one({"_id": plan["product_id"]})

    await state.update_data(key_product_id=str(plan["product_id"]), key_plan_id=plan_id)
    await state.set_state(AdminStates.adding_bulk_keys)

    await callback.message.answer(
        f"📦 {product['name'] if product else '?'} | ⏱️ {plan['name']}\n\n"
        "Step 3/3: Send the keys — one per line (single or multiple):\n\n"
        "KEY-AAAA-1111\nKEY-BBBB-2222\nKEY-CCCC-3333",
        reply_markup=AdminKeyboards.back_button("admin_keys")
    )
    await callback.answer()


@router.message(AdminStates.adding_bulk_keys, F.text)
async def admin_bulk_keys_process(message: types.Message, state: FSMContext):
    """Process keys for the plan selected via inline buttons"""
    data = await state.get_data()
    product_id = data.get("key_product_id")
    plan_id = data.get("key_plan_id")

    if not product_id or not plan_id:
        await state.clear()
        await message.answer("❌ Session expired. Start again from /addkeys.",
                             reply_markup=AdminKeyboards.back_button("admin_keys"))
        return

    key_values = [l.strip() for l in message.text.strip().split("\n") if l.strip()]
    added = 0
    failed = 0

    db = Database.get_db()
    key_repo = KeyRepository(db)

    for kv in key_values:
        try:
            await key_repo.create({
                "product_id": ObjectId(product_id),
                "plan_id": ObjectId(plan_id),
                "key_value": kv.upper(),
                "status": "available",
                "created_at": datetime.utcnow()
            })
            added += 1
        except Exception:
            failed += 1

    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(message.from_user.id),
        telegram_id=message.from_user.id,
        action="add_keys_guided",
        details={"product_id": product_id, "plan_id": plan_id, "added": added, "failed": failed}
    )

    await state.clear()
    await message.answer(
        f"✅ Keys added!\n\nAdded: {added}\nSkipped (duplicates): {failed}",
        reply_markup=AdminKeyboards.back_button("admin_keys")
    )


@router.callback_query(F.data == "admin_bulk_keys")
async def admin_bulk_keys_start(callback: types.CallbackQuery, state: FSMContext):
    """Bulk add keys"""
    await state.set_state(AdminStates.adding_bulk_keys)
    await callback.message.answer(
        "📝 BULK ADD KEYS\n\n"
        "Format (one key per line):\n"
        "product_id plan_id key_value\n\n"
        "Example:\n"
        "68a1b2c3d4e5f6a7b8c9d0e1 68a1b2c3d4e5f6a7b8c9d0e2 KEY-001\n"
        "68a1b2c3d4e5f6a7b8c9d0e1 68a1b2c3d4e5f6a7b8c9d0e2 KEY-002\n\n"
        "Send all keys at once.",
        reply_markup=AdminKeyboards.back_button("admin_keys")
    )
    await callback.answer()


@router.message(AdminStates.adding_bulk_keys, F.text)
async def admin_bulk_keys_process(message: types.Message, state: FSMContext):
    """Process bulk key addition"""
    lines = [l.strip() for l in message.text.strip().split("\n") if l.strip()]
    added = 0
    failed = 0

    db = Database.get_db()
    key_repo = KeyRepository(db)

    for line in lines:
        parts = line.split()
        if len(parts) != 3:
            failed += 1
            continue

        product_id, plan_id, key_value = parts
        try:
            await key_repo.create({
                "product_id": ObjectId(product_id),
                "plan_id": ObjectId(plan_id),
                "key_value": key_value.strip().upper(),
                "status": "available",
                "created_at": datetime.utcnow()
            })
            added += 1
        except Exception:
            failed += 1

    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(message.from_user.id),
        telegram_id=message.from_user.id,
        action="bulk_add_keys",
        details={"added": added, "failed": failed}
    )

    await state.clear()
    await message.answer(
        f"✅ Bulk import complete!\n\n"
        f"Added: {added}\nFailed (duplicates/invalid): {failed}",
        reply_markup=AdminKeyboards.back_button("admin_keys")
    )


@router.callback_query(F.data == "admin_upload_keys")
async def admin_upload_keys_start(callback: types.CallbackQuery, state: FSMContext):
    """Upload keys from TXT/CSV file"""
    await state.set_state(AdminStates.uploading_key_file)
    await callback.message.answer(
        "📁 UPLOAD KEY FILE\n\n"
        "Send a .txt or .csv file with keys.\n"
        "Format per line: product_id,plan_id,key_value",
        reply_markup=AdminKeyboards.back_button("admin_keys")
    )
    await callback.answer()


@router.message(AdminStates.uploading_key_file, F.document)
async def admin_upload_keys_process(message: types.Message, state: FSMContext):
    """Process uploaded key file"""
    doc = message.document
    file_name = doc.file_name.lower()

    if not (file_name.endswith(".txt") or file_name.endswith(".csv")):
        await message.answer("❌ Please upload a .txt or .csv file.")
        return

    # Download file
    file = await message.bot.get_file(doc.file_id)
    file_content = await message.bot.download_file(file.file_path)
    content = file_content.read().decode("utf-8", errors="ignore")

    added = 0
    failed = 0
    db = Database.get_db()
    key_repo = KeyRepository(db)

    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Support both comma and space separated
        parts = line.replace(",", " ").split()
        if len(parts) != 3:
            failed += 1
            continue

        product_id, plan_id, key_value = parts
        try:
            await key_repo.create({
                "product_id": ObjectId(product_id),
                "plan_id": ObjectId(plan_id),
                "key_value": key_value.strip().upper(),
                "status": "available",
                "created_at": datetime.utcnow()
            })
            added += 1
        except Exception:
            failed += 1

    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(message.from_user.id),
        telegram_id=message.from_user.id,
        action="upload_key_file",
        details={"added": added, "failed": failed, "file": doc.file_name}
    )

    await state.clear()
    await message.answer(
        f"✅ File processed!\n\nAdded: {added}\nFailed: {failed}",
        reply_markup=AdminKeyboards.back_button("admin_keys")
    )


@router.callback_query(F.data == "admin_search_keys")
async def admin_search_keys_start(callback: types.CallbackQuery, state: FSMContext):
    """Search keys"""
    await state.set_state(AdminStates.searching_keys)
    await state.update_data(delete_mode=False)
    await callback.message.answer(
        "🔍 SEARCH KEYS\n\n"
        "Send search term (key value partial match):",
        reply_markup=AdminKeyboards.back_button("admin_keys")
    )
    await callback.answer()


@router.message(AdminStates.searching_keys, F.text)
async def admin_keys_search_or_delete(message: types.Message, state: FSMContext):
    """Handle key search or deletion based on mode"""
    data = await state.get_data()
    term = message.text.strip()
    delete_mode = data.get("delete_mode", False)
    await state.clear()
    db = Database.get_db()

    if delete_mode:
        key_values = [l.strip().upper() for l in term.split("\n") if l.strip()]
        deleted = 0
        for kv in key_values:
            result = await db.keys.delete_one({"key_value": kv, "status": "available"})
            deleted += result.deleted_count

        admin_log = AdminLogRepository(db)
        await admin_log.log_action(
            admin_id=str(message.from_user.id),
            telegram_id=message.from_user.id,
            action="delete_keys",
            details={"requested": len(key_values), "deleted": deleted}
        )

        await message.answer(
            f"✅ Deleted {deleted} available keys (requested: {len(key_values)}).\n"
            "Only 'available' keys can be deleted.",
            reply_markup=AdminKeyboards.back_button("admin_keys")
        )
        return

    # Search mode
    keys = await db.keys.find(
        {"key_value": {"$regex": term, "$options": "i"}}
    ).limit(20).to_list(length=20)

    if not keys:
        await message.answer("No keys found.", reply_markup=AdminKeyboards.back_button("admin_keys"))
        return

    result = f"🔍 KEYS MATCHING '{term}'\n\n"
    for k in keys:
        result += f"• {k['key_value']} [{k['status']}]\n"
    await message.answer(result, reply_markup=AdminKeyboards.back_button("admin_keys"))


@router.callback_query(F.data == "admin_delete_keys")
async def admin_delete_keys_start(callback: types.CallbackQuery, state: FSMContext):
    """Delete keys - enter key IDs or values"""
    await state.set_state(AdminStates.searching_keys)
    await state.update_data(delete_mode=True)
    await callback.message.answer(
        "🗑️ DELETE KEYS\n\n"
        "Send key values to delete (one per line):",
        reply_markup=AdminKeyboards.back_button("admin_keys")
    )
    await callback.answer()


@router.message(F.text.regexp(r"^/searchkeys\s+(.+)$"))
async def cmd_search_keys(message: types.Message):
    """Search keys by value"""
    term = message.text.split(None, 1)[1]
    db = Database.get_db()
    keys = await db.keys.find(
        {"key_value": {"$regex": term, "$options": "i"}}
    ).limit(20).to_list(length=20)

    if not keys:
        await message.answer("No keys found.")
        return

    result = f"🔍 KEYS MATCHING '{term}'\n\n"
    for k in keys:
        result += f"• {k['key_value']} [{k['status']}]\n"
    await message.answer(result)


@router.message(F.text == "/addkeys")
async def cmd_add_keys(message: types.Message):
    """Quick command to show key management"""
    await message.answer(
        "🔑 KEY MANAGEMENT\n\nSelect an option:",
        reply_markup=AdminKeyboards.key_management()
    )


@router.message(F.text == "/inventory")
async def cmd_inventory(message: types.Message):
    """Show detailed inventory"""
    db = Database.get_db()
    inventory_manager = InventoryManager(KeyRepository(db))
    inventory = await inventory_manager.get_all_inventory()

    if not inventory:
        await message.answer("Inventory is empty.")
        return

    # Enrich with product/plan names
    message_text = "🔑 INVENTORY STATUS\n\n"
    for item in inventory[:30]:
        product = await db.products.find_one({"_id": item["_id"]["product_id"]})
        plan = await db.plans.find_one({"_id": item["_id"]["plan_id"]})
        pname = product["name"] if product else "?"
        planname = plan["name"] if plan else "?"
        message_text += (
            f"📦 {pname} | ⏱️ {planname}\n"
            f"   Available: {item.get('available', 0)} | "
            f"Sold: {item.get('sold', 0)} | Reserved: {item.get('reserved', 0)}\n\n"
        )

    await message.answer(message_text)
