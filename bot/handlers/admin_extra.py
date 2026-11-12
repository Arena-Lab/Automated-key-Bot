"""Admin extra handlers - orders, customers, payments, broadcast, settings, files, admins"""

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from bson import ObjectId
from datetime import datetime, timedelta

from bot.keyboards.admin import AdminKeyboards
from bot.states.admin import AdminStates
from bot.filters.admin import IsAdminCallbackFilter, IsAdminFilter
from bot.database.repositories import (
    OrderRepository, PaymentRepository, UserRepository,
    SettingRepository, KeyRepository, AdminLogRepository,
    BroadcastRepository
)
from bot.database.connection import Database
from bot.services.order_service import OrderService
from bot.services.payment_service import PaymentService
from bot.delivery.sender import DeliverySender
from bot.inventory.allocator import KeyAllocator
from config import Config
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

router = Router()
router.callback_query.filter(IsAdminCallbackFilter())
router.message.filter(IsAdminFilter())


def ikb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ==================== ORDERS ====================

@router.callback_query(F.data == "admin_list_orders")
async def admin_list_orders(callback: types.CallbackQuery):
    """List recent orders"""
    db = Database.get_db()
    orders = await db.orders.find({}).sort("created_at", -1).limit(20).to_list(length=20)

    if not orders:
        await callback.message.answer(
            "📦 No orders found.",
            reply_markup=AdminKeyboards.back_button("admin_orders")
        )
        await callback.answer()
        return

    message = "📦 RECENT ORDERS\n\n"
    keyboard = []
    for o in orders:
        status_icon = {"pending": "⏳", "paid": "💰", "delivered": "✅", "cancelled": "❌"}.get(o["status"], "❓")
        message += f"{status_icon} {o['order_id']} | ₹{o['amount']} | {o['status']}\n"
        keyboard.append([InlineKeyboardButton(
            text=f"🔍 {o['order_id']}",
            callback_data=f"admin_order_detail_{o['_id']}"
        )])

    keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_orders")])
    await callback.message.answer(message, reply_markup=ikb(keyboard))
    await callback.answer()


@router.callback_query(F.data == "admin_search_order")
async def admin_search_order(callback: types.CallbackQuery, state: FSMContext):
    """Search order by ID"""
    await state.set_state(AdminStates.searching_orders)
    await callback.message.answer(
        "🔍 SEARCH ORDER\n\nSend Order ID (e.g., KS2401010001) or Telegram ID:",
        reply_markup=AdminKeyboards.back_button("admin_orders")
    )
    await callback.answer()


