"""Customer-facing handlers - every interaction sends a NEW message"""

import asyncio
import io
import logging
import os
from datetime import datetime

import qrcode
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from bot.oid import ObjectId

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
    custom_welcome = s.get("welcome_message")
    if custom_welcome:
        # Admin-set welcome - always shown in bold
        welcome = f"<b>{_esc(custom_welcome)}</b>"
    else:
        welcome = (
            f"⚜️ Welcome to <b>{_esc(shop)}</b>\n\n"
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

@router.message(F.text.in_({"🛍️ Purchase Keys", "🤑 Purchase Keys"}))
async def rb_purchase(message: types.Message, state: FSMContext, db):
    await state.clear()
    products = await db.products.find({"status": "active"}).sort("display_order", 1).to_list(100)
    if not products:
        await message.answer("📦 No products available right now.", reply_markup=KB.reply_menu())
        return
    # attach live stock (parallel - one round-trip total)
    counts = await asyncio.gather(*[svc.product_stock_total(db, p["_id"]) for p in products])
    for p, c in zip(products, counts):
        p["stock_total"] = c
    await message.answer(
        "🛍️ <b>SELECT A PRODUCT</b>\n\nChoose a product to purchase:",
        parse_mode="HTML",
        reply_markup=KB.products(products),
    )


@router.message(F.text.in_({"🔑 My Keys", "🪙 My Keys"}))
async def rb_my_keys(message: types.Message, user: dict, state: FSMContext, db):
    await state.clear()
    orders = await db.orders.find(
        {"telegram_id": user["telegram_id"], "key_value": {"$ne": None}}
    ).sort("created_at", -1).to_list(50)
    if not orders:
        await message.answer("🔑 You have no purchased keys yet.", reply_markup=KB.reply_menu())
        return

    # One single message with all keys - no spam
    lines = ["🔑 <b>MY LICENSE KEYS</b>", "━━━━━━━━━━━━━━━━━━"]
    for o in orders:
        lines.append(
            f"\n🎮 <b>{_esc(o.get('product_name',''))}</b>\n"
            f"⏱️ {_esc(o.get('plan_name',''))}\n"
            f"🔑 <code>{_esc(o.get('key_value',''))}</code>\n"
            f"🆔 Order: <code>{_esc(o.get('order_id',''))}</code>\n"
            f"🕐 {_esc(svc.fmt_ist(o.get('created_at')))}"
        )
    lines.append("\n━━━━━━━━━━━━━━━━━━")
    full = "\n".join(lines)
    if len(full) <= 3800:
        await message.answer(full, parse_mode="HTML",
                             reply_markup=KB.reply_menu())
    else:
        # Too many keys for one message - send as a .txt document
        from aiogram.types import BufferedInputFile
        plain = "\n".join(
            l.replace("<b>", "").replace("</b>", "")
             .replace("<code>", "").replace("</code>", "")
            for l in lines)
        await message.answer(
            f"🔑 You have <b>{len(orders)}</b> keys — sent as a file:",
            parse_mode="HTML")
        await message.answer_document(
            BufferedInputFile(plain.encode("utf-8"), filename="my_keys.txt"),
            caption="🔑 <b>MY LICENSE KEYS</b>", parse_mode="HTML")
        await message.answer("Keys exported successfully ✅",
                             reply_markup=KB.reply_menu())


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
    await message.answer(
        "📞 Contact the owner/admin:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💬 Message Owner",
                                 url="https://t.me/zerotrace0x")
        ]]))


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
    counts = await asyncio.gather(*[svc.product_stock_total(db, p["_id"]) for p in products])
    for p, c in zip(products, counts):
        p["stock_total"] = c
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
    plat = product.get("platform")
    plat_line = f"📱 Platform: {plat}\n\n" if plat else ""
    text = (f"🎮 <b>{_esc(product['name'])}</b>\n\n"
            f"{plat_line}{_esc(desc)}\n\n⏱️ <b>Choose validity:</b>")
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

    # New purchase => delete old payment messages + cancel previous pending orders
    old_pending = await db.orders.find(
        {"telegram_id": user["telegram_id"], "status": "pending"}
    ).to_list(length=None)
    for old in old_pending:
        old_pay = await db.payments.find_one({"order_id": old["_id"]})
        if old_pay and old_pay.get("payment_msg_id"):
            try:
                await callback.bot.delete_message(
                    old_pay.get("payment_chat_id", user["telegram_id"]),
                    old_pay["payment_msg_id"])
            except Exception:
                pass
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
        f"💰 Amount: <b>₹{amount:g}</b>\n"
        f"🆔 Order ID: <code>{order['order_id']}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🏦 UPI ID: <code>{_esc(upi)}</code>\n"
        f"👤 Payee: {_esc(payee)}\n\n"
        f"📌 <b>Instructions:</b>\n{_esc(instr)}\n\n"
        f"⏳ Expires: {svc.fmt_ist(expiry)}\n"
        "Order auto-cancels if unpaid."
    )

    # QR code: prefer the configured image file, fall back to generated UPI QR
    qr_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "payment images", "fampay_qr.jpg",
    )
    try:
        if os.path.exists(qr_path):
            sent = await callback.message.answer_photo(
                FSInputFile(qr_path), caption=caption, parse_mode="HTML",
                reply_markup=KB.payment(order["order_id"]),
            )
        else:
            raise FileNotFoundError(qr_path)
    except Exception:
        try:
            qr = _upi_qr(s, amount, order["order_id"])
            sent = await callback.message.answer_photo(
                io.BytesIO(qr), caption=caption, parse_mode="HTML",
                reply_markup=KB.payment(order["order_id"]),
            )
        except Exception:
            sent = await callback.message.answer(caption, parse_mode="HTML",
                                                  reply_markup=KB.payment(order["order_id"]))

    # Persist message id so it can be deleted on cancel/expiry/new order
    pay_doc = await db.payments.find_one({"public_order_id": order["order_id"]})
    if pay_doc:
        await db.payments.update_one(
            {"_id": pay_doc["_id"]},
            {"$set": {"payment_msg_id": sent.message_id,
                      "payment_chat_id": sent.chat.id}})


