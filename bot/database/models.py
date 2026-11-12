"""Database models and schemas"""

from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field, ConfigDict
from pydantic_core import core_schema
from bson import ObjectId


class PyObjectId(ObjectId):
    """Custom ObjectId type compatible with Pydantic v2"""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        return core_schema.no_info_plain_validator_function(
            cls.validate,
            serialization=core_schema.plain_serializer_function_ser_schema(str),
        )

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


class User(BaseModel):
    """User model"""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    telegram_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_admin: bool = False
    is_blocked: bool = False
    is_reseller: bool = False
    total_orders: int = 0
    total_spending: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )


class Product(BaseModel):
    """Product model"""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    name: str
    description: str
    image_url: Optional[str] = None
    image_file_id: Optional[str] = None
    status: str = "active"  # active, disabled
    display_order: int = 0
    delivery_instructions: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    apk_file_id: Optional[str] = None
    apk_version: Optional[str] = None
    setup_video_file_id: Optional[str] = None
    setup_video_url: Optional[str] = None
    setup_document_file_id: Optional[str] = None
    payment_settings: dict = Field(default_factory=dict)

    model_config = ConfigDict(
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )


class Plan(BaseModel):
    """Subscription plan model"""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    product_id: PyObjectId
    name: str  # e.g., "12 Hours", "1 Day"
    duration_hours: int
    price: float
    currency: str = "INR"
    status: str = "active"  # active, disabled
    key_format: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )


class Key(BaseModel):
    """Key inventory model"""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    product_id: PyObjectId
    plan_id: PyObjectId
    key_value: str
    status: str = "available"  # available, sold, invalid, reserved
    order_id: Optional[PyObjectId] = None
    reserved_at: Optional[datetime] = None
    sold_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )


class Order(BaseModel):
    """Order model"""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    order_id: str  # Human-readable ID
    user_id: PyObjectId
    telegram_id: int
    product_id: PyObjectId
    plan_id: PyObjectId
    key_id: Optional[PyObjectId] = None
    key_value: Optional[str] = None
    amount: float
    currency: str = "INR"
    status: str = "pending"  # pending, paid, delivered, cancelled, failed
    payment_method: str = "manual_upi"
    payment_mode: str = "manual"
    payment_provider_snapshot: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    paid_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    delivery_history: List[dict] = Field(default_factory=list)

    model_config = ConfigDict(
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )


class Payment(BaseModel):
    """Payment model"""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    order_id: PyObjectId
    user_id: PyObjectId
    telegram_id: int
    amount: float
    currency: str = "INR"
    payment_method: str
    payment_mode: str
    utr: Optional[str] = None
    payment_screenshot_file_id: Optional[str] = None
    status: str = "pending"  # pending, approved, rejected, expired
    verified_by: Optional[PyObjectId] = None
    verified_at: Optional[datetime] = None
    gateway_transaction_id: Optional[str] = None
    gateway_response: dict = Field(default_factory=dict)
    expiry_time: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )


class Setting(BaseModel):
    """Global settings model"""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    key: str
    value: Any
    description: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )


class Reseller(BaseModel):
    """Reseller model"""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    user_id: PyObjectId
    telegram_id: int
    reseller_code: str
    balance: float = 0.0
    discount_percentage: float = 0.0
    status: str = "pending"  # active, suspended, pending
    approved_by: Optional[PyObjectId] = None
    approved_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )


class Broadcast(BaseModel):
    """Broadcast model"""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    admin_id: PyObjectId
    message_type: str  # text, photo, video, document
    content: Optional[str] = None
    file_id: Optional[str] = None
    total_recipients: int = 0
    sent_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    status: str = "completed"  # completed, partial, failed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )


class AdminLog(BaseModel):
    """Admin activity log model"""
    id: PyObjectId = Field(default_factory=PyObjectId, alias="_id")
    admin_id: PyObjectId
    telegram_id: int
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[PyObjectId] = None
    details: dict = Field(default_factory=dict)
    ip_address: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(
        validate_by_name=True,
        arbitrary_types_allowed=True,
    )
