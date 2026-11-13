"""Admin panel - complete Telegram-based management (all actions send new messages)"""

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.oid import ObjectId

from bot.db import Database
from bot.ui import KB
from bot.fsm import AdminStates
import bot.svc as svc
from config import Config

logger = logging.getLogger(__name__)
router = Router(name="admin")


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message.middleware()
@router.callback_query.middleware()
async def admin_guard(handler, event, data):
    if not data.get("is_admin"):
        if isinstance(event, types.CallbackQuery):
            await event.answer("⛔ Admin only", show_alert=True)
        return None
    return await handler(event, data)


async def _log(db, admin_id, action, details=None):
    try:
        await db.admin_logs.insert_one({
            "admin_id": str(admin_id), "action": action,
            "details": details or {}, "created_at": svc.now_utc(),
        })
    except Exception:
        pass


async def _dash_text(db) -> str:
    # Stats live in the Stats section only - dashboard stays clean
    return "⚜️ <b>KEY SHOP CONTROL PANEL</b>\n\nUse the buttons below to manage the shop."


async def _send_dash(message, db):
    await message.answer(await _dash_text(db), parse_mode="HTML",
                          reply_markup=KB.admin_dashboard())


# ================= Commands & dashboard =================

@router.message(F.text == "/admin")
async def cmd_admin(message: types.Message, db):
    await _send_dash(message, db)


@router.message(F.text == "/settings")
async def cmd_settings(message: types.Message, db):
    # admin_guard middleware restricts this to admins only
    await message.answer("⚙️ <b>BOT SETTINGS</b>", parse_mode="HTML",
                         reply_markup=await _settings_kb(db))


# ================= User block commands (admin only via admin_guard) =================

def _parse_tid(arg: str):
    arg = (arg or "").strip().lstrip("@")
    try:
        return int(arg)
    except ValueError:
        return None


async def _user_card(db, tid: int):
    return await db.users.find_one({"telegram_id": tid})


@router.message(F.text.regexp(r"^/blockuser(\s+\S+)?$"))
async def cmd_block_user(message: types.Message, db):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "🚫 <b>Block a user</b>\n\nUsage: <code>/blockuser USER_ID</code>\n\n"
            "The bot will stop responding to them entirely.",
            parse_mode="HTML")
        return
    tid = _parse_tid(parts[1])
    if not tid:
        await message.answer("❌ Invalid user ID. Send the numeric Telegram ID.")
        return
    if tid in {int(a) for a in Config.ADMIN_IDS}:
        await message.answer("⛔ Cannot block an admin.")
        return
    u = await _user_card(db, tid)
    await db.users.update_one(
        {"telegram_id": tid},
        {"$set": {"is_blocked": True, "updated_at": svc.now_utc()},
         "$setOnInsert": {"telegram_id": tid, "created_at": svc.now_utc()}},
        upsert=True)
    await _log(db, message.from_user.id, "block_user", {"tid": tid})
    name = _esc((u or {}).get("first_name") or (u or {}).get("username") or "-")
    await message.answer(
        f"🚫 <b>User blocked</b>\n\n"
        f"🆔 <code>{tid}</code>\n👤 {name}\n\n"
        "They will get no responses from the bot.\n"
        f"Undo: <code>/unblockuser {tid}</code>",
        parse_mode="HTML")


@router.message(F.text.regexp(r"^/unblockuser(\s+\S+)?$"))
async def cmd_unblock_user(message: types.Message, db):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "✅ <b>Unblock a user</b>\n\nUsage: <code>/unblockuser USER_ID</code>",
            parse_mode="HTML")
        return
    tid = _parse_tid(parts[1])
    if not tid:
        await message.answer("❌ Invalid user ID.")
        return
    u = await _user_card(db, tid)
    if not u:
        await message.answer(f"ℹ️ User <code>{tid}</code> not found in database.",
                             parse_mode="HTML")
        return
    await db.users.update_one({"telegram_id": tid},
        {"$set": {"is_blocked": False, "updated_at": svc.now_utc()}})
    await _log(db, message.from_user.id, "unblock_user", {"tid": tid})
    await message.answer(
        f"✅ <b>User unblocked</b>\n\n🆔 <code>{tid}</code>\n\n"
        "They can use the bot again.",
        parse_mode="HTML")


