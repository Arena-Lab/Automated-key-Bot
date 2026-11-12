"""Customer-facing handlers - every interaction sends a NEW message"""

import io
import logging
from datetime import datetime

import qrcode
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bson import ObjectId

from bot.db import Database
from bot.ui import KB
from bot.fsm import CustomerStates
import bot.svc as svc
from config import Config

logger = logging.getLogger(__name__)
router = Router()


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _channel_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("http"):
        return raw
    return f"https://t.me/{raw.lstrip('@')}"


def _upi_qr(settings: dict, amount: float, order_id: str) -> bytes:
    upi = settings.get("upi_id") or Config.UPI_ID
    payee = settings.get("payee_name") or Config.PAYEE_NAME or "Shop"
    link = f"upi://pay?pa={upi}&pn={payee}&am={amount}&cu=INR&tn={order_id}"
    img = qrcode.make(link)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


# ---------------- /start ----------------

@router.message(F.text == "/start")
async def cmd_start(message: types.Message, state: FSMContext, db):
    await state.clear()
    s = await svc.get_settings(db)
    shop = s.get("shop_name") or Config.SHOP_NAME
    welcome = s.get("welcome_message") or (
        f"⚜️ Welcome to {shop}\n\n"
        "Welcome to our official Key Shop!\n\n"
        "Choose an option below to explore our products and purchase your keys."
    )
    channel = _channel_url(s.get("official_channel") or Config.OFFICIAL_CHANNEL)

    if channel:
        await message.answer(
            welcome,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📢 Join Official Channel", url=channel)]]),
        )
    else:
        await message.answer(welcome, parse_mode="HTML")

    await message.answer("🛍️ Use the menu below to get started:", reply_markup=KB.reply_menu())


# ---------------- Reply keyboard buttons ----------------

@router.message(F.text == "🛍️ Purchase Keys")
async def rb_purchase(message: types.Message, state: FSMContext, db):
    await state.clear()
    products = await db.products.find({"status": "active"}).sort("display_order", 1).to_list(100)
    if not products:
        await message.answer("📦 No products available right now.", reply_markup=KB.reply_menu())
        return
    # attach live stock
    for p in products:
        p["stock_total"] = await svc.product_stock_total(db, p["_id"])
    await message.answer(
        "🛍️ <b>SELECT A PRODUCT</b>\n\nChoose a product to purchase:",
        parse_mode="HTML",
        reply_markup=KB.products(products),
    )


@router.message(F.text == "🔑 My Keys")
async def rb_my_keys(message: types.Message, user: dict, state: FSMContext, db):
    await state.clear()
    orders = await db.orders.find(
        {"telegram_id": user["telegram_id"], "status": "delivered", "key_value": {"$ne": None}}
    ).sort("created_at", -1).to_list(50)
    if not orders:
        await message.answer("🔑 You have no purchased keys yet.", reply_markup=KB.reply_menu())
        return
    for o in orders:
        await message.answer(
            f"🔑 <b>LICENSE KEY</b>\n\n"
            f"🎮 {_esc(o.get('product_name',''))}\n⏱️ {_esc(o.get('plan_name',''))}\n\n"
            f"<code>{_esc(o.get('key_value',''))}</code>\n🆔 {_esc(o.get('order_id',''))}",
            parse_mode="HTML",
            reply_markup=KB.order_actions(o["order_id"]),
        )


@router.message(F.text == "🎁 Setup Channel")
async def rb_channel(message: types.Message, state: FSMContext, db):
    await state.clear()
    s = await svc.get_settings(db)
    url = _channel_url(s.get("official_channel") or Config.OFFICIAL_CHANNEL)
    if url:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        await message.answer(
            "🎁 Join our official channel for updates and offers:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📢 Open Channel", url=url)]]),
        )
    else:
        await message.answer("Channel link not configured yet.")


@router.message(F.text == "📞 Owner Contact")
async def rb_contact(message: types.Message, state: FSMContext, db):
    await state.clear()
    s = await svc.get_settings(db)
    support = s.get("support_username") or Config.SUPPORT_USERNAME
    await message.answer(f"📞 Contact support:\n\n{support or 'Not configured'}")


