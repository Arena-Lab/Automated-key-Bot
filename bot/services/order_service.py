"""Order service - business logic for order operations"""

from typing import Optional, Dict, List
from datetime import datetime, timedelta
from bson import ObjectId
import random
import string

from bot.database.repositories import OrderRepository, KeyRepository, UserRepository


class OrderService:
    """Service for order-related operations"""

    def __init__(
        self,
        order_repo: OrderRepository,
        key_repo: KeyRepository,
        user_repo: UserRepository
    ):
        self.order_repo = order_repo
        self.key_repo = key_repo
        self.user_repo = user_repo

    def generate_order_id(self) -> str:
        """Generate a unique order ID"""
        timestamp = datetime.now().strftime("%y%m%d")
        random_str = ''.join(random.choices(string.digits, k=4))
        return f"KS{timestamp}{random_str}"

    async def create_order(
        self,
        user_id: str,
        telegram_id: int,
        product_id: str,
        plan_id: str,
        amount: float,
        payment_method: str = "manual_upi",
        payment_mode: str = "manual",
        payment_provider_snapshot: Optional[Dict] = None
    ) -> Dict:
        """Create a new order"""
        order_id = self.generate_order_id()

        # Get plan details to calculate expiry
        from bot.database.repositories import PlanRepository
        from bot.database.connection import Database
        plan_repo = PlanRepository(Database.get_db())
        plan = await plan_repo.find_by_id(plan_id)

        expiry_date = None
        if plan and plan.get("duration_hours"):
            expiry_date = datetime.utcnow() + timedelta(hours=plan["duration_hours"])

        order_data = {
            "order_id": order_id,
            "user_id": ObjectId(user_id),
            "telegram_id": telegram_id,
            "product_id": ObjectId(product_id),
            "plan_id": ObjectId(plan_id),
            "amount": amount,
            "currency": "INR",
            "status": "pending",
            "payment_method": payment_method,
            "payment_mode": payment_mode,
            "payment_provider_snapshot": payment_provider_snapshot or {},
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "expiry_date": expiry_date,
            "delivery_history": []
        }

        order_id_db = await self.order_repo.create(order_data)
        return await self.order_repo.find_by_id(order_id_db)

    async def get_order_by_id(self, order_id: str) -> Optional[Dict]:
        """Get order by ID"""
        return await self.order_repo.find_by_id(order_id)

    async def get_order_by_order_id(self, order_id: str) -> Optional[Dict]:
        """Get order by human-readable order ID"""
        return await self.order_repo.find_by_order_id(order_id)

    async def get_user_orders(self, user_id: str) -> List[Dict]:
        """Get all orders for a user"""
        return await self.order_repo.find_by_user(user_id)

    async def get_pending_orders(self) -> List[Dict]:
        """Get all pending orders"""
        return await self.order_repo.find_pending_payments()

    async def update_order_status(self, order_id: str, status: str) -> bool:
        """Update order status"""
        extra = {}
        if status == "paid":
            extra["paid_at"] = datetime.utcnow()
        elif status == "delivered":
            extra["delivered_at"] = datetime.utcnow()

        return await self.order_repo.update_status(order_id, status, extra)

    async def assign_key_to_order(self, order_id: str, key_id: str, key_value: str) -> bool:
        """Assign a key to an order"""
        return await self.order_repo.assign_key(order_id, key_id, key_value)

    async def get_order_with_details(self, order_id: str) -> Optional[Dict]:
        """Get order with full details (product, plan, user)"""
        order = await self.get_order_by_id(order_id)
        if not order:
            return None

        # Load related data
        from bot.database.connection import Database
        db = Database.get_db()

        product = await db.products.find_one({"_id": order["product_id"]})
        plan = await db.plans.find_one({"_id": order["plan_id"]})
        user = await db.users.find_one({"_id": order["user_id"]})

        return {
            "order": order,
            "product": product,
            "plan": plan,
            "user": user
        }
