"""Key inventory manager"""

from typing import List, Optional, Dict
from bot.database.repositories import KeyRepository


class InventoryManager:
    """Manager for key inventory operations"""

    def __init__(self, key_repo: KeyRepository):
        self.key_repo = key_repo

    async def add_key(
        self,
        product_id: str,
        plan_id: str,
        key_value: str
    ) -> bool:
        """Add a single key to inventory"""
        try:
            await self.key_repo.create({
                "product_id": product_id,
                "plan_id": plan_id,
                "key_value": key_value,
                "status": "available",
                "created_at": "now"
            })
            return True
        except Exception:
            # Likely duplicate key
            return False

    async def bulk_add_keys(
        self,
        product_id: str,
        plan_id: str,
        keys: List[str]
    ) -> Dict[str, int]:
        """Bulk add keys to inventory"""
        added = await self.key_repo.bulk_insert(keys, product_id, plan_id)
        duplicates = len(keys) - added
        return {
            "added": added,
            "duplicates": duplicates,
            "total": len(keys)
        }

    async def get_inventory_status(
        self,
        product_id: str,
        plan_id: str
    ) -> Dict[str, int]:
        """Get inventory status for a product/plan"""
        return await self.key_repo.get_inventory_count(product_id, plan_id)

    async def get_all_inventory(self) -> List[Dict]:
        """Get inventory status for all product/plan combinations"""
        from bot.database.connection import Database
        db = Database.get_db()

        pipeline = [
            {
                "$group": {
                    "_id": {
                        "product_id": "$product_id",
                        "plan_id": "$plan_id"
                    },
                    "available": {
                        "$sum": {"$cond": [{"$eq": ["$status", "available"]}, 1, 0]}
                    },
                    "sold": {
                        "$sum": {"$cond": [{"$eq": ["$status", "sold"]}, 1, 0]}
                    },
                    "reserved": {
                        "$sum": {"$cond": [{"$eq": ["$status", "reserved"]}, 1, 0]}
                    }
                }
            }
        ]

        results = await db.keys.aggregate(pipeline).to_list(length=None)
        return results

    async def delete_key(self, key_id: str) -> bool:
        """Delete a key from inventory"""
        return await self.key_repo.delete(key_id)

    async def mark_key_invalid(self, key_id: str) -> bool:
        """Mark a key as invalid"""
        return await self.key_repo.update(key_id, {"status": "invalid"})

    async def search_keys(
        self,
        product_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        status: Optional[str] = None,
        search_term: Optional[str] = None
    ) -> List[Dict]:
        """Search keys with filters"""
        query = {}

        if product_id:
            query["product_id"] = product_id
        if plan_id:
            query["plan_id"] = plan_id
        if status:
            query["status"] = status
        if search_term:
            query["key_value"] = {"$regex": search_term, "$options": "i"}

        return await self.key_repo.find_many(query, limit=1000)

    async def get_low_stock_items(self, threshold: int = 10) -> List[Dict]:
        """Get product/plan combinations with low stock"""
        inventory = await self.get_all_inventory()
        low_stock = [
            item for item in inventory
            if item.get("available", 0) < threshold
        ]
        return low_stock
