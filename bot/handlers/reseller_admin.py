"""Reseller admin management - all owner controls via Telegram.
USDT amounts in cents via bot.rsvc."""

import logging
import secrets
import string
from datetime import datetime, timedelta

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import bot.svc as svc
import bot.rsvc as rs
from bot.db import Database
from bot.fsm import AdminStates
from config import Config

logger = logging.getLogger(__name__)
router = Router(name="reseller_admin")

_ESC = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@router.message.middleware()
@router.callback_query.middleware()
async def admin_guard(handler, event, data):
    if not data.get("is_admin"):
        if isinstance(event, types.CallbackQuery):
            await event.answer("⛔ Admin only", show_alert=True)
        return None
    return await handler(event, data)


def _ikb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _btn(text, cb):
    return InlineKeyboardButton(text=text, callback_data=cb)


async def _log(db, admin_id, action, details=None):
    try:
        await db.admin_logs.insert_one({
            "admin_id": str(admin_id), "action": action,
            "details": details or {}, "created_at": svc.now_utc()})
    except Exception:
        pass


async def _rsearch_kb(db, flt=None):
    rs_ = await db.resellers.find(flt or {}).sort("created_at", -1).to_list(30)
    rows = []
    for r in rs_:
        bal = rs.usdt_fmt(r.get("balance_cents", 0))
        rows.append([_btn(
            f"{'🟢' if r.get('status')=='active' else '🔴' if r.get('status')=='suspended' else '🟡'} "
            f"{r['telegram_id']} @{r.get('username') or '-'} · {bal}",
            f"radm_{r['telegram_id']}")])
    rows.append([_btn("➕ New Code", "rac_gen"), _btn("🔙 Menu", "radm_menu")])
    return _ikb(rows)


# ---------------- menu ----------------

async def send_admin_panel(message, db):
    """Send the reseller management panel as a NEW message (used by /admin
    markup button and adm_resellers callback)."""
    rsys = await rs.rsettings(db)
    en = "🟢 ON" if rsys.get("reseller_enabled") else "🔴 OFF"
    await message.answer(
        "👑 <b>RESELLER MANAGEMENT</b>\n\n"
        f"System: <b>{en}</b> · Min recharge: <b>{rs.usdt_fmt(rsys.get('reseller_min_cents'))}</b> USDT\n\n"
        "All money in <b>USDT</b>.",
        parse_mode="HTML",
        reply_markup=_ikb([
            [_btn("👥 All Resellers", "radm_list"),
             _btn("📩 Pending Apps", "radm_pending")],
            [_btn("🎟️ Redeem Codes", "radm_codes"),
             _btn("💵 Pricing", "radm_pricing")],
            [_btn("⚙️ Reseller Settings", "radm_settings"),
             _btn("📊 Analytics", "radm_analytics")],
            [_btn("🔙 Dashboard", "adm_dash")],
        ]))


@router.callback_query(F.data == "adm_resellers")
async def cb_menu(callback: types.CallbackQuery, db):
    await callback.answer()
    await send_admin_panel(callback.message, db)


# ---------------- reseller list / detail ----------------

@router.callback_query(F.data == "radm_list")
async def cb_list(callback: types.CallbackQuery, db):
    await callback.answer()
    await callback.message.answer("👥 <b>ALL RESELLERS</b>\n\nSelect one:",
                                  parse_mode="HTML",
                                  reply_markup=await _rsearch_kb(db))


@router.callback_query(F.data == "radm_search")
async def cb_search(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.rs_search)
    await callback.message.answer(
        "🔍 Send Telegram ID or @username to find a reseller:")


@router.message(AdminStates.rs_search, F.text)
async def st_search(m: types.Message, state: FSMContext, db):
    data = await state.get_data()
    kind = data.get("kind", "reseller")
    await state.clear()
    q = m.text.strip()
    if kind == "code":
        c = await db.redeem_codes.find_one({"code": q.upper()})
        if not c:
            await m.answer("❌ Code not found.",
                           reply_markup=_ikb([[_btn("🔙 Codes", "radm_codes")]]))
            return
        await m.answer(
            f"🎟️ <code>{c['code']}</code> · {rs.usdt_fmt(c.get('amount_cents'))} USDT · "
            f"{c.get('status')} · by {c.get('redeemed_by','-')}",
            parse_mode="HTML",
            reply_markup=_ikb([[_btn("🔙 Codes", "radm_codes")]]))
        return
    try:
        tid = int(q)
        r = await db.resellers.find_one({"telegram_id": tid})
        rows = [_btn(f"{tid}", f"radm_{tid}")] if r else []
    except ValueError:
        rs_ = await db.resellers.find({"username": q}).to_list(10)
        rows = [_btn(f"{r['telegram_id']} @{r.get('username')}", f"radm_{r['telegram_id']}")
                for r in rs_]
    if not rows:
        await m.answer("❌ No reseller found.", reply_markup=_ikb(
            [[_btn("🔙 Resellers", "adm_resellers")]]))
        return
    await m.answer("Found:", reply_markup=_ikb(rows +
        [[_btn("🔙 Resellers", "adm_resellers")]]))