# ---------------- Payment submission ----------------

async def _get_pending_order(db, order_id, telegram_id):
    order = await db.orders.find_one({"order_id": order_id})
    if not order or order.get("telegram_id") != telegram_id or order.get("status") != "pending":
        return None
    return order


@router.callback_query(F.data.startswith("pay_utr_"))
async def cb_pay_utr(callback: types.CallbackQuery, state: FSMContext, db):
    order_id = callback.data.split("_", 2)[2]
    await callback.answer()
    pay = await db.payments.find_one({"public_order_id": order_id})
    if pay and (pay.get("utr") or pay.get("screenshot_file_id")):
        await callback.message.answer(
            "ℹ️ Payment details already submitted for this order.\n\n"
            "Please wait for verification.",
            parse_mode="HTML", reply_markup=KB.reply_menu())
        return
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

    if utr.startswith("/") or utr in ("🛍️ Purchase Keys", "🤑 Purchase Keys", "🔑 My Keys", "🪙 My Keys",
                                      "🎁 Setup Channel", "📞 Owner Contact", "🔴 How to Buy?", "🤝 Join Reseller"):
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

    # Duplicate UTR check - payments.utr has a unique index, so ANY existing
    # doc with this UTR will collide. Only expired payments may release it.
    existing_utr = await db.payments.find_one({"utr": utr})
    if existing_utr:
        if existing_utr.get("status") != "expired":
            await message.answer("❌ This UTR was already submitted for another order.")
            return
        # Free the UTR from the expired payment so it can be reused
        await db.payments.update_one(
            {"_id": existing_utr["_id"]},
            {"$unset": {"utr": ""}}
        )

    pay = await db.payments.find_one({"public_order_id": order_id})
    if pay:
        try:
            await svc.submit_payment_details(db, pay["_id"], utr=utr)
        except DuplicateKeyError:
            # Lost a race - another payment grabbed this UTR first
            await message.answer("❌ This UTR was already submitted for another order.")
            await state.clear()
            return

    await state.clear()
    await message.answer(
        f"✅ UTR <code>{utr}</code> submitted for order <code>{order_id}</code>.\n\n"
        "⏳ Please wait — your payment is under verification. "
        "You will receive your key once approved.",
        parse_mode="HTML",
        reply_markup=KB.reply_menu(),
    )
    await _notify_admins_payment(db, message.bot, order_id, utr, None)


