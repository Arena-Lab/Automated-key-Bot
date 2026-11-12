"""Admin product and plan management handlers"""

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bson import ObjectId
from datetime import datetime

from bot.keyboards.admin import AdminKeyboards
from bot.keyboards.customer import CustomerKeyboards
from bot.states.admin import AdminStates
from bot.filters.admin import IsAdminCallbackFilter, IsAdminFilter
from bot.database.repositories import (
    ProductRepository, PlanRepository, AdminLogRepository
)
from bot.database.connection import Database
from bot.utils.validators import is_valid_price, is_valid_duration, sanitize_product_name
from config import Config

router = Router()
router.callback_query.filter(IsAdminCallbackFilter())
router.message.filter(IsAdminFilter())


# ---------------- Product Listing ----------------

@router.callback_query(F.data == "admin_list_products")
async def admin_list_products(callback: types.CallbackQuery):
    """List all products"""
    db = Database.get_db()
    products = await db.products.find({}).sort("display_order", 1).to_list(length=100)

    if not products:
        await callback.message.answer(
            "📋 No products found.",
            reply_markup=AdminKeyboards.back_button("admin_products")
        )
        await callback.answer()
        return

    message = "📋 ALL PRODUCTS\n\n"
    keyboard = []
    for p in products:
        status_icon = "🟢" if p.get("status") == "active" else "🔴"
        message += f"{status_icon} {p['name']} (Order: {p.get('display_order', 0)})\n"
        keyboard.append([
            InlineKeyboardButton(
                text=f"✏️ Edit {p['name']}",
                callback_data=f"edit_product_{p['_id']}"
            ),
            InlineKeyboardButton(
                text="🗑️",
                callback_data=f"del_product_{p['_id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton(
        text="🔙 Back", callback_data="admin_products"
    )])

    from aiogram.types import InlineKeyboardMarkup
    await callback.message.answer(
        message,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_edit_product")
async def admin_edit_product(callback: types.CallbackQuery):
    """Edit product - redirect to product list"""
    await admin_list_products(callback)


# ---------------- Add Product ----------------

@router.callback_query(F.data == "admin_add_product")
async def admin_add_product(callback: types.CallbackQuery, state: FSMContext):
    """Start adding a new product"""
    await state.set_state(AdminStates.adding_product_name)
    await callback.message.answer(
        "➕ ADD NEW PRODUCT\n\n"
        "Step 1/4: Enter the product name:",
        reply_markup=AdminKeyboards.back_button("admin_products")
    )
    await callback.answer()


@router.message(AdminStates.adding_product_name, F.text)
async def add_product_name(message: types.Message, state: FSMContext):
    """Receive product name"""
    name = sanitize_product_name(message.text)
    if not name:
        await message.answer("❌ Invalid name. Must be 2-100 characters.")
        return

    # Check duplicate
    db = Database.get_db()
    existing = await db.products.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
    if existing:
        await message.answer("❌ A product with this name already exists.")
        return

    await state.update_data(product_name=name)
    await state.set_state(AdminStates.adding_product_description)
    await message.answer("Step 2/4: Enter product description:")


@router.message(AdminStates.adding_product_description, F.text)
async def add_product_description(message: types.Message, state: FSMContext):
    """Receive product description"""
    await state.update_data(product_description=message.text.strip())
    await state.set_state(AdminStates.adding_product_image)
    await message.answer(
        "Step 3/4: Send a product image (photo), or send '-' to skip:"
    )


@router.message(AdminStates.adding_product_image, F.photo)
async def add_product_image(message: types.Message, state: FSMContext):
    """Receive product image"""
    file_id = message.photo[-1].file_id
    await state.update_data(product_image=file_id)
    await finish_add_product(message, state)


@router.message(AdminStates.adding_product_image, F.text == "-")
async def add_product_no_image(message: types.Message, state: FSMContext):
    """Skip product image"""
    await finish_add_product(message, state)


@router.message(AdminStates.adding_product_image)
async def add_product_image_invalid(message: types.Message):
    """Invalid image input"""
    await message.answer("❌ Please send a photo or '-' to skip.")


async def finish_add_product(message: types.Message, state: FSMContext):
    """Complete product creation"""
    data = await state.get_data()

    db = Database.get_db()
    # Get next display order
    max_order = await db.products.find_one(
        {}, sort=[("display_order", -1)]
    )
    next_order = (max_order.get("display_order", 0) + 1) if max_order else 1

    product_data = {
        "name": data["product_name"],
        "description": data.get("product_description", ""),
        "image_file_id": data.get("product_image"),
        "status": "active",
        "display_order": next_order,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    result = await db.products.insert_one(product_data)
    product_id = result.inserted_id

    # Log admin action
    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(message.from_user.id),
        telegram_id=message.from_user.id,
        action="add_product",
        entity_type="product",
        entity_id=str(product_id),
        details={"name": product_data["name"]}
    )

    await state.clear()
    await message.answer(
        f"✅ Product '{product_data['name']}' created successfully!\n\n"
        f"Now add subscription plans for this product.\n"
        f"Product ID: {product_id}",
        reply_markup=AdminKeyboards.back_button("admin_products")
    )


# ---------------- Edit Product ----------------

@router.callback_query(F.data.startswith("edit_product_"))
async def edit_product_select(callback: types.CallbackQuery, state: FSMContext):
    """Select product to edit"""
    product_id = callback.data.split("_")[2]

    db = Database.get_db()
    product = await db.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        await callback.answer("Product not found", show_alert=True)
        return

    # Show edit options
    keyboard = [
        [InlineKeyboardButton(
            text="✏️ Edit Name", callback_data=f"ep_name_{product_id}"
        )],
        [InlineKeyboardButton(
            text="📝 Edit Description", callback_data=f"ep_desc_{product_id}"
        )],
        [InlineKeyboardButton(
            text="🖼️ Change Image", callback_data=f"ep_image_{product_id}"
        )],
        [InlineKeyboardButton(
            text="⏱️ Manage Plans", callback_data=f"ep_plans_{product_id}"
        )],
        [InlineKeyboardButton(
            text="📱 Upload APK", callback_data=f"ep_apk_{product_id}"
        )],
        [InlineKeyboardButton(
            text="🎥 Upload Setup Video", callback_data=f"ep_video_{product_id}"
        )],
        [InlineKeyboardButton(
            text="📖 Edit Instructions", callback_data=f"ep_instr_{product_id}"
        )],
        [InlineKeyboardButton(
            text="🔄 Toggle Status" if product.get("status") == "active" else "🟢 Enable Product",
            callback_data=f"ep_toggle_{product_id}"
        )],
        [InlineKeyboardButton(
            text="🔙 Back", callback_data="admin_list_products"
        )]
    ]

    from aiogram.types import InlineKeyboardMarkup
    await callback.message.answer(
        f"✏️ EDIT PRODUCT\n\n"
        f"📦 Name: {product['name']}\n"
        f"📝 Description: {product.get('description', 'N/A')}\n"
        f"Status: {product.get('status', 'active').upper()}\n"
        f"APK: {'✅' if product.get('apk_file_id') else '❌'} | "
        f"Video: {'✅' if product.get('setup_video_file_id') else '❌'}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


# Product field editors

@router.callback_query(F.data.startswith("ep_name_"))
async def ep_name(callback: types.CallbackQuery, state: FSMContext):
    product_id = callback.data.split("_")[2]
    await state.update_data(edit_product_id=product_id, edit_field="name")
    await state.set_state(AdminStates.editing_product)
    await callback.message.answer(
        "✏️ Enter the new product name:",
        reply_markup=AdminKeyboards.back_button("admin_list_products")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ep_desc_"))
async def ep_desc(callback: types.CallbackQuery, state: FSMContext):
    product_id = callback.data.split("_")[2]
    await state.update_data(edit_product_id=product_id, edit_field="description")
    await state.set_state(AdminStates.editing_product)
    await callback.message.answer(
        "📝 Enter the new product description:",
        reply_markup=AdminKeyboards.back_button("admin_list_products")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ep_instr_"))
async def ep_instr(callback: types.CallbackQuery, state: FSMContext):
    product_id = callback.data.split("_")[2]
    await state.update_data(edit_product_id=product_id, edit_field="delivery_instructions")
    await state.set_state(AdminStates.editing_product)
    await callback.message.answer(
        "📖 Enter the delivery instructions (sent to customer after purchase):",
        reply_markup=AdminKeyboards.back_button("admin_list_products")
    )
    await callback.answer()


@router.message(AdminStates.editing_product, F.text)
async def process_product_edit(message: types.Message, state: FSMContext):
    """Process product field edit"""
    data = await state.get_data()
    product_id = data.get("edit_product_id")
    field = data.get("edit_field")

    if not product_id or not field:
        await state.clear()
        await message.answer("❌ Session expired.")
        return

    # Media fields expect file uploads, not text
    if field in ("image_file_id", "apk_file_id", "setup_video_file_id"):
        await message.answer("❌ Please send the file (photo/document/video) as requested.")
        return

    value = message.text.strip()
    if field == "name":
        value = sanitize_product_name(value)
        if not value:
            await message.answer("❌ Invalid name.")
            return

    db = Database.get_db()
    await db.products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {field: value, "updated_at": datetime.utcnow()}}
    )

    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(message.from_user.id),
        telegram_id=message.from_user.id,
        action="edit_product",
        entity_type="product",
        entity_id=product_id,
        details={"field": field}
    )

    await state.clear()
    await message.answer(
        f"✅ Product {field} updated!",
        reply_markup=AdminKeyboards.back_button("admin_list_products")
    )


# Product image / APK / video upload

@router.callback_query(F.data.startswith("ep_image_"))
async def ep_image(callback: types.CallbackQuery, state: FSMContext):
    product_id = callback.data.split("_")[2]
    await state.update_data(edit_product_id=product_id, edit_field="image_file_id")
    await state.set_state(AdminStates.editing_product)
    await callback.message.answer(
        "🖼️ Send the new product image (photo):",
        reply_markup=AdminKeyboards.back_button("admin_list_products")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ep_apk_"))
async def ep_apk(callback: types.CallbackQuery, state: FSMContext):
    product_id = callback.data.split("_")[2]
    await state.update_data(edit_product_id=product_id, edit_field="apk_file_id")
    await state.set_state(AdminStates.editing_product)
    await callback.message.answer(
        "📱 Send the APK file (document):\n\n"
        "Send /version followed by version number first if needed, e.g. /version 2.1",
        reply_markup=AdminKeyboards.back_button("admin_list_products")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ep_video_"))
async def ep_video(callback: types.CallbackQuery, state: FSMContext):
    product_id = callback.data.split("_")[2]
    await state.update_data(edit_product_id=product_id, edit_field="setup_video_file_id")
    await state.set_state(AdminStates.editing_product)
    await callback.message.answer(
        "🎥 Send the setup tutorial video:",
        reply_markup=AdminKeyboards.back_button("admin_list_products")
    )
    await callback.answer()


@router.message(AdminStates.editing_product, F.photo)
async def process_product_image(message: types.Message, state: FSMContext):
    """Process product image upload"""
    data = await state.get_data()
    if data.get("edit_field") != "image_file_id":
        await message.answer("❌ Unexpected input. Please try again.")
        return

    file_id = message.photo[-1].file_id
    product_id = data["edit_product_id"]
    db = Database.get_db()
    await db.products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"image_file_id": file_id, "updated_at": datetime.utcnow()}}
    )
    await state.clear()
    await message.answer("✅ Product image updated!",
                         reply_markup=AdminKeyboards.back_button("admin_list_products"))


