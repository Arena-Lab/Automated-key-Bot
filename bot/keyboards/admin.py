"""Inline keyboards for admin panel"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Optional


class AdminKeyboards:
    """Keyboard builders for admin panel"""

    @staticmethod
    def admin_dashboard() -> InlineKeyboardMarkup:
        """Main admin dashboard"""
        keyboard = [
            [
                InlineKeyboardButton(text="📊 Statistics", callback_data="admin_stats"),
                InlineKeyboardButton(text="🛍️ Manage Products", callback_data="admin_products")
            ],
            [
                InlineKeyboardButton(text="🔑 Manage Keys", callback_data="admin_keys"),
                InlineKeyboardButton(text="💰 Payment Management", callback_data="admin_payments")
            ],
            [
                InlineKeyboardButton(text="📦 Manage Orders", callback_data="admin_orders"),
                InlineKeyboardButton(text="👥 Manage Customers", callback_data="admin_customers")
            ],
            [
                InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast"),
                InlineKeyboardButton(text="🎥 Manage Files", callback_data="admin_files")
            ],
            [
                InlineKeyboardButton(text="⚙️ Bot Settings", callback_data="admin_settings"),
                InlineKeyboardButton(text="🛡️ Admin Management", callback_data="admin_admins")
            ],
            [
                InlineKeyboardButton(text="🔄 Restart Bot", callback_data="admin_restart")
            ],
            [
                InlineKeyboardButton(text="🔙 Exit Admin", callback_data="admin_exit")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def product_management() -> InlineKeyboardMarkup:
        """Product management menu"""
        keyboard = [
            [
                InlineKeyboardButton(text="➕ Add Product", callback_data="admin_add_product"),
                InlineKeyboardButton(text="✏️ Edit Product", callback_data="admin_edit_product")
            ],
            [
                InlineKeyboardButton(text="🗑️ Delete Product", callback_data="admin_delete_product"),
                InlineKeyboardButton(text="📋 View All Products", callback_data="admin_list_products")
            ],
            [
                InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_dashboard")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def key_management() -> InlineKeyboardMarkup:
        """Key management menu"""
        keyboard = [
            [
                InlineKeyboardButton(text="➕ Add Single Key", callback_data="admin_add_key"),
                InlineKeyboardButton(text="📝 Bulk Add Keys", callback_data="admin_bulk_keys")
            ],
            [
                InlineKeyboardButton(text="📁 Upload Key File", callback_data="admin_upload_keys"),
                InlineKeyboardButton(text="📋 View Inventory", callback_data="admin_view_inventory")
            ],
            [
                InlineKeyboardButton(text="🔍 Search Keys", callback_data="admin_search_keys"),
                InlineKeyboardButton(text="🗑️ Delete Keys", callback_data="admin_delete_keys")
            ],
            [
                InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_dashboard")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def payment_verification(order_id: str) -> InlineKeyboardMarkup:
        """Payment verification keyboard"""
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Approve Payment",
                    callback_data=f"admin_approve_{order_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Reject Payment",
                    callback_data=f"admin_reject_{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 View Order Details",
                    callback_data=f"admin_view_order_{order_id}"
                ),
                InlineKeyboardButton(
                    text="👤 Customer Profile",
                    callback_data=f"admin_customer_{order_id}"
                )
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def order_management() -> InlineKeyboardMarkup:
        """Order management menu"""
        keyboard = [
            [
                InlineKeyboardButton(text="📋 View All Orders", callback_data="admin_list_orders"),
                InlineKeyboardButton(text="🔍 Search Order", callback_data="admin_search_order")
            ],
            [
                InlineKeyboardButton(text="⏳ Pending Payments", callback_data="admin_pending_payments"),
                InlineKeyboardButton(text="✅ Completed Orders", callback_data="admin_completed_orders")
            ],
            [
                InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_dashboard")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def payment_management() -> InlineKeyboardMarkup:
        """Payment management menu"""
        keyboard = [
            [
                InlineKeyboardButton(text="🔄 Change Payment Mode", callback_data="admin_change_payment_mode"),
                InlineKeyboardButton(text="✏️ Update UPI Details", callback_data="admin_update_upi")
            ],
            [
                InlineKeyboardButton(text="🖼️ Update QR Code", callback_data="admin_update_qr"),
                InlineKeyboardButton(text="⚙️ Payment Settings", callback_data="admin_payment_settings")
            ],
            [
                InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_dashboard")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def bot_settings() -> InlineKeyboardMarkup:
        """Bot settings menu"""
        keyboard = [
            [
                InlineKeyboardButton(text="✏️ Shop Name", callback_data="admin_shop_name"),
                InlineKeyboardButton(text="📝 Welcome Message", callback_data="admin_welcome")
            ],
            [
                InlineKeyboardButton(text="📢 Official Channel", callback_data="admin_channel"),
                InlineKeyboardButton(text="💬 Support Username", callback_data="admin_support")
            ],
            [
                InlineKeyboardButton(text="🔧 Maintenance Mode", callback_data="admin_maintenance"),
                InlineKeyboardButton(text="🔄 Reseller System", callback_data="admin_reseller_toggle")
            ],
            [
                InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_dashboard")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def confirmation_action(action: str, entity_id: str) -> InlineKeyboardMarkup:
        """Confirmation keyboard for actions"""
        keyboard = [
            [
                InlineKeyboardButton(
                    text="✅ Confirm",
                    callback_data=f"confirm_{action}_{entity_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data="cancel_{action}_{entity_id}"
                )
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def payment_mode_selection(current_mode: str) -> InlineKeyboardMarkup:
        """Payment mode selection"""
        keyboard = [
            [
                InlineKeyboardButton(
                    text="🟢 Manual UPI" if current_mode == "manual" else "⚪ Manual UPI",
                    callback_data="set_payment_mode_manual"
                ),
                InlineKeyboardButton(
                    text="🟢 Automatic" if current_mode == "automatic" else "⚪ Automatic",
                    callback_data="set_payment_mode_automatic"
                )
            ],
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="admin_payment_management")
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def back_button(callback_data: str = "admin_dashboard") -> InlineKeyboardMarkup:
        """Simple back button"""
        keyboard = [
            [
                InlineKeyboardButton(text="🔙 Back", callback_data=callback_data)
            ]
        ]
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
