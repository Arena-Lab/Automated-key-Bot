"""Customer-facing handlers - every interaction sends a NEW message"""

import asyncio
import io
import logging
import math
from datetime import timedelta

import qrcode
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton,
                           BufferedInputFile)
from bot.oid import ObjectId

from bot.ui import KB
import bot.svc as svc
from bot import payverify
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


def _qr_png(data: str) -> bytes:
    # compact QR - smaller PNG uploads faster to Telegram
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


# Per-user purchase locks - serialize order creation so rapid clicks
# can never produce two orders for the same purchase action.
_PURCHASE_LOCKS = {}
_PURCHASE_LOCKS_GUARD = asyncio.Lock()


async def _purchase_lock(tid: int) -> asyncio.Lock:
    async with _PURCHASE_LOCKS_GUARD:
        lock = _PURCHASE_LOCKS.get(tid)
        if lock is None:
            lock = _PURCHASE_LOCKS[tid] = asyncio.Lock()
        return lock


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
    url = _channel_url(s.get("setup_channel") or s.get("official_channel") or Config.OFFICIAL_CHANNEL)
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
        "5️⃣ Receive your key automatically once payment is detected!"
    )
    if tut and tut.get("file_id") and tut.get("enabled", True):
        await message.answer_video(
            tut["file_id"], caption=text, parse_mode="HTML"
        )
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=KB.reply_menu())


@router.message(F.text == "👑 Resellers")
async def rb_reseller(message: types.Message, user: dict, state: FSMContext, db,
                      is_admin: bool = False):
    await state.clear()
    if is_admin:
        from bot.handlers import reseller_admin
        await reseller_admin.send_admin_panel(message, db)
        return
    s = await svc.get_settings(db)
    if not s.get("reseller_enabled", Config.RESELLER_SYSTEM_ENABLED):
        await message.answer("🎁 Reseller program is currently closed.")
        return
    r = await db.resellers.find_one({"telegram_id": user["telegram_id"]})
    if r and r.get("status") == "active":
        from bot.handlers import reseller_shop
        await reseller_shop._send_panel(message, db, r)
        return
    if r and r.get("status") == "pending":
        await message.answer("⏳ Your reseller application is under review.")
        return
    if not s.get("reseller_apps_enabled", True):
        await message.answer("🎁 Reseller applications are currently closed.")
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
        # promo broadcast buttons carry a hashed product id
        product = await svc.product_by_code(db, pid)
    if not product or product.get("status") != "active":
        await callback.message.answer("❌ Product unavailable.", reply_markup=KB.reply_menu())
        return
    plans = await svc.enrich_plans(db, product["_id"])
    desc = (product.get("description") or "").strip()
    plat = (product.get("platform") or "").strip()
    title = f"🎮 <b>{_esc(product['name'])}</b>"
    if plat:
        title += f" <i>({_esc(plat)})</i>"
    text = title
    if desc:
        text += f"\n\n{_esc(desc)}"
    text += "\n\n⏱️ <b>Select key duration:</b>"
    await callback.message.answer(text, parse_mode="HTML", reply_markup=KB.plans(plans, pid))