@router.message(AdminStates.editing_product, F.video)
async def process_product_video(message: types.Message, state: FSMContext):
    """Process setup video upload"""
    data = await state.get_data()
    if data.get("edit_field") != "setup_video_file_id":
        await message.answer("❌ Unexpected input. Please try again.")
        return

    file_id = message.video.file_id
    product_id = data["edit_product_id"]
    db = Database.get_db()
    await db.products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"setup_video_file_id": file_id, "updated_at": datetime.utcnow()}}
    )
    await state.clear()
    await message.answer("✅ Setup video updated!",
                         reply_markup=AdminKeyboards.back_button("admin_list_products"))


@router.message(AdminStates.editing_product, F.document)
async def process_product_apk(message: types.Message, state: FSMContext):
    """Process APK document upload"""
    data = await state.get_data()
    if data.get("edit_field") != "apk_file_id":
        await message.answer("❌ Unexpected input. Please try again.")
        return

    file_id = message.document.file_id
    product_id = data["edit_product_id"]
    db = Database.get_db()
    await db.products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {
            "apk_file_id": file_id,
            "apk_version": message.document.file_name,
            "updated_at": datetime.utcnow()
        }}
    )
    await state.clear()
    await message.answer("✅ APK file updated!",
                         reply_markup=AdminKeyboards.back_button("admin_list_products"))


