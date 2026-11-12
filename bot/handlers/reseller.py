"""Reseller admin actions - approve/reject applications"""

import logging

from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import bot.svc as svc
from bot.db import Database

logger = logging.getLogger(__name__)
router = Router(name="reseller")


@router.message.middleware()
@router.callback_query.middleware()
async def admin_guard(handler, event, data):
    if not data.get("is_admin"):
        if isinstance(event, types.CallbackQuery):
            await event.answer("⛔ Admin only", show_alert=True)
        return None
    return await handler(event, data)


@router.callback_query(F.data.startswith("res_ok_"))
async def res_approve(callback: types.CallbackQuery, db):
    tid = int(callback.data[7:])
    await callback.answer("Approving...")
    r = await db.resellers.find_one({"telegram_id": tid, "status": "pending"})
    if not r:
        await callback.message.edit_text("⚠️ Application not found or already processed.")
        return
    code = f"RS{tid % 100000:05d}"
    await db.resellers.update_one({"_id": r["_id"]}, {"$set": {
        "status": "active", "reseller_code": code,
        "discount_percentage": 10, "balance": 0.0,
        "approved_at": svc.now_utc(), "updated_at": svc.now_utc(),
    }})
    await callback.message.edit_text(f"✅ Reseller <code>{tid}</code> approved. Code: {code}")
    try:
        await callback.bot.send_message(tid,
            f"🎉 Your reseller application was approved!\n\n"
            f"Code: <code>{code}</code>\nDiscount: 10%", parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data.startswith("res_no_"))
async def res_reject(callback: types.CallbackQuery, db):
    tid = int(callback.data[7:])
    await callback.answer("Rejecting...")
    r = await db.resellers.find_one({"telegram_id": tid, "status": "pending"})
    if not r:
        await callback.message.edit_text("⚠️ Not found or already processed.")
        return
    await db.resellers.update_one({"_id": r["_id"]}, {"$set": {
        "status": "rejected", "updated_at": svc.now_utc()}})
    await callback.message.edit_text(f"❌ Reseller <code>{tid}</code> rejected.")
    try:
        await callback.bot.send_message(tid, "❌ Your reseller application was not approved.")
    except Exception:
        pass
