"""User service - business logic for user operations"""

from typing import Optional, Dict
from bot.database.repositories import UserRepository


class UserService:
    """Service for user-related operations"""

    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str]
    ) -> Dict:
        """Get existing user or create new one"""
        return await self.user_repo.create_or_update(
            telegram_id, username, first_name, last_name
        )

    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        """Get user by Telegram ID"""
        return await self.user_repo.find_by_telegram_id(telegram_id)

    async def is_admin(self, telegram_id: int) -> bool:
        """Check if user is admin"""
        from config import Config
        return telegram_id in Config.ADMIN_IDS

    async def is_blocked(self, telegram_id: int) -> bool:
        """Check if user is blocked"""
        user = await self.get_user_by_telegram_id(telegram_id)
        return user and user.get("is_blocked", False)

    async def update_user_stats(self, user_id: str, amount: float) -> bool:
        """Update user order statistics"""
        return await self.user_repo.update_stats(user_id, amount)

    async def block_user(self, user_id: str) -> bool:
        """Block a user"""
        return await self.user_repo.update_one(
            {"_id": user_id},
            {"is_blocked": True, "updated_at": "now"}
        )

    async def unblock_user(self, user_id: str) -> bool:
        """Unblock a user"""
        return await self.user_repo.update_one(
            {"_id": user_id},
            {"is_blocked": False, "updated_at": "now"}
        )