@router.callback_query(F.data == "admin_completed_orders")
async def admin_completed_orders(callback: types.CallbackQuery):
    """List completed orders"""
    db = Database.get_db()
    orders = await db.orders.find(
        {"status": {"$in": ["paid", "delivered"]}}
    ).sort("created_at", -1).limit(20).to_list(length=20)

    if not orders:
        await callback.message.answer(
            "✅ No completed orders.",
            reply_markup=AdminKeyboards.back_button("admin_orders")
        )
        await callback.answer()
        return

    message = "✅ COMPLETED ORDERS\n\n"
    for o in orders:
        message += f"🆔 {o['order_id']} | ₹{o['amount']} | {o['status']}\n"

    await callback.message.answer(
        message,
        reply_markup=AdminKeyboards.back_button("admin_orders")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_order_detail_"))
async def admin_order_detail(callback: types.CallbackQuery):
    """Show order details"""
    order_id = callback.data.split("_")[3]
    db = Database.get_db()

    order = await db.orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        await callback.answer("Order not found", show_alert=True)
        return

    product = await db.products.find_one({"_id": order["product_id"]})
    plan = await db.plans.find_one({"_id": order["plan_id"]})
    user = await db.users.find_one({"_id": order["user_id"]})
    payment = await db.payments.find_one({"order_id": order["_id"]})

    message = (
        f"📦 ORDER DETAILS\n\n"
        f"🆔 Order ID: {order['order_id']}\n"
        f"👤 Customer: @{user.get('username', 'N/A')} (ID: {user['telegram_id']})\n"
        f"📦 Product: {product['name'] if product else '?'}\n"
        f"⏱️ Plan: {plan['name'] if plan else '?'}\n"
        f"💰 Amount: ₹{order['amount']}\n"
        f"📊 Status: {order['status'].upper()}\n"
        f"💳 Payment: {payment['status'] if payment else 'N/A'}\n"
        f"🔢 UTR: {payment.get('utr', 'N/A') if payment else 'N/A'}\n"
        f"🔑 Key: {order.get('key_value', 'N/A')}\n"
        f"📅 Created: {order['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
    )

    keyboard = []
    if order.get("key_value"):
        keyboard.append([InlineKeyboardButton(
            text="🔑 Resend Key",
            callback_data=f"admin_resend_key_{order['_id']}"
        )])
    keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_list_orders")])

    await callback.message.answer(message, reply_markup=ikb(keyboard))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_resend_key_"))
async def admin_resend_key(callback: types.CallbackQuery):
    """Resend key to customer"""
    order_oid = callback.data.split("_")[3]
    db = Database.get_db()

    order = await db.orders.find_one({"_id": ObjectId(order_oid)})
    if not order or not order.get("key_value"):
        await callback.answer("No key found for this order", show_alert=True)
        return

    product = await db.products.find_one({"_id": order["product_id"]})
    plan = await db.plans.find_one({"_id": order["plan_id"]})

    delivery = DeliverySender(callback.bot)
    await delivery.resend_key(
        telegram_id=order["telegram_id"],
        product=product,
        plan=plan,
        order=order,
        key_value=order["key_value"]
    )

    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(callback.from_user.id),
        telegram_id=callback.from_user.id,
        action="resend_key",
        entity_type="order",
        entity_id=order_oid
    )

    await callback.answer("✅ Key resent to customer", show_alert=True)


@router.message(AdminStates.searching_orders, F.text)
async def admin_order_search_process(message: types.Message, state: FSMContext):
    """Process order/telegram ID search"""
    term = message.text.strip()
    data = await state.get_data()
    await state.clear()
    db = Database.get_db()

    order = await db.orders.find_one({"order_id": term})
    if not order:
        # Try as telegram_id
        try:
            tid = int(term)
            order = await db.orders.find_one({"telegram_id": tid}, sort=[("created_at", -1)])
        except ValueError:
            pass

    if not order:
        await message.answer("❌ Order not found.", reply_markup=AdminKeyboards.back_button("admin_orders"))
        return

    product = await db.products.find_one({"_id": order["product_id"]})
    plan = await db.plans.find_one({"_id": order["plan_id"]})
    user = await db.users.find_one({"_id": order["user_id"]})

    text = (
        f"📦 ORDER: {order['order_id']}\n\n"
        f"👤 @{user.get('username', 'N/A')} | {user['telegram_id']}\n"
        f"📦 {product['name'] if product else '?'} - {plan['name'] if plan else '?'}\n"
        f"💰 ₹{order['amount']} | {order['status'].upper()}\n"
        f"🔑 {order.get('key_value', 'N/A')}"
    )
    await message.answer(text, reply_markup=AdminKeyboards.back_button("admin_orders"))


@router.message(F.text == "/orders")
async def cmd_orders(message: types.Message):
    """Quick orders command"""
    await message.answer(
        "📦 ORDER MANAGEMENT\n\nSelect an option:",
        reply_markup=AdminKeyboards.order_management()
    )


# ==================== CUSTOMERS ====================

@router.callback_query(F.data == "admin_customers")
async def admin_customers(callback: types.CallbackQuery):
    """Customer management menu"""
    db = Database.get_db()
    total = await db.users.count_documents({})
    blocked = await db.users.count_documents({"is_blocked": True})
    resellers = await db.users.count_documents({"is_reseller": True})

    message = (
        f"👥 CUSTOMER MANAGEMENT\n\n"
        f"Total users: {total}\n"
        f"Blocked: {blocked}\n"
        f"Resellers: {resellers}\n\n"
        f"Use /users to list recent users or /user <telegram_id> for details."
    )
    await callback.message.answer(message, reply_markup=AdminKeyboards.back_button())
    await callback.answer()


