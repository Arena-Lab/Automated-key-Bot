"""Active routers - legacy sibling files in this package are intentionally
NOT imported (dead code pending deletion)."""

from . import customer, admin, reseller

__all__ = ["customer", "admin", "reseller"]
