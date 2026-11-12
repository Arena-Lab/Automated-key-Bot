"""Keyboards module initialization"""

from .customer import CustomerKeyboards
from .admin import AdminKeyboards
from .payment import PaymentKeyboards

__all__ = [
    "CustomerKeyboards",
    "AdminKeyboards",
    "PaymentKeyboards"
]
