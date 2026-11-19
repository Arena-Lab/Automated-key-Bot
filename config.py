import os
from typing import List

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configuration class for the Telegram Key Shop Bot"""

    # Bot Configuration
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: List[int] = list(
        map(int, filter(None, os.getenv("ADMIN_IDS", "").split(",")))
    )

    # Payment Configuration
    PAYMENT_VERIFICATION_GROUP_ID: int = int(
        os.getenv("PAYMENT_VERIFICATION_GROUP_ID", "0")
    )

    # Shop Configuration
    SHOP_NAME: str = os.getenv("SHOP_NAME", "Key Shop")
    SHOP_USERNAME: str = os.getenv("SHOP_USERNAME", "@keyshop")
    OFFICIAL_CHANNEL: str = os.getenv("OFFICIAL_CHANNEL", "")
    SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "")

    # Bot Settings
    MAINTENANCE_MODE: bool = os.getenv("MAINTENANCE_MODE", "false").lower() == "true"
    BROADCAST_CHUNK_SIZE: int = int(os.getenv("BROADCAST_CHUNK_SIZE", "50"))
    BROADCAST_DELAY_SECONDS: int = int(os.getenv("BROADCAST_DELAY_SECONDS", "1"))

    # Daily raw store.db backup target chat/group (0 = feature off)
    @staticmethod
    def _env_int(name: str, default: int = 0) -> int:
        try:
            return int(os.getenv(name, "") or default)
        except (TypeError, ValueError):
            return default

    DB_BACKUP_GROUP_ID: int = _env_int("STORE_DATABASE_BACKUP")

    # Reseller Configuration
    RESELLER_SYSTEM_ENABLED: bool = (
        os.getenv("RESELLER_SYSTEM_ENABLED", "false").lower() == "true"
    )

    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        if not cls.ADMIN_IDS:
            raise ValueError("ADMIN_IDS is required")
        return True
