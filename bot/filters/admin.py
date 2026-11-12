"""Admin filters"""

from aiogram import types
from aiogram.filters import BaseFilter
from config import Config


class IsAdminFilter(BaseFilter):
    """Filter to check if user is admin"""

    async def __call__(self, message: types.Message) -> bool:
        return message.from_user.id in Config.ADMIN_IDS


class IsAdminCallbackFilter(BaseFilter):
    """Filter to check if callback user is admin"""

    async def __call__(self, callback: types.CallbackQuery) -> bool:
        return callback.from_user.id in Config.ADMIN_IDS
