"""Core services: orders, payments, atomic inventory, delivery"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from bson import ObjectId
from pymongo import ReturnDocument

from bot.db import Database
from config import Config

logger = logging.getLogger(__name__)

IST = __import__("datetime").timezone(__import__("datetime").timedelta(hours=5, minutes=30))


def now_utc() -> datetime:
    return datetime.utcnow()


def fmt_ist(dt: datetime) -> str:
    return dt.replace(tzinfo=__import__("datetime").timezone.utc).astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


async def get_settings(db) -> Dict[str, Any]:
    """All settings as dict"""
    cursor = db.settings.find({})
    return {d["key"]: d.get("value") for d in await cursor.to_list(length=None)}


async def next_order_id(db) -> str:
    """Sequential order id KSxxxxxx"""
    doc = await db.counters.find_one_and_update(
        {"_id": "order"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"KS{doc['seq']:06d}"


async def create_order(user: Dict, product: Dict, plan: Dict, db) -> Dict:
    """Create pending order + pending payment atomically-ish"""
    order_id = await next_order_id(db)
    validity = int(Config.PAYMENT_VALIDITY_MINUTES)
    expiry = now_utc() + timedelta(minutes=validity)

    order = {
        "order_id": order_id,
        "user_id": user["_id"],
        "telegram_id": user["telegram_id"],
        "product_id": product["_id"],
        "plan_id": plan["_id"],
        "product_name": product["name"],
        "plan_name": plan["name"],
        "amount": float(plan["price"]),
        "status": "pending",
        "key_id": None,
        "key_value": None,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    res = await db.orders.insert_one(order)
    order["_id"] = res.inserted_id

    payment = {
        "order_id": res.inserted_id,
        "public_order_id": order_id,
        "user_id": user["_id"],
        "telegram_id": user["telegram_id"],
        "amount": float(plan["price"]),
        "status": "pending",
        "utr": None,
        "screenshot_file_id": None,
        "expiry_time": expiry,
        "provider": "manual_upi",
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    await db.payments.insert_one(payment)
    order["payment"] = payment
    return order


async def cancel_user_pending_orders(db, telegram_id: int):
    """Cancel all pending orders+payments for a user (new session / superseded)"""
    pending = await db.orders.find(
        {"telegram_id": telegram_id, "status": "pending"}
    ).to_list(length=None)
    for o in pending:
        await db.orders.update_one(
            {"_id": o["_id"]},
            {"$set": {"status": "cancelled", "updated_at": now_utc()}},
        )
        await db.payments.update_many(
            {"order_id": o["_id"], "status": "pending"},
            {"$set": {"status": "expired", "updated_at": now_utc()}},
        )


async def submit_payment_details(db, payment_oid, utr=None, screenshot_file_id=None):
    upd = {"updated_at": now_utc()}
    if utr:
        upd["utr"] = utr
    if screenshot_file_id:
        upd["screenshot_file_id"] = screenshot_file_id
    await db.payments.update_one({"_id": payment_oid}, {"$set": upd})


async def allocate_key(db, plan_id) -> Optional[Dict]:
    """Atomically allocate one available key for a plan"""
    return await db.keys.find_one_and_update(
        {"plan_id": plan_id, "status": "available"},
        {"$set": {"status": "sold", "sold_at": now_utc()}},
    )


async def approve_payment(db, order: Dict, admin_telegram_id: int) -> Optional[Dict]:
    """Idempotent approval: only pending orders get processed.
    Returns delivery payload or None if not eligible."""
    # Atomic guard: only transition pending -> paid once
    res = await db.orders.update_one(
        {"_id": order["_id"], "status": "pending"},
        {"$set": {"status": "paid", "updated_at": now_utc(), "paid_at": now_utc()}},
    )
    if res.modified_count == 0:
        return None

    key = await allocate_key(db, order["plan_id"])
    if not key:
        # Out of stock - revert to pending and flag
        await db.orders.update_one(
            {"_id": order["_id"]},
            {"$set": {"status": "pending", "updated_at": now_utc()}},
        )
        return {"error": "out_of_stock"}

    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$set": {
            "status": "paid",
            "key_id": key["_id"],
            "key_value": key["key_value"],
            "updated_at": now_utc(),
        }},
    )
    await db.payments.update_many(
        {"order_id": order["_id"]},
        {"$set": {"status": "approved", "updated_at": now_utc(),
                  "approved_by": admin_telegram_id}},
    )

    product = await db.products.find_one({"_id": order["product_id"]})
    return {"key": key, "product": product, "order": order}


async def reject_payment(db, order: Dict, admin_telegram_id: int):
    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$set": {"status": "rejected", "updated_at": now_utc()}},
    )
    await db.payments.update_many(
        {"order_id": order["_id"]},
        {"$set": {"status": "rejected", "updated_at": now_utc(),
                  "rejected_by": admin_telegram_id}},
    )


async def expire_due_payments(db) -> int:
    """Expire pending payments past expiry_time. Returns count."""
    now = now_utc()
    cursor = db.payments.find({"status": "pending", "expiry_time": {"$lt": now}})
    expired = await cursor.to_list(length=None)
    for pay in expired:
        await db.payments.update_one(
            {"_id": pay["_id"]},
            {"$set": {"status": "expired", "updated_at": now}},
        )
        await db.orders.update_one(
            {"order_id": pay.get("public_order_id")},
            {"$set": {"status": "expired", "updated_at": now}},
        )
    return len(expired)


async def stock_for_plan(db, plan_id) -> int:
    return await db.keys.count_documents({"plan_id": plan_id, "status": "available"})


async def enrich_plans(db, product_id) -> list:
    """Plans with live stock counts"""
    plans = await db.plans.find({
        "product_id": product_id, "status": "active"
    }).sort("price", 1).to_list(length=50)
    out = []
    for p in plans:
        p["stock"] = await stock_for_plan(db, p["_id"])
        out.append(p)
    return out


async def product_stock_total(db, product_id) -> int:
    return await db.keys.count_documents({
        "product_id": product_id, "status": "available"
    })


# ---------------- Delivery ----------------

async def deliver_order(bot, db, order: Dict, product: Dict) -> bool:
    """Send key + files + links to the customer. Returns True on success."""
    tid = order["telegram_id"]
    oid = order["order_id"]

    # 1) Key message
    await bot.send_message(
        tid,
        "🔑 <b>YOUR LICENSE KEY</b>\n\n"
        f"🎮 {order.get('product_name', '')}\n"
        f"⏱️ {order.get('plan_name', '')}\n\n"
        f"<code>{order.get('key_value', 'N/A')}</code>\n\n"
        f"🆔 Order: {oid}",
        parse_mode="HTML",
    )

    # 2) Product files (apk / video / docs stored as Telegram file_ids)
    files = product.get("files", {}) if product else {}
    captions = {
        "apk": "📱 <b>Latest APK</b>\nDownload and install to activate your key.",
        "video": "🎬 <b>Setup Video</b>\nWatch this before activating.",
        "document": "📄 <b>Setup Document</b>",
    }
    for kind in ("apk", "video", "document"):
        f = files.get(kind)
        if not f or not f.get("file_id"):
            continue
        try:
            if kind == "apk":
                await bot.send_document(tid, f["file_id"], caption=captions[kind], parse_mode="HTML")
            elif kind == "video":
                await bot.send_video(tid, f["file_id"], caption=captions[kind], parse_mode="HTML")
            else:
                await bot.send_document(tid, f["file_id"], caption=captions[kind], parse_mode="HTML")
        except Exception as e:
            logger.error(f"Delivery file {kind} failed for order {oid}: {e}")
            await bot.send_message(
                tid,
                f"⚠️ Could not deliver {kind} automatically. "
                "Please contact support — your key above is valid.",
            )

    # 3) Instructions
    instr = product.get("instructions") if product else None
    if instr:
        await bot.send_message(tid, f"📝 <b>SETUP INSTRUCTIONS</b>\n\n{instr}", parse_mode="HTML")

    # 4) Important links
    links = product.get("links", []) if product else []
    if links:
        text = "🔗 <b>IMPORTANT LINKS</b>\n"
        for l in links:
            text += f"\n• <a href=\"{l['url']}\">{l.get('title', 'Open')}</a>"
        await bot.send_message(tid, text, parse_mode="HTML", disable_web_page_preview=True)

    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$set": {"status": "delivered", "delivered_at": now_utc(), "updated_at": now_utc()}},
    )
    return True
