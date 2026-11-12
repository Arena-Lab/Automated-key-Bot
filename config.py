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

    # Database Configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "mongodb://localhost:27017")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "key_shop_bot")

    # Payment Configuration
    PAYMENT_MODE: str = os.getenv("PAYMENT_MODE", "manual")  # manual or automatic
    UPI_ID: str = os.getenv("UPI_ID", "")
    PAYEE_NAME: str = os.getenv("PAYEE_NAME", "")
    PAYMENT_VALIDITY_MINUTES: int = int(os.getenv("PAYMENT_VALIDITY_MINUTES", "10"))
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
        if not cls.DATABASE_URL:
            raise ValueError("DATABASE_URL is required")
        return True
