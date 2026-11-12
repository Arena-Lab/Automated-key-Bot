"""Reply keyboard button handlers - registered FIRST so they take precedence
over FSM state handlers (tapping a menu button always ends any active session)."""

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from datetime import datetime  # noqa: F401  (kept for parity)

from bot.keyboards.customer import CustomerKeyboards
from bot.services.product_service import ProductService
from bot.delivery.sender import DeliverySender
from bot.database.repositories import (
    ProductRepository, PlanRepository, SettingRepository
)
from bot.database.connection import Database
from config import Config
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

router = Router()


def _channel_url(raw: str) -> str:
    """Normalize channel setting into a t.me URL"""
    if not raw:
        return ""
    raw = raw.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("@"):
        return f"https://t.me/{raw[1:]}"
    return f"https://t.me/{raw}"


@router.message(F.text == "🤑 Purchase Keys")
async def rb_purchase(message: types.Message, state: FSMContext):
    """Reply keyboard: Purchase Keys -> product list"""
    await state.clear()
    product_repo = ProductRepository(Database.get_db())
    product_service = ProductService(product_repo, PlanRepository(Database.get_db()))
    products = await product_service.get_active_products()

    if not products:
        await message.answer(
            "📦 No products available at the moment.",
            reply_markup=CustomerKeyboards.back_to_main()
        )
        return

    await message.answer(
        "🛍️ SELECT PRODUCT\n\nChoose a product to purchase:",
        reply_markup=CustomerKeyboards.product_list(products)
    )


@router.message(F.text == "🪙 My Keys")
async def rb_my_keys(message: types.Message, user: dict, state: FSMContext):
    """Reply keyboard: My Keys"""
    await state.clear()
    db = Database.get_db()
    orders = await db.orders.find({
        "user_id": user["_id"],
        "status": "delivered",
        "key_value": {"$exists": True, "$ne": None}
    }).sort("created_at", -1).to_list(length=50)

    keys_with_orders = []
    for order in orders:
        product = await db.products.find_one({"_id": order["product_id"]})
        plan = await db.plans.find_one({"_id": order["plan_id"]})
        keys_with_orders.append({
            "order": order, "product": product, "plan": plan,
            "key_value": order["key_value"]
        })

    delivery = DeliverySender(message.bot)
    await delivery.send_my_keys(user["telegram_id"], keys_with_orders)


@router.message(F.text == "🎁 Setup Channel")
async def rb_channel(message: types.Message, state: FSMContext):
    """Reply keyboard: Setup Channel -> channel URL button"""
    await state.clear()
    settings_repo = SettingRepository(Database.get_db())
    channel = await settings_repo.get("official_channel", Config.OFFICIAL_CHANNEL)
    url = _channel_url(channel)

    if url:
        await message.answer(
            "🎁 Join our official channel for updates, free tools and offers:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📢 Open Channel", url=url)
            ]])
        )
    else:
        await message.answer("Channel link not configured yet.")


@router.message(F.text == "📞 Owner Contact")
async def rb_contact(message: types.Message, state: FSMContext):
    """Reply keyboard: Owner Contact"""
    await state.clear()
    settings_repo = SettingRepository(Database.get_db())
    support = await settings_repo.get("support_username", Config.SUPPORT_USERNAME)

    if support:
        await message.answer(f"📞 Contact the owner/admin:\n\n{support}")
    else:
        await message.answer("Contact support is not configured yet.")


@router.message(F.text == "🔴 How to Buy?")
async def rb_how_to(message: types.Message, state: FSMContext):
    """Reply keyboard: How to Buy"""
    await state.clear()
    await message.answer(
        "📖 HOW TO PURCHASE\n\n"
        "1. Tap '🤑 Purchase Keys'\n"
        "2. Select a product\n"
        "3. Choose your plan\n"
        "4. Pay via UPI (scan QR / UPI ID)\n"
        "5. Submit your UTR + screenshot\n"
        "6. Get your key + files automatically!\n\n"
        "Need help? Tap '📞 Owner Contact'.",
        reply_markup=CustomerKeyboards.back_to_main()
    )


@router.message(F.text == "🤝 Join Reseller")
async def rb_reseller(message: types.Message, user: dict, state: FSMContext):
    """Reply keyboard: Join Reseller"""
    await state.clear()
    settings_repo = SettingRepository(Database.get_db())
    enabled = await settings_repo.get("reseller_system_enabled", Config.RESELLER_SYSTEM_ENABLED)

    if not enabled:
        await message.answer("🎁 Reseller program is currently disabled.")
        return

    db = Database.get_db()
    reseller = await db.resellers.find_one({"telegram_id": user["telegram_id"]})

    if reseller and reseller.get("status") == "active":
        await message.answer(
            f"🎁 RESELLER DASHBOARD\n\n"
            f"Code: {reseller['reseller_code']}\n"
            f"Discount: {reseller.get('discount_percentage', 0)}%\n"
            f"Balance: ₹{reseller.get('balance', 0):.2f}\n"
            "Status: ACTIVE"
        )
        return

    await message.answer(
        "🎁 JOIN RESELLER PROGRAM\n\n"
        "Become a reseller and earn discounts on every purchase!\n\n"
        "Tap below to apply:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📝 Apply Now", callback_data="reseller_apply")
        ]])
    )
