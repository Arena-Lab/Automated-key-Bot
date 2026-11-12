"""Authentication middleware"""

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from bot.database.repositories import UserRepository, SettingRepository
from bot.database.connection import Database
from bot.services.user_service import UserService
from typing import Callable, Awaitable, Any, Dict
from config import Config


async def _get_user(data: Dict[str, Any], event) -> Dict:
    """Get or create user and attach to data"""
    user_repo = UserRepository(Database.get_db())
    user_service = UserService(user_repo)

    user = await user_service.get_or_create_user(
        telegram_id=event.from_user.id,
        username=event.from_user.username,
        first_name=event.from_user.first_name,
        last_name=event.from_user.last_name
    )
    data["user"] = user
    return user


async def _check_access(event, user: Dict) -> bool:
    """Check if user is allowed to proceed. Returns True if blocked/maintenance."""
    # Check if user is blocked
    if user.get("is_blocked", False):
        if isinstance(event, Message):
            await event.answer("⛔ You have been blocked from using this bot.")
        else:
            await event.answer("⛔ You have been blocked from using this bot.", show_alert=True)
        return True

    # Check maintenance mode from settings (admin-toggleable) or env
    is_admin = event.from_user.id in Config.ADMIN_IDS
    if not is_admin:
        settings_repo = SettingRepository(Database.get_db())
        maintenance = await settings_repo.get("maintenance_mode", Config.MAINTENANCE_MODE)
        if maintenance or Config.MAINTENANCE_MODE:
            msg = "🔧 Bot is under maintenance. Please try again later."
            if isinstance(event, Message):
                await event.answer(msg)
            else:
                await event.answer(msg, show_alert=True)
            return True

    return False


class AuthMiddleware(BaseMiddleware):
    """Middleware to handle user authentication and registration"""

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        user = await _get_user(data, event)
        if await _check_access(event, user):
            return
        return await handler(event, data)


class CallbackAuthMiddleware(BaseMiddleware):
    """Middleware for callback queries"""

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        user = await _get_user(data, event)
        if await _check_access(event, user):
            return
        return await handler(event, data)