@router.message(F.text == "/users")
async def cmd_users(message: types.Message):
    """List recent users"""
    db = Database.get_db()
    users = await db.users.find({}).sort("created_at", -1).limit(15).to_list(length=15)

    if not users:
        await message.answer("No users found.")
        return

    text = "👥 RECENT USERS\n\n"
    for u in users:
        flags = []
        if u.get("is_admin"): flags.append("ADMIN")
        if u.get("is_blocked"): flags.append("BLOCKED")
        if u.get("is_reseller"): flags.append("RESELLER")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        text += f"• @{u.get('username', 'N/A')} | {u['telegram_id']} | Orders: {u.get('total_orders', 0)}{flag_str}\n"

    await message.answer(text)


@router.message(F.text.regexp(r"^/user\s+(\d+)$"))
async def cmd_user_detail(message: types.Message):
    """User detail by telegram id"""
    tid = int(message.text.split()[1])
    db = Database.get_db()
    user = await db.users.find_one({"telegram_id": tid})

    if not user:
        await message.answer("User not found.")
        return

    orders = await db.orders.find({"user_id": user["_id"]}).to_list(length=100)
    revenue = sum(o.get("amount", 0) for o in orders if o["status"] == "delivered")

    text = (
        f"👤 USER PROFILE\n\n"
        f"Name: {user.get('first_name', '')} {user.get('last_name', '')}\n"
        f"Username: @{user.get('username', 'N/A')}\n"
        f"Telegram ID: {user['telegram_id']}\n"
        f"Total Orders: {user.get('total_orders', 0)}\n"
        f"Total Spending: ₹{user.get('total_spending', 0):.2f}\n"
        f"Delivered Revenue: ₹{revenue:.2f}\n"
        f"Blocked: {user.get('is_blocked', False)}\n"
        f"Reseller: {user.get('is_reseller', False)}"
    )
    await message.answer(text)


@router.message(F.text.regexp(r"^/(block|unblock)\s+(\d+)$"))
async def cmd_block_user(message: types.Message):
    """Block/unblock user"""
    parts = message.text.split()
    action, tid = parts[0][1:], int(parts[1])
    db = Database.get_db()

    user = await db.users.find_one({"telegram_id": tid})
    if not user:
        await message.answer("User not found.")
        return

    blocked = action == "block"
    await db.users.update_one(
        {"telegram_id": tid},
        {"$set": {"is_blocked": blocked, "updated_at": datetime.utcnow()}}
    )
    await message.answer(f"✅ User {'blocked' if blocked else 'unblocked'}.")


# ==================== PAYMENT MANAGEMENT ====================

