"""Core services: orders, payments, atomic inventory, delivery (bot/svc.py)"""

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from bot.db import Database
from bot.oid import ObjectId
from config import Config

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def now_utc() -> datetime:
    return datetime.utcnow()


def fmt_ist(dt: datetime) -> str:
    if dt is None:
        return "-"
    return dt.replace(tzinfo=timezone.utc).astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


_settings_cache = {"ts": 0.0, "data": {}}
_SETTINGS_TTL = 30.0  # seconds


def invalidate_settings():
    _settings_cache["data"] = {}
    _settings_cache["ts"] = 0.0


async def get_settings(db) -> Dict[str, Any]:
    """Settings change rarely - cache briefly to avoid a DB hit per handler."""
    now = time.monotonic()
    if _settings_cache["data"] and now - _settings_cache["ts"] < _SETTINGS_TTL:
        return _settings_cache["data"]
    cursor = db.settings.find({})
    data = {d["key"]: d.get("value") for d in await cursor.to_list(length=None)}
    _settings_cache["ts"] = now
    _settings_cache["data"] = data
    return data


async def get_payment_mode(db) -> str:
    s = await get_settings(db)
    return (s.get("payment_mode") or "manual").lower()


async def next_order_id(db) -> str:
    doc = await db.counters.find_one_and_update(
        {"_id": "order"},
        {"$inc": {"seq": 1}},
        upsert=True,
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
    order_oid = ObjectId()
    order["_id"] = order_oid

    # NOTE: do NOT include utr/screenshot keys here - the legacy unique sparse
    # index on payments.utr treats null as a value and would collide.
    s = await get_settings(db)
    payment = {
        "order_id": order_oid,
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
    # Insert order + payment in parallel - one round-trip instead of two
    await asyncio.gather(
        db.orders.insert_one(order),
        db.payments.insert_one(payment),
    )
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

    # keep the in-memory order in sync so delivery shows the key
    order["status"] = "paid"
    order["key_id"] = key["_id"]
    order["key_value"] = key["key_value"]

    # manual revenue override grows with each approved order
    s = await get_settings(db)
    if s.get("revenue_manual") is not None:
        await db.settings.update_one({"key": "revenue_manual"},
            {"$inc": {"value": float(order.get("amount", 0))}})
        invalidate_settings()

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
                      "expiry_notified": True},
             # Release the UTR from the unique index so it can be reused
             "$unset": {"utr": ""}},
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


def cbid(oid) -> str:
    """24-char hash safe for Telegram's 64-byte callback_data limit."""
    return hashlib.md5(str(oid).encode("utf-8")).hexdigest()[:24]


async def plan_by_code(db, code: str):
    for p in await db.plans.find({}).to_list(500):
        if cbid(p["_id"]) == code:
            return p
    return None


async def product_by_code(db, code: str):
    for p in await db.products.find({}).to_list(500):
        if cbid(p["_id"]) == code:
            return p
    return None


def _norm_id(v) -> str:
    if isinstance(v, dict):
        v = v.get("$oid") or v.get("_id") or ""
    s = str(v).strip().strip("'\"")
    if s.startswith("ObjectId(") and s.endswith(")"):
        s = s[9:-1].strip("'\"")
    return s


async def enrich_plans(db, product_id) -> list:
    all_plans = await db.plans.find({}).to_list(500)
    target = _norm_id(product_id)
    plans = [p for p in all_plans
             if _norm_id(p.get("product_id") or p.get("productId") or p.get("pid")) == target
             and p.get("status", "active") == "active"]
    plans.sort(key=lambda p: p.get("price") or 0)
    # Parallel stock counts - one round-trip total instead of N sequential
    counts = await asyncio.gather(*[stock_for_plan(db, p["_id"]) for p in plans])
    for p, c in zip(plans, counts):
        p["stock"] = c
    return plans


# ---------------- Delivery ----------------

def _product_files(product: Dict) -> Dict[str, Dict]:
    """Normalize file storage - new schema (files.{kind}.file_id) with
    fallback to legacy flat fields."""
    files = dict(product.get("files", {}) or {})
    if product.get("apk_file_id") and "apk" not in files:
        files["apk"] = {"file_id": product["apk_file_id"], "name": product.get("apk_name")}
    if product.get("setup_video_file_id") and "video" not in files:
        files["video"] = {"file_id": product["setup_video_file_id"]}
    return files


async def resend_product_files(bot, telegram_id: int, product: Dict):
    """Send stored product files (used by My Files / redelivery)."""
    files = _product_files(product)
    captions = {
        "apk": "📱 <b>Latest APK</b>\nDownload and install to activate your key.",
        "video": "🎬 <b>Setup Video</b>\nWatch this before activating.",
    }
    for kind in ("apk", "video"):
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

    try:
        await bot.send_message(
            tid,
            "🔑 <b>YOUR LICENSE KEY</b>\n\n"
            f"🎮 {_esc(order.get('product_name',''))}\n"
            f"⏱️ {_esc(order.get('plan_name',''))}\n\n"
            f"<code>{_esc(order.get('key_value','N/A'))}</code>\n\n"
            f"🆔 Order: {oid}",
            parse_mode="HTML",
        )
    except Exception as e:
        # User unreachable (blocked bot etc.) - release the key back to
        # stock and keep order in fulfillment_pending so admin can retry
        logger.error(f"Key delivery failed for {oid}: {e}")
        if order.get("key_id"):
            await db.keys.update_one(
                {"_id": order["key_id"]},
                {"$set": {"status": "available"}, "$unset": {"sold_at": ""}})
            # clear key fields so a retry can't deliver the same key twice
            await db.orders.update_one(
                {"_id": order["_id"]},
                {"$set": {"status": "paid", "updated_at": now_utc()},
                 "$unset": {"key_id": "", "key_value": ""}})
        else:
            await db.orders.update_one(
                {"_id": order["_id"]},
                {"$set": {"status": "paid", "updated_at": now_utc()}})
        return False

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


async def release_order_key(db, order: Dict):
    """Return an allocated key to stock (e.g. approval rolled back)."""
    if order.get("key_id"):
        await db.keys.update_one(
            {"_id": order["key_id"]},
            {"$set": {"status": "available"}, "$unset": {"sold_at": ""}})


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