# Toggle product status

@router.callback_query(F.data.startswith("ep_toggle_"))
async def ep_toggle(callback: types.CallbackQuery):
    """Toggle product active/disabled status"""
    product_id = callback.data.split("_")[2]
    db = Database.get_db()

    product = await db.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        await callback.answer("Product not found", show_alert=True)
        return

    new_status = "disabled" if product.get("status") == "active" else "active"
    await db.products.update_one(
        {"_id": ObjectId(product_id)},
        {"$set": {"status": new_status, "updated_at": datetime.utcnow()}}
    )

    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(callback.from_user.id),
        telegram_id=callback.from_user.id,
        action="toggle_product",
        entity_type="product",
        entity_id=product_id,
        details={"new_status": new_status}
    )

    await callback.answer(f"Product {new_status}", show_alert=True)
    # Refresh edit view
    await edit_product_select(callback)


# ---------------- Delete Product ----------------

@router.callback_query(F.data.startswith("del_product_"))
async def del_product_confirm(callback: types.CallbackQuery):
    """Confirm product deletion"""
    product_id = callback.data.split("_")[2]
    db = Database.get_db()

    product = await db.products.find_one({"_id": ObjectId(product_id)})
    if not product:
        await callback.answer("Product not found", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(
            text="✅ Yes, Delete", callback_data=f"confirm_del_product_{product_id}"
        )],
        [InlineKeyboardButton(
            text="❌ Cancel", callback_data="admin_list_products"
        )]
    ]
    from aiogram.types import InlineKeyboardMarkup
    await callback.message.answer(
        f"⚠️ DELETE PRODUCT\n\n"
        f"Are you sure you want to delete '{product['name']}'?\n"
        f"This will NOT delete orders/keys history.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del_product_"))