@router.message(F.text.regexp(r"^/blockedusers$"))
async def cmd_blocked_users(message: types.Message, db):
    users = await db.users.find({"is_blocked": True}).to_list(200)
    if not users:
        await message.answer("✅ <b>Blocked users</b>\n\nNo users are blocked.",
                             parse_mode="HTML")
        return
    lines = ["🚫 <b>BLOCKED USERS</b>",
             f"<i>{len(users)} user(s)</i>\n"]
    for u in users[:50]:
        tid = u.get("telegram_id")
        name = _esc(u.get("first_name") or u.get("username") or "-")
        uname = f" (@{_esc(u['username'])})" if u.get("username") else ""
        lines.append(f"• <code>{tid}</code> — {name}{uname}")
    lines.append("\n<i>Unblock: <code>/unblockuser USER_ID</code></i>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.text == "/adminhelp")
async def cmd_admin_help(message: types.Message):
    await message.answer(
        "📖 <b>ADMIN COMMANDS & USAGE</b>\n\n"
        "<b>Commands</b>\n"
        "• <code>/admin</code> — opens the main control panel (dashboard with all sections)\n"
        "• <code>/settings</code> — quick settings menu (shop name, messages, payment mode, maintenance)\n"
        "• <code>/adminhelp</code> — this help page\n\n"
        "<b>User moderation</b>\n"
        "• <code>/blockuser USER_ID</code> — block a user; the bot stops responding to them completely "
        "(messages + buttons). Works even if they never used the bot.\n"
        "• <code>/unblockuser USER_ID</code> — restore a blocked user's access.\n"
        "• <code>/blockedusers</code> — list all currently blocked users with their IDs.\n\n"
        "<b>Panel sections (inside /admin)</b>\n"
        "• 💳 <b>Payments</b> — approve/reject UPI payments; approving delivers key + APK + video automatically\n"
        "• 🛍️ <b>Products</b> — add/edit/hide/delete products, manage plans & prices, manage keys\n"
        "• 📁 <b>Files & Links</b> — upload APK + setup video per product, how-to-buy video, product links\n"
        "• 👥 <b>Users</b> — view customers, search orders, block/unblock from customer profile\n"
        "📊 <b>Stats</b> — sales, revenue, pending payments overview\n"
        "📣 <b>Broadcast</b> — send text/photo/video/document to all non-blocked users\n"
        "🎯 <b>Promo</b> — broadcast with product/plan buy buttons attached\n"
        "🤝 <b>Resellers</b> — approve/reject reseller applications\n"
        "🔄 <b>Restart</b> — restart the bot process\n\n"
        "<b>Notes</b>\n"
        "• USER_ID = numeric Telegram ID (find it in 👥 Users)\n"
        "• Blocked users get <b>zero</b> responses and are excluded from broadcasts\n"
        "• All panel actions are logged in admin logs",
        parse_mode="HTML")


@router.callback_query(F.data == "adm_dash")
async def cb_dash(callback: types.CallbackQuery, db):
    await callback.answer()
    await callback.message.edit_text(await _dash_text(db), parse_mode="HTML",
                                  reply_markup=KB.admin_dashboard())


@router.callback_query(F.data == "adm_exit")
async def cb_exit(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("👋 Admin panel closed.", reply_markup=KB.reply_menu())


@router.callback_query(F.data == "adm_restart")
async def cb_restart(callback: types.CallbackQuery, db):
    await _log(db, callback.from_user.id, "restart_bot")
    await callback.answer("🔄 Restarting...", show_alert=True)
    os._exit(0)


@router.callback_query(F.data == "adm_stats")
async def cb_stats(callback: types.CallbackQuery, db):
    await callback.answer()
    now = svc.now_utc()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async def rev_since(dt):
        r = await db.orders.aggregate([
            {"$match": {"status": {"$in": ["paid", "delivered"]}, "created_at": {"$gte": dt}}},
            {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
        ]).to_list(1)
        return r[0]["t"] if r else 0

    s = await svc.get_settings(db)
    manual_rev = s.get("revenue_manual")

    def inr(v):
        return f"₹{v:,.2f}"

    total_rev = float(manual_rev) if manual_rev is not None else await rev_since(datetime(2020,1,1))
    rev_line = f"💰 Total Revenue   <b>{inr(total_rev)}</b>"
    if manual_rev is not None:
        rev_line += "  <i>(manual override)</i>"
    maint = "🔴 ON" if s.get("maintenance_mode") else "🟢 OFF"
    mode = "🤖 Automatic" if s.get("payment_mode") == "automatic" else "✋ Manual"
    await callback.message.edit_text(
        "📊 <b>STATISTICS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Users          <b>{await db.users.count_documents({})}</b>\n"
        f"🛍️ Products       <b>{await db.products.count_documents({})}</b> "
        f"({await db.products.count_documents({'status':'active'})} active)\n"
        f"🔑 Keys           <b>{await db.keys.count_documents({'status':'available'})}</b> avail / "
        f"<b>{await db.keys.count_documents({'status':'sold'})}</b> sold\n"
        f"📦 Orders         <b>{await db.orders.count_documents({})}</b>\n\n"
        f"⏳ Pending        <b>{await db.payments.count_documents({'status':'pending'})}</b>\n"
        f"✅ Approved       <b>{await db.payments.count_documents({'status':'approved'})}</b>\n"
        f"❌ Rejected       <b>{await db.payments.count_documents({'status':'rejected'})}</b>\n\n"
        f"{rev_line}\n"
        f"📅 Today          <b>{inr(await rev_since(day))}</b>\n"
        f"🗓 Month          <b>{inr(await rev_since(month))}</b>\n\n"
        f"💳 Payment Mode   <b>{mode}</b>\n"
        f"🔧 Maintenance    <b>{maint}</b>",
        parse_mode="HTML", reply_markup=_kb([
            [InlineKeyboardButton(text="✏️ Edit Revenue", callback_data="adm_revset")],
            [InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")],
        ]))


@router.callback_query(F.data == "adm_revset")
async def cb_revset(callback: types.CallbackQuery, state: FSMContext, db):
    await callback.answer()
    now = svc.now_utc()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    async def rev(since):
        r = await db.orders.aggregate([
            {"$match": {"status": {"$in": ["paid", "delivered"]},
                        "created_at": {"$gte": since}}},
            {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
        ]).to_list(1)
        return r[0]["t"] if r else 0

    s = await svc.get_settings(db)
    man = s.get("revenue_manual")
    total_c = await rev(datetime(2020, 1, 1))
    shown = float(man) if man is not None else total_c
    mode_txt = "manual override" if man is not None else "auto (order-computed)"
    await state.set_state(AdminStates.revenue_edit)
    await callback.message.edit_text(
        "💰 <b>EDIT REVENUE</b>\n\n"
        f"📊 Current total: <b>₹{shown:,.2f}</b> ({mode_txt})\n"
        f"🧮 Computed from orders: ₹{total_c:,.2f}\n"
        f"📅 Today: ₹{await rev(day):,.2f} | 🗓 Month: ₹{await rev(month):,.2f}\n\n"
        "Send the new <b>total revenue</b> (grows automatically with new orders):\n"
        "<code>12500</code>\n\n"
        "Send <code>auto</code> to go back to order-computed revenue.",
        parse_mode="HTML")


@router.message(AdminStates.revenue_edit, F.text)
async def st_revset(m, state, db):
    text = m.text.strip().lower()
    if text == "auto":
        await db.settings.update_one({"key": "revenue_manual"},
            {"$unset": {"value": ""}})
        svc.invalidate_settings()
        await state.clear()
        await m.answer("✅ Revenue back to auto (order-computed).",
                       reply_markup=KB.back_nav("adm_stats", "🔙 Stats"))
        return
    try:
        val = float(m.text.strip())
        if val < 0:
            raise ValueError
    except ValueError:
        await m.answer("❌ Invalid amount — send a number (e.g. 12500) or 'auto'.")
        return
    await db.settings.update_one({"key": "revenue_manual"},
        {"$set": {"key": "revenue_manual", "value": val,
                  "updated_at": svc.now_utc()}}, upsert=True)
    svc.invalidate_settings()
    await _log(db, m.from_user.id, "edit_revenue", {"value": val})
    await state.clear()
    await m.answer(f"✅ Total revenue set to ₹{val:.2f} <i>(manual)</i>",
                   parse_mode="HTML",
                   reply_markup=KB.back_nav("adm_stats", "🔙 Stats"))


# ================= Products =================

@router.callback_query(F.data == "adm_products")
async def cb_products(callback: types.CallbackQuery, db):
    await callback.answer()
    products = await db.products.find({}).sort("display_order", 1).to_list(100)
    await callback.message.edit_text("🛍️ <b>PRODUCT MANAGEMENT</b>", parse_mode="HTML",
                                  reply_markup=KB.admin_products(products))


# ---------- Add product: name -> platform -> bulk plans ----------

PLATFORM_OPTIONS = [
    ("🤖 Android", "Android"), ("📱 iPhone", "iPhone"), ("📱 iPad", "iPad"),
]

# Preset validities: (label, hours)
PRESET_VALIDITIES = [
    ("1 Day", 24), ("3 Days", 72), ("7 Days", 168), ("30 Days", 720),
    ("Season", 2160), ("180 Days", 4320), ("365 Days", 8760),
]


def _infer_hours(name: str):
    """Guess duration_hours from a plan name like '1 day', '12h', 'season'."""
    n = name.lower()
    if "12h" in n or "12 hr" in n or "12-hour" in n or "12 hour" in n:
        return 12
    if "season" in n:
        return 2160
    if "6 month" in n or "6-month" in n or "180" in n:
        return 4320
    if "3 month" in n or "3-month" in n or "90" in n or "quarter" in n:
        return 2160
    m = re.search(r"(\d+)\s*month", n)
    if m:
        return int(m.group(1)) * 720
    m = re.search(r"(\d+)\s*week", n)
    if m:
        return int(m.group(1)) * 168
    m = re.search(r"(\d+)\s*day", n)
    if m:
        return int(m.group(1)) * 24
    if "week" in n or "7-day" in n:
        return 168
    if "month" in n or "30-day" in n:
        return 720
    if "year" in n or "365" in n or "annual" in n:
        return 8760
    if "day" in n or "daily" in n:
        return 24
    m = re.search(r"(\d+)\s*h", n)
    return int(m.group(1)) if m else None


@router.callback_query(F.data == "adm_prod_add")
async def cb_prod_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(AdminStates.product_name)
    await callback.message.edit_text(
        "➕ <b>NEW PRODUCT</b>\n\nStep 1/3 — Enter product <b>name</b>:",
        parse_mode="HTML")


@router.message(AdminStates.product_name, F.text)
async def st_prod_name(m: types.Message, state: FSMContext):
    await state.update_data(name=m.text.strip(), selected=[], custom_plans=[],
                            platforms=[])
    await state.set_state(AdminStates.product_platform)
    await m.answer(_platform_text(await state.get_data()), parse_mode="HTML",
                   reply_markup=_platform_kb(await state.get_data()))


def _platform_text(data) -> str:
    sel = data.get("platforms", [])
    lines = ["Step 2/3 — Tap platforms to include (multiple allowed), then ✅ Done.", ""]
    lines += [f"✅ {p}" for p in sel] or ["Nothing selected yet."]
    return "\n".join(lines)


def _platform_kb(data) -> InlineKeyboardMarkup:
    sel = set(data.get("platforms", []))
    row = [InlineKeyboardButton(
        text=f"{'✅' if val in sel else '⬜'} {label}",
        callback_data=f"np_ptgl_{val}") for label, val in PLATFORM_OPTIONS]
    return _kb([
        row,
        [InlineKeyboardButton(text="✅ Done", callback_data="np_pdone"),
         InlineKeyboardButton(text="❌ Cancel", callback_data="adm_products")],
    ])


@router.callback_query(F.data.startswith("np_ptgl_"))
async def cb_np_platform_toggle(callback: types.CallbackQuery, state: FSMContext):
    val = callback.data[8:]
    data = await state.get_data()
    platforms = list(data.get("platforms", []))
    if val in platforms:
        platforms.remove(val)
    else:
        platforms.append(val)
    await state.update_data(platforms=platforms)
    await callback.answer()
    await callback.message.edit_text(_platform_text(await state.get_data()),
                                     parse_mode="HTML",
                                     reply_markup=_platform_kb(await state.get_data()))


@router.callback_query(F.data == "np_pdone")
async def cb_np_platform_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    platforms = data.get("platforms", [])
    if not platforms:
        await callback.answer("Select at least one platform", show_alert=True)
        return
    await callback.answer()
    await state.update_data(platform=", ".join(platforms))
    await state.set_state(AdminStates.product_plans_pick)
    await callback.message.edit_text(
        _plans_pick_text(await state.get_data()), parse_mode="HTML",
        reply_markup=_plans_pick_kb(await state.get_data()))


def _plans_pick_text(data) -> str:
    sel = data.get("selected", [])
    cust = data.get("custom_plans", [])
    lines = ["Step 3/3 — Tap validities to include, then ✅ Done.", ""]
    for name, hours in sel:
        lines.append(f"✅ {name}")
    for p in cust:
        lines.append(f"✅ {p['name']} [custom]")
    if not sel and not cust:
        lines.append("Nothing selected yet.")
    return "\n".join(lines)


def _plans_pick_kb(data) -> InlineKeyboardMarkup:
    sel_hours = {h for _, h in data.get("selected", [])}
    rows = []
    row = []
    for label, hours in PRESET_VALIDITIES:
        mark = "✅" if hours in sel_hours else "⬜"
        row.append(InlineKeyboardButton(
            text=f"{mark} {label}", callback_data=f"np_tgl_{hours}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="➕ Custom Plan", callback_data="np_custom"),
        InlineKeyboardButton(text="✅ Done", callback_data="np_done"),
    ])
    rows.append([InlineKeyboardButton(text="❌ Cancel", callback_data="adm_products")])
    return _kb(rows)


@router.callback_query(F.data.startswith("np_tgl_"))
async def cb_np_toggle(callback: types.CallbackQuery, state: FSMContext):
    hours = int(callback.data[7:])
    data = await state.get_data()
    selected = list(data.get("selected", []))
    match = next((p for p in PRESET_VALIDITIES if p[1] == hours), None)
    if not match:
        await callback.answer()
        return
    if any(h == hours for _, h in selected):
        selected = [p for p in selected if p[1] != hours]
    else:
        selected.append(match)
    await state.update_data(selected=selected)
    await callback.answer()
    await callback.message.edit_text(_plans_pick_text(await state.get_data()),
                                  parse_mode="HTML",
                                  reply_markup=_plans_pick_kb(await state.get_data()))


@router.callback_query(F.data == "np_custom")
async def cb_np_custom(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.product_plans_custom)
    await callback.message.edit_text(
        "➕ <b>CUSTOM PLAN(S)</b>\n\nSend one <b>name</b> per line — no price needed:\n"
        "<code>1 day</code>\n<code>12h</code>\n<code>1 month</code>\n"
        "<code>season</code>\n\n"
        "Duration is auto-detected from the name; you set prices at the end.\n"
        "Send 'done' when finished, or 'skip' for none.",
        parse_mode="HTML")


@router.message(AdminStates.product_plans_custom, F.text)
async def st_np_custom(m: types.Message, state: FSMContext):
    text = m.text.strip()
    if text.lower() in ("done", "skip"):
        data = await state.get_data()
        await state.set_state(AdminStates.product_plans_pick)
        await m.answer(_plans_pick_text(data), parse_mode="HTML",
                       reply_markup=_plans_pick_kb(data))
        return
    added, bad = [], 0
    for line in text.splitlines():
        name = line.strip()
        # tolerate a trailing price token - it's ignored, prices come later
        toks = name.rsplit(None, 1)
        if len(toks) == 2:
            try:
                float(toks[1].lstrip("₹Rs"))
                name = toks[0].strip()
            except ValueError:
                pass
        hours = _infer_hours(name)
        if not name or hours is None:
            bad += 1
            continue
        added.append({"name": name, "duration_hours": hours})
    data = await state.get_data()
    custom = list(data.get("custom_plans", [])) + added
    await state.update_data(custom_plans=custom)
    await state.set_state(AdminStates.product_plans_pick)
    msg = f"✅ Added {len(added)} custom plan(s)." if added else ""
    if bad:
        msg += f" ⚠️ {bad} line(s) skipped (use a recognizable name like '1 day', '12h', 'season')."
    await m.answer(msg or "Nothing added.", parse_mode="HTML")
    d = await state.get_data()
    await m.answer(_plans_pick_text(d), parse_mode="HTML",
                   reply_markup=_plans_pick_kb(d))


@router.callback_query(F.data == "np_done")
async def cb_np_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected", [])
    custom = data.get("custom_plans", [])
    if not selected and not custom:
        await callback.answer("Select at least one plan", show_alert=True)
        return
    await callback.answer()
    # ALL plans (presets + customs) get priced in one message
    plan_list = ([{"name": n, "duration_hours": h} for n, h in selected]
                 + list(custom))
    names = "\n".join(f"{i+1}. {p['name']}" for i, p in enumerate(plan_list))
    await state.set_state(AdminStates.product_plans_prices)
    await state.update_data(_price_plan_list=plan_list)
    await callback.message.edit_text(
        f"💰 <b>PRICES</b>\n\n{names}\n\n"
        "Send prices in the SAME order, comma separated:\n"
        "<code>49, 199, 499</code>\n\n"
        "Or <code>same 100</code> for one price on all.",
        parse_mode="HTML")


@router.message(AdminStates.product_plans_prices, F.text)
async def st_np_prices(m: types.Message, state: FSMContext, db):
    data = await state.get_data()
    plan_list = data.get("_price_plan_list",
                         [{"name": n, "duration_hours": h} for n, h in
                          data.get("selected", [])] + data.get("custom_plans", []))
    count = len(plan_list)
    text = m.text.strip().lower().replace("₹", "").replace("rs", "").strip()

    prices = []
    if text.startswith("same"):
        try:
            prices = [float(text.split()[-1])] * count
        except (ValueError, IndexError):
            await m.answer("❌ Invalid. Example: <code>same 100</code>", parse_mode="HTML")
            return
    else:
        try:
            prices = [float(x.strip()) for x in re.split(r"[,\n]", text) if x.strip()]
        except ValueError:
            await m.answer("❌ Invalid prices. Send numbers separated by commas.")
            return
        if len(prices) != count:
            await m.answer(f"❌ Expected {count} price(s), got {len(prices)}. Try again:")
            return

    final_plans = [{"name": p["name"], "price": price,
                    "duration_hours": p["duration_hours"]}
                   for p, price in zip(plan_list, prices)]
    await state.clear()
    await _insert_product(m, state, data, final_plans, db)


async def _insert_product(m, state, data, plans, db):
    if not plans:
        await m.answer("❌ Add at least one plan.")
        return
    res = await db.products.insert_one({
        "name": data["name"], "platform": data.get("platform", "Both"),
        "description": "", "image_file_id": None,
        "status": "active", "display_order": await db.products.count_documents({}) + 1,
        "files": {}, "links": [], "instructions": None,
        "created_at": svc.now_utc(), "updated_at": svc.now_utc(),
    })
    pid = res.inserted_id
    for pl in plans:
        await db.plans.insert_one({
            "product_id": pid, "name": pl["name"], "price": pl["price"],
            "duration_hours": pl["duration_hours"], "status": "active",
            "created_at": svc.now_utc(), "updated_at": svc.now_utc(),
        })
    await _log(db, m.from_user.id, "add_product",
               {"name": data["name"], "plans": len(plans)})
    await m.answer(
        f"✅ <b>{_esc(data['name'])}</b> created with {len(plans)} plan(s).",
        parse_mode="HTML", reply_markup=KB.back_nav("adm_products", "🔙 Products"))


@router.callback_query(F.data.startswith("adm_prod_"))
async def cb_prod_detail(callback: types.CallbackQuery, db):
    rest = callback.data[len("adm_prod_"):]
    if rest == "add":
        return  # handled by dedicated handler
    await callback.answer()
    try:
        pid = ObjectId(rest)
    except Exception:
        await callback.message.edit_text("❌ Invalid product.")
        return
    p = await db.products.find_one({"_id": pid})
    if not p:
        await callback.message.edit_text("❌ Product not found.")
        return
    plans = await _plans_of(db, pid)
    stock = await svc.product_stock_total(db, pid)
    plan_txt = "\n".join(
        f"• {_esc(x['name'])} — ₹{x['price']}"
        for x in plans) or "none"
    files = p.get("files", {}) or {}
    apk_ok = bool(files.get("apk", {}).get("file_id") or p.get("apk_file_id"))
    vid_ok = bool(files.get("video", {}).get("file_id") or p.get("setup_video_file_id"))
    plat = p.get("platform") or "-"
    await callback.message.edit_text(
        f"🎮 <b>{_esc(p['name'])}</b> {'🟢' if p.get('status')=='active' else '🔴'}\n\n"
        f"📱 Platform: {_esc(plat)}\n"
        f"{_esc(p.get('description') or '')}\n\n"
        f"⏱️ Plans ({len(plans)}):\n{plan_txt}\n\n"
        f"🔑 Stock: {stock}\n"
        f"📁 APK {'✅' if apk_ok else '❌'} | Video {'✅' if vid_ok else '❌'}",
        parse_mode="HTML", reply_markup=KB.product_detail(str(pid)))


@router.callback_query(F.data.startswith("adm_pview_"))
async def cb_prod_view(callback: types.CallbackQuery, db):
    pid = callback.data[10:]  # "adm_pview_" is 10 chars
    await callback.answer()
    try:
        p = await db.products.find_one({"_id": ObjectId(pid)})
    except Exception:
        p = None
    if not p:  # fallback for migrated docs with non-ObjectId ids
        for doc in await db.products.find({}).to_list(500):
            if _norm_id(doc.get("_id")) == pid:
                p = doc
                break
    if not p:
        await callback.message.edit_text("❌ Not found.")
        return
    plans = await _plans_of(db, pid)
    stock = await svc.product_stock_total(db, pid)
    plan_txt = "\n".join(
        f"• {_esc(x['name'])} — ₹{x['price']}" for x in plans) or "none"
    files = p.get("files", {}) or {}
    apk_ok = bool(files.get("apk", {}).get("file_id") or p.get("apk_file_id"))
    vid_ok = bool(files.get("video", {}).get("file_id") or p.get("setup_video_file_id"))
    await callback.message.edit_text(
        f"👁 <b>PREVIEW — {_esc(p['name'])}</b>\n\n"
        f"{_esc(p.get('description') or '')}\n\n"
        f"⏱️ Plans:\n{plan_txt}\n\n🔑 Available stock: {stock}\n"
        f"📁 APK {'✅' if apk_ok else '❌'} | Video {'✅' if vid_ok else '❌'}\n\n"
        "<i>This is what customers see.</i>",
        parse_mode="HTML",
        reply_markup=KB.back_nav(f"adm_prod_{pid}", "🔙 Product"))


# ---- product field edits ----

FIELD_LABELS = {"name": "name", "desc": "description",
                "ord": "display order", "toggle": "status", "plat": "platform"}


@router.callback_query(F.data.startswith("adm_pe_"))
async def cb_prod_edit(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("✏️ <b>EDIT PRODUCT</b> — choose field:",
                                  parse_mode="HTML",
                                  reply_markup=KB.product_edit(callback.data[7:]))


@router.callback_query(F.data.startswith("adm_f_"))
async def cb_prod_field(callback: types.CallbackQuery, state: FSMContext, db):
    parts = callback.data.split("_")
    field, pid = parts[2], parts[3]
    await callback.answer()

    if field == "toggle":
        p = await db.products.find_one({"_id": ObjectId(pid)})
        new = "disabled" if p.get("status") == "active" else "active"
        await db.products.update_one({"_id": p["_id"]},
            {"$set": {"status": new, "updated_at": svc.now_utc()}})
        await _log(db, callback.from_user.id, "toggle_product", {"id": pid})
        await callback.message.edit_text(f"Product {'🟢 enabled' if new=='active' else '🔴 disabled'}.")
        return

    await state.set_state(AdminStates.edit_field)
    await state.update_data(pid=pid, field=field)
    await callback.message.edit_text(f"✏️ Enter new {FIELD_LABELS.get(field, field)}:")


@router.message(AdminStates.edit_field, F.text)
async def st_edit_field(m: types.Message, state: FSMContext, db):
    data = await state.get_data()
    field, pid = data["field"], data["pid"]
    val = m.text.strip()
    upd = {"updated_at": svc.now_utc()}
    if field == "ord":
        try:
            upd["display_order"] = int(val)
        except ValueError:
            await m.answer("❌ Invalid number.")
            return
    else:
        upd[{"name": "name", "desc": "description", "plat": "platform"}[field]] = val
    await db.products.update_one({"_id": ObjectId(pid)}, {"$set": upd})
    await _log(db, m.from_user.id, "edit_product", {"id": pid, "field": field})
    await state.clear()
    await m.answer(f"✅ {FIELD_LABELS.get(field, field)} updated.",
                   reply_markup=KB.back_nav(f"adm_prod_{pid}", "🔙 Product"))


@router.callback_query(F.data.startswith("adm_pdel_"))
async def cb_prod_del(callback: types.CallbackQuery, db):
    pid = callback.data[9:]  # "adm_pdel_" is 9 chars
    await callback.answer()
    p = await db.products.find_one({"_id": ObjectId(pid)})
    if not p:
        await callback.message.edit_text("❌ Not found.")
        return
    await callback.message.edit_text(
        f"🗑 Delete <b>{_esc(p['name'])}</b> and ALL its plans/keys?",
        parse_mode="HTML",
        reply_markup=KB.yes_no(f"adm_pdelok_{pid}", f"adm_prod_{pid}"))


@router.callback_query(F.data.startswith("adm_pdelok_"))
async def cb_prod_del_ok(callback: types.CallbackQuery, db):
    pid = callback.data[11:]  # "adm_pdelok_" is 11 chars
    oid = ObjectId(pid)
    await db.keys.delete_many({"product_id": oid})
    await db.plans.delete_many({"product_id": oid})
    await db.products.delete_one({"_id": oid})
    await _log(db, callback.from_user.id, "delete_product", {"id": pid})
    await callback.answer("Deleted.")
    await callback.message.edit_text("✅ Product deleted.", reply_markup=KB.back_nav("adm_products", "🔙 Products"))


# ================= Plans =================

def _cbid(oid) -> str:
    """Short callback-safe id - raw migrated _ids can exceed Telegram's
    64-byte callback_data limit, so buttons carry a 24-char hash."""
    return hashlib.md5(str(oid).encode("utf-8")).hexdigest()[:24]


async def _plan_by_code(db, code: str):
    for p in await db.plans.find({}).to_list(500):
        if _cbid(p["_id"]) == code:
            return p
    return None


async def _key_by_code(db, code: str):
    for k in await db.keys.find({}).to_list(2000):
        if _cbid(k["_id"]) == code:
            return k
    return None


def _norm_id(v) -> str:
    """Normalize an id for comparison - handles str, ObjectId-repr,
    and {'$oid': ...} extended-JSON forms from migrations."""
    if isinstance(v, dict):
        v = v.get("$oid") or v.get("_id") or ""
    s = str(v).strip().strip("'\"")
    if s.startswith("ObjectId(") and s.endswith(")"):
        s = s[9:-1].strip("'\"")
    return s


def _plan_pid(p) -> str:
    return _norm_id(p.get("product_id") or p.get("productId") or p.get("pid"))


async def _plans_of(db, pid) -> list:
    """Plans for a product - tolerant id match so migrated docs
    with differently-typed product_id still resolve."""
    plans = await db.plans.find({}).to_list(500)
    target = _norm_id(pid)
    matched = [p for p in plans if _plan_pid(p) == target]
    return sorted(matched, key=lambda p: p.get("price") or 0)


@router.callback_query(F.data.startswith("adm_plans_"))
async def cb_plans(callback: types.CallbackQuery, db):
    pid = callback.data[10:]
    await callback.answer()
    p = await db.products.find_one({"_id": ObjectId(pid)})
    plans = await _plans_of(db, pid)
    rows = []
    for pl in plans:
        flag = "🟢" if pl.get("status") == "active" else "🔴"
        stock = await svc.stock_for_plan(db, pl["_id"])
        rows.append([InlineKeyboardButton(
            text=f"{flag} {pl['name']} ₹{pl['price']} | {stock} keys",
            callback_data=f"adm_plan_{_cbid(pl['_id'])}")])  # hashed - 64B limit
    rows.append([InlineKeyboardButton(text="➕ Add Plan", callback_data=f"adm_planadd_{pid}")])
    rows.append([InlineKeyboardButton(text="🔙 Product", callback_data=f"adm_prod_{pid}")])
    await callback.message.edit_text(
        f"⏱️ <b>PLANS — {_esc(p['name'] if p else '?')}</b>",
        parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_planadd_"))
async def cb_plan_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(AdminStates.plan_add_name)
    await state.update_data(pid=callback.data[12:], plans_count=0)
    await callback.message.edit_text("➕ Plan <b>name</b> (e.g. 1 Day):", parse_mode="HTML")


@router.message(AdminStates.plan_add_name, F.text)
async def st_pa_name(m, state):
    await state.update_data(_pn=m.text.strip())
    await state.set_state(AdminStates.plan_add_price)
    await m.answer("Plan <b>price</b> (₹):", parse_mode="HTML")


@router.message(AdminStates.plan_add_price, F.text)
async def st_pa_price(m, state, db):
    try:
        price = float(m.text.strip())
    except ValueError:
        await m.answer("❌ Invalid price.")
        return
    data = await state.get_data()
    await db.plans.insert_one({
        "product_id": ObjectId(data["pid"]), "name": data["_pn"],
        "price": price, "duration_hours": None, "status": "active",
        "created_at": svc.now_utc(), "updated_at": svc.now_utc(),
    })
    await _log(db, m.from_user.id, "add_plan", {"product": data["pid"], "name": data["_pn"]})
    await state.clear()
    await m.answer("✅ Plan added.", reply_markup=KB.back_nav(f"adm_plans_{data['pid']}", "🔙 Plans"))


@router.callback_query(F.data.startswith("adm_plan_"))
async def cb_plan_detail(callback: types.CallbackQuery, db):
    # adm_plan_{code} - hashed id, resolved via scan (64B callback limit)
    code = callback.data[len("adm_plan_"):]
    await callback.answer()
    pl = await _plan_by_code(db, code)
    if not pl:
        await callback.message.edit_text("❌ Plan not found.")
        return
    plan_id = str(pl["_id"])
    pid = str(pl.get("product_id") or "")
    stock = await svc.stock_for_plan(db, pl["_id"])
    await callback.message.edit_text(
        f"⏱️ <b>{_esc(pl['name'])}</b> {'🟢' if pl.get('status')=='active' else '🔴'}\n\n"
        f"💰 ₹{pl['price']}\n"
        f"🔑 Available keys: {stock}",
        parse_mode="HTML", reply_markup=KB.plan_detail(code, pid))


PLAN_FIELDS = {"name": "name", "price": "price", "hours": "duration_hours"}


@router.callback_query(F.data.startswith("adm_q_"))
async def cb_plan_action(callback: types.CallbackQuery, state: FSMContext, db):
    rest = callback.data[len("adm_q_"):]
    if rest.startswith("toggle_") or rest.startswith("del_"):
        code = rest.split("_", 1)[1]
        pl = await _plan_by_code(db, code)
        if not pl:
            await callback.answer("Not found", show_alert=True)
            return
        plan_id = str(pl["_id"])
        if rest.startswith("toggle_"):
            new = "disabled" if pl.get("status") == "active" else "active"
            await db.plans.update_one({"_id": pl["_id"]},
                {"$set": {"status": new, "updated_at": svc.now_utc()}})
            await callback.answer(f"Plan {'enabled' if new=='active' else 'disabled'}")
        else:
            # only delete if no sold keys reference it - still allow, keys keep plan_id
            await db.plans.delete_one({"_id": pl["_id"]})
            await callback.answer("Plan deleted")
        return
    # edit field: adm_q_{field}_{code}
    field, code = rest.split("_", 1)
    pl = await _plan_by_code(db, code)
    if not pl:
        await callback.answer("Not found", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AdminStates.plan_edit_field)
    await state.update_data(plan_id=str(pl["_id"]), field=field)
    labels = {"name": "name", "price": "price (₹)", "hours": "duration hours"}
    await callback.message.edit_text(f"✏️ Enter new plan {labels.get(field, field)}:")


@router.message(AdminStates.plan_edit_field, F.text)
async def st_plan_edit(m, state, db):
    data = await state.get_data()
    field = PLAN_FIELDS.get(data["field"])
    if not field:
        await state.clear()
        return
    val = m.text.strip()
    if field == "duration_hours":
        try:
            val = int(val)
        except ValueError:
            await m.answer("❌ Invalid number.")
            return
    elif field == "price":
        try:
            val = float(val)
        except ValueError:
            await m.answer("❌ Invalid price.")
            return
    await db.plans.update_one({"_id": ObjectId(data["plan_id"])},
        {"$set": {field: val, "updated_at": svc.now_utc()}})
    await state.clear()
    await m.answer("✅ Plan updated.", reply_markup=KB.back_nav("adm_products", "🔙 Products"))


# ================= Keys =================

@router.callback_query(F.data.startswith("adm_pkeys_"))
async def cb_pkeys(callback: types.CallbackQuery, db):
    pid = callback.data[10:]  # "adm_pkeys_" is 10 chars
    await callback.answer()
    p = await db.products.find_one({"_id": ObjectId(pid)})
    plans = await _plans_of(db, pid)
    rows = []
    for pl in plans:
        avail = await svc.stock_for_plan(db, pl["_id"])
        sold = await db.keys.count_documents({"plan_id": pl["_id"], "status": "sold"})
        icon = "🟢" if avail > 10 else ("🟡" if avail > 0 else "🔴")
        rows.append([InlineKeyboardButton(
            text=f"{icon} {pl['name']}: {avail} avail / {sold} sold",
            callback_data=f"adm_inv_{_cbid(pl['_id'])}")])  # hashed - 64B limit
    rows.append([InlineKeyboardButton(text="➕ Add Keys", callback_data=f"adm_keyadd_{pid}")])
    rows.append([InlineKeyboardButton(text="🔙 Product", callback_data=f"adm_prod_{pid}")])
    await callback.message.edit_text(
        f"🔑 <b>INVENTORY — {_esc(p['name'] if p else '?')}</b>",
        parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_keyadd_"))
async def cb_key_add(callback: types.CallbackQuery, db):
    pid = callback.data[11:]
    await callback.answer()
    plans = await _plans_of(db, pid)
    if not plans:
        await callback.message.edit_text("❌ No plans — add a plan first.")
        return
    rows = [[InlineKeyboardButton(
            text=f"{'🟢' if pl.get('status','active')=='active' else '🔴'} "
                 f"⏱️ {pl['name']} (₹{pl['price']})",
            callback_data=f"adm_keyplan_{_cbid(pl['_id'])}")] for pl in plans]  # hashed - 64B limit
    rows.append([InlineKeyboardButton(text="🔙 Inventory", callback_data=f"adm_pkeys_{pid}")])
    await callback.message.edit_text("Select plan to add keys to:", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_keyplan_"))
async def cb_key_plan(callback: types.CallbackQuery, state: FSMContext, db):
    code = callback.data[len("adm_keyplan_"):]  # hashed id - 64B limit
    await callback.answer()
    pl = await _plan_by_code(db, code)
    plan_id = str(pl["_id"]) if pl else ""
    pid = str(pl.get("product_id")) if pl else ""
    await state.set_state(AdminStates.adding_keys)
    await state.update_data(plan_id=plan_id, pid=pid)
    await callback.message.edit_text(
        "🔑 Send keys — <b>comma or newline separated</b>, single or bulk:\n\n"
        "<code>KEY-AAAA-1111, KEY-BBBB-2222</code>\n"
        "<code>KEY-CCCC-3333\nKEY-DDDD-4444</code>\n\n"
        "Type 'done' when finished.",
        parse_mode="HTML")


@router.message(AdminStates.adding_keys, F.text)
async def st_add_keys(m, state, db):
    text = m.text.strip()
    if text.lower() in ("done", "finish", "exit"):
        data = await state.get_data()
        pid = data.get("pid") or ""
        await state.clear()
        # same flow as the Done button - back to plan picker for this product
        plans = await _plans_of(db, pid) if pid else []
        if plans:
            rows = [[InlineKeyboardButton(
                    text=f"{'🟢' if pl.get('status','active')=='active' else '🔴'} "
                         f"⏱️ {pl['name']} (₹{pl['price']})",
                    callback_data=f"adm_keyplan_{_cbid(pl['_id'])}")] for pl in plans]
            rows.append([InlineKeyboardButton(text="🔙 Product", callback_data=f"adm_prod_{pid}")])
            await m.answer("✅ Key entry finished. Select a plan to add more keys:",
                           reply_markup=_kb(rows))
        else:
            await m.answer("✅ Key entry finished.",
                           reply_markup=KB.back_nav(f"adm_prod_{pid}", "🔙 Product") if pid
                           else KB.back_nav("adm_products", "🔙 Products"))
        return
    data = await state.get_data()
    # delete the previous prompt/reply so Done buttons never stack up
    prev = data.get("last_msg")
    if prev:
        try:
            await m.bot.delete_message(m.chat.id, prev)
        except Exception:
            pass
    # commas, newlines, spaces - all treated as separators; each key stored individually
    keys = [k.strip().upper() for k in re.split(r"[,\n\r]+", text) if k.strip()]
    # also split on whitespace if no commas/newlines were used
    if len(keys) == 1 and " " in keys[0]:
        keys = [k.strip().upper() for k in keys[0].split() if k.strip()]
    keys = list(dict.fromkeys(keys))  # dedupe within this message
    if not keys:
        await m.answer("❌ No keys detected.")
        return
    plan_oid = ObjectId(data["plan_id"])
    pid = ObjectId(data["pid"])
    # skip keys already in inventory - duplicates get individual add/skip prompts
    existing = {k["key_value"] for k in
                await db.keys.find({"plan_id": plan_oid}).to_list(500)}
    dups = [kv for kv in keys if kv in existing]
    added = 0
    for kv in keys:
        if kv in existing:
            continue
        await db.keys.insert_one({
            "product_id": pid, "plan_id": plan_oid,
            "key_value": kv, "status": "available",
            "created_at": svc.now_utc(),
        })
        existing.add(kv)
        added += 1
    await _log(db, m.from_user.id, "add_keys",
               {"plan": data["plan_id"], "added": added, "dups": len(dups)})
    # register pending duplicates in state, one message each
    dups_map = dict(data.get("dups") or {})
    for kv in dups:
        code = hashlib.md5(f"{data['plan_id']}|{kv}".encode()).hexdigest()[:12]
        dups_map[code] = {"kv": kv, "plan_id": data["plan_id"], "pid": data["pid"]}
        await m.answer(
            f"⚠️ <b>Duplicate key detected</b>\n\n<code>{_esc(kv)}</code>\n\n"
            "Already exists in inventory. Add anyway or skip?",
            parse_mode="HTML",
            reply_markup=_kb([
                [InlineKeyboardButton(text="✅ Add Anyway", callback_data=f"adm_dupadd_{code}"),
                 InlineKeyboardButton(text="⏭ Skip", callback_data=f"adm_dupskip_{code}")],
            ]))
    if dups_map:
        await state.update_data(dups=dups_map)
    # stay in state - admin can send more keys or press Done
    summary = f"✅ Added {added} key(s)"
    if dups:
        summary += f", {len(dups)} duplicate(s) — see prompts above."
    summary += "\n\nSend more keys or type 'done'."
    sent = await m.answer(summary)
    await state.update_data(last_msg=sent.message_id)


@router.callback_query(F.data.startswith("adm_keydone_"))
async def cb_key_done(callback: types.CallbackQuery, state: FSMContext, db):
    pid = callback.data[12:]
    await state.clear()
    await callback.answer("Done")
    plans = await _plans_of(db, pid)
    if not plans:
        await callback.message.edit_text("✅ Keys added.",
            reply_markup=KB.back_nav(f"adm_prod_{pid}", "🔙 Product"))
        return
    rows = [[InlineKeyboardButton(
            text=f"{'🟢' if pl.get('status','active')=='active' else '🔴'} "
                 f"⏱️ {pl['name']} (₹{pl['price']})",
            callback_data=f"adm_keyplan_{_cbid(pl['_id'])}")] for pl in plans]
    rows.append([InlineKeyboardButton(text="🔙 Product", callback_data=f"adm_prod_{pid}")])
    await callback.message.edit_text(
        "✅ Keys added.\n\nSelect a plan to add keys to:",
        reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_inv_"))
async def cb_inventory(callback: types.CallbackQuery, db):
    code = callback.data[len("adm_inv_"):]  # hashed plan id - 64B limit
    await callback.answer()
    pl = await _plan_by_code(db, code)
    if not pl:
        await callback.message.answer("❌ Plan not found.")
        return
    plan_id = str(pl["_id"])
    pid = str(pl.get("product_id") or "")
    keys = await db.keys.find({"plan_id": plan_id}).sort("created_at", -1).to_list(25)
    rows = []
    avail = sold = 0
    for k in keys:
        if k.get("status") == "available":
            avail += 1
            icon = "🟢"
        else:
            sold += 1
            icon = "🔒"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {k['key_value'][:28]} — {'SOLD' if icon=='🔒' else 'avail'}",
            callback_data=f"adm_keydel_{_cbid(k['_id'])}")])  # hashed - 64B limit
    rows.append([InlineKeyboardButton(text="🔙 Inventory", callback_data=f"adm_pkeys_{pid}")])
    await callback.message.edit_text(
        f"🔑 <b>{_esc(pl['name'] if pl else '?')} — INVENTORY</b>\n"
        f"🟢 {avail} available | ⚫ {sold} sold\n"
        "Tap a key to delete it (sold keys can't be deleted).",
        parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_keydel_"))
async def cb_key_del(callback: types.CallbackQuery, db):
    code = callback.data[11:]  # hashed key id - 64B limit
    await callback.answer()
    k = await _key_by_code(db, code)
    if not k:
        await callback.message.edit_text("❌ Not found.")
        return
    if k.get("status") == "sold":
        await callback.message.edit_text(
            f"🔒 <b>Sold key</b>\n\n<code>{_esc(k['key_value'])}</code>\n\n"
            "Unlock it to make it available again?\n"
            "<i>(e.g. you bought it for testing)</i>",
            parse_mode="HTML",
            reply_markup=KB.yes_no(f"adm_kunlockok_{code}",
                                   f"adm_inv_{_cbid(k['plan_id'])}"))
        return
    await callback.message.edit_text(
        f"⚠️ <b>Delete this key?</b>\n\n<code>{_esc(k['key_value'])}</code>\n\n"
        "This permanently removes it from inventory.",
        parse_mode="HTML",
        reply_markup=KB.yes_no(f"adm_keydelok_{code}",
                               f"adm_inv_{_cbid(k['plan_id'])}"))


@router.callback_query(F.data.startswith("adm_keydelok_"))
async def cb_key_del_ok(callback: types.CallbackQuery, db):
    code = callback.data[13:]
    await callback.answer("Deleted")
    k = await _key_by_code(db, code)
    if not k:
        await callback.message.edit_text("❌ Not found.")
        return
    plan_code = _cbid(k["plan_id"])
    await db.keys.delete_one({"_id": k["_id"]})
    await _log(db, callback.from_user.id, "delete_key", {"id": str(k["_id"])})
    pl = await _plan_by_code(db, plan_code)
    if not pl:
        await callback.message.edit_text(
            f"🗑 Key <code>{_esc(k['key_value'])}</code> deleted.",
            parse_mode="HTML")
        return
    text, kb = await _plan_inventory(db, pl)
    await callback.message.edit_text(
        f"🗑 Deleted <code>{_esc(k['key_value'])}</code>\n\n" + text,
        parse_mode="HTML", reply_markup=kb)


async def _plan_inventory(db, pl):
    """Shared inventory view: (text, keyboard) for a plan."""
    keys = await db.keys.find({"plan_id": pl["_id"]}).sort("created_at", -1).to_list(25)
    rows = []
    avail = sold = 0
    for kk in keys:
        if kk.get("status") == "available":
            avail += 1
            icon, st = "🟢", "avail"
        else:
            sold += 1
            icon, st = "🔒", "SOLD"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {kk['key_value'][:28]} — {st}",
            callback_data=f"adm_keydel_{_cbid(kk['_id'])}")])
    pid = str(pl.get("product_id") or "")
    rows.append([InlineKeyboardButton(text="🔙 Inventory", callback_data=f"adm_pkeys_{pid}")])
    text = (f"🔑 <b>{_esc(pl['name'])} — INVENTORY</b>\n"
            f"🟢 {avail} available | 🔒 {sold} sold")
    return text, _kb(rows)


@router.callback_query(F.data.startswith("adm_kunlockok_"))
async def cb_key_unlock_ok(callback: types.CallbackQuery, db):
    code = callback.data[14:]  # "adm_kunlockok_" is 14 chars
    await callback.answer("Unlocked")
    k = await _key_by_code(db, code)
    if not k:
        await callback.message.edit_text("❌ Not found.")
        return
    await db.keys.update_one({"_id": k["_id"]},
        {"$set": {"status": "available", "unlocked_at": svc.now_utc()},
         "$unset": {"order_id": "", "sold_at": "", "telegram_id": ""}})
    await _log(db, callback.from_user.id, "unlock_key", {"id": str(k["_id"])})
    pl = await _plan_by_code(db, _cbid(k["plan_id"]))
    if not pl:
        await callback.message.edit_text(
            f"🔓 Key <code>{_esc(k['key_value'])}</code> unlocked — now available.",
            parse_mode="HTML")
        return
    text, kb = await _plan_inventory(db, pl)
    await callback.message.edit_text(
        f"🔓 Unlocked <code>{_esc(k['key_value'])}</code>\n\n" + text,
        parse_mode="HTML", reply_markup=kb)


# ---- duplicate-key prompts (while in adding_keys state) ----

@router.callback_query(F.data.startswith("adm_dupadd_"))
async def cb_dup_add(callback: types.CallbackQuery, state: FSMContext, db):
    code = callback.data[10:]
    data = await state.get_data()
    d = (data.get("dups") or {}).get(code)
    if not d:
        await callback.answer("Session expired — re-send the keys.", show_alert=True)
        return
    await db.keys.insert_one({
        "product_id": ObjectId(d["pid"]), "plan_id": ObjectId(d["plan_id"]),
        "key_value": d["kv"], "status": "available",
        "created_at": svc.now_utc(), "duplicate_override": True})
    dups = dict(data.get("dups") or {})
    dups.pop(code, None)
    await state.update_data(dups=dups)
    await _log(db, callback.from_user.id, "add_key_duplicate",
               {"key": d["kv"][:40]})
    await callback.answer("✅ Added")
    await callback.message.edit_text(
        f"✅ Duplicate added anyway:\n<code>{_esc(d['kv'])}</code>",
        parse_mode="HTML")


@router.callback_query(F.data.startswith("adm_dupskip_"))
async def cb_dup_skip(callback: types.CallbackQuery, state: FSMContext):
    code = callback.data[11:]
    data = await state.get_data()
    d = (data.get("dups") or {}).get(code)
    if not d:
        await callback.answer("Already handled.", show_alert=True)
        return
    dups = dict(data.get("dups") or {})
    dups.pop(code, None)
    await state.update_data(dups=dups)
    await callback.answer("Skipped")
    await callback.message.edit_text(
        f"⏭ Skipped duplicate:\n<code>{_esc(d['kv'])}</code>",
        parse_mode="HTML")


# ================= Payments =================

@router.callback_query(F.data == "adm_payments")
async def cb_payments(callback: types.CallbackQuery, db):
    await callback.answer()
    pays = await db.payments.find({"status": "pending"}).sort("created_at", -1).to_list(20)
    if not pays:
        await callback.message.edit_text("✅ No pending payments.",
            reply_markup=KB.back_nav("adm_dash", "🔙 Dashboard"))
        return
    rows = [[InlineKeyboardButton(
        text=f"🟡 {p.get('public_order_id','?')} — ₹{p.get('amount',0):.0f} — UTR: {p.get('utr') or '-'}",
        callback_data=f"ver_{p.get('public_order_id')}")] for p in pays]
    rows.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")])
    await callback.message.edit_text("💳 <b>PENDING PAYMENTS</b>", parse_mode="HTML",
                                  reply_markup=_kb(rows))


async def _payment_detail_text(db, order_id):
    order = await db.orders.find_one({"order_id": order_id})
    if not order:
        return None, None
    pay = await db.payments.find_one({"order_id": order["_id"]})
    user = await db.users.find_one({"_id": order["user_id"]})
    uname = f"@{user.get('username')}" if user and user.get("username") else (user or {}).get("first_name", "?")
    text = (
        "🔔 <b>PAYMENT REQUEST</b>\n\n"
        f"🆔 Order: <code>{order_id}</code>\n"
        f"👤 {_esc(uname)} (<code>{order.get('telegram_id')}</code>)\n"
        f"🎮 {_esc(order.get('product_name',''))} | ⏱️ {_esc(order.get('plan_name',''))}\n"
        f"💰 ₹{order.get('amount',0):.2f}\n"
        f"🏦 UTR: <code>{pay.get('utr') if pay else '-'}</code>\n"
        f"📷 Screenshot: {'yes' if pay and pay.get('screenshot_file_id') else 'no'}\n"
        f"⏳ Expires: {svc.fmt_ist(pay.get('expiry_time')) if pay and pay.get('expiry_time') else '-'}"
    )
    return text, pay


async def _announce_delivery(bot, db, order, result, delivered=True):
    """Post key-delivery audit to the verification group.
    Manual mode: edits the original payment-request message in place.
    Automatic mode: sends a fresh delivery message.
    Mirrors what the user actually received - shows 'None' if undelivered."""
    pay = await db.payments.find_one({"order_id": order["_id"]})
    user = await db.users.find_one({"_id": order["user_id"]})
    uname = (f"@{user.get('username')}" if user and user.get("username")
             else (user or {}).get("first_name", "?"))
    key_val = result["key"]["key_value"] if delivered else None
    shown_key = _esc(key_val) if key_val else "None"
    title = "✅ <b>KEY DELIVERED</b>" if delivered else "⚠️ <b>DELIVERY FAILED</b> (key released to stock)"
    text = (
        f"{title}\n\n"
        f"🆔 Order: <code>{order['order_id']}</code>\n"
        f"👤 Customer: {_esc(uname)} (<code>{order.get('telegram_id')}</code>)\n"
        f"🎮 {_esc(order.get('product_name',''))} | ⏱️ {_esc(order.get('plan_name',''))}\n"
        f"💰 ₹{order.get('amount',0):.2f}\n"
        f"🔑 Key: <code>{shown_key}</code>\n"
        f"🕐 {svc.fmt_ist(svc.now_utc())}"
    )
    # Manual mode -> edit the original alert message so the group sees
    # request -> delivered in one place
    if pay and pay.get("notify_chat_id") and pay.get("notify_message_id"):
        try:
            await bot.edit_message_text(
                text, chat_id=pay["notify_chat_id"],
                message_id=pay["notify_message_id"], parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
            if (pay.get("provider") or "manual") == "automatic":
                pass  # fall through to also send fresh below
            else:
                return
        except Exception:
            pass
    # Fresh message path - STRICTLY the verification group
    if Config.PAYMENT_VERIFICATION_GROUP_ID:
        try:
            await bot.send_message(Config.PAYMENT_VERIFICATION_GROUP_ID,
                                   text, parse_mode="HTML")
        except Exception:
            pass


@router.callback_query(F.data.regexp(r"^ver_(?!ok_|no_|cust_)"))
async def cb_verify(callback: types.CallbackQuery, db):
    order_id = callback.data[4:]
    await callback.answer()
    text, pay = await _payment_detail_text(db, order_id)
    if not text:
        await callback.message.edit_text("❌ Order not found.")
        return
    if pay and pay.get("screenshot_file_id"):
        try:
            await callback.message.answer_photo(
                pay["screenshot_file_id"], caption=text, parse_mode="HTML",
                reply_markup=KB.verify_payment(order_id))
            return
        except Exception:
            pass
    await callback.message.edit_text(text, parse_mode="HTML",
                                  reply_markup=KB.verify_payment(order_id))


async def _edit_alert(callback: types.CallbackQuery, text: str,
                      reply_markup=None, parse_mode="HTML"):
    """Edit a verification message - works for both text and media
    (photo/document) messages, which only support edit_caption."""
    msg = callback.message
    is_media = any(getattr(msg, a, None) for a in
                   ("photo", "video", "document", "animation"))
    try:
        if is_media:
            await msg.edit_caption(caption=text, parse_mode=parse_mode,
                                   reply_markup=reply_markup)
        else:
            await msg.edit_text(text, parse_mode=parse_mode,
                                reply_markup=reply_markup)
    except Exception:
        await msg.answer(text, parse_mode=parse_mode,
                         reply_markup=reply_markup)


@router.callback_query(F.data.startswith("ver_ok_"))
async def cb_verify_ok(callback: types.CallbackQuery, db):
    order_id = callback.data[7:]
    await callback.answer("Approving...")
    order = await db.orders.find_one({"order_id": order_id})
    if not order or order.get("status") != "pending":
        await _edit_alert(callback, "⚠️ Order not pending — already processed.",
                          reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        return
    result = await svc.approve_payment(db, order, callback.from_user.id)
    if result is None:
        await _edit_alert(callback, "⚠️ Already processed.",
                          reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        return
    if result.get("error") == "out_of_stock":
        await _edit_alert(callback,
            "🔴 OUT OF STOCK — order left pending. Add keys first.",
            reply_markup=KB.back_nav("adm_payments", "🔙 Payments"))
        await _notify_customer_text(callback.bot, order["telegram_id"],
            f"⚠️ Your order {order_id} is approved but we're out of stock. Support will resolve shortly.")
        return

    product = result["product"]
    delivered = await svc.deliver_order(callback.bot, db, result["order"], product)
    await _announce_delivery(callback.bot, db, order, result, delivered=delivered)
    await _log(db, callback.from_user.id, "approve_payment", {"order": order_id})
    if delivered:
        await _edit_alert(callback,
            f"✅ Payment approved & delivered.\nOrder: <code>{order_id}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
    else:
        await _edit_alert(callback,
            f"⚠️ Approved but delivery FAILED (user unreachable).\n"
            f"Key returned to stock — order stays paid.\nOrder: <code>{order_id}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        await _notify_customer_text(callback.bot, order["telegram_id"],
            f"⚠️ Your order {order_id} is approved but we couldn't reach you. "
            f"Please /start the bot so we can deliver your key.")


@router.callback_query(F.data.startswith("ver_no_"))
async def cb_verify_no(callback: types.CallbackQuery, db):
    order_id = callback.data[7:]
    await callback.answer("Rejecting...")
    order = await db.orders.find_one({"order_id": order_id})
    if not order or order.get("status") != "pending":
        await _edit_alert(callback, "⚠️ Already processed.",
                          reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
        return
    await svc.reject_payment(db, order, callback.from_user.id)
    await _log(db, callback.from_user.id, "reject_payment", {"order": order_id})
    await _edit_alert(callback, f"❌ Order <code>{order_id}</code> rejected.",
                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[]))
    await _notify_customer_text(callback.bot, order["telegram_id"],
        f"❌ Payment for order {order_id} was rejected. Contact support if this is a mistake.")


@router.callback_query(F.data.startswith("ver_cust_"))
async def cb_verify_cust(callback: types.CallbackQuery, db):
    order_id = callback.data[9:]
    await callback.answer()
    order = await db.orders.find_one({"order_id": order_id})
    if not order:
        await callback.message.edit_text("❌ Not found.")
        return
    user = await db.users.find_one({"_id": order["user_id"]})
    await callback.message.edit_text(
        f"👤 <b>CUSTOMER</b>\n\n"
        f"Name: {_esc((user or {}).get('first_name',''))} {(user or {}).get('last_name','')}\n"
        f"Username: @{_esc((user or {}).get('username','-'))}\n"
        f"ID: <code>{order.get('telegram_id')}</code>\n"
        f"Joined: {svc.fmt_ist((user or {}).get('created_at', svc.now_utc()))}",
        parse_mode="HTML")


async def _notify_customer_text(bot, telegram_id, text):
    try:
        await bot.send_message(telegram_id, text)
    except Exception:
        pass


# ================= Orders =================

@router.callback_query(F.data == "adm_orders")
async def cb_orders(callback: types.CallbackQuery, db):
    await callback.answer()
    orders = await db.orders.find({}).sort("created_at", -1).to_list(15)
    if not orders:
        await callback.message.edit_text("No orders.", reply_markup=KB.back_nav("adm_dash", "🔙"))
        return
    rows = [[InlineKeyboardButton(
        text=f"{o.get('order_id')} — {_esc(o.get('product_name',''))[:15]} ₹{o.get('amount',0):.0f} [{o.get('status','?')[:4]}]",
        callback_data=f"adm_order_{o['order_id']}")] for o in orders]
    rows.append([InlineKeyboardButton(text="🔍 Search Order", callback_data="adm_ordersearch")])
    rows.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")])
    await callback.message.edit_text("📦 <b>RECENT ORDERS</b>", parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_order_"))
async def cb_order_detail(callback: types.CallbackQuery, db):
    oid = callback.data[10:]
    await callback.answer()
    o = await db.orders.find_one({"order_id": oid})
    if not o:
        await callback.message.edit_text("❌ Not found.")
        return
    pay = await db.payments.find_one({"order_id": o["_id"]})
    await callback.message.edit_text(
        f"📦 <b>ORDER {oid}</b>\n\n"
        f"🎮 {_esc(o.get('product_name',''))} | ⏱️ {_esc(o.get('plan_name',''))}\n"
        f"💰 ₹{o.get('amount',0):.2f} | Status: {o.get('status')}\n"
        f"👤 ID: <code>{o.get('telegram_id')}</code>\n"
        f"🕐 {svc.fmt_ist(o.get('created_at'))}\n"
        f"💳 Payment: {(pay or {}).get('status','-')} | UTR: {(pay or {}).get('utr') or '-'}\n"
        f"🔑 Key: <code>{_esc(o.get('key_value') or '-')}</code>",
        parse_mode="HTML",
        reply_markup=_kb([
            [InlineKeyboardButton(text="🔑 Resend Delivery", callback_data=f"adm_redeliver_{oid}")],
            [InlineKeyboardButton(text="🔙 Orders", callback_data="adm_orders")],
        ]) if o.get("status") in ("delivered", "paid") else KB.back_nav("adm_orders", "🔙 Orders"))


@router.callback_query(F.data.startswith("adm_redeliver_"))
async def cb_redeliver(callback: types.CallbackQuery, db):
    oid = callback.data[14:]
    await callback.answer("Resending...")
    o = await db.orders.find_one({"order_id": oid})
    if not o:
        await callback.message.edit_text("❌ Not found.")
        return
    product = await db.products.find_one({"_id": o["product_id"]})
    if product:
        await svc.deliver_order(callback.bot, db, o, product)
    await _log(db, callback.from_user.id, "redeliver", {"order": oid})
    await callback.message.edit_text("✅ Delivery resent.")


@router.callback_query(F.data == "adm_ordersearch")
async def cb_order_search(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.search_orders)
    await callback.message.edit_text("🔍 Send order ID (e.g. KS000123) or Telegram ID:")


@router.message(AdminStates.search_orders, F.text)
async def st_search_orders(m, state, db):
    q = m.text.strip()
    await state.clear()
    order = await db.orders.find_one({"order_id": q})
    if not order and q.isdigit():
        order = await db.orders.find_one({"telegram_id": int(q)})
    if not order:
        await m.answer("❌ Order not found.", reply_markup=KB.back_nav("adm_dash", "🔙"))
        return
    pay = await db.payments.find_one({"order_id": order["_id"]})
    await m.answer(
        f"📦 <b>{order.get('order_id')}</b>\n\n"
        f"🎮 {_esc(order.get('product_name',''))} | {_esc(order.get('plan_name',''))}\n"
        f"💰 ₹{order.get('amount',0):.2f} | {order.get('status')}\n"
        f"👤 <code>{order.get('telegram_id')}</code> | 🕐 {svc.fmt_ist(order.get('created_at'))}\n"
        f"💳 {(pay or {}).get('status','-')} | UTR: {(pay or {}).get('utr') or '-'}",
        parse_mode="HTML", reply_markup=KB.back_nav("adm_orders", "🔙 Orders"))


# ================= Customers =================

@router.callback_query(F.data == "adm_customers")
async def cb_customers(callback: types.CallbackQuery, db):
    await callback.answer()
    users = await db.users.find({}).sort("created_at", -1).to_list(15)
    rows = []
    for u in users:
        flag = "🚫" if u.get("is_blocked") else "👤"
        name = u.get("username") or u.get("first_name") or str(u["telegram_id"])
        rows.append([InlineKeyboardButton(
            text=f"{flag} {name} ({u['telegram_id']})",
            callback_data=f"adm_cust_{u['telegram_id']}")])
    rows.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")])
    await callback.message.edit_text("👥 <b>CUSTOMERS</b> (latest 15)", parse_mode="HTML",
                                  reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_cust_"))
async def cb_customer(callback: types.CallbackQuery, db):
    tid = int(callback.data[9:])
    await callback.answer()
    u = await db.users.find_one({"telegram_id": tid})
    if not u:
        await callback.message.edit_text("❌ Not found.")
        return
    orders = await db.orders.count_documents({"telegram_id": tid})
    spent = await db.orders.aggregate([
        {"$match": {"telegram_id": tid, "status": {"$in": ["paid", "delivered"]}}},
        {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
    ]).to_list(1)
    blocked = u.get("is_blocked", False)
    await callback.message.edit_text(
        f"👤 <b>CUSTOMER</b>\n\n"
        f"Name: {_esc(u.get('first_name',''))} {_esc(u.get('last_name') or '')}\n"
        f"Username: @{_esc(u.get('username') or '-')}\n"
        f"ID: <code>{tid}</code>\n"
        f"Orders: {orders} | Spent: ₹{(spent[0]['t'] if spent else 0):.2f}\n"
        f"Status: {'🚫 BLOCKED' if blocked else '✅ Active'}",
        parse_mode="HTML",
        reply_markup=_kb([
            [InlineKeyboardButton(
                text="🚫 Unblock" if blocked else "🚫 Block",
                callback_data=f"adm_custblock_{tid}")],
            [InlineKeyboardButton(text="🔙 Customers", callback_data="adm_customers")],
        ]))


@router.callback_query(F.data.startswith("adm_custblock_"))
async def cb_cust_block(callback: types.CallbackQuery, db):
    tid = int(callback.data[14:])
    u = await db.users.find_one({"telegram_id": tid})
    if not u:
        await callback.answer("Not found", show_alert=True)
        return
    new = not u.get("is_blocked", False)
    await db.users.update_one({"telegram_id": tid},
        {"$set": {"is_blocked": new, "updated_at": svc.now_utc()}})
    await _log(db, callback.from_user.id, "block_user" if new else "unblock_user", {"tid": tid})
    await callback.answer("Blocked" if new else "Unblocked")
    await cb_customer(callback, db)


# ================= Files per product =================

@router.callback_query(F.data == "adm_files")
async def cb_files_main(callback: types.CallbackQuery, db):
    await callback.answer()
    products = await db.products.find({"status": "active"}).sort("display_order", 1).to_list(50)
    rows = []
    for p in products:
        files = p.get("files", {}) or {}
        apk_ok = bool(files.get("apk", {}).get("file_id") or p.get("apk_file_id"))
        vid_ok = bool(files.get("video", {}).get("file_id") or p.get("setup_video_file_id"))
        mark = "✅" if (apk_ok and vid_ok) else ("🟡" if (apk_ok or vid_ok) else "❌")
        rows.append([InlineKeyboardButton(
            text=f"🎮 {p['name']} {mark}", callback_data=f"adm_pfiles_{p['_id']}")])
    # global tutorial
    tut = await db.tutorial.find_one({"_id": "howto"})
    rows.append([InlineKeyboardButton(
        text=f"🎓 How-to-Buy Video {'✅' if tut and tut.get('file_id') else '❌'}",
        callback_data="adm_tutorial")])
    rows.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")])
    await callback.message.edit_text("📁 <b>FILES & LINKS</b> — pick a product:",
                                  parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data == "adm_tutorial")
async def cb_tutorial(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.tutorial_video)
    await callback.message.edit_text(
        "🎓 Send the <b>How to Buy</b> video (or '-' to remove):", parse_mode="HTML")


@router.message(AdminStates.tutorial_video, F.video)
async def st_tutorial_video(m, state, db):
    await db.tutorial.update_one({"_id": "howto"},
        {"$set": {"file_id": m.video.file_id, "enabled": True}}, upsert=True)
    await state.clear()
    await m.answer("✅ Tutorial video updated.", reply_markup=KB.back_nav("adm_files", "🔙 Files"))


@router.message(AdminStates.tutorial_video, F.text == "-")
async def st_tutorial_rm(m, state, db):
    await db.tutorial.update_one({"_id": "howto"}, {"$set": {"file_id": None, "enabled": False}})
    await state.clear()
    await m.answer("🗑 Tutorial removed.", reply_markup=KB.back_nav("adm_files", "🔙 Files"))


@router.callback_query(F.data.startswith("adm_pfiles_"))
async def cb_pfiles(callback: types.CallbackQuery, db):
    pid = callback.data[11:]
    await callback.answer()
    p = await db.products.find_one({"_id": ObjectId(pid)})
    if not p:
        await callback.message.edit_text("❌ Not found.")
        return
    files = p.get("files", {})
    status = {k: ("✅" if files.get(k, {}).get("file_id") else "❌")
              for k in ("apk", "video")}
    await callback.message.edit_text(
        f"📁 <b>FILES — {_esc(p['name'])}</b>\n\n"
        f"📱 APK: {status['apk']} | 🎬 Video: {status['video']}",
        parse_mode="HTML",
        reply_markup=_kb([
            [InlineKeyboardButton(text="📱 Upload APK", callback_data=f"adm_fu_apk_{pid}"),
             InlineKeyboardButton(text="🎬 Upload Video", callback_data=f"adm_fu_vid_{pid}")],
            [InlineKeyboardButton(text="📝 Instructions", callback_data=f"adm_fi_{pid}"),
             InlineKeyboardButton(text="🗑 Clear Files", callback_data=f"adm_fc_{pid}")],
            [InlineKeyboardButton(text="🗑 Clear Files", callback_data=f"adm_fc_{pid}"),
             InlineKeyboardButton(text="🔗 Links", callback_data=f"adm_plinks_{pid}")],
            [InlineKeyboardButton(text="🔙 Product", callback_data=f"adm_prod_{pid}")],
        ]))


class _FileStates(StatesGroup):
    apk = State()
    vid = State()


FILE_STATE_MAP = {"fu_apk": _FileStates.apk, "fu_vid": _FileStates.vid}


@router.callback_query(F.data.startswith("adm_fu_"))
async def cb_file_upload(callback: types.CallbackQuery, state: FSMContext):
    rest = callback.data[7:]
    kind, pid = rest.rsplit("_", 1)
    st = FILE_STATE_MAP.get(f"fu_{kind}")
    if not st:
        await callback.answer("Invalid", show_alert=True)
        return
    await callback.answer()
    await state.set_state(st)
    await state.update_data(pid=pid,
        kind={"apk": "apk", "vid": "video"}[kind])
    labels = {"apk": "APK file (send as document/file)", "vid": "setup video"}
    await callback.message.edit_text(f"📤 Send the {labels[kind]}:")


async def _save_file(m, state, db, file_id, fname):
    data = await state.get_data()
    pid, kind = data["pid"], data["kind"]
    await db.products.update_one({"_id": ObjectId(pid)},
        {"$set": {f"files.{kind}.file_id": file_id,
                  f"files.{kind}.name": fname,
                  f"files.{kind}.updated_at": svc.now_utc(),
                  "updated_at": svc.now_utc()}})
    await state.clear()
    await m.answer(f"✅ {kind.upper()} updated.", reply_markup=KB.back_nav(f"adm_pfiles_{pid}", "🔙 Files"))


@router.message(_FileStates.apk, F.document)
async def st_fu_apk(m, state, db):
    await _save_file(m, state, db, m.document.file_id, m.document.file_name)


@router.message(_FileStates.vid, F.video)
async def st_fu_vid(m, state, db):
    await _save_file(m, state, db, m.video.file_id, "setup.mp4")


@router.callback_query(F.data.startswith("adm_fc_"))
async def cb_files_clear(callback: types.CallbackQuery, db):
    pid = callback.data[7:]
    await callback.answer()
    await db.products.update_one({"_id": ObjectId(pid)}, {"$set": {"files": {}}})
    await callback.message.edit_text("🗑 All product files cleared.")


@router.callback_query(F.data.startswith("adm_fi_"))
async def cb_file_instr(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.file_instructions)
    await state.update_data(pid=callback.data[7:])
    await callback.message.edit_text("📝 Send new <b>setup instructions</b> text:", parse_mode="HTML")


@router.message(AdminStates.file_instructions, F.text)
async def st_file_instr(m, state, db):
    data = await state.get_data()
    await db.products.update_one({"_id": ObjectId(data["pid"])},
        {"$set": {"instructions": m.text.strip(), "updated_at": svc.now_utc()}})
    await state.clear()
    await m.answer("✅ Instructions updated.", reply_markup=KB.back_nav(f"adm_pfiles_{data['pid']}", "🔙 Files"))


# ================= Links =================

@router.callback_query(F.data.startswith("adm_plinks_"))
async def cb_plinks(callback: types.CallbackQuery, db):
    pid = callback.data[11:]
    await callback.answer()
    p = await db.products.find_one({"_id": ObjectId(pid)})
    links = p.get("links", []) if p else []
    rows = []
    for i, l in enumerate(links):
        rows.append([InlineKeyboardButton(
            text=f"🗑 {l.get('title','Link')}",
            callback_data=f"adm_ldel_{pid}_{i}")])
    rows.append([InlineKeyboardButton(text="➕ Add Link", callback_data=f"adm_ladd_{pid}")])
    rows.append([InlineKeyboardButton(text="🔙 Files", callback_data=f"adm_pfiles_{pid}")])
    txt = "🔗 <b>LINKS</b>\n" + ("\n".join(f"• {l.get('title')}: {l.get('url')}" for l in links) or "none")
    await callback.message.edit_text(txt, parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_ladd_"))
async def cb_link_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.link_title)
    await state.update_data(pid=callback.data[9:])  # "adm_ladd_" is 9 chars
    await callback.message.edit_text("🔗 Link <b>title</b> (e.g. Download APK):", parse_mode="HTML")


@router.message(AdminStates.link_title, F.text)
async def st_link_title(m, state):
    await state.update_data(title=m.text.strip())
    await state.set_state(AdminStates.link_url)
    await m.answer("Link <b>URL</b>:", parse_mode="HTML")


@router.message(AdminStates.link_url, F.text)
async def st_link_url(m, state, db):
    data = await state.get_data()
    await db.products.update_one({"_id": ObjectId(data["pid"])},
        {"$push": {"links": {"title": data["title"], "url": m.text.strip()}},
         "$set": {"updated_at": svc.now_utc()}})
    await state.clear()
    await m.answer("✅ Link added.", reply_markup=KB.back_nav(f"adm_plinks_{data['pid']}", "🔙 Links"))


@router.callback_query(F.data.startswith("adm_ldel_"))
async def cb_link_del(callback: types.CallbackQuery, db):
    rest = callback.data[9:]  # "adm_ldel_" is 9 chars
    pid, idx = rest.rsplit("_", 1)
    p = await db.products.find_one({"_id": ObjectId(pid)})
    if p and 0 <= int(idx) < len(p.get("links", [])):
        links = p["links"]
        links.pop(int(idx))
        await db.products.update_one({"_id": p["_id"]}, {"$set": {"links": links}})
    await callback.answer("Deleted")
    await cb_plinks(callback, db)


# ================= Promo Broadcast =================

@router.callback_query(F.data == "adm_promo")
async def cb_promo(callback: types.CallbackQuery, db):
    await callback.answer()
    products = await db.products.find({"status": "active"}).sort("display_order", 1).to_list(100)
    if not products:
        await callback.message.edit_text("❌ No active products.",
            reply_markup=KB.back_nav("adm_dash", "🔙 Dashboard"))
        return
    rows = [[InlineKeyboardButton(text=f"🎮 {p['name']}",
            callback_data=f"promo_{_cbid(p['_id'])}")] for p in products]  # hashed - 64B limit
    rows.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")])
    await callback.message.edit_text(
        "🎯 <b>PROMO BROADCAST</b>\n\nPick a product to promote:",
        parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.regexp(r"^promo_(?!go_)"))
async def cb_promo_product(callback: types.CallbackQuery, db):
    code = callback.data[6:]  # hashed product id - 64B limit
    await callback.answer()
    p = await svc.product_by_code(db, code)
    if not p:
        await callback.message.edit_text("❌ Product not found.")
        return
    pid = str(p["_id"])
    plans = await _plans_of(db, pid)
    rows = [[InlineKeyboardButton(text="📦 Whole Product (all plans)",
            callback_data=f"promo_go_{_cbid(pid)}_all")]]
    for pl in plans:
        rows.append([InlineKeyboardButton(
            text=f"⏱️ {pl['name']} — ₹{pl['price']:g}",
            callback_data=f"promo_go_{_cbid(pid)}_{svc.cbid(pl['_id'])}")])  # hashed - 64B
    rows.append([InlineKeyboardButton(text="🔙 Products", callback_data="adm_promo")])
    await callback.message.edit_text(
        f"🎯 Promote <b>{_esc(p['name'])}</b> — pick target:",
        parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("promo_go_"))
async def cb_promo_go(callback: types.CallbackQuery, state: FSMContext, db):
    rest = callback.data[len("promo_go_"):]
    pcode, code = rest.rsplit("_", 1)  # hashed product id + plan code/all
    await callback.answer()
    p = await svc.product_by_code(db, pcode)
    if not p:
        await callback.message.edit_text("❌ Product not found.")
        return
    pid = str(p["_id"])
    plan = None
    if code != "all":
        plan = await svc.plan_by_code(db, code)
        if not plan:
            await callback.message.edit_text("❌ Plan not found.")
            return
    await state.update_data(promo_pid=pid, promo_plan=str(plan["_id"]) if plan else None)
    await state.set_state(AdminStates.promo_text)
    await callback.message.edit_text(
        "✏️ <b>PROMO MESSAGE</b>\n\n"
        "Send the broadcast text, or 'default' for an auto promo:\n\n"
        "<i>Default looks like:</i>\n"
        "🎉 NEW DROP! 🎮 product ⏱️ plan 💰 price — tap button below",
        parse_mode="HTML")


@router.message(AdminStates.promo_text, F.text)
async def st_promo_text(m, state, db):
    data = await state.get_data()
    pid = data["promo_pid"]
    p = await db.products.find_one({"_id": ObjectId(pid)})
    if not p:
        await state.clear()
        await m.answer("❌ Product gone.", reply_markup=KB.reply_menu())
        return
    plan = None
    if data.get("promo_plan"):
        plan = await db.plans.find_one({"_id": ObjectId(data["promo_plan"])})

    text = m.text.strip()
    if text.lower() == "default":
        price = plan.get("price") if plan else None
        price_txt = f"💰 ₹{price:g}" if price else "💰 Check plans inside"
        plan_line = f"⏱️ {_esc(plan['name'])}\n" if plan else ""
        text = (
            "🎉 <b>NEW DROP!</b> ⚡\n\n"
            f"🎮 <b>{_esc(p['name'])}</b>\n"
            f"{plan_line}{price_txt}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Tap the button below to grab yours! 🔥"
        )
    # button deep-links straight into purchase flow
    if plan:
        cb = {"label": f"🛒 {_esc(p['name'])} — {_esc(plan['name'])}"[:64],
              "data": f"plan_{svc.cbid(plan['_id'])}"}
    else:
        cb = {"label": f"🛒 {_esc(p['name'])}"[:64],
              "data": f"prod_{svc.cbid(p['_id'])}"}  # hashed - 64B limit
    await state.clear()
    await _do_broadcast(m, state, db, "text", text, None, cb=cb)


# ================= Broadcast =================

@router.callback_query(F.data == "adm_broadcast")
async def cb_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.broadcast_content)
    await callback.message.edit_text(
        "📢 <b>BROADCAST</b>\n\nSend the message to ALL users:\n"
        "• Text, or\n• Photo (with optional caption), or\n• Video/Document",
        parse_mode="HTML")


async def _ask_broadcast_link(m, state, kind, payload, caption):
    """Content received - optionally ask for an inline link button."""
    await state.update_data(bc_kind=kind, bc_payload=payload, bc_caption=caption)
    await state.set_state(AdminStates.broadcast_link)
    await m.answer(
        "🔗 <b>ADD A BUTTON?</b>\n\n"
        "Send a URL to attach an inline button, or 'skip' for none.\n"
        "Format: <code>https://t.me/channel | Join Channel</code>\n"
        "(label optional — defaults to '🔗 Open Link')",
        parse_mode="HTML")


@router.message(AdminStates.broadcast_content, F.photo)
async def st_bc_photo(m, state, db):
    await _ask_broadcast_link(m, state, "photo", m.photo[-1].file_id, m.caption)


@router.message(AdminStates.broadcast_content, F.video)
async def st_bc_video(m, state, db):
    await _ask_broadcast_link(m, state, "video", m.video.file_id, m.caption)


@router.message(AdminStates.broadcast_content, F.document)
async def st_bc_doc(m, state, db):
    await _ask_broadcast_link(m, state, "document", m.document.file_id, m.caption)


@router.message(AdminStates.broadcast_content, F.text)
async def st_bc_text(m, state, db):
    await _ask_broadcast_link(m, state, "text", m.text, None)


@router.message(AdminStates.broadcast_link, F.text)
async def st_bc_link(m, state, db):
    text = m.text.strip()
    link = None
    if text.lower() not in ("skip", "none", "no", "-"):
        parts = [p.strip() for p in text.split("|")]
        url = parts[0]
        label = parts[1] if len(parts) > 1 and parts[1] else "🔗 Open Link"
        if not url.startswith(("http://", "https://", "tg://")):
            await m.answer("❌ Invalid URL — send a full link (https://...) or 'skip'.")
            return
        link = {"url": url, "label": label[:64]}
    data = await state.get_data()
    await _do_broadcast(m, state, db, data["bc_kind"],
                        data["bc_payload"], data["bc_caption"], link)


async def _do_broadcast(m, state, db, kind, payload, caption, link=None, cb=None):
    users = await db.users.find({"is_blocked": {"$ne": True}}, {"telegram_id": 1}).to_list(10000)
    status = await m.answer(f"📢 Broadcasting to {len(users)} users...")
    kb = None
    if link:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=link["label"], url=link["url"])]])
    elif cb:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=cb["label"], callback_data=cb["data"])]])
    sent = failed = 0
    for u in users:
        try:
            if kind == "text":
                await m.bot.send_message(u["telegram_id"], payload, reply_markup=kb)
            elif kind == "photo":
                await m.bot.send_photo(u["telegram_id"], payload, caption=caption,
                                       reply_markup=kb)
            elif kind == "video":
                await m.bot.send_video(u["telegram_id"], payload, caption=caption,
                                       reply_markup=kb)
            else:
                await m.bot.send_document(u["telegram_id"], payload, caption=caption,
                                          reply_markup=kb)
            sent += 1
        except Exception:
            failed += 1
        # rate limit ~30 msg/s
        if (sent + failed) % 30 == 0:
            await asyncio.sleep(1)
    await _log(db, m.from_user.id, "broadcast",
               {"sent": sent, "failed": failed, "kind": kind,
                "link": bool(link), "cb": bool(cb)})
    await state.clear()
    try:
        await status.edit_text(f"✅ Broadcast done: {sent} sent, {failed} failed.")
    except Exception:
        await m.answer(f"✅ Broadcast done: {sent} sent, {failed} failed.")


# ================= Settings =================

SETTING_LABELS = {
    "name": ("shop_name", "🏪 Shop Name"),
    "welcome": ("welcome_message", "👋 Welcome Message"),
    "channel": ("official_channel", "📢 Official Channel (@name or link)"),
    "support": ("support_username", "📞 Support Username (@name)"),
    "upi": ("upi_id", "🏦 UPI ID"),
    "payee": ("payee_name", "👤 Payee Name"),
    "instructions": ("payment_instructions", "📋 Payment Instructions"),
    "maint": ("maintenance_message", "🔧 Maintenance Message"),
    "howto": ("how_to_text", "🔴 How to Buy Text"),
}


async def _settings_kb(db):
    s = await svc.get_settings(db)
    return KB.settings_menu(bool(s.get("maintenance_mode")),
                            s.get("payment_mode", "manual"))


@router.callback_query(F.data == "adm_settings")
async def cb_settings(callback: types.CallbackQuery, db):
    await callback.answer()
    await callback.message.edit_text("⚙️ <b>BOT SETTINGS</b>", parse_mode="HTML",
                                  reply_markup=await _settings_kb(db))


@router.callback_query(F.data.startswith("set_"))
async def cb_set_field(callback: types.CallbackQuery, state: FSMContext):
    short = callback.data[4:]
    if short not in SETTING_LABELS:
        await callback.answer("Unknown", show_alert=True)
        return
    key, label = SETTING_LABELS[short]
    await callback.answer()
    await state.set_state(AdminStates.edit_setting)
    await state.update_data(key=key)
    await callback.message.edit_text(f"✏️ Enter new value for <b>{label}</b>:",
                                  parse_mode="HTML")


@router.message(AdminStates.edit_setting, F.text)
async def st_edit_setting(m, state, db):
    data = await state.get_data()
    await db.settings.update_one({"key": data["key"]},
        {"$set": {"key": data["key"], "value": m.text.strip(), "updated_at": svc.now_utc()}},
        upsert=True)
    svc.invalidate_settings()
    await _log(db, m.from_user.id, "edit_setting", {"key": data["key"]})
    await state.clear()
    await m.answer("✅ Setting saved.", reply_markup=KB.back_nav("adm_settings", "🔙 Settings"))


@router.callback_query(F.data == "adm_paymode")
async def cb_paymode_legacy(callback: types.CallbackQuery, db):
    # old single-button keyboards (pre-restart) still carry this callback
    s = await svc.get_settings(db)
    new = "automatic" if s.get("payment_mode", "manual") == "manual" else "manual"
    await db.settings.update_one({"key": "payment_mode"},
        {"$set": {"key": "payment_mode", "value": new, "updated_at": svc.now_utc()}}, upsert=True)
    svc.invalidate_settings()
    await _log(db, callback.from_user.id, "payment_mode", {"mode": new})
    await callback.answer(f"Payment mode → {new}")
    await callback.message.edit_text(
        "⚙️ <b>BOT SETTINGS</b>", parse_mode="HTML",
        reply_markup=await _settings_kb(db))


@router.callback_query(F.data.startswith("adm_paymode_"))
async def cb_paymode(callback: types.CallbackQuery, db):
    new = callback.data.rsplit("_", 1)[-1]
    if new == "auto":
        new = "automatic"
    if new not in ("manual", "automatic"):
        await callback.answer("Unknown", show_alert=True)
        return
    s = await svc.get_settings(db)
    cur = s.get("payment_mode", "manual")
    if cur == new:
        await callback.answer(f"Already {new}")
        return
    await db.settings.update_one({"key": "payment_mode"},
        {"$set": {"key": "payment_mode", "value": new, "updated_at": svc.now_utc()}}, upsert=True)
    svc.invalidate_settings()
    await _log(db, callback.from_user.id, "payment_mode", {"mode": new})
    warn = ""
    if new == "automatic":
        from bot import payverify
        if not payverify.PayVerifyConfig.from_env().configured:
            warn = ("\n\n⚠️ Gmail IMAP not configured — add IMAP_USERNAME, "
                    "IMAP_APP_PASSWORD and DEFAULT_UPI_ID to .env")
    await callback.answer(
        "Auto-verify ON — Gmail IMAP not configured" if warn
        else f"Payment mode → {new}",
        show_alert=bool(warn))
    await callback.message.edit_text(
        "⚙️ <b>BOT SETTINGS</b>" + warn,
        parse_mode="HTML", reply_markup=await _settings_kb(db))


# (payment_notify_target toggle removed - alerts go strictly to the group)


@router.callback_query(F.data == "adm_maintoggle")
async def cb_maintoggle(callback: types.CallbackQuery, db):
    await callback.answer()
    cur = await db.settings.find_one({"key": "maintenance_mode"})
    new = not (cur and cur.get("value"))
    await db.settings.update_one({"key": "maintenance_mode"},
        {"$set": {"key": "maintenance_mode", "value": new, "updated_at": svc.now_utc()}}, upsert=True)
    await _log(db, callback.from_user.id, "maintenance", {"on": new})
    svc.invalidate_settings()
    await callback.message.edit_text("⚙️ <b>BOT SETTINGS</b>", parse_mode="HTML",
                                     reply_markup=await _settings_kb(db))


# ================= Admins =================
# (removed - admins are managed via ADMIN_IDS in .env)
