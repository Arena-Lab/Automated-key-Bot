"""Reseller customer-facing panel - wallet, purchases, redeem, buy flow.
All money in USDT (integer cents via bot.rsvc)."""

import asyncio
import logging

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import bot.svc as svc
import bot.rsvc as rs
from bot.ui import KB
from bot.fsm import ResellerStates
from config import Config

logger = logging.getLogger(__name__)
router = Router(name="reseller_shop")

_ESC = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# per-reseller purchase locks (same pattern as customer shop)
_LOCKS = {}
_LOCKS_GUARD = asyncio.Lock()


async def _lock(tid: int) -> asyncio.Lock:
    async with _LOCKS_GUARD:
        lk = _LOCKS.get(tid)
        if lk is None:
            lk = _LOCKS[tid] = asyncio.Lock()
        return lk


def _ikb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _btn(text, cb):
    return InlineKeyboardButton(text=text, callback_data=cb)


async def _panel_kb(db, reseller) -> InlineKeyboardMarkup:
    bal = rs.usdt_fmt(reseller.get("balance_cents", 0))
    return _ikb([
        [_btn(f"💰 Wallet: {bal}", "rs_panel")],
        [_btn("🛒 Buy Products", "rs_buy"),
         _btn("🎟️ Redeem Code", "rs_redeem")],
        [_btn("📦 My Purchases", "rs_purchases"),
         _btn("💳 Transactions", "rs_txns")],
        [_btn("📊 My Statistics", "rs_stats"),
         _btn("👤 My Account", "rs_account")],
        [_btn("🔙 Shop Menu", "rs_close")],
    ])


async def _panel_text(db, reseller) -> str:
    bal = rs.usdt_fmt(reseller.get("balance_cents", 0))
    return (f"🏪 <b>RESELLER PANEL</b>\n\n"
            f"💰 Wallet Balance: <b>{bal}</b> USDT\n"
            f"🆔 Code: <code>{_ESC(reseller.get('reseller_code','-'))}</code>\n\n"
            f"All prices in <b>USDT</b>. Buy products at reseller rates, "
            f"pay from your wallet.")


async def _send_panel(message, db, reseller):
    await message.answer(await _panel_text(db, reseller), parse_mode="HTML",
                         reply_markup=await _panel_kb(db, reseller))


async def _require_reseller(message, db, tid=None):
    """Returns active reseller doc or sends a message and returns None.
    tid = the Telegram user id (callback.from_user.id for callbacks)."""
    uid = tid if tid is not None else message.from_user.id
    rsys = await rs.rsettings(db)
    if not rsys.get("reseller_enabled"):
        await message.answer("🔒 The reseller program is currently closed.")
        return None
    r = await rs.get_reseller(db, uid)
    if not r or r.get("status") == "pending":
        await message.answer("🎁 You are not an approved reseller yet. "
                             "Tap 👑 Resellers to apply.",
                             reply_markup=KB.reply_menu())
        return None
    if r.get("status") == "suspended":
        reason = r.get("suspend_reason") or "Policy violation"
        await message.answer(f"🚫 Your reseller account is suspended.\n\nReason: {_ESC(reason)}\n\n"
                             "Contact admin to reactivate.", parse_mode="HTML",
                             reply_markup=KB.reply_menu())
        return None
    if r.get("status") != "active":
        await message.answer("❌ Your reseller application was not approved.",
                             reply_markup=KB.reply_menu())
        return None
    return r


# ---------------- panel entry ----------------

@router.callback_query(F.data == "rs_panel")
async def cb_panel(callback: types.CallbackQuery, db):
    await callback.answer()
    r = await rs.get_reseller(db, callback.from_user.id)
    if not r or r.get("status") != "active":
        await callback.message.answer("🔒 Reseller panel unavailable.",
                                      reply_markup=KB.reply_menu())
        return
    await callback.message.answer(await _panel_text(db, r), parse_mode="HTML",
                                  reply_markup=await _panel_kb(db, r))


