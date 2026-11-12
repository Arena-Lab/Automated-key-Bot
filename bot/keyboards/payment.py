"""Inline keyboards for payment interface"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


class PaymentKeyboards:
    """Keyboard builders for payment interface"""

    @staticmethod
    def submit_utr_button(order_id: str) -> InlineKeyboardMarkup:
        """Submit UTR button"""
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Submit UTR",
                    callback_data=f"submit_utr_{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📸 Upload Screenshot",
                    callback_data=f"upload_screenshot_{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Cancel Order",
                    callback_data=f"cancel_order_{order_id}"
                )
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
