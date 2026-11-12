"""Key Shop Bot - entry point"""

import asyncio
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
import bot.svc as svc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def global_error_handler(event: ErrorEvent):
    exc = event.exception
    update = event.update
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
        "upi_id": Config.UPI_ID,
        "payee_name": Config.PAYEE_NAME,
        "payment_instructions": Config.PAYMENT_INSTRUCTIONS,
        "payment_mode": Config.PAYMENT_MODE,
        "maintenance_mode": False,
        "maintenance_message": "🔧 Bot is under maintenance. Please try later.",
        "reseller_enabled": Config.RESELLER_SYSTEM_ENABLED,
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

    # Expiry job
    expiry_task = asyncio.create_task(payment_expiry_job(bot))

    logger.info("Bot started successfully!")
    try:
        await dp.start_polling(bot)
    finally:
        expiry_task.cancel()
        await Database.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
