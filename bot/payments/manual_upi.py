"""Manual UPI payment provider implementation"""

from typing import Dict, Optional
from datetime import datetime

from .base import BasePaymentProvider
from config import Config


class ManualUPIProvider(BasePaymentProvider):
    """Manual UPI payment verification provider"""

    def __init__(self, config: Optional[Dict] = None):
        config = config or {}
        super().__init__(config)
        self.upi_id = config.get("upi_id", Config.UPI_ID)
        self.payee_name = config.get("payee_name", Config.PAYEE_NAME)
        self.qr_code_file_id = config.get("qr_code_file_id")
        self.payment_instructions = config.get(
            "payment_instructions",
            "Scan the QR code or pay using the UPI ID. Submit your UTR after payment."
        )

    async def create_payment(
        self,
        amount: float,
        order_id: str,
        user_id: str,
        telegram_id: int
    ) -> Dict:
        """Create a manual UPI payment record"""
        return {
            "payment_method": "manual_upi",
            "payment_mode": "manual",
            "upi_id": self.upi_id,
            "payee_name": self.payee_name,
            "qr_code_file_id": self.qr_code_file_id,
            "amount": amount,
            "order_id": order_id,
            "created_at": datetime.utcnow()
        }

    async def verify_payment(self, payment_id: str, transaction_id: str) -> bool:
        """
        For manual payments, verification is done by admin.
        This method always returns False for manual mode.
        """
        return False

    async def get_payment_status(self, payment_id: str) -> str:
        """Manual payments require admin verification"""
        return "pending_admin_verification"

    async def cancel_payment(self, payment_id: str) -> bool:
        """Cancel a manual payment"""
        return True

    def get_payment_instructions(self) -> str:
        """Get payment instructions"""
        return self.payment_instructions

    def get_payment_display_data(self, payment: Dict) -> Dict:
        """Get data for payment UI display"""
        return {
            "upi_id": self.upi_id,
            "payee_name": self.payee_name,
            "qr_code_file_id": self.qr_code_file_id,
            "amount": payment.get("amount", 0),
            "order_id": payment.get("order_id", ""),
            "instructions": self.payment_instructions
        }

    def update_config(self, config: Dict):
        """Update payment provider configuration"""
        self.upi_id = config.get("upi_id", self.upi_id)
        self.payee_name = config.get("payee_name", self.payee_name)
        self.qr_code_file_id = config.get("qr_code_file_id", self.qr_code_file_id)
        self.payment_instructions = config.get(
            "payment_instructions",
            self.payment_instructions
        )
        self.config.update(config)
