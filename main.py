"""Key Shop Bot - entry point"""

import asyncio
import html
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from config import Config
from bot.db import Database
from bot.middleware import AuthMiddleware, MaintenanceMiddleware
from bot.handlers import customer, admin, reseller
from bot.handlers import reseller_shop, reseller_admin
import bot.svc as svc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def global_error_handler(event: ErrorEvent):
    exc = event.exception
    update = event.update
    # Stale inline buttons clicked after a restart - harmless, ignore quietly
    msg = str(exc)
    if "query is too old" in msg or "query ID is invalid" in msg \
            or "message is not modified" in msg:
        logger.debug("Stale callback ignored: %s", msg)
        return
    logger.error("Unhandled error: %s", exc, exc_info=exc)
    try:
        if update.message:
            await update.message.answer(
                "⚠️ Something went wrong. Please try again or contact support.")
        elif update.callback_query:
            await update.callback_query.answer(
                "⚠️ Something went wrong. Please try again.", show_alert=True)
    except Exception:
        pass


async def payment_expiry_job(bot: Bot):
    """Expire pending payments past their expiry_time - runs every 30s"""
    while True:
        try:
            db = Database.get_db()
            expired = await svc.expire_due_payments(db)
            for p in expired:
                # Delete the payment/QR message if we stored its id
                if p.get("payment_msg_id"):
                    try:
                        await bot.delete_message(
                            p.get("payment_chat_id", p["telegram_id"]),
                            p["payment_msg_id"])
                    except Exception:
                        pass
                try:
                    await bot.send_message(
                        p["telegram_id"],
                        f"⌛ Order <code>{p.get('public_order_id','')}</code> expired — "
                        "payment not received in time. Start a new purchase anytime.",
                        parse_mode="HTML")
                except Exception:
                    pass
            if expired:
                logger.info("Expired %d pending payments", len(expired))
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Expiry job error: %s", e)
            await asyncio.sleep(30)


async def _verify_group_notice(bot: Bot, text: str):
    """Audit note to the payment-verification group (never raises)."""
    if not Config.PAYMENT_VERIFICATION_GROUP_ID:
        return
    try:
        await bot.send_message(Config.PAYMENT_VERIFICATION_GROUP_ID,
                               text, parse_mode="HTML")
    except Exception:
        pass