@router.callback_query(F.data.regexp(r"^radm_\d+$"))
async def cb_detail(callback: types.CallbackQuery, db):
    tid = int(callback.data[5:])
    await callback.answer()
    r = await db.resellers.find_one({"telegram_id": tid})
    if not r:
        await callback.message.answer("❌ Reseller not found.")
        return
    orders = await db.orders.find(
        {"telegram_id": tid, "source": "reseller"}).to_list(500)
    spent = sum(int(o.get("price_usdt_cents", 0)) for o in orders)
    status = r.get("status", "?")
    await callback.message.answer(
        "👤 <b>RESELLER</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 <code>{tid}</code>\n"
        f"👤 @{_ESC(r.get('username') or '-')} · {_ESC(r.get('first_name') or '')}\n"
        f"🎫 Code: <code>{_ESC(r.get('reseller_code','-'))}</code>\n"
        f"📊 Status: <b>{_ESC(status)}</b>"
        + (f"\n🚫 Reason: {_ESC(r.get('suspend_reason',''))}" if status == "suspended" else "")
        + f"\n💰 Balance: <b>{rs.usdt_fmt(r.get('balance_cents',0))}</b> USDT\n"
        f"🛒 Purchases: <b>{len(orders)}</b> · Spent: <b>{rs.usdt_fmt(spent)}</b> USDT\n"
        f"📅 Joined: {_ESC(svc.fmt_ist(r.get('created_at')))}\n"
        f"✅ Approved: {_ESC(svc.fmt_ist(r.get('approved_at')))}",
        parse_mode="HTML",
        reply_markup=_ikb([
            [_btn("💰 Wallet ±", f"raw_{tid}"),
             _btn("🎟️ Codes", f"rcd_{tid}")],
            [_btn("💵 Prices", f"rpr_{tid}"),
             _btn("📜 Txns", f"rtx_{tid}")],
            [_btn("🚫 Suspend" if status == "active" else "✅ Activate",
                  f"rst_{tid}"),
             _btn("🗑 Reject" if status == "pending" else "🔙 List", "radm_list")],
            [_btn("🔙 Resellers", "adm_resellers")],
        ]))


# ---------------- pending applications ----------------

@router.callback_query(F.data == "radm_pending")
async def cb_pending(callback: types.CallbackQuery, db):
    await callback.answer()
    apps = await db.resellers.find({"status": "pending"}).sort("created_at", 1).to_list(50)
    if not apps:
        await callback.message.answer("✅ No pending applications.",
                                      reply_markup=_ikb([[_btn("🔙 Menu", "adm_resellers")]]))
        return
    rows = []
    for a in apps:
        rows.append([_btn(
            f"🟡 {a['telegram_id']} @{a.get('username') or '-'} · "
            f"{_ESC(svc.fmt_ist(a.get('created_at')))[:16]}",
            f"radm_{a['telegram_id']}")])
    rows.append([_btn("🔙 Menu", "adm_resellers")])
    await callback.message.answer("📩 <b>PENDING APPLICATIONS</b>", parse_mode="HTML",
                                  reply_markup=_ikb(rows))


# reuse existing approve/reject callbacks from reseller.py (res_ok_/res_no_)
# but route new pending list through detail for suspend/etc.


# ---------------- wallet adjust ----------------

@router.callback_query(F.data.regexp(r"^raw_\d+$"))
async def cb_wallet(callback: types.CallbackQuery, state: FSMContext):
    tid = int(callback.data[4:])
    await callback.answer()
    await state.set_state(AdminStates.rs_amount)
    await state.update_data(tid=tid)
    await callback.message.answer(
        f"💰 Wallet adjust for <code>{tid}</code>\n\n"
        "Send amount in USDT:\n"
        "• <code>+50</code> credit $50\n"
        "• <code>-20</code> deduct $20\n"
        "• Optionally add note after amount: <code>+50 topup</code>",
        parse_mode="HTML")


