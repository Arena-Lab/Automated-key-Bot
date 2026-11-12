"""Middlewares: user upsert, silent blocklist, maintenance mode, admin injection"""

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.db import Database
from config import Config

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Upserts the user into MongoDB and injects `user` + `db` + `is_admin`.
    Blocked users are silently ignored - the bot never responds to them."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)

        db = Database.get_db()
        now = datetime.utcnow()

        await db.users.update_one(
            {"telegram_id": user.id},
            {
                "$set": {
                    "telegram_id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "is_blocked": False,
                    "is_admin": user.id in Config.ADMIN_IDS,
                    "created_at": now,
                },
            },
            upsert=True,
        )

        doc = await db.users.find_one(
            {"telegram_id": user.id},
            {"is_blocked": 1, "is_admin": 1, "_id": 1},
        )
        if not doc:
            return await handler(event, data)

        # Silent block - bot never responds
        if doc.get("is_blocked"):
            return None

        data["user"] = doc
        data["db"] = db
        data["is_admin"] = doc.get("is_admin", False) or user.id in Config.ADMIN_IDS
        return await handler(event, data)


class MaintenanceMiddleware(BaseMiddleware):
    """Blocks customer actions during maintenance (admins always pass)."""

    async def __call__(self, handler, event, data):
        if data.get("is_admin"):
            return await handler(event, data)
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        db = Database.get_db()
        doc = await db.settings.find_one({"key": "maintenance_mode"})
        if doc and doc.get("value") is True:
            if isinstance(event, Message):
                await event.answer("🔧 Bot is under maintenance. Please try later.")
            else:
                await event.answer("🔧 Under maintenance", show_alert=True)
            return None
        return await handler(event, data)