@router.message(F.text == "🔴 How to Buy?")
async def rb_howto(message: types.Message, state: FSMContext, db):
    await state.clear()
    s = await svc.get_settings(db)
    tut = await db.tutorial.find_one({"_id": "howto"})
    text = s.get("how_to_text") or (
        "🔴 <b>HOW TO BUY</b>\n\n"
        "1️⃣ Tap 🛍️ Purchase Keys\n"
        "2️⃣ Select a product\n"
        "3️⃣ Choose a validity plan\n"
        "4️⃣ Pay via UPI (scan QR)\n"
        "5️⃣ Submit UTR + screenshot\n"
        "6️⃣ Receive your key + files instantly!"
    )
    if tut and tut.get("file_id") and tut.get("enabled", True):
        await message.answer_video(
            tut["file_id"], caption=text, parse_mode="HTML"
        )
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=KB.reply_menu())


@router.message(F.text == "🤝 Join Reseller")
async def rb_reseller(message: types.Message, user: dict, state: FSMContext, db):
    await state.clear()
    s = await svc.get_settings(db)
    if not s.get("reseller_enabled", Config.RESELLER_SYSTEM_ENABLED):
        await message.answer("🎁 Reseller program is currently closed.")
        return
    r = await db.resellers.find_one({"telegram_id": user["telegram_id"]})
    if r and r.get("status") == "active":
        await message.answer(
            f"🎁 <b>RESELLER DASHBOARD</b>\n\n"
            f"Code: <code>{r.get('reseller_code','-')}</code>\n"
            f"Discount: {r.get('discount_percentage',0)}%\n"
            f"Balance: ₹{r.get('balance',0):.2f}",
            parse_mode="HTML",
        )
        return
    if r and r.get("status") == "pending":
        await message.answer("⏳ Your reseller application is under review.")
        return
    await message.answer(
        "🎁 <b>JOIN RESELLER PROGRAM</b>\n\nEarn discounts on every purchase!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📝 Apply Now", callback_data="res_apply")]]),
    )


# ---------------- Navigation callbacks (all send NEW messages) ----------------

@router.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "nav_products")
async def cb_products(callback: types.CallbackQuery, db):
    await callback.answer()
    products = await db.products.find({"status": "active"}).sort("display_order", 1).to_list(100)
    for p in products:
        p["stock_total"] = await svc.product_stock_total(db, p["_id"])
    await callback.message.answer(
        "🛍️ <b>SELECT A PRODUCT</b>\n\nChoose a product to purchase:",
        parse_mode="HTML", reply_markup=KB.products(products),
    )


@router.callback_query(F.data.startswith("prod_"))
async def cb_product(callback: types.CallbackQuery, db):
    pid = callback.data[5:]
    await callback.answer()
    product = await db.products.find_one({"_id": ObjectId(pid), "status": "active"})
    if not product:
        await callback.message.answer("❌ Product unavailable.", reply_markup=KB.reply_menu())
        return
    plans = await svc.enrich_plans(db, product["_id"])
    desc = product.get("description") or ""
    text = f"🎮 <b>{_esc(product['name'])}</b>\n\n{_esc(desc)}\n\n⏱️ <b>Choose validity:</b>"
    await callback.message.answer(text, parse_mode="HTML", reply_markup=KB.plans(plans, pid))