@router.message(AdminStates.rs_amount, F.text)
async def st_wallet(m: types.Message, state: FSMContext, db):
    data = await state.get_data()
    tid = data["tid"]
    parts = m.text.strip().split(None, 1)
    try:
        sign = 1 if parts[0].startswith("+") else -1 if parts[0].startswith("-") else 1
        cents = rs.usdt_parse(parts[0].lstrip("+-"))
        if cents is None or cents == 0:
            raise ValueError
        cents *= sign
    except (ValueError, IndexError):
        await m.answer("❌ Invalid amount. Use e.g. <code>+50</code> or <code>-20</code>.",
                       parse_mode="HTML")
        return
    note = parts[1] if len(parts) > 1 else ("admin credit" if cents > 0 else "admin debit")
    r = await db.resellers.find_one({"telegram_id": tid})
    if not r:
        await state.clear()
        await m.answer("❌ Reseller not found.")
        return
    new_bal = await rs.wallet_adjust(db, r, cents,
        "admin_credit" if cents > 0 else "admin_debit", note, m.from_user.id)
    await state.clear()
    if new_bal is None:
        await m.answer(f"❌ Debit refused - balance too low (negatives disabled).",
                       reply_markup=_ikb([[_btn("🔙 Reseller", f"radm_{tid}")]]))
        return
    await _log(db, m.from_user.id, "reseller_wallet_adjust",
               {"tid": tid, "cents": cents, "note": note})
    await m.answer(
        f"✅ {'Credited' if cents>0 else 'Deducted'} {rs.usdt_fmt(abs(cents))} USDT\n"
        f"👛 New balance: <b>{rs.usdt_fmt(new_bal)}</b> USDT",
        parse_mode="HTML",
        reply_markup=_ikb([[_btn("🔙 Reseller", f"radm_{tid}")]]))
    try:
        await m.bot.send_message(
            tid,
            f"💰 <b>Wallet {'Credit' if cents>0 else 'Debit'} — {rs.usdt_fmt(abs(cents))} USDT</b>\n\n"
            f"📝 {_ESC(note)}\n"
            f"👛 New balance: <b>{rs.usdt_fmt(new_bal)}</b> USDT",
            parse_mode="HTML")
    except Exception:
        pass


# ---------------- suspend / activate / reject ----------------

@router.callback_query(F.data.regexp(r"^rst_\d+$"))
async def cb_suspend(callback: types.CallbackQuery, state: FSMContext):
    tid = int(callback.data[4:])
    await callback.answer()
    await state.set_state(AdminStates.rs_suspend_reason)
    await state.update_data(tid=tid, action="toggle")
    await callback.message.answer(
        "🚫 Send suspension reason (or 'activate' to reactivate):")


@router.message(AdminStates.rs_suspend_reason, F.text)
async def st_suspend(m: types.Message, state: FSMContext, db):
    data = await state.get_data()
    tid = data["tid"]
    await state.clear()
    r = await db.resellers.find_one({"telegram_id": tid})
    if not r:
        await m.answer("❌ Reseller not found.")
        return
    if r.get("status") == "active":
        reason = m.text.strip() or "Suspended by admin"
        await db.resellers.update_one({"_id": r["_id"]}, {"$set": {
            "status": "suspended", "suspend_reason": reason,
            "updated_at": svc.now_utc()}})
        await _log(db, m.from_user.id, "reseller_suspend", {"tid": tid, "reason": reason})
        try:
            await m.bot.send_message(tid,
                f"🚫 Your reseller account was suspended.\n\nReason: {reason}")
        except Exception:
            pass
        await m.answer(f"🚫 Reseller {tid} suspended.")
    else:
        await db.resellers.update_one({"_id": r["_id"]}, {"$set": {
            "status": "active", "suspend_reason": "",
            "updated_at": svc.now_utc()}})
        await _log(db, m.from_user.id, "reseller_activate", {"tid": tid})
        try:
            await m.bot.send_message(tid, "✅ Your reseller account is active again!")
        except Exception:
            pass
        await m.answer(f"✅ Reseller {tid} reactivated.")


# approve / reject pending (kept from old reseller.py logic, extended)
@router.callback_query(F.data.startswith("res_ok_"))
async def res_approve(callback: types.CallbackQuery, db):
    tid = int(callback.data[7:])
    await callback.answer("Approving...")
    r = await db.resellers.find_one({"telegram_id": tid, "status": "pending"})
    if not r:
        await callback.message.answer("⚠️ Application not found or already processed.")
        return
    code = f"RS{tid % 100000:05d}"
    while await db.resellers.find_one({"reseller_code": code}):
        code = "RS" + "".join(secrets.choice(string.digits) for _ in range(6))
    await db.resellers.update_one({"_id": r["_id"]}, {"$set": {
        "status": "active", "reseller_code": code,
        "balance_cents": 0, "price_overrides": {},
        "approved_at": svc.now_utc(), "updated_at": svc.now_utc()}})
    await _log(db, callback.from_user.id, "reseller_approve", {"tid": tid})
    await callback.message.answer(f"✅ Reseller <code>{tid}</code> approved. Code: {code}",
                                  parse_mode="HTML")
    try:
        await callback.bot.send_message(tid,
            "🎉 Your reseller application was approved!\n\n"
            f"Code: <code>{code}</code>\n\n"
            "Open 👑 Resellers → 🏪 Reseller Panel to start.",
            parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data.startswith("res_no_"))
