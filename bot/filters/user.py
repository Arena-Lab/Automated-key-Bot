"""User filters"""

from aiogram import types
from aiogram.filters import BaseFilter
from bot.database.repositories import UserRepository
from bot.database.connection import Database


class IsBlockedFilter(BaseFilter):
    """Filter to check if user is blocked"""

    async def __call__(self, message: types.Message) -> bool:
        user_repo = UserRepository(Database.get_db())
        user = await user_repo.find_by_telegram_id(message.from_user.id)
        return user and user.get("is_blocked", False)


class IsResellerFilter(BaseFilter):
    """Filter to check if user is reseller"""

    async def __call__(self, message: types.Message) -> bool:
        user_repo = UserRepository(Database.get_db())
        user = await user_repo.find_by_telegram_id(message.from_user.id)
        return user and user.get("is_reseller", False)