async def confirm_del_product(callback: types.CallbackQuery):
    """Execute product deletion"""
    product_id = callback.data.split("_")[3]
    db = Database.get_db()

    await db.products.delete_one({"_id": ObjectId(product_id)})
    # Disable related plans
    await db.plans.update_many(
        {"product_id": ObjectId(product_id)},
        {"$set": {"status": "disabled", "updated_at": datetime.utcnow()}}
    )

    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(callback.from_user.id),
        telegram_id=callback.from_user.id,
        action="delete_product",
        entity_type="product",
        entity_id=product_id
    )

    await callback.answer("✅ Product deleted", show_alert=True)
    await admin_list_products(callback)


# ---------------- Plan Management ----------------

async def _render_plans_view(callback: types.CallbackQuery, product_id: str):
    """Render the plans list view for a product"""
    db = Database.get_db()

    product = await db.products.find_one({"_id": ObjectId(product_id)})
    plans = await db.plans.find({"product_id": ObjectId(product_id)}).to_list(length=100)

    if not product:
        await callback.answer("Product not found", show_alert=True)
        return

    message = f"⏱️ PLANS - {product['name']}\n\n"
    keyboard = []

    if not plans:
        message += "No plans yet. Add one below."
    else:
        for plan in plans:
            status_icon = "🟢" if plan.get("status") == "active" else "🔴"
            message += (
                f"{status_icon} {plan['name']} - ₹{plan['price']} "
                f"({plan.get('duration_hours', 0)}h)\n"
                f"   ID: {plan['_id']}\n"
            )
            keyboard.append([
                InlineKeyboardButton(
                    text=f"✏️ {plan['name']}", callback_data=f"edit_plan_{plan['_id']}"
                ),
                InlineKeyboardButton(
                    text="🗑️", callback_data=f"del_plan_{plan['_id']}"
                )
            ])

    keyboard.append([
        InlineKeyboardButton(
            text="➕ Add Plan", callback_data=f"add_plan_{product_id}"
        )
    ])
    keyboard.append([
        InlineKeyboardButton(
            text="🔙 Back", callback_data=f"edit_product_{product_id}"
        )
    ])

    message += (
        f"\n💡 Product ID (for key entry): {product_id}\n"
        "Use 🔑 Manage Keys → Add Key with format: product_id plan_id key_value"
    )

    from aiogram.types import InlineKeyboardMarkup
    await callback.message.answer(
        message,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ep_plans_"))
async def manage_plans(callback: types.CallbackQuery):
    """Show plans for a product"""
    product_id = callback.data.split("_")[2]
    await _render_plans_view(callback, product_id)


@router.callback_query(F.data.startswith("add_plan_"))
async def add_plan_start(callback: types.CallbackQuery, state: FSMContext):
    """Start adding a plan"""
    product_id = callback.data.split("_")[2]
    await state.update_data(plan_product_id=product_id)
    await state.set_state(AdminStates.adding_plan_name)
    await callback.message.answer(
        "➕ ADD PLAN\n\nStep 1/3: Enter plan name (e.g., '12 Hours', '1 Day', 'Monthly'):",
        reply_markup=AdminKeyboards.back_button("admin_list_products")
    )
    await callback.answer()


@router.message(AdminStates.adding_plan_name, F.text)
async def add_plan_name(message: types.Message, state: FSMContext):
    """Receive plan name"""
    name = message.text.strip()
    if not name or len(name) > 50:
        await message.answer("❌ Invalid plan name.")
        return
    await state.update_data(plan_name=name)
    await state.set_state(AdminStates.adding_plan_duration)
    await message.answer("Step 2/3: Enter duration in hours (e.g., 12 for 12 hours, 168 for 7 days):")


@router.message(AdminStates.adding_plan_duration, F.text)
async def add_plan_duration(message: types.Message, state: FSMContext):
    """Receive plan duration"""
    if not is_valid_duration(message.text):
        await message.answer("❌ Invalid duration. Enter a positive number of hours.")
        return
    await state.update_data(plan_duration=int(message.text))
    await state.set_state(AdminStates.adding_plan_price)
    await message.answer("Step 3/3: Enter price in INR (e.g., 99 or 99.50):")


@router.message(AdminStates.adding_plan_price, F.text)
async def add_plan_price(message: types.Message, state: FSMContext):
    """Receive plan price and create plan"""
    if not is_valid_price(message.text):
        await message.answer("❌ Invalid price. Enter a positive number.")
        return

    data = await state.get_data()
    product_id = data["plan_product_id"]

    db = Database.get_db()
    plan_data = {
        "product_id": ObjectId(product_id),
        "name": data["plan_name"],
        "duration_hours": data["plan_duration"],
        "price": float(message.text),
        "currency": "INR",
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }

    result = await db.plans.insert_one(plan_data)

    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(message.from_user.id),
        telegram_id=message.from_user.id,
        action="add_plan",
        entity_type="plan",
        entity_id=str(result.inserted_id),
        details={"product_id": product_id, "name": plan_data["name"], "price": plan_data["price"]}
    )

    await state.clear()
    await message.answer(
        f"✅ Plan '{plan_data['name']}' created!",
        reply_markup=AdminKeyboards.back_button(f"ep_plans_{product_id}")
    )


