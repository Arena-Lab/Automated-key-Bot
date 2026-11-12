"""Data access layer - Repository pattern"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from .models import (
    User, Product, Plan, Key, Order, Payment,
    Setting, Reseller, Broadcast, AdminLog, PyObjectId
)


class BaseRepository:
    """Base repository with common operations"""

    def __init__(self, db: AsyncIOMotorDatabase, collection_name: str):
        self.db = db
        self.collection = db[collection_name]

    async def create(self, data: Dict[str, Any]) -> str:
        """Insert a document and return its ID"""
        result = await self.collection.insert_one(data)
        return str(result.inserted_id)

    async def find_by_id(self, id: str) -> Optional[Dict]:
        """Find document by ID"""
        return await self.collection.find_one({"_id": ObjectId(id)})

    async def find_one(self, query: Dict[str, Any]) -> Optional[Dict]:
        """Find one document matching query"""
        return await self.collection.find_one(query)

    async def find_many(
        self,
        query: Dict[str, Any],
        skip: int = 0,
        limit: int = 100,
        sort: Optional[List[tuple]] = None
    ) -> List[Dict]:
        """Find multiple documents matching query"""
        cursor = self.collection.find(query).skip(skip).limit(limit)
        if sort:
            cursor = cursor.sort(sort)
        return await cursor.to_list(length=limit)

    async def update(self, id: str, data: Dict[str, Any]) -> bool:
        """Update document by ID"""
        result = await self.collection.update_one(
            {"_id": ObjectId(id)},
            {"$set": data}
        )
        return result.modified_count > 0

    async def update_one(self, query: Dict[str, Any], data: Dict[str, Any]) -> bool:
        """Update one document matching query"""
        result = await self.collection.update_one(query, {"$set": data})
        return result.modified_count > 0

    async def update_raw(self, query: Dict[str, Any], update: Dict[str, Any]) -> bool:
        """Update one document with raw MongoDB update operators"""
        result = await self.collection.update_one(query, update)
        return result.modified_count > 0

    async def delete(self, id: str) -> bool:
        """Delete document by ID"""
        result = await self.collection.delete_one({"_id": ObjectId(id)})
        return result.deleted_count > 0

    async def count(self, query: Dict[str, Any]) -> int:
        """Count documents matching query"""
        return await self.collection.count_documents(query)


class UserRepository(BaseRepository):
    """User repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "users")

    async def find_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        """Find user by Telegram ID"""
        return await self.find_one({"telegram_id": telegram_id})

    async def create_or_update(
        self,
        telegram_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str]
    ) -> Dict:
        """Create user or update existing"""
        existing = await self.find_by_telegram_id(telegram_id)

        if existing:
            await self.update_one(
                {"telegram_id": telegram_id},
                {
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "last_active": datetime.utcnow()
                }
            )
            return await self.find_by_telegram_id(telegram_id)
        else:
            user_data = {
                "telegram_id": telegram_id,
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "is_admin": False,
                "is_blocked": False,
                "is_reseller": False,
                "total_orders": 0,
                "total_spending": 0.0,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "last_active": datetime.utcnow()
            }
            user_id = await self.create(user_data)
            return await self.find_by_id(user_id)

    async def update_stats(self, user_id: str, amount: float) -> bool:
        """Update user order statistics"""
        return await self.update_raw(
            {"_id": ObjectId(user_id)},
            {
                "$inc": {
                    "total_orders": 1,
                    "total_spending": amount
                },
                "$set": {"updated_at": datetime.utcnow()}
            }
        )


class ProductRepository(BaseRepository):
    """Product repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "products")

    async def find_active(self) -> List[Dict]:
        """Find all active products sorted by display order"""
        return await self.find_many(
            {"status": "active"},
            sort=[("display_order", 1)]
        )

    async def find_by_name(self, name: str) -> Optional[Dict]:
        """Find product by name"""
        return await self.find_one({"name": name})


class PlanRepository(BaseRepository):
    """Plan repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "plans")

    async def find_by_product(self, product_id: str) -> List[Dict]:
        """Find all active plans for a product"""
        return await self.find_many(
            {
                "product_id": ObjectId(product_id),
                "status": "active"
            }
        )

    async def find_by_id(self, plan_id: str) -> Optional[Dict]:
        """Find plan by ID"""
        return await super().find_by_id(plan_id)


