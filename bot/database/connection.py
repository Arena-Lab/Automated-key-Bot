"""MongoDB connection management"""

from motor.motor_asyncio import AsyncIOMotorClient
from config import Config


class Database:
    """Database connection manager"""

    client: AsyncIOMotorClient = None
    database = None

    @classmethod
    async def connect(cls):
        """Establish database connection"""
        cls.client = AsyncIOMotorClient(Config.DATABASE_URL)
        cls.database = cls.client[Config.DATABASE_NAME]
        print(f"Connected to MongoDB: {Config.DATABASE_NAME}")

    @classmethod
    async def close(cls):
        """Close database connection"""
        if cls.client is not None:
            cls.client.close()
            print("MongoDB connection closed")

    @classmethod
    def get_db(cls):
        """Get database instance"""
        if cls.database is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return cls.database

    @classmethod
    async def ensure_indexes(cls):
        """Create database indexes"""
        db = cls.get_db()

        # Users collection indexes
        await db.users.create_index("telegram_id", unique=True)
        await db.users.create_index("username")
        await db.users.create_index("is_reseller")

        # Products collection indexes
        await db.products.create_index("status")
        await db.products.create_index("display_order")

        # Plans collection indexes
        await db.plans.create_index("product_id")
        await db.plans.create_index([("product_id", 1), ("status", 1)])

        # Keys collection indexes
        await db.keys.create_index("key_value", unique=True)
        await db.keys.create_index("product_id")
        await db.keys.create_index("plan_id")
        await db.keys.create_index("status")
        await db.keys.create_index([("product_id", 1), ("plan_id", 1), ("status", 1)])

        # Orders collection indexes
        await db.orders.create_index("order_id", unique=True)
        await db.orders.create_index("user_id")
        await db.orders.create_index("telegram_id")
        await db.orders.create_index("status")
        await db.orders.create_index("created_at")

        # Payments collection indexes
        await db.payments.create_index("utr", unique=True, sparse=True)
        await db.payments.create_index("order_id")
        await db.payments.create_index("status")
        await db.payments.create_index("expiry_time")

        # Settings collection indexes
        await db.settings.create_index("key", unique=True)

        # Resellers collection indexes
        await db.resellers.create_index("reseller_code", unique=True)
        await db.resellers.create_index("telegram_id")
        await db.resellers.create_index("status")

        # Broadcasts collection indexes
        await db.broadcasts.create_index("created_at")
        await db.broadcasts.create_index("status")

        # Admin logs collection indexes
        await db.admin_logs.create_index("admin_id")
        await db.admin_logs.create_index("action")
        await db.admin_logs.create_index("created_at")

        # One-time cleanup: remove empty-string UTRs that collide on the unique index
        await db.payments.update_many(
            {"utr": ""},
            {"$unset": {"utr": ""}}
        )

        print("Database indexes created successfully")