@router.callback_query(F.data.startswith("pay_ss_"))
async def cb_pay_ss(callback: types.CallbackQuery, state: FSMContext, db):
    order_id = callback.data.split("_", 2)[2]
    await callback.answer()
    pay = await db.payments.find_one({"public_order_id": order_id})
    if pay and (pay.get("utr") or pay.get("screenshot_file_id")):
        await callback.message.answer(
            "ℹ️ Payment details already submitted for this order.\n\n"
            "Please wait for verification.",
            parse_mode="HTML", reply_markup=KB.reply_menu())
        return
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
    await message.answer(
        "✅ Screenshot received.\n\n⏳ Please wait — your payment is under verification. "
        "You will receive your key once approved.",
        reply_markup=KB.reply_menu())
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


async def _payment_destinations(db):
    """Resolve (group_ids, admin_ids) for payment alerts.
    Setting 'payment_notify_target': group (default) | admins | both.
    Falls back to admin DMs if the group isn't configured."""
    s = await svc.get_settings(db)
    mode = s.get("payment_notify_target", "group")
    group_id = Config.PAYMENT_VERIFICATION_GROUP_ID
    group_ids = [group_id] if (mode in ("group", "both") and group_id) else []
    admin_ids = list(Config.ADMIN_IDS) if (
        mode in ("admins", "both") or (mode == "group" and not group_id)
    ) else []
    return group_ids, admin_ids


async def _send_alert(bot, tid, text, reply_markup=None, screenshot_file_id=None):
    """Send one payment alert; returns {"chat_id","message_id"} on success."""
    try:
        if screenshot_file_id:
            msg = await bot.send_photo(tid, screenshot_file_id,
                                       caption=text, parse_mode="HTML",
                                       reply_markup=reply_markup)
        else:
            msg = await bot.send_message(tid, text, parse_mode="HTML",
                                         reply_markup=reply_markup)
        return {"chat_id": tid, "message_id": msg.message_id}
    except Exception:
        try:
            msg = await bot.send_message(tid, text + "\n\n📷 (screenshot unavailable)",
                                         parse_mode="HTML", reply_markup=reply_markup)
            return {"chat_id": tid, "message_id": msg.message_id}
        except Exception:
            return None


async def _dispatch_alert(db, bot, text, reply_markup=None, screenshot_file_id=None):
    """Send to configured targets; if NOTHING was delivered, fall back to
    every possible destination (group + admin DMs) regardless of the toggle,
    so payment alerts are never lost. Returns list of sent message refs."""
    group_ids, admin_ids = await _payment_destinations(db)
    refs = []
    for tid in group_ids + admin_ids:
        ref = await _send_alert(bot, tid, text, reply_markup, screenshot_file_id)
        if ref:
            refs.append(ref)
    # Total failure -> try every reachable destination as fallback
    if not refs:
        fallback = []
        if Config.PAYMENT_VERIFICATION_GROUP_ID:
            fallback.append(Config.PAYMENT_VERIFICATION_GROUP_ID)
        fallback.extend(Config.ADMIN_IDS)
        for tid in dict.fromkeys(fallback):  # dedupe, preserve order
            ref = await _send_alert(bot, tid, text, reply_markup, screenshot_file_id)
            if ref:
                refs.append(ref)
    return refs


