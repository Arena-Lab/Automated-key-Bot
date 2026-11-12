"""Inline keyboards for customer interface"""

from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from typing import List, Dict, Optional


class CustomerKeyboards:
    """Keyboard builders for customer interface"""

    @staticmethod
    def main_menu_inline() -> InlineKeyboardMarkup:
        """Inline menu keyboard (used after actions that need button navigation)"""
        keyboard = [
            [
                InlineKeyboardButton(text="🛍️ Purchase Products", callback_data="menu_purchase")
            ],
            [
                InlineKeyboardButton(text="🔑 My Keys", callback_data="menu_my_keys"),
                InlineKeyboardButton(text="📦 My Orders", callback_data="menu_my_orders")
            ],
            [
                InlineKeyboardButton(text="🎁 Join Reseller", callback_data="menu_reseller"),
                InlineKeyboardButton(text="💬 Contact Support", callback_data="menu_support")
            ],
            [
                InlineKeyboardButton(text="📖 How to Purchase", callback_data="menu_how_to")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def main_reply_keyboard() -> ReplyKeyboardMarkup:
        """Persistent reply keyboard shown after /start"""
        keyboard = [
            [
                KeyboardButton(text="🤑 Purchase Keys"),
                KeyboardButton(text="🪙 My Keys")
            ],
            [
                KeyboardButton(text="🎁 Setup Channel"),
                KeyboardButton(text="📞 Owner Contact")
            ],
            [
                KeyboardButton(text="🔴 How to Buy?")
            ],
            [
                KeyboardButton(text="🤝 Join Reseller")
            ]
        ]
        return ReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=True
        )

    @staticmethod
    def product_list(products: List[Dict]) -> InlineKeyboardMarkup:
        """Product selection keyboard"""
        keyboard = []
        for product in products:
            keyboard.append([
                InlineKeyboardButton(
                    text=product["name"],
                    callback_data=f"product_{product['_id']}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu_main")
        ])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def plan_list(plans: List[Dict], product_id: str) -> InlineKeyboardMarkup:
        """Plan selection keyboard"""
        keyboard = []
        for plan in plans:
            keyboard.append([
                InlineKeyboardButton(
                    text=f"⏱️ {plan['name']} – ₹{plan['price']}",
                    callback_data=f"plan_{plan['_id']}"
                )
            ])

        keyboard.append([
            InlineKeyboardButton(text="🔙 Back to Products", callback_data="menu_purchase")
        ])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def back_to_main() -> ReplyKeyboardMarkup:
        """Show the persistent reply keyboard (replaces old inline back button)"""
        return CustomerKeyboards.main_reply_keyboard()

    @staticmethod
    def main_menu_inline() -> InlineKeyboardMarkup:
        """Inline keyboard for edit_text contexts (reply keyboards can't be attached to edited messages)"""
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu_main")
        ]])

    @staticmethod
    def order_actions(order_id: str) -> InlineKeyboardMarkup:
        """Order action buttons"""
        keyboard = [
            [
                InlineKeyboardButton(
                    text="🔑 View Key",
                    callback_data=f"view_key_{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📥 Download Files",
                    callback_data=f"download_files_{order_id}"
                )
            ],
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="menu_my_orders")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