async def res_reject(callback: types.CallbackQuery, db):
    tid = int(callback.data[7:])
    await callback.answer("Rejecting...")
    r = await db.resellers.find_one({"telegram_id": tid, "status": "pending"})
    if not r:
        await callback.message.answer("⚠️ Not found or already processed.")
        return
    await db.resellers.update_one({"_id": r["_id"]}, {"$set": {
        "status": "rejected", "updated_at": svc.now_utc()}})
    await _log(db, callback.from_user.id, "reseller_reject", {"tid": tid})
    await callback.message.answer(f"❌ Reseller <code>{tid}</code> rejected.",
                                  parse_mode="HTML")
    try:
        await callback.bot.send_message(tid, "❌ Your reseller application was not approved.")
    except Exception:
        pass


# ---------------- redeem codes admin ----------------

@router.callback_query(F.data == "radm_codes")
async def cb_codes_menu(callback: types.CallbackQuery, db):
    await callback.answer()
    total = await db.redeem_codes.count_documents({})
    unused = await db.redeem_codes.count_documents({"status": "unused"})
    redeemed = await db.redeem_codes.count_documents({"status": "redeemed"})
    await callback.message.answer(
        "🎟️ <b>REDEEM CODES</b>\n\n"
        f"Total: {total} · Unused: {unused} · Redeemed: {redeemed}\n\nAll amounts in USDT.",
        parse_mode="HTML",
        reply_markup=_ikb([
            [_btn("➕ Generate", "rac_gen"),
             _btn("📦 Bulk Generate", "rac_bulk")],
            [_btn("📋 Unused", "rac_list_unused"),
             _btn("✅ Redeemed", "rac_list_redeemed")],
            [_btn("🚫 Revoked", "rac_list_revoked"),
             _btn("🔍 Search", "rac_search")],
            [_btn("🔙 Menu", "adm_resellers")],
        ]))


@router.callback_query(F.data == "rac_gen")
async def cb_gen1(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.rs_code_amount)
    await state.update_data(count=1, bulk=False)
    await callback.message.answer(
        "🎟️ Generate <b>1</b> code\n\nSend amount in USDT (e.g. <code>25</code> for $25):",
        parse_mode="HTML")


@router.callback_query(F.data == "rac_bulk")
async def cb_genbulk(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.rs_code_amount)
    await state.update_data(count=10, bulk=True)
    await callback.message.answer(
        "🎟️ Bulk generate <b>10</b> codes\n\nSend amount per code in USDT (e.g. <code>10</code>):",
        parse_mode="HTML")


@router.message(AdminStates.rs_code_amount, F.text)
async def st_code_amount(m: types.Message, state: FSMContext):
    data = await state.get_data()
    cents = rs.usdt_parse(m.text)
    if cents is None or cents <= 0:
        await m.answer("❌ Invalid amount. Send a positive number, e.g. <code>25</code>.",
                       parse_mode="HTML")
        return
    await state.update_data(cents=cents)
    await state.set_state(AdminStates.rs_code_expiry)
    await m.answer(
        f"Amount: <b>{rs.usdt_fmt(cents)}</b> USDT per code\n\n"
        "Send expiry in <b>days</b> (e.g. <code>30</code>), or <code>never</code>:",
        parse_mode="HTML")


@router.message(AdminStates.rs_code_expiry, F.text)
async def st_code_expiry(m: types.Message, state: FSMContext, db):
    data = await state.get_data()
    text = m.text.strip().lower()
    exp = None
    if text not in ("never", "no", "none", "-"):
        try:
            days = int(text)
            exp = svc.now_utc() + timedelta(days=days)
        except ValueError:
            await m.answer("❌ Send days as a number or <code>never</code>.", parse_mode="HTML")
            return
    count = data.get("count", 1)
    await state.clear()
    codes = await rs.gen_codes(db, data["cents"], count, exp,
                               note=f"admin gen {svc.fmt_ist(svc.now_utc())[:10]}")
    await _log(db, m.from_user.id, "redeem_gen",
               {"count": count, "cents": data["cents"]})
    body = "\n".join(codes)
    if len(codes) > 15:
        from aiogram.types import BufferedInputFile
        await m.answer_document(
            BufferedInputFile(body.encode(), filename="codes.txt"),
            caption=f"🎟️ {len(codes)} codes × {rs.usdt_fmt(data['cents'])} USDT")
    else:
        await m.answer(f"🎟️ <b>{len(codes)} code(s)</b> × {rs.usdt_fmt(data['cents'])} USDT"
                       + (f" · expires {svc.fmt_ist(exp)}" if exp else " · no expiry"),
                       parse_mode="HTML")
        await m.answer(f"<code>{body}</code>", parse_mode="HTML")