@router.callback_query(F.data.startswith("plan_"))
async def cb_plan(callback: types.CallbackQuery, user: dict, state: FSMContext, db):
    plan_id = callback.data[5:]
    await callback.answer("Creating order...")

    plan = await db.plans.find_one({"_id": ObjectId(plan_id), "status": "active"})
    if not plan:
        await callback.message.answer("❌ Plan unavailable.")
        return
    product = await db.products.find_one({"_id": plan["product_id"], "status": "active"})
    if not product:
        await callback.message.answer("❌ Product unavailable.")
        return
    if await svc.stock_for_plan(db, plan["_id"]) <= 0:
        await callback.message.answer("🔴 Out of stock for this plan.")
        return

    # New purchase => cancel previous pending orders
    await svc.cancel_user_pending_orders(db, user["telegram_id"])
    order = await svc.create_order(user, product, plan, db)

    s = await svc.get_settings(db)
    upi = s.get("upi_id") or Config.UPI_ID
    payee = s.get("payee_name") or Config.PAYEE_NAME or "Key Shop"
    instr = s.get("payment_instructions") or Config.PAYMENT_INSTRUCTIONS
    amount = order["amount"]
    expiry = order["payment"]["expiry_time"]

    caption = (
        "💳 <b>PAYMENT DETAILS</b>\n\n"
        f"🎮 {_esc(product['name'])}\n⏱️ {_esc(plan['name'])}\n\n"
        f"💰 Amount: <b>₹{amount:.2f}</b>\n"
        f"🆔 Order ID: <code>{order['order_id']}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🏦 UPI ID: <code>{_esc(upi)}</code>\n"
        f"👤 Payee: {_esc(payee)}\n\n"
        f"📌 <b>Instructions:</b>\n{_esc(instr)}\n\n"
        f"⏳ Expires: {svc.fmt_ist(expiry)}\n"
        "Order auto-cancels if unpaid."
    )

    try:
        qr = _upi_qr(s, amount, order["order_id"])
        await callback.message.answer_photo(
            io.BytesIO(qr), caption=caption, parse_mode="HTML",
            reply_markup=KB.payment(order["order_id"]),
        )
    except Exception:
        await callback.message.answer(caption, parse_mode="HTML",
                                      reply_markup=KB.payment(order["order_id"]))


# ---------------- Payment submission ----------------

async def _get_pending_order(db, order_id, telegram_id):
    order = await db.orders.find_one({"order_id": order_id})
    if not order or order.get("telegram_id") != telegram_id or order.get("status") != "pending":
        return None
    return order