# Edit plan

async def _render_plan_edit(callback: types.CallbackQuery, plan_id: str):
    """Render the plan edit view"""
    db = Database.get_db()
    plan = await db.plans.find_one({"_id": ObjectId(plan_id)})

    if not plan:
        await callback.answer("Plan not found", show_alert=True)
        return

    keyboard = [
        [InlineKeyboardButton(
            text="✏️ Edit Name", callback_data=f"epl_name_{plan_id}"
        )],
        [InlineKeyboardButton(
            text="⏱️ Edit Duration", callback_data=f"epl_dur_{plan_id}"
        )],
        [InlineKeyboardButton(
            text="💰 Edit Price", callback_data=f"epl_price_{plan_id}"
        )],
        [InlineKeyboardButton(
            text="🔄 Toggle Status",
            callback_data=f"epl_toggle_{plan_id}"
        )],
        [InlineKeyboardButton(
            text="🔙 Back", callback_data=f"ep_plans_{plan['product_id']}"
        )]
    ]
    from aiogram.types import InlineKeyboardMarkup
    await callback.message.answer(
        f"⏱️ EDIT PLAN\n\n"
        f"Name: {plan['name']}\n"
        f"Duration: {plan.get('duration_hours', 0)} hours\n"
        f"Price: ₹{plan['price']}\n"
        f"Status: {plan.get('status', 'active').upper()}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("edit_plan_"))
async def edit_plan_select(callback: types.CallbackQuery):
    """Edit a plan"""
    plan_id = callback.data.split("_")[2]
    await _render_plan_edit(callback, plan_id)


@router.callback_query(F.data.startswith("epl_name_"))
async def epl_name(callback: types.CallbackQuery, state: FSMContext):
    plan_id = callback.data.split("_")[2]
    await state.update_data(edit_plan_id=plan_id, plan_field="name")
    await state.set_state(AdminStates.editing_plan)
    await callback.message.answer("✏️ Enter new plan name:",
                                     reply_markup=AdminKeyboards.back_button("admin_list_products"))
    await callback.answer()


@router.callback_query(F.data.startswith("epl_dur_"))
async def epl_dur(callback: types.CallbackQuery, state: FSMContext):
    plan_id = callback.data.split("_")[2]
    await state.update_data(edit_plan_id=plan_id, plan_field="duration_hours")
    await state.set_state(AdminStates.editing_plan)
    await callback.message.answer("⏱️ Enter new duration in hours:",
                                     reply_markup=AdminKeyboards.back_button("admin_list_products"))
    await callback.answer()


@router.callback_query(F.data.startswith("epl_price_"))
async def epl_price(callback: types.CallbackQuery, state: FSMContext):
    plan_id = callback.data.split("_")[2]
    await state.update_data(edit_plan_id=plan_id, plan_field="price")
    await state.set_state(AdminStates.editing_plan)
    await callback.message.answer("💰 Enter new price in INR:",
                                     reply_markup=AdminKeyboards.back_button("admin_list_products"))
    await callback.answer()


@router.callback_query(F.data.startswith("epl_toggle_"))
async def epl_toggle(callback: types.CallbackQuery):
    """Toggle plan status"""
    plan_id = callback.data.split("_")[2]
    db = Database.get_db()
    plan = await db.plans.find_one({"_id": ObjectId(plan_id)})
    if not plan:
        await callback.answer("Plan not found", show_alert=True)
        return

    new_status = "disabled" if plan.get("status") == "active" else "active"
    await db.plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$set": {"status": new_status, "updated_at": datetime.utcnow()}}
    )
    await callback.answer(f"Plan {new_status}", show_alert=True)
    await _render_plan_edit(callback, plan_id)


