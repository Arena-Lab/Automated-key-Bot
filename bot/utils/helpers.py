"""Utility functions for the key shop bot"""

import re
from datetime import datetime


def validate_utr(utr: str) -> bool:
    """Validate UTR format (typically 12 digits)"""
    return bool(re.match(r'^\d{10,16}$', utr))


def format_price(amount: float) -> str:
    """Format price with currency symbol"""
    return f"₹{amount:.2f}"


def format_datetime(dt: datetime) -> str:
    """Format datetime for display"""
    if not dt:
        return "N/A"
    return dt.strftime("%Y-%m-%d %H:%M")


def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text with ellipsis"""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def sanitize_key_value(key: str) -> str:
    """Sanitize a key value for display"""
    return key.strip().upper()


def generate_reseller_code() -> str:
    """Generate a unique reseller code"""
    import secrets
    import string
    prefix = "RS"
    suffix = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"{prefix}{suffix}"