@router.callback_query(F.data == "rs_close")
async def cb_close(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("👋 Back to shop menu.", reply_markup=KB.reply_menu())


# ---------------- buy flow ----------------

@router.callback_query(F.data == "rs_buy")
async def cb_buy_products(callback: types.CallbackQuery, db):
    await callback.answer()
    r = await _require_reseller(callback.message, db, callback.from_user.id)
    if not r:
        return
    rsys = await rs.rsettings(db)
    if not rsys.get("reseller_purchases_enabled"):
        await callback.message.answer("🔒 Reseller purchases are disabled right now.",
                                      reply_markup=KB.reply_menu())
        return
    products = await db.products.find({"status": "active"}).sort("display_order", 1).to_list(100)
    if not products:
        await callback.message.answer("📦 No products available.", reply_markup=KB.reply_menu())
        return
    counts = await asyncio.gather(*[svc.product_stock_total(db, p["_id"]) for p in products])
    rows = []
    for p, c in zip(products, counts):
        label = p["name"] if c > 0 else f"{p['name']} (Out of stock)"
        rows.append([_btn(f"🎮 {label}", f"rsp_{p['_id']}")])
    rows.append([_btn("🔙 Panel", "rs_panel")])
    await callback.message.answer("🛒 <b>BUY PRODUCTS (USDT)</b>\n\nSelect a product:",
                                  parse_mode="HTML", reply_markup=_ikb(rows))


@router.callback_query(F.data.startswith("rsp_"))
async def cb_buy_plans(callback: types.CallbackQuery, db):
    pid = callback.data[4:]
    await callback.answer()
    product = await db.products.find_one({"_id": svc.ObjectId(pid), "status": "active"}) if hasattr(svc, "ObjectId") else None
    if not product:
        product = await svc.product_by_code(db, pid)
    if not product or product.get("status") != "active":
        await callback.message.answer("❌ Product unavailable.")
        return
    r = await rs.get_reseller(db, callback.from_user.id)
    plans = await svc.enrich_plans(db, product["_id"])
    rows = []
    for pl in plans:
        price = await rs.plan_price_cents(db, r, pl)
        if price is None:
            label = f"⏱️ {pl['name']} - price TBD"
        else:
            label = f"⏱️ {pl['name']} - {rs.usdt_fmt(price)}"
        if pl.get("stock", 0) <= 0:
            label += " (out)"
        rows.append([_btn(label, f"rspl_{svc.cbid(pl['_id'])}")])
    rows.append([_btn("🔙 Products", "rs_buy")])
    await callback.message.answer(
        f"🎮 <b>{_ESC(product['name'])}</b>\n\nSelect a plan (USDT prices):",
        parse_mode="HTML", reply_markup=_ikb(rows))


@router.callback_query(F.data.startswith("rspl_"))
async def cb_buy_confirm(callback: types.CallbackQuery, state: FSMContext, db):
    code = callback.data[5:]
    await callback.answer()
    plan = await svc.plan_by_code(db, code)
    if not plan or plan.get("status", "active") != "active":
        await callback.message.answer("❌ Plan unavailable.")
        return
    product = await db.products.find_one({"_id": plan["product_id"], "status": "active"})
    if not product:
        await callback.message.answer("❌ Product unavailable.")
        return
    r = await _require_reseller(callback.message, db, callback.from_user.id)
    if not r:
        return
    price = await rs.plan_price_cents(db, r, plan)
    if price is None:
        await callback.message.answer(
            "💬 Reseller price not configured for this plan. Contact admin.",
            reply_markup=KB.reply_menu())
        return
    stock = await svc.stock_for_plan(db, plan["_id"])
    if stock <= 0:
        admin = ""
        s = await svc.get_settings(db)
        admin = (s.get("support_username") or "").strip().lstrip("@")
        extra = f"\n\n📞 Contact admin: @{admin}" if admin else ""
        await callback.message.answer(f"🔴 Out of stock for this plan.{extra}",
                                      parse_mode="HTML", reply_markup=KB.reply_menu())
        return
    bal = int(r.get("balance_cents", 0))
    await state.set_state(ResellerStates.buy_confirm)
    await state.update_data(plan_id=str(plan["_id"]), product_id=str(product["_id"]),
                            price_cents=price)
    await callback.message.answer(
        "🛒 <b>CONFIRM PURCHASE</b>\n\n"
        f"🎮 Product: {_ESC(product['name'])}\n"
        f"⏱️ Plan: {_ESC(plan['name'])}\n"
        f"📦 Stock: {stock}\n"
        f"💰 Reseller Price: <b>{rs.usdt_fmt(price)}</b> USDT\n"
        f"👛 Wallet: {rs.usdt_fmt(bal)} USDT\n"
        f"💳 After: {rs.usdt_fmt(bal - price)} USDT\n\n"
        "Confirm?",
        parse_mode="HTML",
        reply_markup=_ikb([
            [_btn("✅ Confirm", "rs_confirm"), _btn("❌ Cancel", "rs_panel")]]))


@router.callback_query(F.data == "rs_confirm")
async def cb_buy_do(callback: types.CallbackQuery, state: FSMContext, db):
    data = await state.get_data()
    await callback.answer("Processing...")
    await state.clear()
    r = await _require_reseller(callback.message, db, callback.from_user.id)
    if not r:
        return
    plan = await db.plans.find_one({"_id": svc.ObjectId(data["plan_id"])})
    product = await db.products.find_one({"_id": svc.ObjectId(data["product_id"])})
    if not plan or not product:
        await callback.message.answer("❌ Item no longer available.")
        return
    # re-resolve price at purchase time (may have changed)
    price = await rs.plan_price_cents(db, r, plan)
    if price is None:
        await callback.message.answer("💬 Price not configured. Contact admin.")
        return
    lock = await _lock(r["telegram_id"])
    async with lock:
        ok, order, key, bal = await rs.reseller_buy(db, r, product, plan, price)
    if not ok:
        await callback.message.answer(f"❌ {order}", reply_markup=KB.reply_menu())
        return
    await callback.message.answer(
        "✅ <b>PURCHASE SUCCESSFUL</b>\n\n"
        f"🎮 {_ESC(product['name'])}\n"
        f"⏱️ {_ESC(plan['name'])}\n"
        f"🔑 Your Key: <code>{_ESC(key.get('key_value',''))}</code>\n"
        f"💰 Deducted: {rs.usdt_fmt(price)} USDT\n"
        f"👛 Remaining: {rs.usdt_fmt(bal)} USDT\n"
        f"🆔 Order: <code>{order['order_id']}</code>",
        parse_mode="HTML", reply_markup=KB.reply_menu())
    # deliver files like normal orders
    try:
        await svc.resend_product_files(callback.bot, r["telegram_id"], product)
    except Exception as e:
        logger.warning("reseller file resend failed: %s", e)


# ---------------- redeem ----------------

@router.callback_query(F.data == "rs_redeem")
async def cb_redeem(callback: types.CallbackQuery, state: FSMContext, db):
    await callback.answer()
    r = await _require_reseller(callback.message, db, callback.from_user.id)
    if not r:
        return
    rsys = await rs.rsettings(db)
    if not rsys.get("reseller_codes_enabled"):
        await callback.message.answer("🔒 Redeem codes are disabled.",
                                      reply_markup=KB.reply_menu())
        return
    await state.set_state(ResellerStates.redeem_code)
    await callback.message.answer(
        "🎟️ <b>REDEEM CODE</b>\n\nSend your redeem code (e.g. R-XXXXXXXXXX):",
        parse_mode="HTML")


@router.message(ResellerStates.redeem_code, F.text)
async def msg_redeem(message: types.Message, state: FSMContext, db):
    await state.clear()
    r = await _require_reseller(message, db)
    if not r:
        return
    lock = await _lock(r["telegram_id"])
    async with lock:
        ok, msg, bal = await rs.redeem_code(db, r, message.text)
    if ok:
        await message.answer(f"{msg}\n\n👛 New balance: {rs.usdt_fmt(bal)} USDT",
                             parse_mode="HTML", reply_markup=await _panel_kb(db, r))
    else:
        await message.answer(msg, reply_markup=KB.reply_menu())


# ---------------- history / stats / account ----------------

@router.callback_query(F.data == "rs_purchases")
async def cb_purchases(callback: types.CallbackQuery, db):
    await callback.answer()
    r = await rs.get_reseller(db, callback.from_user.id)
    if not r or r.get("status") != "active":
        return
    orders = await db.orders.find(
        {"telegram_id": r["telegram_id"], "source": "reseller"}
    ).sort("created_at", -1).to_list(30)
    if not orders:
        await callback.message.answer("📦 No purchases yet.", reply_markup=KB.reply_menu())
        return
    lines = ["📦 <b>MY PURCHASES</b>\n━━━━━━━━━━━━━━━━━━"]
    for o in orders:
        lines.append(
            f"\n🎮 {_ESC(o.get('product_name',''))}\n"
            f"⏱️ {_ESC(o.get('plan_name',''))}\n"
            f"🔑 <code>{_ESC(o.get('key_value',''))}</code>\n"
            f"💰 {rs.usdt_fmt(o.get('price_usdt_cents'))} USDT\n"
            f"🆔 <code>{o.get('order_id','')}</code> · {_ESC(svc.fmt_ist(o.get('created_at')))}")
    if len("\n".join(lines)) > 3800:
        await callback.message.answer("Too many purchases - showing latest 10.",
                                      reply_markup=KB.reply_menu())
        lines = lines[:10]
    await callback.message.answer("\n".join(lines)[:3900], parse_mode="HTML",
                                  reply_markup=KB.reply_menu())


@router.callback_query(F.data == "rs_txns")
async def cb_txns(callback: types.CallbackQuery, db):
    await callback.answer()
    r = await rs.get_reseller(db, callback.from_user.id)
    if not r or r.get("status") != "active":
        return
    txns = await db.wallet_txns.find(
        {"telegram_id": r["telegram_id"]}).sort("created_at", -1).to_list(30)
    if not txns:
        await callback.message.answer("💳 No transactions yet.", reply_markup=KB.reply_menu())
        return
    icons = {"redeem": "🎟️", "purchase": "🛒", "admin_credit": "➕",
             "admin_debit": "➖", "refund": "↩️"}
    lines = ["💳 <b>TRANSACTION HISTORY</b>\n━━━━━━━━━━━━━━━━━━"]
    for t in txns:
        amt = int(t.get("amount_cents", 0))
        sign = "+" if amt >= 0 else "-"
        lines.append(
            f"{icons.get(t.get('type'), '•')} {sign}{rs.usdt_fmt(abs(amt))} USDT "
            f"({t.get('type','')})\n"
            f"   {_ESC(t.get('note',''))} · bal {rs.usdt_fmt(t.get('balance_after_cents'))} · "
            f"{_ESC(svc.fmt_ist(t.get('created_at')))}")
    await callback.message.answer("\n".join(lines)[:3900], parse_mode="HTML",
                                  reply_markup=KB.reply_menu())


@router.callback_query(F.data == "rs_stats_view")
async def cb_stats_view(callback: types.CallbackQuery, db):
    await callback.answer()
    r = await rs.get_reseller(db, callback.from_user.id)
    if not r or r.get("status") != "active":
        return
    orders = await db.orders.find(
        {"telegram_id": r["telegram_id"], "source": "reseller"}
    ).to_list(500)
    txns = await db.wallet_txns.find(
        {"telegram_id": r["telegram_id"], "type": {"$ne": "purchase"}}
    ).to_list(500)
    spent = sum(int(o.get("price_usdt_cents", 0)) for o in orders)
    recharged = sum(int(t.get("amount_cents", 0)) for t in txns
                    if int(t.get("amount_cents", 0)) > 0)
    from collections import Counter
    top = Counter(o.get("product_name", "?") for o in orders).most_common(3)
    top_txt = "\n".join(f"   {_ESC(n)} ×{c}" for n, c in top) or "   -"
    await callback.message.answer(
        "📊 <b>MY STATISTICS</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🛒 Total Purchases: <b>{len(orders)}</b>\n"
        f"💸 Total Spent: <b>{rs.usdt_fmt(spent)}</b> USDT\n"
        f"🎟️ Total Recharged: <b>{rs.usdt_fmt(recharged)}</b> USDT\n"
        f"💳 Transactions: <b>{len(txns)}</b>\n\n"
        f"🏆 Top Products:\n{top_txt}",
        parse_mode="HTML", reply_markup=KB.reply_menu())


@router.callback_query(F.data == "rs_stats")
async def cb_stats(callback: types.CallbackQuery, db):
    # route to stats view
    await cb_stats_view(callback, db)


@router.callback_query(F.data == "rs_account")
async def cb_account(callback: types.CallbackQuery, db):
    await callback.answer()
    r = await rs.get_reseller(db, callback.from_user.id)
    if not r or r.get("status") != "active":
        return
    orders = await db.orders.count_documents(
        {"telegram_id": r["telegram_id"], "source": "reseller"})
    await callback.message.answer(
        "👤 <b>MY ACCOUNT</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Telegram ID: <code>{r['telegram_id']}</code>\n"
        f"🎫 Code: <code>{_ESC(r.get('reseller_code','-'))}</code>\n"
        f"📊 Status: <b>{_ESC(r.get('status',''))}</b>\n"
        f"💰 Balance: <b>{rs.usdt_fmt(r.get('balance_cents',0))}</b> USDT\n"
        f"🛒 Purchases: <b>{orders}</b>\n"
        f"📅 Joined: {_ESC(svc.fmt_ist(r.get('created_at')))}\n"
        f"✅ Approved: {_ESC(svc.fmt_ist(r.get('approved_at')))}",
        parse_mode="HTML", reply_markup=KB.reply_menu())