async def _payverify_cycle(bot: Bot, db, cfg):
    """One poll cycle: expire stale verifies, scan Gmail once, approve matches."""
    from bot import payverify
    now = svc.now_utc()

    # verify window passed -> mark expired; the payment job expires the order
    stale = await db.orders.find(
        {"verify_status": "pending", "verify_expires_at": {"$lt": now}}
    ).to_list(50)
    for o in stale:
        await db.orders.update_one(
            {"_id": o["_id"], "verify_status": "pending"},
            {"$set": {"verify_status": "expired", "updated_at": now}})

    orders = await db.orders.find({
        "status": "pending",
        "verify_status": "pending",
        "verify_expires_at": {"$gt": now},
        "verify_purpose": {"$exists": True},
    }).sort("created_at", 1).to_list(10)
    if not orders:
        return

    candidates = [
        (str(o["_id"]),
         o.get("verify_created_at") or o.get("created_at"),
         o["verify_purpose"], o.get("amount"))
        for o in orders
    ]
    try:
        matches = await payverify.find_matching_payments(cfg, candidates)
    except payverify.GmailError as e:
        logger.warning("PayVerify IMAP error: %s", e)
        return
    except Exception as e:
        logger.error("PayVerify scan failed: %s", e)
        return
    if not matches:
        return

    admin_id = Config.ADMIN_IDS[0] if Config.ADMIN_IDS else 0
    for o in orders:
        msg = matches.get(str(o["_id"]))
        if not msg:
            continue
        # re-check: order may have been settled/cancelled since the fetch
        fresh = await db.orders.find_one({"_id": o["_id"], "status": "pending"})
        if not fresh:
            await db.orders.update_one(
                {"_id": o["_id"]},
                {"$set": {"verify_status": "skipped", "updated_at": now}})
            continue
        # one Gmail message may only verify one order
        used = await db.payverify_logs.find_one({"gmail_msg_id": msg.message_id})
        if used and used.get("order_id") != fresh.get("order_id"):
            continue
        if not used:
            await db.payverify_logs.insert_one({
                "gmail_msg_id": msg.message_id,
                "order_id": fresh.get("order_id"),
                "purpose": msg.purpose,
                "amount": str(msg.amount) if msg.amount is not None else None,
                "matched_at": now,
            })
        await db.orders.update_one(
            {"_id": fresh["_id"]},
            {"$set": {"verify_status": "verified",
                      "gmail_msg_id": msg.message_id,
                      "verify_matched_at": now,
                      "updated_at": now}})

        # shared settlement path: mark paid, allocate key, deliver, audit
        result = await svc.mark_order_paid(db, fresh, admin_id)
        if result is None:
            continue  # lost a race with another settlement/expiry
        if result.get("error") == "out_of_stock":
            # keep verify_status pending so a later cycle retries once
            # stock is replenished; warn the group only once
            await db.orders.update_one(
                {"_id": fresh["_id"]},
                {"$set": {"verify_status": "pending"}})
            if not fresh.get("verify_stock_warned"):
                await db.orders.update_one(
                    {"_id": fresh["_id"]},
                    {"$set": {"verify_stock_warned": True}})
                await _verify_group_notice(
                    bot,
                    "🤖 <b>AUTO-VERIFY: OUT OF STOCK</b>\n\n"
                    f"🆔 Order: <code>{fresh['order_id']}</code> — payment matched "
                    f"(₹{fresh.get('amount',0):.2f}) but no keys available. "
                    "Order stays pending; will auto-approve when stock is added.")
            continue

        product = result["product"]
        delivered = await svc.deliver_order(bot, db, result["order"], product)

        # payment detected -> remove the customer's payment-details message
        pay_doc = await db.payments.find_one({"order_id": fresh["_id"]})
        if pay_doc and pay_doc.get("payment_msg_id"):
            try:
                await bot.delete_message(
                    pay_doc.get("payment_chat_id") or fresh.get("telegram_id"),
                    pay_doc["payment_msg_id"])
            except Exception:
                pass

        user = await db.users.find_one({"_id": fresh.get("user_id")})
        disp = (user or {}).get("first_name") or (user or {}).get("username") or "Customer"
        uname = (f"@{user['username']}" if user and user.get("username")
                 else html.escape(str(disp)))
        key_val = result["key"]["key_value"] if delivered else None
        try:
            amt = float(fresh.get("amount") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        audit = "\n".join([
            "🤖 <b>AUTO-VERIFIED PAYMENT</b>", "",
            "👤 <b>User</b>",
            f"├ Name: {html.escape(str(disp))}",
            f"├ User ID: <code>{fresh.get('telegram_id')}</code>",
            f"└ Username: {uname}", "",
            "💳 <b>Transaction</b>",
            "├ Method: UPI Auto (Gmail IMAP)",
            f"├ Order: <code>{fresh['order_id']}</code>",
            f"├ Product: {html.escape(str(fresh.get('product_name') or ''))}",
            f"├ Plan: {html.escape(str(fresh.get('plan_name') or ''))}",
            f"├ Amount: ₹{amt:.2f}",
            f"├ Note: <code>{html.escape(str(fresh.get('verify_purpose') or ''))}</code>",
            (f"├ UTR/TXN: <code>{html.escape(str(msg.utr))}</code>"
             if msg.utr else "├ UTR/TXN: —"),
            f"├ Gmail ID: <code>{html.escape(str(msg.message_id))}</code>",
            f"└ Time: {svc.fmt_ist(svc.now_utc())}", "",
            "🔑 <b>Key</b>",
            (f"└ <code>{html.escape(str(key_val))}</code>"
             if key_val else "└ <b>None</b>"), "",
            f"Delivery: {'✅ sent' if delivered else '⚠️ failed (key released)'}",
        ])
        await _verify_group_notice(bot, audit)
        await admin._log(db, admin_id, "auto_verify_payment",
                         {"order": fresh["order_id"],
                          "gmail_msg_id": msg.message_id,
                          "utr": msg.utr})
        if not delivered:
            await admin._notify_customer_text(
                bot, fresh["telegram_id"],
                f"⚠️ Your order {fresh['order_id']} is approved but we couldn't "
                "reach you. Please /start the bot so we can deliver your key.")
        logger.info("Auto-verified order %s via Gmail msg %s",
                    fresh["order_id"], msg.message_id)


async def payment_verify_job(bot: Bot):
    """Poll Gmail for FamApp/bank credit alerts and auto-approve matching
    orders. No-op unless Gmail IMAP is configured."""
    from bot import payverify
    while True:
        interval = 30
        try:
            db = Database.get_db()
            cfg = payverify.PayVerifyConfig.from_env()
            interval = max(10, cfg.poll_interval_seconds)
            if cfg.configured:
                await _payverify_cycle(bot, db, cfg)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("PayVerify job error: %s", e)
            await asyncio.sleep(30)


async def main():
    await Database.connect()
    db = Database.get_db()
    await Database.ensure_indexes()

    # Seed default settings if missing
    defaults = {
        "shop_name": Config.SHOP_NAME,
        "welcome_message": None,  # None => handler uses built-in default
        "official_channel": Config.OFFICIAL_CHANNEL,
        "support_username": Config.SUPPORT_USERNAME,
        "maintenance_mode": False,
        "maintenance_message": "🔧 Bot is under maintenance. Please try later.",
        "reseller_enabled": Config.RESELLER_SYSTEM_ENABLED,
        "reseller_apps_enabled": True,
        "reseller_purchases_enabled": True,
        "reseller_codes_enabled": True,
        "reseller_individual_pricing": True,
        "reseller_stats_enabled": True,
        "reseller_min_enabled": True,
        "reseller_min_cents": 30000,
        "reseller_min_scope": "all",
        "reseller_allow_negative": False,
        "how_to_text": None,
    }
    for k, v in defaults.items():
        if v is None:
            continue
        await db.settings.update_one(
            {"key": k}, {"$setOnInsert": {"key": k, "value": v}}, upsert=True)

    bot = Bot(token=Config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Middlewares (outer -> inner)
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())
    dp.message.middleware(MaintenanceMiddleware())
    dp.callback_query.middleware(MaintenanceMiddleware())

    dp.errors.register(global_error_handler)

    dp.include_router(customer.router)
    dp.include_router(admin.router)
    dp.include_router(reseller.router)
    dp.include_router(reseller_shop.router)
    dp.include_router(reseller_admin.router)

    # Expiry job + automatic backups (every 6h)
    expiry_task = asyncio.create_task(payment_expiry_job(bot))
    verify_task = asyncio.create_task(payment_verify_job(bot))
    from bot.store import get_store
    backup_task = asyncio.create_task(get_store().backup_loop())

    logger.info("Bot started successfully!")
    try:
        await dp.start_polling(bot)
    finally:
        expiry_task.cancel()
        verify_task.cancel()
        backup_task.cancel()
        await Database.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped.")