@router.callback_query(F.data == "admin_change_payment_mode")
async def admin_change_payment_mode(callback: types.CallbackQuery):
    """Show payment mode selection"""
    settings_repo = SettingRepository(Database.get_db())
    current = await settings_repo.get("current_payment_mode", Config.PAYMENT_MODE)
    await callback.message.answer(
        f"💰 PAYMENT MODE\n\nCurrent: {current.upper()}\n\nSelect new mode:",
        reply_markup=AdminKeyboards.payment_mode_selection(current)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_payment_mode_"))
async def set_payment_mode(callback: types.CallbackQuery):
    """Set payment mode"""
    mode = callback.data.split("_")[-1]
    settings_repo = SettingRepository(Database.get_db())
    await settings_repo.set("current_payment_mode", mode, "Current payment mode")

    admin_log = AdminLogRepository(Database.get_db())
    await admin_log.log_action(
        admin_id=str(callback.from_user.id),
        telegram_id=callback.from_user.id,
        action="change_payment_mode",
        details={"mode": mode}
    )

    await callback.answer(f"✅ Payment mode set to {mode.upper()}", show_alert=True)
    await callback.message.answer(
        "💰 PAYMENT MANAGEMENT\n\nSelect an option:",
        reply_markup=AdminKeyboards.payment_management()
    )


@router.callback_query(F.data == "admin_update_upi")
async def admin_update_upi(callback: types.CallbackQuery, state: FSMContext):
    """Update UPI ID"""
    await state.set_state(AdminStates.editing_upi_id)
    await callback.message.answer(
        "💳 UPDATE UPI DETAILS\n\nSend new UPI ID (e.g., shop@upi):",
        reply_markup=AdminKeyboards.back_button("admin_payments")
    )
    await callback.answer()


@router.message(AdminStates.editing_upi_id, F.text)
async def process_upi_id(message: types.Message, state: FSMContext):
    """Save new UPI ID"""
    upi = message.text.strip()
    settings_repo = SettingRepository(Database.get_db())
    await settings_repo.set("upi_id", upi, "UPI ID for payments")
    await state.clear()
    await message.answer(f"✅ UPI ID updated to {upi}",
                         reply_markup=AdminKeyboards.back_button("admin_payments"))


@router.callback_query(F.data == "admin_update_qr")
async def admin_update_qr(callback: types.CallbackQuery, state: FSMContext):
    """Update QR code"""
    await state.set_state(AdminStates.editing_qr_code)
    await callback.message.answer(
        "🖼️ UPDATE QR CODE\n\nSend the new QR code image (photo):",
        reply_markup=AdminKeyboards.back_button("admin_payments")
    )
    await callback.answer()


@router.message(AdminStates.editing_qr_code, F.photo)
async def process_qr_code(message: types.Message, state: FSMContext):
    """Save new QR code"""
    file_id = message.photo[-1].file_id
    settings_repo = SettingRepository(Database.get_db())
    await settings_repo.set("qr_code_file_id", file_id, "Payment QR code")
    await state.clear()
    await message.answer("✅ QR code updated!",
                         reply_markup=AdminKeyboards.back_button("admin_payments"))


@router.callback_query(F.data == "admin_payment_settings")
async def admin_payment_settings(callback: types.CallbackQuery):
    """Show payment settings"""
    settings_repo = SettingRepository(Database.get_db())
    upi = await settings_repo.get("upi_id", "Not set")
    payee = await settings_repo.get("payee_name", "Not set")
    mode = await settings_repo.get("current_payment_mode", "manual")
    validity = Config.PAYMENT_VALIDITY_MINUTES

    message = (
        f"⚙️ PAYMENT SETTINGS\n\n"
        f"Mode: {mode.upper()}\n"
        f"UPI ID: {upi}\n"
        f"Payee: {payee}\n"
        f"Validity: {validity} minutes\n"
        f"Verification Group: {Config.PAYMENT_VERIFICATION_GROUP_ID or 'Not set'}"
    )
    await callback.message.answer(message, reply_markup=AdminKeyboards.back_button("admin_payments"))
    await callback.answer()


@router.message(F.text == "/payment")
async def cmd_payment(message: types.Message):
    """Payment management command"""
    settings_repo = SettingRepository(Database.get_db())
    mode = await settings_repo.get("current_payment_mode", Config.PAYMENT_MODE)
    upi = await settings_repo.get("upi_id", "Not set")

    text = (
        f"💰 PAYMENT MANAGEMENT\n\n"
        f"Current Mode: {mode.upper()}\n"
        f"UPI ID: {upi}\n\n"
        f"Select an option:"
    )
    await message.answer(text, reply_markup=AdminKeyboards.payment_management())


# ==================== BROADCAST ====================

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    """Start broadcast"""
    keyboard = ikb([
        [InlineKeyboardButton(text="📝 Text Message", callback_data="bc_text")],
        [InlineKeyboardButton(text="🖼️ Photo", callback_data="bc_photo")],
        [InlineKeyboardButton(text="🎬 Video", callback_data="bc_video")],
        [InlineKeyboardButton(text="📄 Document", callback_data="bc_document")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_dashboard")]
    ])
    await callback.message.answer(
        "📢 BROADCAST\n\nSelect message type:",
        reply_markup=keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bc_"))
async def bc_type_selected(callback: types.CallbackQuery, state: FSMContext):
    """Broadcast type selected"""
    msg_type = callback.data.split("_")[1]
    await state.update_data(broadcast_type=msg_type)

    if msg_type == "text":
        await state.set_state(AdminStates.broadcast_content)
        await callback.message.answer(
            "📝 Send the broadcast text message:\n\n"
            "HTML formatting supported. You can also include buttons using format:\n"
            "Text | button_text | https://url",
            reply_markup=AdminKeyboards.back_button("admin_dashboard")
        )
    else:
        await state.set_state(AdminStates.broadcast_file)
        type_names = {"photo": "photo", "video": "video", "document": "document"}
        await callback.message.answer(
            f"📤 Send the {type_names.get(msg_type, msg_type)} to broadcast:",
            reply_markup=AdminKeyboards.back_button("admin_dashboard")
        )
    await callback.answer()


@router.message(AdminStates.broadcast_content, F.text)
async def bc_text_process(message: types.Message, state: FSMContext):
    """Process text broadcast"""
    data = await state.get_data()
    await state.clear()
    await execute_broadcast(message.bot, message, data.get("broadcast_type", "text"), text=message.text)


@router.message(AdminStates.broadcast_file, F.photo | F.video | F.document)
async def bc_file_process(message: types.Message, state: FSMContext):
    """Process file broadcast"""
    data = await state.get_data()
    await state.clear()

    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        media_type = "video"
    else:
        file_id = message.document.file_id
        media_type = "document"

    caption = message.caption or ""
    await execute_broadcast(
        message.bot, message, media_type,
        file_id=file_id, caption=caption
    )


async def execute_broadcast(bot, admin_message, msg_type, text=None, file_id=None, caption=None):
    """Execute broadcast to all users"""
    db = Database.get_db()
    users = await db.users.find({"is_blocked": {"$ne": True}}).to_list(length=None)

    total = len(users)
    sent = 0
    failed = 0
    blocked = 0

    status_msg = await admin_message.answer(
        f"📢 Broadcasting to {total} users...\n0/{total}"
    )

    for i, user in enumerate(users):
        tid = user["telegram_id"]
        try:
            if msg_type == "text":
                await bot.send_message(tid, text, parse_mode="HTML")
            elif msg_type == "photo":
                await bot.send_photo(tid, file_id, caption=caption)
            elif msg_type == "video":
                await bot.send_video(tid, file_id, caption=caption)
            elif msg_type == "document":
                await bot.send_document(tid, file_id, caption=caption)
            sent += 1
        except Exception as e:
            if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
                blocked += 1
            else:
                failed += 1

        # Rate limiting - send a fresh progress message and remove the old one
        if (i + 1) % 25 == 0:
            new_status = await status_msg.answer(
                f"📢 Broadcasting...\n{i+1}/{total} (sent: {sent})"
            )
            try:
                await status_msg.delete()
            except Exception:
                pass
            status_msg = new_status
            import asyncio
            await asyncio.sleep(Config.BROADCAST_DELAY_SECONDS)

    # Save broadcast record
    admin_user = await db.users.find_one({"telegram_id": admin_message.from_user.id})
    bcast_repo = BroadcastRepository(db)
    await bcast_repo.create({
        "admin_id": admin_user["_id"] if admin_user else None,
        "message_type": msg_type,
        "content": text,
        "file_id": file_id,
        "total_recipients": total,
        "sent_count": sent,
        "failed_count": failed,
        "blocked_count": blocked,
        "status": "completed",
        "created_at": datetime.utcnow(),
        "completed_at": datetime.utcnow()
    })

    await status_msg.answer(
        f"✅ Broadcast complete!\n\n"
        f"Total: {total}\nSent: {sent}\nFailed: {failed}\nBlocked: {blocked}"
    )
    try:
        await status_msg.delete()
    except Exception:
        pass


@router.message(F.text == "/broadcast")
async def cmd_broadcast(message: types.Message):
    """Broadcast command shortcut"""
    await message.answer("📢 BROADCAST - select type:", reply_markup=ikb([
        [InlineKeyboardButton(text="📝 Text", callback_data="bc_text")],
        [InlineKeyboardButton(text="🖼️ Photo", callback_data="bc_photo")],
        [InlineKeyboardButton(text="🎬 Video", callback_data="bc_video")],
        [InlineKeyboardButton(text="📄 Document", callback_data="bc_document")],
    ]))


# ==================== SETTINGS ====================

@router.callback_query(F.data == "admin_shop_name")
async def admin_shop_name(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.editing_shop_name)
    await state.update_data(setting_key="shop_name")
    await callback.message.answer("✏️ Enter new shop name:",
                                     reply_markup=AdminKeyboards.back_button("admin_settings"))
    await callback.answer()


@router.message(AdminStates.editing_shop_name, F.text)
async def process_shop_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    setting_key = data.get("setting_key", "shop_name")
    settings_repo = SettingRepository(Database.get_db())
    await settings_repo.set(setting_key, message.text.strip(), f"Setting {setting_key}")
    await state.clear()
    await message.answer("✅ Setting updated!", reply_markup=AdminKeyboards.back_button("admin_settings"))


@router.callback_query(F.data == "admin_welcome")
async def admin_welcome(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.editing_welcome_message)
    await callback.message.answer(
        "📝 Enter new welcome message (HTML supported):",
        reply_markup=AdminKeyboards.back_button("admin_settings")
    )
    await callback.answer()


@router.message(AdminStates.editing_welcome_message, F.text)
async def process_welcome(message: types.Message, state: FSMContext):
    settings_repo = SettingRepository(Database.get_db())
    await settings_repo.set("welcome_message", message.text, "Welcome message")
    await state.clear()
    await message.answer("✅ Welcome message updated!", reply_markup=AdminKeyboards.back_button("admin_settings"))


@router.callback_query(F.data == "admin_channel")
async def admin_channel(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.editing_shop_name)  # reuse
    await state.update_data(setting_key="official_channel")
    await callback.message.answer("📢 Enter official channel (@channel):",
                                     reply_markup=AdminKeyboards.back_button("admin_settings"))
    await callback.answer()


@router.callback_query(F.data == "admin_support")
async def admin_support(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.editing_shop_name)
    await state.update_data(setting_key="support_username")
    await callback.message.answer("💬 Enter support username (@support):",
                                     reply_markup=AdminKeyboards.back_button("admin_settings"))
    await callback.answer()


@router.callback_query(F.data == "admin_reseller_toggle")
async def admin_reseller_toggle(callback: types.CallbackQuery):
    settings_repo = SettingRepository(Database.get_db())
    current = await settings_repo.get("reseller_system_enabled", False)
    new_val = not current
    await settings_repo.set("reseller_system_enabled", new_val, "Reseller system toggle")
    await callback.answer(f"Reseller system {'ENABLED' if new_val else 'DISABLED'}", show_alert=True)
    await callback.message.answer(
        "⚙️ BOT SETTINGS\n\nSelect an option:",
        reply_markup=AdminKeyboards.bot_settings()
    )


# ==================== FILES ====================

@router.callback_query(F.data == "admin_files")
async def admin_files(callback: types.CallbackQuery):
    """File management overview"""
    db = Database.get_db()
    products = await db.products.find({
        "$or": [
            {"apk_file_id": {"$exists": True, "$ne": None}},
            {"setup_video_file_id": {"$exists": True, "$ne": None}},
            {"setup_document_file_id": {"$exists": True, "$ne": None}}
        ]
    }).to_list(length=50)

    message = "🎥 FILE MANAGEMENT\n\n"
    keyboard = []
    if not products:
        message += "No files uploaded yet.\n\nEdit a product to upload APK/video/docs."
    else:
        for p in products:
            files = []
            if p.get("apk_file_id"): files.append("APK")
            if p.get("setup_video_file_id"): files.append("Video")
            if p.get("setup_document_file_id"): files.append("Doc")
            message += f"📦 {p['name']}: {', '.join(files)}\n"
            keyboard.append([InlineKeyboardButton(
                text=f"✏️ {p['name']}",
                callback_data=f"edit_product_{p['_id']}"
            )])

    keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="admin_dashboard")])
    await callback.message.answer(message, reply_markup=ikb(keyboard))
    await callback.answer()


