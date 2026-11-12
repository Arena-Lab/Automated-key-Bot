"""Seed script - creates an example product with plans for testing"""

import asyncio
from datetime import datetime
from bson import ObjectId

from bot.database.connection import Database


async def seed():
    await Database.connect()
    await Database.ensure_indexes()
    db = Database.get_db()

    # Check if products already exist
    count = await db.products.count_documents({})
    if count > 0:
        print("Database already has products. Skipping seed.")
        await Database.close()
        return

    # Create example product
    product = {
        "name": "Spy Loader",
        "description": "Premium spy loader tool with advanced features.",
        "status": "active",
        "display_order": 1,
        "delivery_instructions": "1. Install the APK\n2. Open the app\n3. Enter your key to activate",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    product_id = (await db.products.insert_one(product)).inserted_id
    print(f"Created product: {product['name']} (ID: {product_id})")

    # Create plans
    plans = [
        {"name": "12 Hours", "duration_hours": 12, "price": 99},
        {"name": "1 Day", "duration_hours": 24, "price": 149},
        {"name": "7 Days", "duration_hours": 168, "price": 599},
        {"name": "30 Days", "duration_hours": 720, "price": 999},
    ]

    for p in plans:
        plan_data = {
            "product_id": product_id,
            "name": p["name"],
            "duration_hours": p["duration_hours"],
            "price": p["price"],
            "currency": "INR",
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        plan_id = (await db.plans.insert_one(plan_data)).inserted_id
        print(f"  Plan: {p['name']} - ₹{p['price']} (ID: {plan_id})")

    print("\nSeed complete! Now add keys via the admin panel (/addkeys).")
    await Database.close()


if __name__ == "__main__":
    asyncio.run(seed())