async def _code_list(callback, db, flt, title):
    codes = await db.redeem_codes.find(flt).sort("created_at", -1).to_list(30)
    if not codes:
        await callback.message.answer(f"📭 No {title} codes.",
                                      reply_markup=_ikb([[_btn("🔙 Codes", "radm_codes")]]))
        return
    rows = []
    for c in codes:
        mark = {"unused": "🟢", "redeemed": "✅", "revoked": "🚫"}.get(c.get("status"), "•")
        extra = f" → {c.get('redeemed_by')}" if c.get("redeemed_by") else ""
        rows.append([_btn(
            f"{mark} {c['code']} · {rs.usdt_fmt(c.get('amount_cents'))}{extra}",
            f"rcx_{c['code']}")])
    rows.append([_btn("🔙 Codes", "radm_codes")])
    await callback.message.answer(f"🎟️ <b>{title.upper()} CODES</b>", parse_mode="HTML",
                                  reply_markup=_ikb(rows))


@router.callback_query(F.data == "rac_list_unused")
async def cb_lu(callback, db):
    await callback.answer()
    await _code_list(callback, db, {"status": "unused"}, "unused")


@router.callback_query(F.data == "rac_list_redeemed")
async def cb_lr(callback, db):
    await callback.answer()
    await _code_list(callback, db, {"status": "redeemed"}, "redeemed")


@router.callback_query(F.data == "rac_list_revoked")
async def cb_lv(callback, db):
    await callback.answer()
    await _code_list(callback, db, {"status": "revoked"}, "revoked")


@router.callback_query(F.data == "rac_search")
async def cb_csearch(callback, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.rs_search)
    await state.update_data(kind="code")
    await callback.message.answer("🔍 Send code to inspect (e.g. R-XXXXXXXXXX):")


@router.callback_query(F.data.startswith("rcx_"))
async def cb_code_detail(callback: types.CallbackQuery, db):
    code = callback.data[4:]
    await callback.answer()
    c = await db.redeem_codes.find_one({"code": code})
    if not c:
        await callback.message.answer("❌ Code not found.")
        return
    await callback.message.answer(
        "🎟️ <b>CODE</b>\n\n"
        f"🔑 <code>{c['code']}</code>\n"
        f"💰 {rs.usdt_fmt(c.get('amount_cents'))} USDT\n"
        f"📊 Status: <b>{c.get('status')}</b>\n"
        f"👤 Redeemed by: <code>{c.get('redeemed_by','-')}</code>\n"
        f"📅 Redeemed: {_ESC(svc.fmt_ist(c.get('redeemed_at')))}\n"
        f"⏳ Expires: {_ESC(svc.fmt_ist(c.get('expires_at')))}\n"
        f"📝 {_ESC(c.get('note',''))}",
        parse_mode="HTML",
        reply_markup=_ikb([
            [_btn("🚫 Revoke" if c.get("status") == "unused" else "—",
                  f"rcv_{c['code']}")],
            [_btn("🔙 Codes", "radm_codes")],
        ]))


@router.callback_query(F.data.startswith("rcv_"))
async def cb_revoke(callback: types.CallbackQuery, db):
    code = callback.data[4:]
    await callback.answer("Revoking...")
    c = await db.redeem_codes.find_one({"code": code, "status": "unused"})
    if not c:
        await callback.message.answer("⚠️ Only unused codes can be revoked.")
        return
    await db.redeem_codes.update_one({"_id": c["_id"]},
        {"$set": {"status": "revoked"}})
    await _log(db, callback.from_user.id, "code_revoke", {"code": code})
    await callback.message.answer(f"🚫 Code <code>{code}</code> revoked.",
                                  parse_mode="HTML")


# ---------------- pricing ----------------

@router.callback_query(F.data == "radm_pricing")
async def cb_pricing(callback: types.CallbackQuery, db):
    await callback.answer()
    products = await db.products.find({"status": "active"}).sort("display_order", 1).to_list(50)
    rows = []
    for p in products:
        plans = await svc.enrich_plans(db, p["_id"])
        rows.append([_btn(f"🎮 {p['name']} ({len(plans)} plans)", f"rpp_{p['_id']}")])
    rows.append([_btn("👤 Individual Prices", "rip_menu"),
                 _btn("🔙 Menu", "adm_resellers")])
    await callback.message.answer(
        "💵 <b>RESELLER PRICING (USDT)</b>\n\nGlobal default per plan, "
        "or set individual overrides per reseller.",
        parse_mode="HTML", reply_markup=_ikb(rows))