async def _notify_admins_payment(db, bot, order_id, utr, screenshot_file_id):
    """Notify admins once with full details; later submissions send a short update."""
    order = await db.orders.find_one({"order_id": order_id})
    if not order:
        return
    pay = await db.payments.find_one({"order_id": order["_id"]})
    already_notified = bool(pay and pay.get("admin_notified"))

    if already_notified:
        # Brief update only - no duplicate verification request
        note = f"📎 Order <code>{order_id}</code>: "
        note += f"UTR <code>{utr}</code> added.\n" if utr else ""
        note += "📷 Screenshot added.\n" if screenshot_file_id else ""
        note += "(Already notified - see Payments menu to review)"
        await _dispatch_alert(db, bot, note)
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
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Approve", callback_data=f"ver_ok_{order_id}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"ver_no_{order_id}"),
    ]])

    # Mark notified BEFORE sending so a retry can't double-send
    if pay:
        await db.payments.update_one({"_id": pay["_id"]},
                                     {"$set": {"admin_notified": True}})

    refs = await _dispatch_alert(db, bot, text, reply_markup=kb,
                                 screenshot_file_id=screenshot_file_id)
    # Remember where the first alert landed so delivery can edit it later
    if refs and pay:
        await db.payments.update_one(
            {"_id": pay["_id"]},
            {"$set": {"notify_chat_id": refs[0]["chat_id"],
                      "notify_message_id": refs[0]["message_id"]}})


# ---------------- My Orders / Key / Files ----------------

@router.callback_query(F.data == "nav_orders")
async def cb_orders(callback: types.CallbackQuery, user: dict, db):
    await callback.answer()
    orders = await db.orders.find({"telegram_id": user["telegram_id"]}).sort("created_at", -1).to_list(20)
    if not orders:
        await callback.message.answer("📦 No orders yet.", reply_markup=KB.reply_menu())
        return
    # One message, one inline button per order - no spam
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    icon = {"pending": "🟡", "paid": "🟢", "delivered": "✅", "cancelled": "⚫",
            "rejected": "🔴", "expired": "⌛"}
    lines = ["📦 <b>MY ORDERS</b>\n"]
    rows = []
    for o in orders:
        st = o.get("status", "?")
        lines.append(
            f"{icon.get(st,'⚪')} <b>{o.get('order_id')}</b> — "
            f"{_esc(o.get('product_name',''))} ({_esc(o.get('plan_name',''))})\n"
            f"💰 ₹{o.get('amount',0):.2f} | {st.upper()} | "
            f"{_esc(svc.fmt_ist(o.get('created_at')))}\n")
        rows.append([InlineKeyboardButton(
            text=f"{icon.get(st,'⚪')} {o.get('order_id')} — {st.upper()}",
            callback_data=f"order_{o['order_id']}")])
    await callback.message.answer("\n".join(lines)[:4000], parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("order_"))
async def cb_order_view(callback: types.CallbackQuery, user: dict, db):
    """Order detail with key/files actions"""
    await callback.answer()
    o = await _own_order(db, callback.data[6:], user["telegram_id"])
    if not o:
        await callback.message.answer("❌ Order not found.")
        return
    icon = {"pending": "🟡", "paid": "🟢", "delivered": "✅", "cancelled": "⚫",
            "rejected": "🔴", "expired": "⌛"}.get(o.get("status"), "⚪")
    text = (
        f"📦 <b>ORDER {o.get('order_id')}</b>\n\n"
        f"🎮 {_esc(o.get('product_name',''))} | ⏱️ {_esc(o.get('plan_name',''))}\n"
        f"💰 ₹{o.get('amount',0):g} | {icon} {o.get('status','').upper()}\n"
        f"🕐 {svc.fmt_ist(o.get('created_at'))}"
    )
    if o.get("key_value"):
        text += (f"\n\n━━━━━━━━━━━━━━━━━━\n"
                 f"🔑 <b>LICENSE KEY</b>\n<code>{_esc(o['key_value'])}</code>")
    await callback.message.answer(text, parse_mode="HTML",
                                  reply_markup=KB.order_actions(o["order_id"]))


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
        "🔑 <b>YOUR LICENSE KEY</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🎮 <b>{_esc(o.get('product_name',''))}</b>\n"
        f"⏱️ {_esc(o.get('plan_name',''))}\n\n"
        f"🔑 <code>{_esc(o['key_value'])}</code>\n\n"
        f"🆔 Order: <code>{_esc(o.get('order_id',''))}</code>",
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