# ==================== ADMIN MANAGEMENT ====================

@router.callback_query(F.data == "admin_admins")
async def admin_admins(callback: types.CallbackQuery):
    """Admin management"""
    message = (
        "🛡️ ADMIN MANAGEMENT\n\n"
        f"Current admins (from config): {len(Config.ADMIN_IDS)}\n\n"
        "Admin IDs are configured via ADMIN_IDS env variable.\n"
        "To add admins, update the .env file and restart the bot.\n\n"
        f"Admin IDs: {', '.join(map(str, Config.ADMIN_IDS))}"
    )
    await callback.message.answer(message, reply_markup=AdminKeyboards.back_button())
    await callback.answer()


@router.message(F.text == "/help")
async def cmd_help(message: types.Message):
    """Admin help"""
    help_text = (
        "🤖 ADMIN COMMANDS\n\n"
        "/admin - Open admin panel\n"
        "/stats - View statistics\n"
        "/payment - Payment management\n"
        "/addproduct - Add product (via panel)\n"
        "/addkeys - Key management\n"
        "/inventory - View inventory\n"
        "/orders - Order management\n"
        "/users - List users\n"
        "/user <id> - User details\n"
        "/block <id> /unblock <id> - Block user\n"
        "/broadcast - Send broadcast\n"
        "/searchkeys <term> - Search keys\n"
        "/maintenance - Toggle maintenance (panel)\n"
        "/help - This message"
    )
    await message.answer(help_text)