@router.callback_query(F.data.startswith("pay_utr_"))
async def cb_pay_utr(callback: types.CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_", 2)[2]
    await callback.answer()
    await state.set_state(CustomerStates.waiting_for_utr)
    await state.update_data(order_id=order_id)
    await callback.message.answer(
        f"🧾 Submit UTR for order <code>{order_id}</code>\n\n"
        "Send the UTR / transaction ID (numbers only):",
        parse_mode="HTML",
    )


@router.message(CustomerStates.waiting_for_utr, F.text)
async def msg_utr(message: types.Message, state: FSMContext, user: dict, db):
    data = await state.get_data()
    order_id = data.get("order_id")
    utr = (message.text or "").strip()

    if utr.startswith("/") or utr in ("🛍️ Purchase Keys", "🔑 My Keys", "🎁 Setup Channel",
                                      "📞 Owner Contact", "🔴 How to Buy?", "🤝 Join Reseller"):
        await state.clear()
        await message.answer("Payment session ended.", reply_markup=KB.reply_menu())
        return

    if not utr.isdigit() or len(utr) < 8:
        await message.answer("❌ Invalid UTR. Send numbers only (min 8 digits).")
        return

    order = await _get_pending_order(db, order_id, user["telegram_id"])
    if not order:
        await state.clear()
        await message.answer("❌ Order expired or already processed.", reply_markup=KB.reply_menu())
        return

    # Duplicate UTR check
    dup = await db.payments.find_one({"utr": utr, "status": {"$ne": "expired"}})
    if dup and dup.get("public_order_id") != order_id:
        await message.answer("❌ This UTR was already submitted for another order.")
        return

    pay = await db.payments.find_one({"public_order_id": order_id})
    if pay:
        await svc.submit_payment_details(db, pay["_id"], utr=utr)

    await state.clear()
    await message.answer(
        f"✅ UTR <code>{utr}</code> submitted for order <code>{order_id}</code>.\n\n"
        "📸 You can also upload a payment screenshot, or wait for verification.",
        parse_mode="HTML",
        reply_markup=KB.payment(order_id),
    )
    await _notify_admins_payment(db, message.bot, order_id, utr, None)


@router.callback_query(F.data.startswith("pay_ss_"))
async def cb_pay_ss(callback: types.CallbackQuery, state: FSMContext):
    order_id = callback.data.split("_", 2)[2]
    await callback.answer()
    await state.set_state(CustomerStates.waiting_for_screenshot)
    await state.update_data(order_id=order_id)
    await callback.message.answer(
        f"📸 Send the payment screenshot for order <code>{order_id}</code>:",
        parse_mode="HTML",
    )


@router.message(CustomerStates.waiting_for_screenshot, F.photo)
async def msg_screenshot(message: types.Message, state: FSMContext, user: dict, db):
    data = await state.get_data()
    order_id = data.get("order_id")
    file_id = message.photo[-1].file_id
    order = await _get_pending_order(db, order_id, user["telegram_id"])
    if not order:
        await state.clear()
        await message.answer("❌ Order expired.", reply_markup=KB.reply_menu())
        return
    pay = await db.payments.find_one({"public_order_id": order_id})
    if pay:
        await svc.submit_payment_details(db, pay["_id"], screenshot_file_id=file_id)
    await state.clear()
    await message.answer("✅ Screenshot received. Waiting for verification.")
    await _notify_admins_payment(db, message.bot, order_id, None, file_id)


@router.message(CustomerStates.waiting_for_screenshot, F.text)
async def msg_ss_text(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Payment session ended.", reply_markup=KB.reply_menu())


@router.callback_query(F.data.startswith("pay_cancel_"))
async def cb_pay_cancel(callback: types.CallbackQuery, user: dict, state: FSMContext, db):
    await state.clear()
    order_id = callback.data.split("_", 2)[2]
    order = await db.orders.find_one({"order_id": order_id})
    if order and order.get("telegram_id") == user["telegram_id"] and order.get("status") == "pending":
        await db.orders.update_one({"_id": order["_id"]},
            {"$set": {"status": "cancelled", "updated_at": svc.now_utc()}})
        await db.payments.update_many({"order_id": order["_id"], "status": "pending"},
            {"$set": {"status": "expired", "updated_at": svc.now_utc()}})
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.bot.send_message(user["telegram_id"],
        f"❌ Payment for order {order_id} cancelled.", reply_markup=KB.reply_menu())
    await callback.answer()


async def _notify_admins_payment(db, bot, order_id, utr, screenshot_file_id):
    order = await db.orders.find_one({"order_id": order_id})
    if not order:
        return
    user = await db.users.find_one({"_id": order["user_id"]})
    uname = f"@{user.get('username')}" if user and user.get("username") else (user or {}).get("first_name", "?")
    text = (
        "🔔 <b>NEW PAYMENT REQUEST</b>\n\n"
        f"🆔 Order: <code>{order_id}</code>\n"
        f"👤 Customer: {uname} (<code>{order['telegram_id']}</code>)\n"
        f"🎮 {_esc(order.get('product_name',''))} | ⏱️ {_esc(order.get('plan_name',''))}\n"
        f"💰 ₹{order.get('amount',0):.2f}\n"
        + (f"🏦 UTR: <code>{utr}</code>\n" if utr else "")
        + ("📷 Screenshot: attached below\n" if screenshot_file_id else "")
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Approve", callback_data=f"ver_ok_{order_id}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"ver_no_{order_id}"),
    ]])
    for aid in Config.ADMIN_IDS:
        try:
            await bot.send_photo(aid, screenshot_file_id,
                                 caption=text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            try:
                await bot.send_message(aid, text + "\n\n📷 (screenshot unavailable)",
                                       parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass
    if not screenshot_file_id:
        for aid in Config.ADMIN_IDS:
            try:
                await bot.send_message(aid, text, parse_mode="HTML", reply_markup=kb)
            except Exception:
                pass


# ---------------- My Orders / Key / Files ----------------

@router.callback_query(F.data == "nav_orders")
async def cb_orders(callback: types.CallbackQuery, user: dict, db):
    await callback.answer()
    orders = await db.orders.find({"telegram_id": user["telegram_id"]}).sort("created_at", -1).to_list(20)
    if not orders:
        await callback.message.answer("📦 No orders yet.", reply_markup=KB.reply_menu())
        return
    for o in orders:
        icon = {"pending": "🟡", "paid": "🟢", "delivered": "✅", "cancelled": "⚫",
                "rejected": "🔴", "expired": "⌛"}.get(o.get("status"), "⚪")
        await callback.message.answer(
            f"{icon} <b>{o.get('order_id')}</b> — {_esc(o.get('product_name',''))} "
            f"({_esc(o.get('plan_name',''))})\n💰 ₹{o.get('amount',0):.2f} | "
            f"{o.get('status','').upper()} | {_esc(svc.fmt_ist(o.get('created_at', svc.now_utc())))}",
            parse_mode="HTML",
            reply_markup=KB.order_actions(o["order_id"]),
        )


async def _own_order(db, order_id, telegram_id):
    o = await db.orders.find_one({"order_id": order_id})
    if not o or o.get("telegram_id") != telegram_id:
        return None
    return o


@router.callback_query(F.data.startswith("key_"))
async def cb_key(callback: types.CallbackQuery, user: dict, db):
    await callback.answer()
    o = await _own_order(db, callback.data[4:], user["telegram_id"])
    if not o or not o.get("key_value"):
        await callback.message.answer("❌ No key for this order.")
        return
    await callback.message.answer(
        f"🔑 <b>KEY</b>\n\n<code>{_esc(o['key_value'])}</code>\n🆔 {_esc(o.get('order_id',''))}",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("files_"))
async def cb_files(callback: types.CallbackQuery, user: dict, db):
    await callback.answer()
    o = await _own_order(db, callback.data[6:], user["telegram_id"])
    if not o or o.get("status") != "delivered":
        await callback.message.answer("❌ Files available after delivery.")
        return
    product = await db.products.find_one({"_id": o["product_id"]})
    if not product:
        await callback.message.answer("❌ Product data missing.")
        return
    files = product.get("files", {})
    for kind in ("apk", "video", "document"):
        f = files.get(kind)
        if not f or not f.get("file_id"):
            continue
        try:
            if kind == "video":
                await callback.message.answer_video(f["file_id"], caption="🎬 Setup Video")
            else:
                await callback.message.answer_document(f["file_id"], caption=f"📎 {kind.upper()}")
        except Exception:
            pass
    if product.get("instructions"):
        await callback.message.answer(f"📝 Instructions:\n{product['instructions']}")
    links = product.get("links", [])
    if links:
        txt = "🔗 Links:\n" + "\n".join(f"• {l.get('title','')}: {l.get('url','')}" for l in links)
        await callback.message.answer(txt)


# ---------------- Reseller apply ----------------

@router.callback_query(F.data == "res_apply")
async def cb_res_apply(callback: types.CallbackQuery, user: dict, state: FSMContext, db):
    await callback.answer()
    s = await svc.get_settings(db)
    if not s.get("reseller_enabled", Config.RESELLER_SYSTEM_ENABLED):
        await callback.message.answer("Reseller program closed.")
        return
    existing = await db.resellers.find_one({"telegram_id": user["telegram_id"]})
    if existing:
        await callback.message.answer("Already registered/pending.")
        return
    await db.resellers.insert_one({
        "telegram_id": user["telegram_id"],
        "user_id": user["_id"],
        "status": "pending",
        "created_at": svc.now_utc(),
    })
    for aid in Config.ADMIN_IDS:
        try:
            await callback.bot.send_message(
                aid,
                f"📝 <b>New reseller application</b>\n\n"
                f"{user.get('first_name','')} (@{user.get('username','-')})\n"
                f"ID: <code>{user['telegram_id']}</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Approve", callback_data=f"res_ok_{user['telegram_id']}"),
                    InlineKeyboardButton(text="❌ Reject", callback_data=f"res_no_{user['telegram_id']}"),
                ]]),
            )
        except Exception:
            pass
    await callback.message.answer("✅ Application submitted! Admin will review.")