@router.callback_query(F.data.startswith("rpp_"))
async def cb_product_prices(callback: types.CallbackQuery, db):
    pid = callback.data[4:]
    await callback.answer()
    product = await db.products.find_one({"_id": svc.ObjectId(pid)}) if hasattr(svc, "ObjectId") else None
    if not product:
        product = await svc.product_by_code(db, pid)
    if not product:
        await callback.message.answer("❌ Product not found.")
        return
    plans = await svc.enrich_plans(db, product["_id"])
    rows = []
    for pl in plans:
        cur = pl.get("reseller_price_cents")
        label = f"⏱️ {pl['name']} · ₹{pl.get('price','-')} → " + \
                (rs.usdt_fmt(cur) if cur is not None else "❓ not set")
        rows.append([_btn(label, f"rps_{svc.cbid(pl['_id'])}")])
    rows.append([_btn("🔙 Pricing", "radm_pricing")])
    await callback.message.answer(
        f"🎮 <b>{_ESC(product['name'])}</b>\n\nGlobal reseller prices (USDT):",
        parse_mode="HTML", reply_markup=_ikb(rows))


@router.callback_query(F.data.startswith("rps_"))
async def cb_set_price(callback: types.CallbackQuery, state: FSMContext, db):
    code = callback.data[4:]
    plan = await svc.plan_by_code(db, code)
    if not plan:
        await callback.answer("Plan not found.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.rs_price_value)
    await state.update_data(plan_id=str(plan["_id"]), scope="global")
    cur = plan.get("reseller_price_cents")
    await callback.message.answer(
        f"💵 Set global reseller price for <b>{_ESC(plan['name'])}</b>\n\n"
        f"Current: {rs.usdt_fmt(cur) if cur is not None else 'not set'}\n"
        f"Retail: ₹{plan.get('price','-')}\n\n"
        "Send USDT amount (e.g. <code>3.50</code>), or <code>clear</code> to remove:",
        parse_mode="HTML")


@router.message(AdminStates.rs_price_value, F.text)
async def st_price_value(m: types.Message, state: FSMContext, db):
    data = await state.get_data()
    await state.clear()
    plan = await db.plans.find_one({"_id": svc.ObjectId(data["plan_id"])})
    if not plan:
        await m.answer("❌ Plan not found.")
        return
    text = m.text.strip().lower()
    if text == "clear":
        await db.plans.update_one({"_id": plan["_id"]},
            {"$unset": {"reseller_price_cents": ""}})
        await m.answer("✅ Global price cleared.",
                       reply_markup=_ikb([[_btn("🔙 Pricing", "radm_pricing")]]))
        return
    cents = rs.usdt_parse(m.text)
    if cents is None or cents < 0:
        await m.answer("❌ Invalid amount. Send e.g. <code>3.50</code>.", parse_mode="HTML")
        return
    await rs.set_global_price(db, plan["_id"], cents)
    await _log(db, m.from_user.id, "reseller_price_set",
               {"plan": plan.get("name"), "cents": cents})
    await m.answer(f"✅ <b>{_ESC(plan['name'])}</b> global reseller price = "
                   f"<b>{rs.usdt_fmt(cents)}</b> USDT",
                   parse_mode="HTML",
                   reply_markup=_ikb([[_btn("🔙 Pricing", "radm_pricing")]]))


# ---------------- individual overrides ----------------

@router.callback_query(F.data == "rip_menu")
async def cb_ip_menu(callback: types.CallbackQuery, db):
    await callback.answer()
    await callback.message.answer(
        "⚙️ <b>INDIVIDUAL PRICING</b>\n\nSelect a reseller to customize their prices:",
        parse_mode="HTML",
        reply_markup=await _rsearch_kb(db))


@router.callback_query(F.data.regexp(r"^rpr_\d+$"))
async def cb_reseller_prices(callback: types.CallbackQuery, db):
    tid = int(callback.data[4:])
    await callback.answer()
    r = await db.resellers.find_one({"telegram_id": tid})
    if not r:
        await callback.message.answer("❌ Reseller not found.")
        return
    products = await db.products.find({"status": "active"}).sort("display_order", 1).to_list(50)
    rows = []
    for p in products:
        plans = await svc.enrich_plans(db, p["_id"])
        for pl in plans:
            eff = await rs.plan_price_cents(db, r, pl)
            glob = pl.get("reseller_price_cents")
            tag = "★" if (r.get("price_overrides") or {}).get(str(pl["_id"])) is not None else " "
            label = f"{tag} {_ESC(pl['name'][:18])} · " + \
                    (rs.usdt_fmt(eff) if eff is not None else "❓") + \
                    (f" (global {rs.usdt_fmt(glob)})" if glob is not None else "")
            rows.append([_btn(label, f"rpi_{tid}_{svc.cbid(pl['_id'])}")])
    rows.append([_btn("🗑 Reset all overrides", f"rip_reset_{tid}"),
                 _btn("🔙 Pricing", "radm_pricing")])
    await callback.message.answer(
        f"⚙️ Prices for <code>{tid}</code>\n★ = individual override\n\nSelect plan:",
        parse_mode="HTML", reply_markup=_ikb(rows))


@router.callback_query(F.data.regexp(r"^rpi_\d+_"))
async def cb_set_override(callback: types.CallbackQuery, state: FSMContext):
    # rpi_{tid}_{plan_cbid}
    parts = callback.data.split("_")
    tid = int(parts[1])
    plan_code = parts[2]
    await callback.answer()
    await state.set_state(AdminStates.rs_override_value)
    await state.update_data(tid=tid, plan_code=plan_code)
    await callback.message.answer(
        "💵 Send individual USDT price (e.g. <code>2.80</code>), "
        "or <code>global</code> to remove override:", parse_mode="HTML")


@router.message(AdminStates.rs_override_value, F.text)
async def st_override(m: types.Message, state: FSMContext, db):
    data = await state.get_data()
    await state.clear()
    plan = await svc.plan_by_code(db, data["plan_code"])
    r = await db.resellers.find_one({"telegram_id": data["tid"]})
    if not plan or not r:
        await m.answer("❌ Plan or reseller not found.")
        return
    text = m.text.strip().lower()
    if text == "global":
        await rs.set_override(db, r["_id"], plan["_id"], None)
        await m.answer(f"✅ Override removed for <b>{_ESC(plan['name'])}</b> - "
                       "back to global price.", parse_mode="HTML",
                       reply_markup=_ikb([[_btn("🔙 Prices", f"rpr_{data['tid']}")]]))
        return
    cents = rs.usdt_parse(m.text)
    if cents is None or cents < 0:
        await m.answer("❌ Invalid amount.", parse_mode="HTML")
        return
    await rs.set_override(db, r["_id"], plan["_id"], cents)
    await _log(db, m.from_user.id, "reseller_price_override",
               {"tid": data["tid"], "plan": plan.get("name"), "cents": cents})
    await m.answer(f"✅ <b>{data['tid']}</b> now pays <b>{rs.usdt_fmt(cents)}</b> USDT "
                   f"for <b>{_ESC(plan['name'])}</b>", parse_mode="HTML",
                   reply_markup=_ikb([[_btn("🔙 Prices", f"rpr_{data['tid']}")]]))


@router.callback_query(F.data.regexp(r"^rip_reset_\d+$"))
async def cb_reset_overrides(callback: types.CallbackQuery, db):
    tid = int(callback.data[10:])
    await callback.answer("Resetting...")
    r = await db.resellers.find_one({"telegram_id": tid})
    if not r:
        await callback.message.answer("❌ Reseller not found.")
        return
    await db.resellers.update_one({"_id": r["_id"]},
        {"$set": {"price_overrides": {}, "updated_at": svc.now_utc()}})
    await _log(db, callback.from_user.id, "reseller_overrides_reset", {"tid": tid})
    await callback.message.answer(f"✅ All price overrides cleared for {tid} - "
                                  "global prices apply.",
                                  reply_markup=_ikb([[_btn("🔙 Pricing", "radm_pricing")]]))


# ---------------- transactions / analytics ----------------

@router.callback_query(F.data.regexp(r"^rtx_\d+$"))
async def cb_reseller_txns(callback: types.CallbackQuery, db):
    tid = int(callback.data[4:])
    await callback.answer()
    txns = await db.wallet_txns.find({"telegram_id": tid}).sort("created_at", -1).to_list(30)
    if not txns:
        await callback.message.answer("📜 No transactions.")
        return
    lines = [f"📜 <b>TRANSACTIONS - {tid}</b>\n━━━━━━━━━━━━━━━━━━"]
    for t in txns:
        amt = int(t.get("amount_cents", 0))
        sign = "+" if amt >= 0 else "-"
        lines.append(f"{sign}{rs.usdt_fmt(abs(amt))} · {t.get('type')} · "
                     f"{_ESC(t.get('note',''))[:30]} · {_ESC(svc.fmt_ist(t.get('created_at')))[:16]}")
    await callback.message.answer("\n".join(lines)[:3900], parse_mode="HTML",
                                  reply_markup=_ikb([[_btn("🔙 Reseller", f"radm_{tid}")]]))


@router.callback_query(F.data == "radm_analytics")
async def cb_analytics(callback: types.CallbackQuery, db):
    await callback.answer()
    resellers = await db.resellers.find({"status": "active"}).to_list(500)
    total_bal = sum(int(r.get("balance_cents", 0)) for r in resellers)
    orders = await db.orders.find({"source": "reseller"}).to_list(2000)
    spent = sum(int(o.get("price_usdt_cents", 0)) for o in orders)
    txns = await db.wallet_txns.find({"type": {"$in": ["redeem", "admin_credit"]}}).to_list(2000)
    credited = sum(int(t.get("amount_cents", 0)) for t in txns
                   if int(t.get("amount_cents", 0)) > 0)
    pending = await db.resellers.count_documents({"status": "pending"})
    suspended = await db.resellers.count_documents({"status": "suspended"})
    await callback.message.answer(
        "📊 <b>RESELLER ANALYTICS</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Active: <b>{len(resellers)}</b> · Pending: <b>{pending}</b> · Suspended: <b>{suspended}</b>\n"
        f"💰 Wallets total: <b>{rs.usdt_fmt(total_bal)}</b> USDT\n"
        f"🛒 Reseller orders: <b>{len(orders)}</b>\n"
        f"💸 Reseller revenue: <b>{rs.usdt_fmt(spent)}</b> USDT\n"
        f"🎟️ Total credited: <b>{rs.usdt_fmt(credited)}</b> USDT",
        parse_mode="HTML", reply_markup=_ikb([[_btn("🔙 Menu", "adm_resellers")]]))


# ---------------- reseller settings ----------------

SETTING_LABELS = [
    ("reseller_enabled", "🏪 Reseller System"),
    ("reseller_apps_enabled", "📩 Applications"),
    ("reseller_purchases_enabled", "🛒 Wallet Purchases"),
    ("reseller_codes_enabled", "🎟️ Redeem Codes"),
    ("reseller_individual_pricing", "⚙️ Individual Pricing"),
    ("reseller_stats_enabled", "📊 Statistics"),
    ("reseller_min_enabled", "💵 Min Recharge Rule"),
    ("reseller_allow_negative", "➖ Allow Negative Balance"),
]


@router.callback_query(F.data == "radm_settings")
async def cb_settings(callback: types.CallbackQuery, db):
    await callback.answer()
    rsys = await rs.rsettings(db)
    rows = []
    for key, label in SETTING_LABELS:
        state = "🟢" if rsys.get(key) else "🔴"
        rows.append([_btn(f"{state} {label}", f"rstt_{key}")])
    rows.append([_btn(f"💰 Min Recharge: {rs.usdt_fmt(rsys.get('reseller_min_cents'))}",
                      "rst_min")])
    rows.append([_btn("🔙 Menu", "adm_resellers")])
    await callback.message.answer(
        "⚙️ <b>RESELLER SETTINGS</b>\n\nTap to toggle. Changes apply instantly.",
        parse_mode="HTML", reply_markup=_ikb(rows))


@router.callback_query(F.data.startswith("rstt_"))
async def cb_toggle(callback: types.CallbackQuery, db):
    key = callback.data[5:]
    if key not in dict(SETTING_LABELS) and key != "reseller_min_enabled":
        await callback.answer("Unknown setting.", show_alert=True)
        return
    new = await rs.toggle_rsetting(db, key)
    await _log(db, callback.from_user.id, "reseller_setting_toggle",
               {"key": key, "value": new})
    await callback.answer(f"{'🟢 Enabled' if new else '🔴 Disabled'}")
    await cb_settings(callback, db)


@router.callback_query(F.data == "rst_min")
async def cb_min(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.rs_min_recharge)
    await callback.message.answer(
        "💰 Send minimum recharge in USDT (e.g. <code>50</code> for $50):\n\n"
        "Applies to redeem codes when 'Min Recharge Rule' is ON "
        "(scope: every recharge). Admin wallet credits always bypass it.",
        parse_mode="HTML")


@router.message(AdminStates.rs_min_recharge, F.text)
async def st_min(m: types.Message, state: FSMContext, db):
    await state.clear()
    cents = rs.usdt_parse(m.text)
    if cents is None or cents < 0:
        await m.answer("❌ Invalid amount.", parse_mode="HTML")
        return
    await rs.rset(db, "reseller_min_cents", cents)
    await _log(db, m.from_user.id, "reseller_min_set", {"cents": cents})
    await m.answer(f"✅ Minimum recharge = <b>{rs.usdt_fmt(cents)}</b> USDT",
                   parse_mode="HTML",
                   reply_markup=_ikb([[_btn("🔙 Settings", "radm_settings")]]))