class KeyRepository(BaseRepository):
    """Key repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "keys")

    async def find_available(
        self,
        product_id: str,
        plan_id: str
    ) -> Optional[Dict]:
        """Find an available key for product and plan"""
        return await self.find_one({
            "product_id": ObjectId(product_id),
            "plan_id": ObjectId(plan_id),
            "status": "available"
        })

    async def reserve_key(
        self,
        key_id: str,
        order_id: str
    ) -> bool:
        """Reserve a key for an order"""
        return await self.update(
            key_id,
            {
                "status": "reserved",
                "order_id": ObjectId(order_id),
                "reserved_at": datetime.utcnow()
            }
        )

    async def mark_as_sold(self, key_id: str) -> bool:
        """Mark a reserved key as sold"""
        return await self.update(
            key_id,
            {
                "status": "sold",
                "sold_at": datetime.utcnow()
            }
        )

    async def release_reservation(self, key_id: str) -> bool:
        """Release a key reservation"""
        return await self.update(
            key_id,
            {
                "status": "available",
                "order_id": None,
                "reserved_at": None
            }
        )

    async def get_inventory_count(
        self,
        product_id: str,
        plan_id: str
    ) -> Dict[str, int]:
        """Get inventory counts for a product/plan"""
        available = await self.count({
            "product_id": ObjectId(product_id),
            "plan_id": ObjectId(plan_id),
            "status": "available"
        })
        sold = await self.count({
            "product_id": ObjectId(product_id),
            "plan_id": ObjectId(plan_id),
            "status": "sold"
        })
        return {"available": available, "sold": sold}

    async def bulk_insert(self, keys: List[str], product_id: str, plan_id: str) -> int:
        """Bulk insert keys"""
        documents = []
        for key in keys:
            documents.append({
                "product_id": ObjectId(product_id),
                "plan_id": ObjectId(plan_id),
                "key_value": key,
                "status": "available",
                "created_at": datetime.utcnow()
            })
        if documents:
            result = await self.collection.insert_many(documents)
            return len(result.inserted_ids)
        return 0


class OrderRepository(BaseRepository):
    """Order repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "orders")

    async def find_by_order_id(self, order_id: str) -> Optional[Dict]:
        """Find order by human-readable order ID"""
        return await self.find_one({"order_id": order_id})

    async def find_by_user(self, user_id: str) -> List[Dict]:
        """Find all orders for a user"""
        return await self.find_many(
            {"user_id": ObjectId(user_id)},
            sort=[("created_at", -1)]
        )

    async def find_pending_payments(self) -> List[Dict]:
        """Find all orders with pending payments"""
        return await self.find_many(
            {"status": "pending"},
            sort=[("created_at", -1)]
        )

    async def update_status(
        self,
        order_id: str,
        status: str,
        extra: Optional[Dict] = None
    ) -> bool:
        """Update order status"""
        update_data = {
            "status": status,
            "updated_at": datetime.utcnow()
        }
        if extra:
            update_data.update(extra)
        return await self.update(order_id, update_data)

    async def assign_key(self, order_id: str, key_id: str, key_value: str) -> bool:
        """Assign a key to an order"""
        return await self.update(
            order_id,
            {
                "key_id": ObjectId(key_id),
                "key_value": key_value,
                "updated_at": datetime.utcnow()
            }
        )


class PaymentRepository(BaseRepository):
    """Payment repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "payments")

    async def find_by_order(self, order_id: str) -> Optional[Dict]:
        """Find payment by order ID"""
        return await self.find_one({"order_id": ObjectId(order_id)})

    async def find_by_utr(self, utr: str) -> Optional[Dict]:
        """Find payment by UTR"""
        return await self.find_one({"utr": utr})

    async def find_expired(self) -> List[Dict]:
        """Find expired pending payments"""
        return await self.find_many({
            "status": "pending",
            "expiry_time": {"$lt": datetime.utcnow()}
        })

    async def update_status(
        self,
        payment_id: str,
        status: str,
        verified_by: Optional[str] = None
    ) -> bool:
        """Update payment status"""
        update_data = {
            "status": status,
            "updated_at": datetime.utcnow()
        }
        if verified_by:
            update_data["verified_by"] = ObjectId(verified_by)
            update_data["verified_at"] = datetime.utcnow()

        return await self.update(payment_id, update_data)


class SettingRepository(BaseRepository):
    """Settings repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "settings")

    async def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value"""
        setting = await self.find_one({"key": key})
        return setting["value"] if setting else default

    async def set(self, key: str, value: Any, description: Optional[str] = None) -> bool:
        """Set a setting value"""
        existing = await self.find_one({"key": key})
        if existing:
            return await self.update_one(
                {"key": key},
                {
                    "value": value,
                    "description": description,
                    "updated_at": datetime.utcnow()
                }
            )
        else:
            await self.create({
                "key": key,
                "value": value,
                "description": description,
                "updated_at": datetime.utcnow()
            })
            return True

    async def get_all(self) -> Dict[str, Any]:
        """Get all settings as a dictionary"""
        settings = await self.find_many({})
        return {s["key"]: s["value"] for s in settings}


class ResellerRepository(BaseRepository):
    """Reseller repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "resellers")

    async def find_by_telegram_id(self, telegram_id: int) -> Optional[Dict]:
        """Find reseller by Telegram ID"""
        return await self.find_one({"telegram_id": telegram_id})

    async def find_by_code(self, code: str) -> Optional[Dict]:
        """Find reseller by reseller code"""
        return await self.find_one({"reseller_code": code})


class BroadcastRepository(BaseRepository):
    """Broadcast repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "broadcasts")


class AdminLogRepository(BaseRepository):
    """Admin log repository"""

    def __init__(self, db: AsyncIOMotorDatabase):
        super().__init__(db, "admin_logs")

    async def log_action(
        self,
        admin_id: Any,
        telegram_id: int,
        action: str,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        details: Optional[Dict] = None
    ) -> str:
        """Log an admin action. admin_id may be a user _id or a telegram id."""
        admin_oid = None
        if admin_id:
            try:
                admin_oid = ObjectId(str(admin_id))
            except Exception:
                # Treat as telegram id and resolve to user _id
                user = await self.db.users.find_one({"telegram_id": int(admin_id)})
                if user:
                    admin_oid = user["_id"]

        entity_oid = None
        if entity_id:
            try:
                entity_oid = ObjectId(str(entity_id))
            except Exception:
                entity_oid = None

        log_data = {
            "admin_id": admin_oid,
            "telegram_id": telegram_id,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_oid,
            "details": details or {},
            "created_at": datetime.utcnow()
        }
        return await self.create(log_data)
