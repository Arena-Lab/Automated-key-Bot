"""Key allocation logic with transaction safety"""

from typing import Optional, Dict
from bot.database.repositories import KeyRepository, OrderRepository


class KeyAllocator:
    """Handles atomic key allocation for orders"""

    def __init__(self, key_repo: KeyRepository, order_repo: OrderRepository):
        self.key_repo = key_repo
        self.order_repo = order_repo

    async def allocate_key(
        self,
        product_id: str,
        plan_id: str,
        order_id: str
    ) -> Optional[Dict]:
        """
        Atomically allocate a key for an order.
        Returns the allocated key or None if no keys available.
        """
        # Find an available key
        key = await self.key_repo.find_available(product_id, plan_id)

        if not key:
            return None

        # Reserve the key
        reserved = await self.key_repo.reserve_key(str(key["_id"]), order_id)

        if not reserved:
            # Race condition - another order took this key
            # Try recursively
            return await self.allocate_key(product_id, plan_id, order_id)

        return key

    async def confirm_allocation(
        self,
        key_id: str,
        order_id: str
    ) -> bool:
        """
        Confirm key allocation after successful payment.
        Marks the key as sold and links it to the order.
        """
        try:
            # Mark key as sold
            await self.key_repo.mark_as_sold(key_id)

            # Update order with key details
            key = await self.key_repo.find_by_id(key_id)
            if key:
                await self.order_repo.assign_key(
                    order_id,
                    key_id,
                    key["key_value"]
                )

            return True
        except Exception:
            return False

    async def rollback_allocation(self, key_id: str) -> bool:
        """
        Rollback key allocation if payment fails.
        Releases the key back to available pool.
        """
        try:
            await self.key_repo.release_reservation(key_id)
            return True
        except Exception:
            return False

    async def check_availability(
        self,
        product_id: str,
        plan_id: str
    ) -> bool:
        """Check if keys are available for a product/plan"""
        key = await self.key_repo.find_available(product_id, plan_id)
        return key is not None

    async def get_available_count(
        self,
        product_id: str,
        plan_id: str
    ) -> int:
        """Get count of available keys"""
        inventory = await self.key_repo.get_inventory_count(product_id, plan_id)
        return inventory.get("available", 0)
