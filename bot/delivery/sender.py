"""Product delivery sender"""

from typing import Optional, Dict
from aiogram import Bot
from aiogram.types import InputFile
from bot.delivery.formatter import DeliveryFormatter


class DeliverySender:
    """Handles sending product delivery to customers"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.formatter = DeliveryFormatter()

    async def send_successful_delivery(
        self,
        telegram_id: int,
        product: Dict,
        plan: Dict,
        order: Dict,
        key_value: str
    ) -> bool:
        """Send successful delivery message with key and files"""
        try:
            # Format success message
            message = self.formatter.format_success_message(
                product_name=product["name"],
                plan_name=plan["name"],
                order_id=order["order_id"],
                key_value=key_value,
                expiry_date=order.get("expiry_date")
            )

            # Send success message
            await self.bot.send_message(
                chat_id=telegram_id,
                text=message,
                parse_mode="HTML"
            )

            # Send APK file if available
            if product.get("apk_file_id"):
                await self.bot.send_document(
                    chat_id=telegram_id,
                    document=product["apk_file_id"],
                    caption="📱 Download Application"
                )

            # Send setup video if available
            if product.get("setup_video_file_id"):
                await self.bot.send_video(
                    chat_id=telegram_id,
                    video=product["setup_video_file_id"],
                    caption="🎥 Setup Tutorial"
                )

            # Send setup document if available
            if product.get("setup_document_file_id"):
                await self.bot.send_document(
                    chat_id=telegram_id,
                    document=product["setup_document_file_id"],
                    caption="📖 Setup Instructions"
                )

            # Send custom delivery instructions if available
            if product.get("delivery_instructions"):
                await self.bot.send_message(
                    chat_id=telegram_id,
                    text=product["delivery_instructions"],
                    parse_mode="HTML"
                )

            return True

        except Exception as e:
            print(f"Error sending delivery: {e}")
            return False

    async def send_payment_pending(
        self,
        telegram_id: int,
        product: Dict,
        plan: Dict,
        order: Dict,
        upi_id: str
    ) -> list:
        """Send payment details text message. Returns list of sent message IDs."""
        message_ids = []
        try:
            from config import Config
            message = self.formatter.format_payment_pending_message(
                product_name=product["name"],
                plan_name=plan["name"],
                amount=order["amount"],
                order_id=order["order_id"],
                upi_id=upi_id,
                expiry_minutes=Config.PAYMENT_VALIDITY_MINUTES
            )

            details_msg = await self.bot.send_message(
                chat_id=telegram_id,
                text=message,
                parse_mode="HTML"
            )
            message_ids.append(details_msg.message_id)

            return message_ids

        except Exception as e:
            print(f"Error sending payment pending: {e}")
            return message_ids

    async def send_payment_qr(
        self,
        telegram_id: int,
        qr_code_file_id: str
    ):
        """Send the payment QR code as its own media message. Returns the Message or None."""
        try:
            return await self.bot.send_photo(
                chat_id=telegram_id,
                photo=qr_code_file_id,
                caption="💳 Scan the QR code to complete payment",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Error sending payment QR: {e}")
            return None

    async def send_payment_rejected(
        self,
        telegram_id: int,
        order_id: str
    ) -> bool:
        """Send payment rejected message"""
        try:
            message = self.formatter.format_payment_rejected_message(order_id)
            await self.bot.send_message(
                chat_id=telegram_id,
                text=message,
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            print(f"Error sending payment rejected: {e}")
            return False

    async def send_payment_expired(
        self,
        telegram_id: int,
        order_id: str
    ) -> bool:
        """Send payment expired message"""
        try:
            message = self.formatter.format_payment_expired_message(order_id)
            await self.bot.send_message(
                chat_id=telegram_id,
                text=message,
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            print(f"Error sending payment expired: {e}")
            return False

    async def send_order_history(
        self,
        telegram_id: int,
        orders_with_details: list
    ) -> bool:
        """Send order history to user"""
        try:
            if not orders_with_details:
                message = "📦 My Orders\n\nYou haven't placed any orders yet."
            else:
                message = "📦 MY ORDERS\n\n"
                for item in orders_with_details:
                    order = item["order"]
                    product = item["product"]
                    plan = item["plan"]
                    message += self.formatter.format_order_history_item(
                        order, product, plan
                    )
                    message += "\n"

            await self.bot.send_message(
                chat_id=telegram_id,
                text=message,
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            print(f"Error sending order history: {e}")
            return False

    async def send_my_keys(
        self,
        telegram_id: int,
        keys_with_orders: list
    ) -> bool:
        """Send purchased keys to user"""
        try:
            message = self.formatter.format_my_keys_message(keys_with_orders)
            await self.bot.send_message(
                chat_id=telegram_id,
                text=message,
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            print(f"Error sending my keys: {e}")
            return False

    async def resend_key(
        self,
        telegram_id: int,
        product: Dict,
        plan: Dict,
        order: Dict,
        key_value: str
    ) -> bool:
        """Resend a purchased key to customer"""
        try:
            message = (
                f"🔑 KEY RESEND\n\n"
                f"Here is your key for Order ID: {order['order_id']}\n\n"
                f"📦 Product: {product['name']}\n"
                f"⏱️ Plan: {plan['name']}\n\n"
                f"🔑 YOUR ACTIVATION KEY:\n\n"
                f"<code>{key_value}</code>"
            )

            await self.bot.send_message(
                chat_id=telegram_id,
                text=message,
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            print(f"Error resending key: {e}")
            return False
