"""Message formatter for delivery messages"""

from typing import Dict, Optional
from datetime import datetime


class DeliveryFormatter:
    """Formats delivery messages for customers"""

    @staticmethod
    def format_success_message(
        product_name: str,
        plan_name: str,
        order_id: str,
        key_value: str,
        expiry_date: Optional[datetime] = None
    ) -> str:
        """Format successful payment and delivery message"""
        message = (
            "🎉 PAYMENT SUCCESSFUL!\n\n"
            f"Your order has been successfully verified.\n\n"
            f"📦 Product: {product_name}\n"
            f"⏱️ Plan: {plan_name}\n"
            f"🆔 Order ID: {order_id}\n\n"
            f"🔑 YOUR ACTIVATION KEY:\n\n"
            f"<code>{key_value}</code>\n\n"
        )

        if expiry_date:
            message += f"⏰ Valid Until: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

        message += "Thank you for purchasing!"
        return message

    @staticmethod
    def format_payment_pending_message(
        product_name: str,
        plan_name: str,
        amount: float,
        order_id: str,
        upi_id: str,
        expiry_minutes: int
    ) -> str:
        """Format payment pending message"""
        return (
            "⏳ PAYMENT PENDING\n\n"
            f"📦 Product: {product_name}\n"
            f"⏱️ Plan: {plan_name}\n"
            f"💰 Amount: ₹{amount:.2f}\n"
            f"🆔 Order ID: {order_id}\n\n"
            f"💳 UPI ID: {upi_id}\n"
            f"⏰ Payment valid for: {expiry_minutes} minutes\n\n"
            "Please complete the payment and submit your UTR."
        )

    @staticmethod
    def format_payment_rejected_message(order_id: str) -> str:
        """Format payment rejected message"""
        return (
            "❌ PAYMENT REJECTED\n\n"
            f"Your payment for Order ID: {order_id} has been rejected.\n\n"
            "Please contact support if you believe this is an error."
        )

    @staticmethod
    def format_payment_expired_message(order_id: str) -> str:
        """Format payment expired message"""
        return (
            "⏰ PAYMENT EXPIRED\n\n"
            f"Your payment window for Order ID: {order_id} has expired.\n\n"
            "Please place a new order to continue."
        )

    @staticmethod
    def format_order_history_item(order: Dict, product: Dict, plan: Dict) -> str:
        """Format a single order history item"""
        status_emoji = {
            "pending": "⏳",
            "paid": "💰",
            "delivered": "✅",
            "cancelled": "❌",
            "failed": "⚠️"
        }

        status = order.get("status", "unknown")
        emoji = status_emoji.get(status, "❓")

        return (
            f"{emoji} Order: {order['order_id']}\n"
            f"📦 {product['name']}\n"
            f"⏱️ {plan['name']} - ₹{order['amount']:.2f}\n"
            f"📅 {order['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
            f"Status: {status.upper()}\n"
        )

    @staticmethod
    def format_my_keys_message(keys_with_orders: list) -> str:
        """Format My Keys section message"""
        if not keys_with_orders:
            return "🔑 My Keys\n\nYou haven't purchased any keys yet."

        message = "🔑 MY KEYS\n\n"

        for item in keys_with_orders:
            order = item["order"]
            product = item["product"]
            plan = item["plan"]
            key = item.get("key_value", "N/A")

            message += (
                f"📦 {product['name']}\n"
                f"⏱️ {plan['name']}\n"
                f"🔑 Key: <code>{key}</code>\n"
                f"🆔 Order: {order['order_id']}\n"
                f"📅 Purchased: {order['created_at'].strftime('%Y-%m-%d')}\n\n"
            )

        return message

    @staticmethod
    def format_admin_payment_verification(
        order: Dict,
        user: Dict,
        product: Dict,
        plan: Dict,
        payment: Dict
    ) -> str:
        """Format admin payment verification message"""
        return (
            "🔔 NEW PAYMENT VERIFICATION REQUEST\n\n"
            f"Order ID: {order['order_id']}\n\n"
            f"👤 Customer: @{user.get('username', 'N/A')}\n"
            f"Telegram ID: {user['telegram_id']}\n\n"
            f"📦 Product: {product['name']}\n"
            f"⏱️ Plan: {plan['name']}\n"
            f"💰 Amount: ₹{payment['amount']:.2f}\n\n"
            f"🔢 UTR: {payment.get('utr', 'Not submitted')}\n"
            f"Payment Screenshot: {'Attached' if payment.get('payment_screenshot_file_id') else 'Not submitted'}\n\n"
            f"⏰ Expiry: {payment['expiry_time'].strftime('%Y-%m-%d %H:%M:%S')}"
        )