@router.message(F.text == "/stats")
async def cmd_stats(message: types.Message):
    """Quick stats command"""
    db = Database.get_db()
    total_users = await db.users.count_documents({})
    total_orders = await db.orders.count_documents({})
    delivered = await db.orders.count_documents({"status": "delivered"})
    pending = await db.orders.count_documents({"status": "pending"})

    delivered_orders = await db.orders.find({"status": "delivered"}).to_list(length=None)
    revenue = sum(o.get("amount", 0) for o in delivered_orders)

    text = (
        f"📊 STATISTICS\n\n"
        f"👥 Users: {total_users}\n"
        f"📦 Orders: {total_orders}\n"
        f"✅ Delivered: {delivered}\n"
        f"⏳ Pending: {pending}\n"
        f"💰 Revenue: ₹{revenue:.2f}"
    )
    await message.answer(text)


@router.message(F.text == "/blocked")
async def cmd_blocked(message: types.Message):
    """List all blocked users"""
    db = Database.get_db()
    blocked = await db.users.find({"is_blocked": True}).sort("updated_at", -1).to_list(length=100)

    if not blocked:
        await message.answer("✅ No blocked users.")
        return

    lines = ["🚫 BLOCKED USERS\n"]
    for u in blocked:
        name = u.get("full_name") or u.get("username") or str(u["telegram_id"])
        lines.append(f"• {name} (ID: {u['telegram_id']})")

    lines.append(f"\nTotal: {len(blocked)}")
    await message.answer("\n".join(lines))


@router.message(F.text == "/maintenance")
async def cmd_maintenance(message: types.Message):
    """Toggle maintenance mode"""
    settings_repo = SettingRepository(Database.get_db())
    current = await settings_repo.get("maintenance_mode", False)
    new_val = not current
    await settings_repo.set("maintenance_mode", new_val, "Maintenance mode toggle")
    await message.answer(f"🔧 Maintenance mode {'ENABLED' if new_val else 'DISABLED'}")
