"""Product service - business logic for product operations"""

from typing import List, Optional, Dict
from bot.database.repositories import ProductRepository, PlanRepository


class ProductService:
    """Service for product-related operations"""

    def __init__(self, product_repo: ProductRepository, plan_repo: PlanRepository):
        self.product_repo = product_repo
        self.plan_repo = plan_repo

    async def get_active_products(self) -> List[Dict]:
        """Get all active products"""
        return await self.product_repo.find_active()

    async def get_product_by_id(self, product_id: str) -> Optional[Dict]:
        """Get product by ID"""
        return await self.product_repo.find_by_id(product_id)

    async def get_product_plans(self, product_id: str) -> List[Dict]:
        """Get all active plans for a product"""
        return await self.plan_repo.find_by_product(product_id)

    async def get_plan_by_id(self, plan_id: str) -> Optional[Dict]:
        """Get plan by ID"""
        return await self.plan_repo.find_by_id(plan_id)

    async def create_product(self, product_data: Dict) -> str:
        """Create a new product"""
        return await self.product_repo.create(product_data)

    async def update_product(self, product_id: str, data: Dict) -> bool:
        """Update product"""
        return await self.product_repo.update(product_id, data)

    async def delete_product(self, product_id: str) -> bool:
        """Delete product"""
        return await self.product_repo.delete(product_id)

    async def create_plan(self, plan_data: Dict) -> str:
        """Create a new plan"""
        return await self.plan_repo.create(plan_data)

    async def update_plan(self, plan_id: str, data: Dict) -> bool:
        """Update plan"""
        return await self.plan_repo.update(plan_id, data)

    async def delete_plan(self, plan_id: str) -> bool:
        """Delete plan"""
        return await self.plan_repo.delete(plan_id)
