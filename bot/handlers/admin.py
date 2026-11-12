"""Admin panel - complete Telegram-based management (all actions send new messages)"""

import asyncio
import logging
import os
from datetime import datetime

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bson import ObjectId

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


@router.message.outer_middleware()
@router.callback_query.outer_middleware()
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
    s = await svc.get_settings(db)
    users = await db.users.count_documents({})
    products = await db.products.count_documents({})
    active_products = await db.products.count_documents({"status": "active"})
    avail = await db.keys.count_documents({"status": "available"})
    sold = await db.keys.count_documents({"status": "sold"})
    pending = await db.payments.count_documents({"status": "pending"})
    rev = await db.orders.aggregate([
        {"$match": {"status": {"$in": ["paid", "delivered"]}}},
        {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
    ]).to_list(1)
    today = svc.now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    trev = await db.orders.aggregate([
        {"$match": {"status": {"$in": ["paid", "delivered"]}, "created_at": {"$gte": today}}},
        {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
    ]).to_list(1)
    maint = "🔴 ON" if s.get("maintenance_mode") else "🟢 OFF"
    return (
        "⚜️ <b>KEY SHOP CONTROL PANEL</b>\n\n"
        f"👥 Users: {users} | 🛍️ Products: {active_products}/{products}\n"
        f"🔑 Keys: {avail} avail / {sold} sold | ⏳ Pending: {pending}\n"
        f"💰 Revenue: ₹{(rev[0]['t'] if rev else 0):.2f} "
        f"(today ₹{(trev[0]['t'] if trev else 0):.2f})\n"
        f"💳 Mode: {s.get('payment_mode','manual')} | 🔧 Maint: {maint}"
    )


async def _send_dash(message, db):
    await message.answer(await _dash_text(db), parse_mode="HTML",
                          reply_markup=KB.admin_dashboard())


# ================= Commands & dashboard =================

@router.message(F.text == "/admin")
async def cmd_admin(message: types.Message, db):
    await _send_dash(message, db)


@router.callback_query(F.data == "adm_dash")
async def cb_dash(callback: types.CallbackQuery, db):
    await callback.answer()
    await callback.message.answer(await _dash_text(db), parse_mode="HTML",
                                  reply_markup=KB.admin_dashboard())


@router.callback_query(F.data == "adm_exit")
async def cb_exit(callback: types.CallbackQuery):
    await callback.answer()
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

    await callback.message.answer(
        "📊 <b>STATISTICS</b>\n\n"
        f"👥 Users: {await db.users.count_documents({})}\n"
        f"🛍️ Products: {await db.products.count_documents({})} "
        f"({await db.products.count_documents({'status':'active'})} active)\n"
        f"🔑 Keys: {await db.keys.count_documents({'status':'available'})} avail / "
        f"{await db.keys.count_documents({'status':'sold'})} sold\n"
        f"📦 Orders: {await db.orders.count_documents({})}\n"
        f"💳 Pending: {await db.payments.count_documents({'status':'pending'})} | "
        f"✅ Approved: {await db.payments.count_documents({'status':'approved'})} | "
        f"❌ Rejected: {await db.payments.count_documents({'status':'rejected'})}\n"
        f"💰 Revenue: ₹{await rev_since(datetime(2020,1,1)):.2f} | "
        f"Today ₹{await rev_since(day):.2f} | Month ₹{await rev_since(month):.2f}",
        parse_mode="HTML", reply_markup=KB.back_nav("adm_dash", "🔙 Dashboard"))


# ================= Products =================

@router.callback_query(F.data == "adm_products")
async def cb_products(callback: types.CallbackQuery, db):
    await callback.answer()
    products = await db.products.find({}).sort("display_order", 1).to_list(100)
    await callback.message.answer("🛍️ <b>PRODUCT MANAGEMENT</b>", parse_mode="HTML",
                                  reply_markup=KB.admin_products(products))


@router.callback_query(F.data == "adm_prod_add")
async def cb_prod_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(AdminStates.product_name)
    await state.update_data(plans=[])
    await callback.message.answer("➕ <b>NEW PRODUCT</b>\n\n1/4 — Enter product <b>name</b>:",
                                  parse_mode="HTML")


@router.message(AdminStates.product_name, F.text)
async def st_prod_name(m: types.Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await state.set_state(AdminStates.product_image)
    await m.answer("2/4 — Send product <b>image</b> (photo) or '-' to skip:", parse_mode="HTML")


@router.message(AdminStates.product_image, F.photo)
async def st_prod_img_photo(m: types.Message, state: FSMContext):
    await state.update_data(image_file_id=m.photo[-1].file_id)
    await state.set_state(AdminStates.product_desc)
    await m.answer("3/4 — Enter product <b>description</b>:", parse_mode="HTML")


@router.message(AdminStates.product_image, F.text == "-")
async def st_prod_img_skip(m: types.Message, state: FSMContext):
    await state.update_data(image_file_id=None)
    await state.set_state(AdminStates.product_desc)
    await m.answer("3/4 — Enter product <b>description</b>:", parse_mode="HTML")


@router.message(AdminStates.product_desc, F.text)
async def st_prod_desc(m: types.Message, state: FSMContext):
    await state.update_data(description=m.text.strip())
    await state.set_state(AdminStates.product_plan_name)
    await m.answer("4/4 — Plans. Send plan <b>name</b> or 'done':", parse_mode="HTML")


@router.message(AdminStates.product_plan_name, F.text)
async def st_plan_name(m: types.Message, state: FSMContext):
    if m.text.strip().lower() == "done":
        await _finish_product(m, state)
        return
    await state.update_data(_pn=m.text.strip())
    await state.set_state(AdminStates.product_plan_price)
    await m.answer("Plan <b>price</b> (₹):", parse_mode="HTML")


@router.message(AdminStates.product_plan_price, F.text)
async def st_plan_price(m: types.Message, state: FSMContext):
    try:
        price = float(m.text.strip())
    except ValueError:
        await m.answer("❌ Invalid price. Send a number:")
        return
    await state.update_data(_pp=price)
    await state.set_state(AdminStates.product_plan_hours)
    await m.answer("Duration in <b>hours</b>:", parse_mode="HTML")


@router.message(AdminStates.product_plan_hours, F.text)
async def st_plan_hours(m: types.Message, state: FSMContext):
    try:
        hours = int(m.text.strip())
    except ValueError:
        await m.answer("❌ Invalid hours. Send a number:")
        return
    data = await state.get_data()
    plans = data.get("plans", []) + [{
        "name": data["_pn"], "price": data["_pp"], "duration_hours": hours,
    }]
    await state.update_data(plans=plans)
    await state.set_state(AdminStates.product_plan_name)
    await m.answer(f"✅ Plan added ({len(plans)} total). Another plan name or 'done':")


async def _finish_product(m: types.Message, state: FSMContext):
    data = await state.get_data()
    db = Database.get_db()
    plans = data.get("plans", [])
    if not plans:
        await m.answer("❌ Add at least one plan.")
        return
    res = await db.products.insert_one({
        "name": data["name"], "description": data.get("description", ""),
        "image_file_id": data.get("image_file_id"),
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
    await _log(db, m.from_user.id, "add_product", {"name": data["name"]})
    await state.clear()
    await m.answer(f"✅ <b>{_esc(data['name'])}</b> created with {len(plans)} plan(s).",
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
        await callback.message.answer("❌ Invalid product.")
        return
    p = await db.products.find_one({"_id": pid})
    if not p:
        await callback.message.answer("❌ Product not found.")
        return
    plans = await db.plans.find({"product_id": pid}).to_list(50)
    stock = await svc.product_stock_total(db, pid)
    plan_txt = "\n".join(
        f"• {_esc(x['name'])} — ₹{x['price']} ({x.get('duration_hours',0)}h)"
        for x in plans) or "none"
    await callback.message.answer(
        f"🎮 <b>{_esc(p['name'])}</b> {'🟢' if p.get('status')=='active' else '🔴'}\n\n"
        f"{_esc(p.get('description') or '')}\n\n"
        f"⏱️ Plans ({len(plans)}):\n{plan_txt}\n\n🔑 Stock: {stock}",
        parse_mode="HTML", reply_markup=KB.product_detail(str(pid)))


# ---- product field edits ----

FIELD_LABELS = {"name": "name", "desc": "description", "img": "image",
                "ord": "display order", "toggle": "status"}


@router.callback_query(F.data.startswith("adm_pe_"))
async def cb_prod_edit(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("✏️ <b>EDIT PRODUCT</b> — choose field:",
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
        await callback.message.answer(f"Product {'🟢 enabled' if new=='active' else '🔴 disabled'}.")
        return

    if field == "img":
        await state.set_state(AdminStates.edit_field_img)
        await state.update_data(pid=pid)
        await callback.message.answer("🖼 Send new product <b>image</b> (photo):", parse_mode="HTML")
        return

    await state.set_state(AdminStates.edit_field)
    await state.update_data(pid=pid, field=field)
    await callback.message.answer(f"✏️ Enter new {FIELD_LABELS.get(field, field)}:")


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
        upd[{"name": "name", "desc": "description"}[field]] = val
    await db.products.update_one({"_id": ObjectId(pid)}, {"$set": upd})
    await _log(db, m.from_user.id, "edit_product", {"id": pid, "field": field})
    await state.clear()
    await m.answer(f"✅ {FIELD_LABELS.get(field, field)} updated.",
                   reply_markup=KB.back_nav(f"adm_prod_{pid}", "🔙 Product"))


@router.message(AdminStates.edit_field_img, F.photo)
async def st_edit_img(m: types.Message, state: FSMContext, db):
    data = await state.get_data()
    await db.products.update_one({"_id": ObjectId(data["pid"])},
        {"$set": {"image_file_id": m.photo[-1].file_id, "updated_at": svc.now_utc()}})
    await state.clear()
    await m.answer("✅ Image updated.", reply_markup=KB.back_nav(f"adm_prod_{data['pid']}", "🔙 Product"))


@router.callback_query(F.data.startswith("adm_pdel_"))
async def cb_prod_del(callback: types.CallbackQuery, db):
    pid = callback.data[10:]
    await callback.answer()
    p = await db.products.find_one({"_id": ObjectId(pid)})
    if not p:
        await callback.message.answer("❌ Not found.")
        return
    await callback.message.answer(
        f"🗑 Delete <b>{_esc(p['name'])}</b> and ALL its plans/keys?",
        parse_mode="HTML",
        reply_markup=KB.yes_no(f"adm_pdelok_{pid}", f"adm_prod_{pid}"))


@router.callback_query(F.data.startswith("adm_pdelok_"))
async def cb_prod_del_ok(callback: types.CallbackQuery, db):
    pid = callback.data[11:]
    oid = ObjectId(pid)
    await db.keys.delete_many({"product_id": oid})
    await db.plans.delete_many({"product_id": oid})
    await db.products.delete_one({"_id": oid})
    await _log(db, callback.from_user.id, "delete_product", {"id": pid})
    await callback.answer("Deleted.")
    await callback.message.answer("✅ Product deleted.", reply_markup=KB.back_nav("adm_products", "🔙 Products"))


@router.callback_query(F.data.startswith("adm_pview_"))
async def cb_prod_view(callback: types.CallbackQuery, db):
    pid = callback.data[10:]
    await callback.answer()
    p = await db.products.find_one({"_id": ObjectId(pid)})
    if not p:
        await callback.message.answer("❌ Not found.")
        return
    text = f"🎮 <b>{_esc(p['name'])}</b>\n\n{_esc(p.get('description') or '')}"
    if p.get("image_file_id"):
        try:
            await callback.message.answer_photo(p["image_file_id"], caption=text, parse_mode="HTML")
            return
        except Exception:
            pass
    await callback.message.answer(text, parse_mode="HTML")


# ================= Plans =================

@router.callback_query(F.data.startswith("adm_plans_"))
async def cb_plans(callback: types.CallbackQuery, db):
    pid = callback.data[10:]
    await callback.answer()
    p = await db.products.find_one({"_id": ObjectId(pid)})
    plans = await db.plans.find({"product_id": ObjectId(pid)}).sort("price", 1).to_list(50)
    rows = []
    for pl in plans:
        flag = "🟢" if pl.get("status") == "active" else "🔴"
        stock = await svc.stock_for_plan(db, pl["_id"])
        rows.append([InlineKeyboardButton(
            text=f"{flag} {pl['name']} ₹{pl['price']} | {stock} keys",
            callback_data=f"adm_plan_{pl['_id']}_{pid}")])
    rows.append([InlineKeyboardButton(text="➕ Add Plan", callback_data=f"adm_planadd_{pid}")])
    rows.append([InlineKeyboardButton(text="🔙 Product", callback_data=f"adm_prod_{pid}")])
    await callback.message.answer(
        f"⏱️ <b>PLANS — {_esc(p['name'] if p else '?')}</b>",
        parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_planadd_"))
async def cb_plan_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(AdminStates.plan_add_name)
    await state.update_data(pid=callback.data[12:], plans_count=0)
    await callback.message.answer("➕ Plan <b>name</b> (e.g. 1 Day):", parse_mode="HTML")


@router.message(AdminStates.plan_add_name, F.text)
async def st_pa_name(m, state):
    await state.update_data(_pn=m.text.strip())
    await state.set_state(AdminStates.plan_add_price)
    await m.answer("Plan <b>price</b> (₹):", parse_mode="HTML")


@router.message(AdminStates.plan_add_price, F.text)
async def st_pa_price(m, state):
    try:
        price = float(m.text.strip())
    except ValueError:
        await m.answer("❌ Invalid price.")
        return
    await state.update_data(_pp=price)
    await state.set_state(AdminStates.plan_add_hours)
    await m.answer("Duration in <b>hours</b>:", parse_mode="HTML")


@router.message(AdminStates.plan_add_hours, F.text)
async def st_pa_hours(m, state, db):
    try:
        hours = int(m.text.strip())
    except ValueError:
        await m.answer("❌ Invalid hours.")
        return
    data = await state.get_data()
    await db.plans.insert_one({
        "product_id": ObjectId(data["pid"]), "name": data["_pn"],
        "price": data["_pp"], "duration_hours": hours, "status": "active",
        "created_at": svc.now_utc(), "updated_at": svc.now_utc(),
    })
    await _log(db, m.from_user.id, "add_plan", {"product": data["pid"], "name": data["_pn"]})
    await state.clear()
    await m.answer("✅ Plan added.", reply_markup=KB.back_nav(f"adm_plans_{data['pid']}", "🔙 Plans"))


@router.callback_query(F.data.startswith("adm_plan_"))
async def cb_plan_detail(callback: types.CallbackQuery, db):
    # adm_plan_{plan_id}_{pid}
    rest = callback.data[len("adm_plan_"):]
    plan_id, pid = rest.rsplit("_", 1)
    await callback.answer()
    pl = await db.plans.find_one({"_id": ObjectId(plan_id)})
    if not pl:
        await callback.message.answer("❌ Plan not found.")
        return
    stock = await svc.stock_for_plan(db, pl["_id"])
    await callback.message.answer(
        f"⏱️ <b>{_esc(pl['name'])}</b> {'🟢' if pl.get('status')=='active' else '🔴'}\n\n"
        f"💰 ₹{pl['price']} | ⏳ {pl.get('duration_hours',0)}h\n"
        f"🔑 Available keys: {stock}",
        parse_mode="HTML", reply_markup=KB.plan_detail(plan_id, pid))


PLAN_FIELDS = {"name": "name", "price": "price", "hours": "duration_hours"}


@router.callback_query(F.data.startswith("adm_q_"))
async def cb_plan_action(callback: types.CallbackQuery, state: FSMContext, db):
    rest = callback.data[len("adm_q_"):]
    if rest.startswith("toggle_") or rest.startswith("del_"):
        plan_id = rest.split("_", 1)[1]
        pl = await db.plans.find_one({"_id": ObjectId(plan_id)})
        if not pl:
            await callback.answer("Not found", show_alert=True)
            return
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
    # edit field: adm_q_{field}_{plan_id}
    field, plan_id = rest.split("_", 1)
    await callback.answer()
    await state.set_state(AdminStates.plan_edit_field)
    await state.update_data(plan_id=plan_id, field=field)
    labels = {"name": "name", "price": "price (₹)", "hours": "duration hours"}
    await callback.message.answer(f"✏️ Enter new plan {labels.get(field, field)}:")


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
    pid = callback.data[11:]
    await callback.answer()
    p = await db.products.find_one({"_id": ObjectId(pid)})
    plans = await db.plans.find({"product_id": ObjectId(pid)}).to_list(50)
    rows = []
    for pl in plans:
        avail = await svc.stock_for_plan(db, pl["_id"])
        sold = await db.keys.count_documents({"plan_id": pl["_id"], "status": "sold"})
        icon = "🟢" if avail > 10 else ("🟡" if avail > 0 else "🔴")
        rows.append([InlineKeyboardButton(
            text=f"{icon} {pl['name']}: {avail} avail / {sold} sold",
            callback_data=f"adm_inv_{pl['_id']}_{pid}")])
    rows.append([InlineKeyboardButton(text="➕ Add Keys", callback_data=f"adm_keyadd_{pid}")])
    rows.append([InlineKeyboardButton(text="🔙 Product", callback_data=f"adm_prod_{pid}")])
    await callback.message.answer(
        f"🔑 <b>INVENTORY — {_esc(p['name'] if p else '?')}</b>",
        parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_keyadd_"))
async def cb_key_add(callback: types.CallbackQuery, db):
    pid = callback.data[11:]
    await callback.answer()
    plans = await db.plans.find({"product_id": ObjectId(pid), "status": "active"}).to_list(50)
    if not plans:
        await callback.message.answer("❌ No active plans.")
        return
    rows = [[InlineKeyboardButton(text=f"⏱️ {pl['name']} (₹{pl['price']})",
            callback_data=f"adm_keyplan_{pl['_id']}_{pid}")] for pl in plans]
    rows.append([InlineKeyboardButton(text="🔙 Inventory", callback_data=f"adm_pkeys_{pid}")])
    await callback.message.answer("Select plan to add keys to:", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_keyplan_"))
async def cb_key_plan(callback: types.CallbackQuery, state: FSMContext):
    rest = callback.data[len("adm_keyplan_"):]
    plan_id, pid = rest.rsplit("_", 1)
    await callback.answer()
    await state.set_state(AdminStates.adding_keys)
    await state.update_data(plan_id=plan_id, pid=pid)
    await callback.message.answer(
        "🔑 Send keys — <b>one per line</b> (single or bulk paste):\n\n"
        "<code>KEY-AAAA-1111\nKEY-BBBB-2222</code>",
        parse_mode="HTML")


@router.message(AdminStates.adding_keys, F.text)
async def st_add_keys(m, state, db):
    data = await state.get_data()
    keys = [l.strip() for l in m.text.splitlines() if l.strip()]
    if not keys:
        await m.answer("❌ No keys detected.")
        return
    plan_oid = ObjectId(data["plan_id"])
    pid = ObjectId(data["pid"])
    added = skipped = 0
    for kv in keys:
        try:
            await db.keys.insert_one({
                "product_id": pid, "plan_id": plan_oid,
                "key_value": kv.upper(), "status": "available",
                "created_at": svc.now_utc(),
            })
            added += 1
        except Exception:
            skipped += 1
    await _log(db, m.from_user.id, "add_keys",
               {"plan": data["plan_id"], "added": added})
    await state.clear()
    await m.answer(f"✅ Added {added} key(s)" + (f", skipped {skipped} duplicates." if skipped else "."),
                   reply_markup=KB.back_nav(f"adm_pkeys_{data['pid']}", "🔙 Inventory"))


@router.callback_query(F.data.startswith("adm_inv_"))
async def cb_inventory(callback: types.CallbackQuery, db):
    rest = callback.data[len("adm_inv_"):]
    plan_id, pid = rest.rsplit("_", 1)
    await callback.answer()
    pl = await db.plans.find_one({"_id": ObjectId(plan_id)})
    keys = await db.keys.find({"plan_id": ObjectId(plan_id)}).sort("created_at", -1).to_list(30)
    lines = [f"🔑 <b>{_esc(pl['name'] if pl else '?')} — INVENTORY</b>\n"]
    for k in keys:
        icon = "🟢" if k.get("status") == "available" else "⚫"
        lines.append(f"{icon} <code>{_esc(k['key_value'])}</code> — {k.get('status')}")
    await callback.message.answer("\n".join(lines)[:4000], parse_mode="HTML",
        reply_markup=_kb([
            [InlineKeyboardButton(text="🗑 Delete Key", callback_data=f"adm_keydel_{plan_id}")],
            [InlineKeyboardButton(text="🔍 Search Keys", callback_data="adm_keysearch")],
            [InlineKeyboardButton(text="🔙 Inventory", callback_data=f"adm_pkeys_{pid}")],
        ]))


@router.callback_query(F.data == "adm_keys")
async def cb_keys_main(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "🔑 <b>KEY MANAGEMENT</b>\n\nPick a product to view inventory, or search keys.",
        parse_mode="HTML",
        reply_markup=_kb([
            [InlineKeyboardButton(text="🔍 Search Keys", callback_data="adm_keysearch")],
            [InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")],
        ]))


@router.callback_query(F.data == "adm_keysearch")
async def cb_key_search(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.search_keys)
    await callback.message.answer("🔍 Send key text to search (partial match):")


@router.message(AdminStates.search_keys, F.text)
async def st_search_keys(m, state, db):
    q = m.text.strip()
    await state.clear()
    keys = await db.keys.find(
        {"key_value": {"$regex": q, "$options": "i"}}).to_list(20)
    if not keys:
        await m.answer("No keys found.", reply_markup=KB.back_nav("adm_dash", "🔙 Dashboard"))
        return
    rows = []
    for k in keys:
        rows.append([InlineKeyboardButton(
            text=f"{'🟢' if k.get('status')=='available' else '⚫'} {_esc(k['key_value'][:30])}",
            callback_data=f"adm_keydel_{k['_id']}")])
    rows.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")])
    await m.answer(f"🔍 {len(keys)} result(s):", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_keydel_"))
async def cb_key_del(callback: types.CallbackQuery, db):
    kid = callback.data[11:]
    await callback.answer()
    k = await db.keys.find_one({"_id": ObjectId(kid)})
    if not k:
        await callback.message.answer("❌ Not found.")
        return
    if k.get("status") == "sold":
        await callback.message.answer("⚠️ Key already sold — cannot delete.")
        return
    await db.keys.delete_one({"_id": k["_id"]})
    await _log(db, callback.from_user.id, "delete_key", {"id": kid})
    await callback.message.answer(f"🗑 Key <code>{_esc(k['key_value'])}</code> deleted.",
                                  parse_mode="HTML")


# ================= Payments =================

@router.callback_query(F.data == "adm_payments")
async def cb_payments(callback: types.CallbackQuery, db):
    await callback.answer()
    pays = await db.payments.find({"status": "pending"}).sort("created_at", -1).to_list(20)
    if not pays:
        await callback.message.answer("✅ No pending payments.",
            reply_markup=KB.back_nav("adm_dash", "🔙 Dashboard"))
        return
    rows = [[InlineKeyboardButton(
        text=f"🟡 {p.get('public_order_id','?')} — ₹{p.get('amount',0):.0f} — UTR: {p.get('utr') or '-'}",
        callback_data=f"ver_{p.get('public_order_id')}")] for p in pays]
    rows.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")])
    await callback.message.answer("💳 <b>PENDING PAYMENTS</b>", parse_mode="HTML",
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


@router.callback_query(F.data.regexp(r"^ver_(?!ok_|no_|cust_)"))
async def cb_verify(callback: types.CallbackQuery, db):
    order_id = callback.data[4:]
    await callback.answer()
    text, pay = await _payment_detail_text(db, order_id)
    if not text:
        await callback.message.answer("❌ Order not found.")
        return
    if pay and pay.get("screenshot_file_id"):
        try:
            await callback.message.answer_photo(
                pay["screenshot_file_id"], caption=text, parse_mode="HTML",
                reply_markup=KB.verify_payment(order_id))
            return
        except Exception:
            pass
    await callback.message.answer(text, parse_mode="HTML",
                                  reply_markup=KB.verify_payment(order_id))


@router.callback_query(F.data.startswith("ver_ok_"))
async def cb_verify_ok(callback: types.CallbackQuery, db):
    order_id = callback.data[7:]
    await callback.answer("Approving...")
    order = await db.orders.find_one({"order_id": order_id})
    if not order or order.get("status") != "pending":
        await callback.message.answer("⚠️ Order not pending — already processed.")
        return
    result = await svc.approve_payment(db, order, callback.from_user.id)
    if result is None:
        await callback.message.answer("⚠️ Already processed.")
        return
    if result.get("error") == "out_of_stock":
        await callback.message.answer(
            "🔴 OUT OF STOCK — order left pending. Add keys first.",
            reply_markup=KB.back_nav("adm_payments", "🔙 Payments"))
        await _notify_customer_text(callback.bot, order["telegram_id"],
            f"⚠️ Your order {order_id} is approved but we're out of stock. Support will resolve shortly.")
        return

    product = result["product"]
    await svc.deliver_order(callback.bot, db, result["order"], product)
    await _log(db, callback.from_user.id, "approve_payment", {"order": order_id})
    await callback.message.answer(
        f"✅ Payment approved & delivered.\nOrder: <code>{order_id}</code>",
        parse_mode="HTML", reply_markup=KB.back_nav("adm_payments", "🔙 Payments"))
    await _notify_customer_text(callback.bot, order["telegram_id"],
        f"🎉 Payment verified! Your key + files are on the way. 🆔 {order_id}")


@router.callback_query(F.data.startswith("ver_no_"))
async def cb_verify_no(callback: types.CallbackQuery, db):
    order_id = callback.data[7:]
    await callback.answer("Rejecting...")
    order = await db.orders.find_one({"order_id": order_id})
    if not order or order.get("status") != "pending":
        await callback.message.answer("⚠️ Already processed.")
        return
    await svc.reject_payment(db, order, callback.from_user.id)
    await _log(db, callback.from_user.id, "reject_payment", {"order": order_id})
    await callback.message.answer(f"❌ Order <code>{order_id}</code> rejected.",
                                  parse_mode="HTML",
                                  reply_markup=KB.back_nav("adm_payments", "🔙 Payments"))
    await _notify_customer_text(callback.bot, order["telegram_id"],
        f"❌ Payment for order {order_id} was rejected. Contact support if this is a mistake.")


@router.callback_query(F.data.startswith("ver_cust_"))
async def cb_verify_cust(callback: types.CallbackQuery, db):
    order_id = callback.data[9:]
    await callback.answer()
    order = await db.orders.find_one({"order_id": order_id})
    if not order:
        await callback.message.answer("❌ Not found.")
        return
    user = await db.users.find_one({"_id": order["user_id"]})
    await callback.message.answer(
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
        await callback.message.answer("No orders.", reply_markup=KB.back_nav("adm_dash", "🔙"))
        return
    rows = [[InlineKeyboardButton(
        text=f"{o.get('order_id')} — {_esc(o.get('product_name',''))[:15]} ₹{o.get('amount',0):.0f} [{o.get('status','?')[:4]}]",
        callback_data=f"adm_order_{o['order_id']}")] for o in orders]
    rows.append([InlineKeyboardButton(text="🔍 Search Order", callback_data="adm_ordersearch")])
    rows.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")])
    await callback.message.answer("📦 <b>RECENT ORDERS</b>", parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_order_"))
async def cb_order_detail(callback: types.CallbackQuery, db):
    oid = callback.data[10:]
    await callback.answer()
    o = await db.orders.find_one({"order_id": oid})
    if not o:
        await callback.message.answer("❌ Not found.")
        return
    pay = await db.payments.find_one({"order_id": o["_id"]})
    await callback.message.answer(
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
        ]) if o.get("status") == "delivered" else KB.back_nav("adm_orders", "🔙 Orders"))


@router.callback_query(F.data.startswith("adm_redeliver_"))
async def cb_redeliver(callback: types.CallbackQuery, db):
    oid = callback.data[14:]
    await callback.answer("Resending...")
    o = await db.orders.find_one({"order_id": oid})
    if not o:
        await callback.message.answer("❌ Not found.")
        return
    product = await db.products.find_one({"_id": o["product_id"]})
    if product:
        await svc.deliver_order(callback.bot, db, o, product)
    await _log(db, callback.from_user.id, "redeliver", {"order": oid})
    await callback.message.answer("✅ Delivery resent.")


@router.callback_query(F.data == "adm_ordersearch")
async def cb_order_search(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.search_orders)
    await callback.message.answer("🔍 Send order ID (e.g. KS000123) or Telegram ID:")


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
    await callback.message.answer("👥 <b>CUSTOMERS</b> (latest 15)", parse_mode="HTML",
                                  reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_cust_"))
async def cb_customer(callback: types.CallbackQuery, db):
    tid = int(callback.data[9:])
    await callback.answer()
    u = await db.users.find_one({"telegram_id": tid})
    if not u:
        await callback.message.answer("❌ Not found.")
        return
    orders = await db.orders.count_documents({"telegram_id": tid})
    spent = await db.orders.aggregate([
        {"$match": {"telegram_id": tid, "status": {"$in": ["paid", "delivered"]}}},
        {"$group": {"_id": None, "t": {"$sum": "$amount"}}},
    ]).to_list(1)
    blocked = u.get("is_blocked", False)
    await callback.message.answer(
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
    rows = [[InlineKeyboardButton(text=f"🎮 {p['name']}", callback_data=f"adm_pfiles_{p['_id']}")]
            for p in products]
    # global tutorial
    tut = await db.tutorial.find_one({"_id": "howto"})
    rows.append([InlineKeyboardButton(
        text=f"🎓 How-to-Buy Video {'✅' if tut and tut.get('file_id') else '❌'}",
        callback_data="adm_tutorial")])
    rows.append([InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")])
    await callback.message.answer("📁 <b>FILES & LINKS</b> — pick a product:",
                                  parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data == "adm_tutorial")
async def cb_tutorial(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.tutorial_video)
    await callback.message.answer(
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
        await callback.message.answer("❌ Not found.")
        return
    files = p.get("files", {})
    status = {k: ("✅" if files.get(k, {}).get("file_id") else "❌")
              for k in ("apk", "video", "document")}
    await callback.message.answer(
        f"📁 <b>FILES — {_esc(p['name'])}</b>\n\n"
        f"📱 APK: {status['apk']} | 🎬 Video: {status['video']} | 📄 Doc: {status['document']}",
        parse_mode="HTML",
        reply_markup=_kb([
            [InlineKeyboardButton(text="📱 Upload APK", callback_data=f"adm_fu_apk_{pid}"),
             InlineKeyboardButton(text="🎬 Upload Video", callback_data=f"adm_fu_vid_{pid}")],
            [InlineKeyboardButton(text="📄 Upload Doc", callback_data=f"adm_fu_doc_{pid}"),
             InlineKeyboardButton(text="📝 Instructions", callback_data=f"adm_fi_{pid}")],
            [InlineKeyboardButton(text="🗑 Clear Files", callback_data=f"adm_fc_{pid}"),
             InlineKeyboardButton(text="🔗 Links", callback_data=f"adm_plinks_{pid}")],
            [InlineKeyboardButton(text="🔙 Product", callback_data=f"adm_prod_{pid}")],
        ]))


class _FileStates(StatesGroup):
    apk = State()
    vid = State()
    doc = State()


FILE_STATE_MAP = {"fu_apk": _FileStates.apk, "fu_vid": _FileStates.vid, "fu_doc": _FileStates.doc}


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
        kind={"apk": "apk", "vid": "video", "doc": "document"}[kind])
    labels = {"apk": "APK file (send as document/file)", "vid": "setup video", "doc": "document"}
    await callback.message.answer(f"📤 Send the {labels[kind]}:")


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


@router.message(_FileStates.doc, F.document)
async def st_fu_doc(m, state, db):
    await _save_file(m, state, db, m.document.file_id, m.document.file_name)


@router.callback_query(F.data.startswith("adm_fc_"))
async def cb_files_clear(callback: types.CallbackQuery, db):
    pid = callback.data[7:]
    await callback.answer()
    await db.products.update_one({"_id": ObjectId(pid)}, {"$set": {"files": {}}})
    await callback.message.answer("🗑 All product files cleared.")


@router.callback_query(F.data.startswith("adm_fi_"))
async def cb_file_instr(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.file_instructions)
    await state.update_data(pid=callback.data[7:])
    await callback.message.answer("📝 Send new <b>setup instructions</b> text:", parse_mode="HTML")


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
    await callback.message.answer(txt, parse_mode="HTML", reply_markup=_kb(rows))


@router.callback_query(F.data.startswith("adm_ladd_"))
async def cb_link_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.link_title)
    await state.update_data(pid=callback.data[8:])
    await callback.message.answer("🔗 Link <b>title</b> (e.g. Download APK):", parse_mode="HTML")


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
    rest = callback.data[8:]
    pid, idx = rest.rsplit("_", 1)
    p = await db.products.find_one({"_id": ObjectId(pid)})
    if p and 0 <= int(idx) < len(p.get("links", [])):
        links = p["links"]
        links.pop(int(idx))
        await db.products.update_one({"_id": p["_id"]}, {"$set": {"links": links}})
    await callback.answer("Deleted")
    await cb_plinks(callback, db)


# ================= Broadcast =================

@router.callback_query(F.data == "adm_broadcast")
async def cb_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AdminStates.broadcast_content)
    await callback.message.answer(
        "📢 <b>BROADCAST</b>\n\nSend the message to ALL users:\n"
        "• Text, or\n• Photo (with optional caption), or\n• Video/Document",
        parse_mode="HTML")


@router.message(AdminStates.broadcast_content, F.photo)
async def st_bc_photo(m, state, db):
    await _do_broadcast(m, state, db, "photo", m.photo[-1].file_id, m.caption)


@router.message(AdminStates.broadcast_content, F.video)
async def st_bc_video(m, state, db):
    await _do_broadcast(m, state, db, "video", m.video.file_id, m.caption)


@router.message(AdminStates.broadcast_content, F.document)
async def st_bc_doc(m, state, db):
    await _do_broadcast(m, state, db, "document", m.document.file_id, m.caption)


@router.message(AdminStates.broadcast_content, F.text)
async def st_bc_text(m, state, db):
    await _do_broadcast(m, state, db, "text", m.text, None)


async def _do_broadcast(m, state, db, kind, payload, caption):
    users = await db.users.find({"is_blocked": {"$ne": True}}, {"telegram_id": 1}).to_list(10000)
    status = await m.answer(f"📢 Broadcasting to {len(users)} users...")
    sent = failed = 0
    for u in users:
        try:
            if kind == "text":
                await m.bot.send_message(u["telegram_id"], payload)
            elif kind == "photo":
                await m.bot.send_photo(u["telegram_id"], payload, caption=caption)
            elif kind == "video":
                await m.bot.send_video(u["telegram_id"], payload, caption=caption)
            else:
                await m.bot.send_document(u["telegram_id"], payload, caption=caption)
            sent += 1
        except Exception:
            failed += 1
        # rate limit ~30 msg/s
        if (sent + failed) % 30 == 0:
            await asyncio.sleep(1)
    await _log(db, m.from_user.id, "broadcast", {"sent": sent, "failed": failed, "kind": kind})
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


@router.callback_query(F.data == "adm_settings")
async def cb_settings(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("⚙️ <b>BOT SETTINGS</b>", parse_mode="HTML",
                                  reply_markup=KB.settings_menu())


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
    await callback.message.answer(f"✏️ Enter new value for <b>{label}</b>:",
                                  parse_mode="HTML")


@router.message(AdminStates.edit_setting, F.text)
async def st_edit_setting(m, state, db):
    data = await state.get_data()
    await db.settings.update_one({"key": data["key"]},
        {"$set": {"key": data["key"], "value": m.text.strip(), "updated_at": svc.now_utc()}},
        upsert=True)
    await _log(db, m.from_user.id, "edit_setting", {"key": data["key"]})
    await state.clear()
    await m.answer("✅ Setting saved.", reply_markup=KB.back_nav("adm_settings", "🔙 Settings"))


@router.callback_query(F.data == "adm_paymode")
async def cb_paymode(callback: types.CallbackQuery, db):
    await callback.answer()
    s = await svc.get_settings(db)
    cur = s.get("payment_mode", "manual")
    new = "automatic" if cur == "manual" else "manual"
    await db.settings.update_one({"key": "payment_mode"},
        {"$set": {"key": "payment_mode", "value": new, "updated_at": svc.now_utc()}}, upsert=True)
    await _log(db, callback.from_user.id, "payment_mode", {"mode": new})
    await callback.message.answer(
        f"💳 Payment mode → <b>{new.upper()}</b>\n\n"
        "⚠️ 'automatic' requires a configured provider — manual UPI is the safe default.",
        parse_mode="HTML", reply_markup=KB.back_nav("adm_settings", "🔙 Settings"))


@router.callback_query(F.data == "adm_maintoggle")
async def cb_maintoggle(callback: types.CallbackQuery, db):
    await callback.answer()
    cur = await db.settings.find_one({"key": "maintenance_mode"})
    new = not (cur and cur.get("value"))
    await db.settings.update_one({"key": "maintenance_mode"},
        {"$set": {"key": "maintenance_mode", "value": new, "updated_at": svc.now_utc()}}, upsert=True)
    await _log(db, callback.from_user.id, "maintenance", {"on": new})
    await callback.message.answer(
        f"🔧 Maintenance {'🔴 ENABLED' if new else '🟢 DISABLED'}",
        reply_markup=KB.back_nav("adm_settings", "🔙 Settings"))


# ================= Admins =================

@router.callback_query(F.data == "adm_admins")
async def cb_admins(callback: types.CallbackQuery, db):
    await callback.answer()
    admins = await db.users.find({"is_admin": True}).to_list(50)
    rows = "\n".join(
        f"• {_esc(u.get('first_name',''))} @{_esc(u.get('username') or '-')} — <code>{u['telegram_id']}</code>"
        for u in admins)
    await callback.message.answer(
        f"🛡️ <b>ADMINS</b>\n\n{rows or 'none'}\n\n"
        f"Env ADMIN_IDS: {', '.join(map(str, Config.ADMIN_IDS))}\n\n"
        "To add an admin: add their Telegram ID to ADMIN_IDS in .env and restart.",
        parse_mode="HTML", reply_markup=KB.back_nav("adm_dash", "🔙 Dashboard"))