@router.callback_query(F.data.startswith("plan_"))
async def cb_plan(callback: types.CallbackQuery, user: dict, state: FSMContext, db):
    plan_id = callback.data[5:]
    await callback.answer("Creating order...")

    plan = await db.plans.find_one({"_id": ObjectId(plan_id), "status": "active"})
    if not plan:
        # promo broadcast buttons carry a hashed plan id
        plan = await svc.plan_by_code(db, plan_id)
    if not plan or plan.get("status", "active") != "active":
        await callback.message.answer("❌ Plan unavailable.")
        return
    product = await db.products.find_one({"_id": plan["product_id"], "status": "active"})
    if not product:
        await callback.message.answer("❌ Product unavailable.")
        return
    if await svc.stock_for_plan(db, plan["_id"]) <= 0:
        s = await svc.get_settings(db)
        admin = (s.get("support_username") or "").strip().lstrip("@") or "zerotrace0x"
        await callback.message.answer(
            f"🔴 Out of stock for this plan.\n\n📞 Contact admin: @{admin}",
            reply_markup=KB.reply_menu())
        return

    # ONE purchase action = ONE order. The per-user lock serializes rapid
    # clicks; a pending order for the SAME plan is reused (fresh payment
    # message, same order/QR reference) instead of duplicated.
    pv_cfg = payverify.PayVerifyConfig.from_env()
    fallback_expiry = svc.now_utc() + timedelta(
        minutes=pv_cfg.order_expiry_minutes)
    lock = await _purchase_lock(user["telegram_id"])
    async with lock:
        existing = await db.orders.find_one({
            "telegram_id": user["telegram_id"], "status": "pending",
            "plan_id": plan["_id"]})
        if existing:
            order = existing
            order["payment"] = await db.payments.find_one(
                {"order_id": existing["_id"]}) or {}
            old_pay = order["payment"]
            if old_pay.get("payment_msg_id"):
                try:
                    await callback.bot.delete_message(
                        old_pay.get("payment_chat_id") or user["telegram_id"],
                        old_pay["payment_msg_id"])
                except Exception:
                    pass
        else:
            # different plan -> retire old pending orders, then create fresh
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
            order = await svc.create_order(
                user, product, plan, db, expires_at=fallback_expiry)

    amount = order["amount"]
    upi_id = pv_cfg.default_upi_id
    purpose = order.get("verify_purpose")
    verify_expires = order.get("verify_expires_at")
    if purpose:
        verify_expires = verify_expires or fallback_expiry
        upi_uri = order.get("upi_uri") or payverify.build_upi_uri(
            upi_id, pv_cfg.payee_name,
            payverify.parse_amount(amount), purpose)
    else:
        purpose = payverify.generate_purpose(pv_cfg.purpose_prefix)
        verify_expires = fallback_expiry
        upi_uri = payverify.build_upi_uri(
            upi_id, pv_cfg.payee_name,
            payverify.parse_amount(amount), purpose)

    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$set": {
            "verify_purpose": purpose,
            "verify_created_at": order.get("verify_created_at") or svc.now_utc(),
            "verify_expires_at": verify_expires,
            "verify_status": "pending",
            "upi_uri": upi_uri,
            "updated_at": svc.now_utc(),
        }})
    await db.payments.update_one(
        {"public_order_id": order["order_id"]},
        {"$set": {"expiry_time": verify_expires,
                  "updated_at": svc.now_utc()}})

    expiry = verify_expires
    try:
        mins = max(1, math.ceil((expiry - svc.now_utc()).total_seconds() / 60))
    except Exception:
        mins = pv_cfg.order_expiry_minutes
    caption = (
        f"🎮 <b>Game:</b> {_esc(product['name'])}\n"
        f"⏱️ <b>Plan:</b> {_esc(plan['name'])}\n\n"
        f"💸 <b>Scan & Pay Exactly:</b> ₹{float(amount):.2f}\n\n"
        f"🆔 <b>Order ID:</b> <code>{order['order_id']}</code>\n"
        f"⏰ <b>Valid for {mins} minutes</b>\n\n"
        "Your key is sent automatically once payment is detected."
    )
    pay_kb = KB.payment(order["order_id"])

    # QR code: single send attempt - generated per-order UPI QR. On ANY
    # failure send text-only payment info; never chain photo fallbacks
    # (a timed-out send may still deliver -> duplicate messages/orders).
    _t0 = svc.now_utc()
    try:
        qr_bytes = await asyncio.to_thread(_qr_png, upi_uri)
    except Exception as e:
        logger.warning("QR generation failed: %s", e)
        qr_bytes = None
    logger.info("Order %s QR gen: %dms (%s)", order["order_id"],
                int((svc.now_utc() - _t0).total_seconds() * 1000),
                "ok" if qr_bytes else "FAILED")
    # ONE attempt only - no fallback chain. If the photo send fails/times
    # out, Telegram may still have delivered it; sending anything else
    # would duplicate the payment message. Order persists - retrying the
    # plan button reuses this same order with a fresh QR.
    try:
        if qr_bytes:
            sent = await asyncio.wait_for(
                callback.message.answer_photo(
                    BufferedInputFile(qr_bytes, filename="qr.png"),
                    caption=caption, parse_mode="HTML", reply_markup=pay_kb,
                ), timeout=25)
        else:
            sent = await callback.message.answer(
                caption, parse_mode="HTML", reply_markup=pay_kb)
    except Exception as e:
        logger.warning("Payment message send failed for %s: %r",
                       order["order_id"], e)
        return
    if sent is None:
        return

    # Persist message id so it can be deleted on cancel/expiry/new order
    pay_doc = await db.payments.find_one({"public_order_id": order["order_id"]})
    if pay_doc:
        await db.payments.update_one(
            {"_id": pay_doc["_id"]},
            {"$set": {"payment_msg_id": sent.message_id,
                      "payment_chat_id": sent.chat.id}})


# ---------------- Payment cancellation ----------------

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
    for kind in ("apk", "video"):
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
    if not s.get("reseller_apps_enabled", True):
        await callback.answer("Reseller applications are currently closed.", show_alert=True)
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
