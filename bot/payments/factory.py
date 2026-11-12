"""Payment provider factory - resolves the active provider from settings"""

from typing import Dict, Optional
from bot.database.repositories import SettingRepository
from bot.database.connection import Database
from .base import BasePaymentProvider
from .manual_upi import ManualUPIProvider
from .automatic import AutomaticPaymentProvider
from config import Config


class PaymentProviderFactory:
    """Factory that returns the configured payment provider"""

    _providers: Dict[str, BasePaymentProvider] = {}

    @classmethod
    async def get_provider(cls, mode: Optional[str] = None) -> BasePaymentProvider:
        """
        Get the active payment provider.
        mode: 'manual' or 'automatic'. If None, reads from settings.
        """
        if mode is None:
            settings_repo = SettingRepository(Database.get_db())
            mode = await settings_repo.get("current_payment_mode", Config.PAYMENT_MODE)

        mode = (mode or "manual").lower()

        if mode == "automatic":
            provider_name = "automatic"
            if provider_name not in cls._providers:
                cls._providers[provider_name] = AutomaticPaymentProvider()
            return cls._providers[provider_name]

        # Default: manual UPI
        provider_name = "manual_upi"
        if provider_name not in cls._providers:
            cls._providers[provider_name] = ManualUPIProvider()
        return cls._providers[provider_name]

    @classmethod
    async def get_provider_snapshot(cls, mode: Optional[str] = None) -> Dict:
        """
        Get a snapshot of the current payment provider config.
        Stored on each order so pending orders survive config changes.
        """
        settings_repo = SettingRepository(Database.get_db())

        if mode is None:
            mode = await settings_repo.get("current_payment_mode", Config.PAYMENT_MODE)

        mode = (mode or "manual").lower()

        if mode == "automatic":
            return {
                "payment_mode": "automatic",
                "payment_method": "automatic_gateway",
                "gateway_name": "Default Gateway"
            }

        return {
            "payment_mode": "manual",
            "payment_method": "manual_upi",
            "upi_id": await settings_repo.get("upi_id", Config.UPI_ID),
            "payee_name": await settings_repo.get("payee_name", Config.PAYEE_NAME),
            "qr_code_file_id": await settings_repo.get("qr_code_file_id"),
            "payment_instructions": await settings_repo.get(
                "payment_instructions",
                "Scan QR or pay via UPI ID, then submit UTR."
            )
        }

    @classmethod
    def list_modes(cls) -> list:
        """List available payment modes"""
        return ["manual", "automatic"]
