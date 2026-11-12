"""Validation utilities"""

import re
from typing import Optional


def is_valid_price(price_str: str) -> bool:
    """Validate price input"""
    try:
        price = float(price_str)
        return price > 0
    except (ValueError, TypeError):
        return False


def is_valid_duration(duration_str: str) -> bool:
    """Validate duration input (hours)"""
    try:
        duration = int(duration_str)
        return duration > 0
    except (ValueError, TypeError):
        return False


def is_valid_telegram_id(telegram_id: str) -> bool:
    """Validate Telegram ID"""
    try:
        tid = int(telegram_id)
        return len(str(abs(tid))) >= 5
    except (ValueError, TypeError):
        return False


def sanitize_product_name(name: str) -> Optional[str]:
    """Sanitize product name"""
    if not name:
        return None
    name = name.strip()
    if len(name) < 2 or len(name) > 100:
        return None
    return name