@router.callback_query(F.data.startswith("del_plan_"))
async def del_plan_confirm(callback: types.CallbackQuery):
    """Delete a plan"""
    plan_id = callback.data.split("_")[2]
    db = Database.get_db()
    plan = await db.plans.find_one({"_id": ObjectId(plan_id)})
    if not plan:
        await callback.answer("Plan not found", show_alert=True)
        return

    product_id = str(plan["product_id"])
    await db.plans.delete_one({"_id": ObjectId(plan_id)})
    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(callback.from_user.id),
        telegram_id=callback.from_user.id,
        action="delete_plan",
        entity_type="plan",
        entity_id=plan_id
    )
    await callback.answer("✅ Plan deleted", show_alert=True)
    await _render_plans_view(callback, product_id)


# Plan edit message handler

@router.message(AdminStates.editing_plan, F.text)
async def process_plan_edit(message: types.Message, state: FSMContext):
    """Process plan field edits"""
    data = await state.get_data()
    plan_id = data.get("edit_plan_id")
    field = data.get("plan_field")

    if not plan_id or not field:
        return  # Let other handlers process (product edits handled in admin_products too)

    value = message.text.strip()

    if field == "name":
        if not value or len(value) > 50:
            await message.answer("❌ Invalid plan name.")
            return
    elif field == "duration_hours":
        if not is_valid_duration(value):
            await message.answer("❌ Invalid duration.")
            return
        value = int(value)
    elif field == "price":
        if not is_valid_price(value):
            await message.answer("❌ Invalid price.")
            return
        value = float(value)

    db = Database.get_db()
    await db.plans.update_one(
        {"_id": ObjectId(plan_id)},
        {"$set": {field: value, "updated_at": datetime.utcnow()}}
    )

    admin_log = AdminLogRepository(db)
    await admin_log.log_action(
        admin_id=str(message.from_user.id),
        telegram_id=message.from_user.id,
        action="edit_plan",
        entity_type="plan",
        entity_id=plan_id,
        details={"field": field}
    )

    await state.clear()
    await message.answer("✅ Plan updated!",
                         reply_markup=AdminKeyboards.back_button("admin_list_products"))
