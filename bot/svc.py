"""Core services: orders, payments, atomic inventory, delivery (bot/svc.py)"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from pymongo import ReturnDocument

from bot.db import Database
from config import Config

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def now_utc() -> datetime:
    return datetime.utcnow()


def fmt_ist(dt: datetime) -> str:
    if dt is None:
        return "-"
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


async def get_settings(db) -> Dict[str, Any]:
    cursor = db.settings.find({})
    return {d["key"]: d.get("value") for d in await cursor.to_list(length=None)}


async def next_order_id(db) -> str:
    doc = await db.counters.find_one_and_update(
        {"_id": "order"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return f"KS{doc['seq']:06d}"


async def create_order(user: Dict, product: Dict, plan: Dict, db) -> Dict:
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

    # NOTE: do NOT include utr/screenshot keys here - the legacy unique sparse
    # index on payments.utr treats null as a value and would collide.
    s = await get_settings(db)
    payment = {
        "order_id": res.inserted_id,
        "public_order_id": order_id,
        "user_id": user["_id"],
        "telegram_id": user["telegram_id"],
        "amount": float(plan["price"]),
        "status": "pending",
        "expiry_time": expiry,
        "provider": s.get("payment_mode", "manual") or "manual",
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    await db.payments.insert_one(payment)
    order["payment"] = payment
    return order


async def cancel_user_pending_orders(db, telegram_id: int):
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


async def stock_for_plan(db, plan_id) -> int:
    return await db.keys.count_documents({"plan_id": plan_id, "status": "available"})


async def allocate_key(db, plan_id) -> Optional[Dict]:
    """Atomically allocate one available key - safe under concurrency"""
    return await db.keys.find_one_and_update(
        {"plan_id": plan_id, "status": "available"},
        {"$set": {"status": "sold", "sold_at": now_utc()}},
    )


async def approve_payment(db, order: Dict, admin_telegram_id: int) -> Optional[Dict]:
    """Idempotent approval. Returns payload dict, {'error':...}, or None if ineligible."""
    res = await db.orders.update_one(
        {"_id": order["_id"], "status": "pending"},
        {"$set": {"status": "paid", "updated_at": now_utc(), "paid_at": now_utc()}},
    )
    if res.modified_count == 0:
        return None

    key = await allocate_key(db, order["plan_id"])
    if not key:
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


async def expire_due_payments(db):
    """Expire pending payments past expiry_time. Returns list of expired docs."""
    now = now_utc()
    cursor = db.payments.find({"status": "pending", "expiry_time": {"$lt": now}})
    expired = await cursor.to_list(length=None)
    for pay in expired:
        await db.payments.update_one(
            {"_id": pay["_id"]},
            {"$set": {"status": "expired", "updated_at": now,
                      "expiry_notified": True}},
        )
        if pay.get("public_order_id"):
            await db.orders.update_one(
                {"order_id": pay["public_order_id"]},
                {"$set": {"status": "expired", "updated_at": now}},
            )
    return expired


async def product_stock_total(db, product_id) -> int:
    return await db.keys.count_documents({
        "product_id": product_id, "status": "available"
    })


async def enrich_plans(db, product_id) -> list:
    plans = await db.plans.find({
        "product_id": product_id, "status": "active"
    }).sort("price", 1).to_list(length=50)
    out = []
    for p in plans:
        p["stock"] = await stock_for_plan(db, p["_id"])
        out.append(p)
    return out


# ---------------- Delivery ----------------

def _product_files(product: Dict) -> Dict[str, Dict]:
    """Normalize file storage - new schema (files.{kind}.file_id) with
    fallback to legacy flat fields."""
    files = dict(product.get("files", {}) or {})
    if product.get("apk_file_id") and "apk" not in files:
        files["apk"] = {"file_id": product["apk_file_id"], "name": product.get("apk_name")}
    if product.get("setup_video_file_id") and "video" not in files:
        files["video"] = {"file_id": product["setup_video_file_id"]}
    if product.get("setup_doc_file_id") and "document" not in files:
        files["document"] = {"file_id": product["setup_doc_file_id"]}
    return files


async def resend_product_files(bot, telegram_id: int, product: Dict):
    """Send stored product files (used by My Files / redelivery)."""
    files = _product_files(product)
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
            if kind == "video":
                await bot.send_video(telegram_id, f["file_id"],
                                     caption=captions[kind], parse_mode="HTML")
            else:
                await bot.send_document(telegram_id, f["file_id"],
                                        caption=captions[kind], parse_mode="HTML")
        except Exception as e:
            logger.error(f"File resend {kind} failed: {e}")


async def deliver_order(bot, db, order: Dict, product: Dict) -> bool:
    """Send key + files + instructions + links. Marks order delivered."""
    tid = order["telegram_id"]
    oid = order["order_id"]

    await bot.send_message(
        tid,
        "🔑 <b>YOUR LICENSE KEY</b>\n\n"
        f"🎮 {_esc(order.get('product_name',''))}\n"
        f"⏱️ {_esc(order.get('plan_name',''))}\n\n"
        f"<code>{_esc(order.get('key_value','N/A'))}</code>\n\n"
        f"🆔 Order: {oid}",
        parse_mode="HTML",
    )

    await resend_product_files(bot, tid, product or {})

    instr = (product or {}).get("instructions")
    if instr:
        await bot.send_message(tid, f"📝 <b>SETUP INSTRUCTIONS</b>\n\n{instr}",
                               parse_mode="HTML")

    links = (product or {}).get("links", [])
    if links:
        text = "🔗 <b>IMPORTANT LINKS</b>"
        for l in links:
            text += f"\n• <a href=\"{l['url']}\">{_esc(l.get('title','Open'))}</a>"
        await bot.send_message(tid, text, parse_mode="HTML",
                               disable_web_page_preview=True)

    await db.orders.update_one(
        {"_id": order["_id"]},
        {"$set": {"status": "delivered", "delivered_at": now_utc(),
                  "updated_at": now_utc()}},
    )
    return True


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
