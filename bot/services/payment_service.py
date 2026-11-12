"""Payment service - business logic for payment operations"""

from typing import Optional, Dict, List
from datetime import datetime, timedelta
from bson import ObjectId

from bot.database.repositories import PaymentRepository, OrderRepository
from config import Config


class PaymentService:
    """Service for payment-related operations"""

    def __init__(self, payment_repo: PaymentRepository, order_repo: OrderRepository):
        self.payment_repo = payment_repo
        self.order_repo = order_repo

    async def create_payment(
        self,
        order_id: str,
        user_id: str,
        telegram_id: int,
        amount: float,
        payment_method: str = "manual_upi",
        payment_mode: str = "manual"
    ) -> Dict:
        """Create a new payment record"""
        from bot.database.connection import Database
        db = Database.get_db()

        # Get payment validity from settings or config
        validity_minutes = Config.PAYMENT_VALIDITY_MINUTES
        expiry_time = datetime.utcnow() + timedelta(minutes=validity_minutes)

        payment_data = {
            "order_id": ObjectId(order_id),
            "user_id": ObjectId(user_id),
            "telegram_id": telegram_id,
            "amount": amount,
            "currency": "INR",
            "payment_method": payment_method,
            "payment_mode": payment_mode,
            "status": "pending",
            "expiry_time": expiry_time,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        payment_id = await self.payment_repo.create(payment_data)
        return await self.payment_repo.find_by_id(payment_id)

    async def get_payment_by_order(self, order_id: str) -> Optional[Dict]:
        """Get payment by order ID"""
        return await self.payment_repo.find_by_order(order_id)

    async def submit_payment_details(
        self,
        payment_id: str,
        utr: Optional[str] = None,
        screenshot_file_id: Optional[str] = None
    ) -> bool:
        """Submit payment details (UTR and/or screenshot).
        Only writes fields that have actual values - never stores empty strings,
        which would collide on the unique utr index."""
        update = {"updated_at": datetime.utcnow()}
        if utr:
            update["utr"] = utr
        if screenshot_file_id:
            update["payment_screenshot_file_id"] = screenshot_file_id
        return await self.payment_repo.update(payment_id, update)

    async def approve_payment(
        self,
        payment_id: str,
        verified_by: str
    ) -> bool:
        """Approve a payment"""
        return await self.payment_repo.update_status(
            payment_id,
            "approved",
            verified_by
        )

    async def reject_payment(
        self,
        payment_id: str,
        verified_by: str
    ) -> bool:
        """Reject a payment"""
        return await self.payment_repo.update_status(
            payment_id,
            "rejected",
            verified_by
        )

    async def check_utr_duplicate(self, utr: str) -> bool:
        """Check if UTR has been used before"""
        existing = await self.payment_repo.find_by_utr(utr)
        return existing is not None

    async def get_payment_details(self, payment_id: str) -> Optional[Dict]:
        """Get payment with order details"""
        payment = await self.payment_repo.find_by_id(payment_id)
        if not payment:
            return None

        from bot.database.connection import Database
        db = Database.get_db()

        order = await db.orders.find_one({"_id": payment["order_id"]})
        user = await db.users.find_one({"_id": payment["user_id"]})

        return {
            "payment": payment,
            "order": order,
            "user": user
        }

    async def mark_expired(self, payment_id: str) -> bool:
        """Mark payment as expired"""
        return await self.payment_repo.update_status(payment_id, "expired")

    async def get_expired_payments(self) -> List[Dict]:
        """Get all expired pending payments"""
        return await self.payment_repo.find_expired()

    async def get_payment_info_display(self, payment_id: str) -> str:
        """Get formatted payment information for display"""
        payment = await self.payment_repo.find_by_id(payment_id)
        if not payment:
            return "Payment not found"

        from bot.database.connection import Database
        db = Database.get_db()

        order = await db.orders.find_one({"_id": payment["order_id"]})
        product = await db.products.find_one({"_id": order["product_id"]}) if order else None
        plan = await db.plans.find_one({"_id": order["plan_id"]}) if order else None

        product_name = product["name"] if product else "Unknown"
        plan_name = plan["name"] if plan else "Unknown"

        return (
            f"📦 Product: {product_name}\n"
            f"⏱️ Plan: {plan_name}\n"
            f"💰 Amount: ₹{payment['amount']:.2f}\n"
            f"🆔 Order ID: {order['order_id'] if order else 'N/A'}\n"
            f"⏰ Valid until: {payment['expiry_time'].strftime('%Y-%m-%d %H:%M:%S')}"
        )
