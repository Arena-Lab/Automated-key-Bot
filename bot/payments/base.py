"""Base payment provider interface"""

from abc import ABC, abstractmethod
from typing import Dict, Optional


class BasePaymentProvider(ABC):
    """Base class for payment providers"""

    def __init__(self, config: Dict):
        self.config = config

    @abstractmethod
    async def create_payment(
        self,
        amount: float,
        order_id: str,
        user_id: str,
        telegram_id: int
    ) -> Dict:
        """Create a payment"""
        pass

    @abstractmethod
    async def verify_payment(self, payment_id: str, transaction_id: str) -> bool:
        """Verify a payment transaction"""
        pass

    @abstractmethod
    async def get_payment_status(self, payment_id: str) -> str:
        """Get payment status"""
        pass

    @abstractmethod
    async def cancel_payment(self, payment_id: str) -> bool:
        """Cancel a payment"""
        pass

    @abstractmethod
    def get_payment_instructions(self) -> str:
        """Get payment instructions for the user"""
        pass

    @abstractmethod
    def get_payment_display_data(self, payment: Dict) -> Dict:
        """Get data for payment UI display"""
        pass
