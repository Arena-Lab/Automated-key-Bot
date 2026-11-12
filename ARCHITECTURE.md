# Telegram Digital Key Shop Bot - Architecture Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [Technology Stack](#technology-stack)
3. [Project Structure](#project-structure)
4. [Database Schema](#database-schema)
5. [System Architecture](#system-architecture)
6. [Key Design Decisions](#key-design-decisions)
7. [Security Considerations](#security-considerations)

---

## Project Overview

This is a production-grade Telegram bot for selling digital keys with:
- Product management with unlimited customizable products
- Flexible subscription plans and pricing
- Key inventory management
- UPI payment integration (manual and automatic modes)
- Automatic product delivery
- Complete admin panel
- Customer order management
- Broadcast system
- Reseller system (optional)

---

## Technology Stack

### Core Framework
- **Python 3.10+**: Primary programming language
- **Aiogram 3.x**: Telegram Bot API framework
- **Motor**: Async MongoDB driver
- **MongoDB**: NoSQL database for data persistence

### Supporting Libraries
- **python-dotenv**: Environment variable management
- **Pillow**: Image processing
- **python-dateutil**: Date/time utilities
- **qrcode**: QR code generation
- **aiofiles**: Async file operations
- **pydantic**: Data validation

---

## Project Structure

```
automated-key-bot/
├── bot/
│   ├── __init__.py
│   ├── handlers/           # Telegram message and callback handlers
│   │   ├── __init__.py
│   │   ├── customer.py     # Customer-facing handlers
│   │   ├── admin.py        # Admin panel handlers
│   │   └── payment.py      # Payment-related handlers
│   ├── keyboards/          # Inline keyboard builders
│   │   ├── __init__.py
│   │   ├── customer.py
│   │   ├── admin.py
│   │   └── payment.py
│   ├── middlewares/        # Custom middlewares
│   │   ├── __init__.py
│   │   ├── auth.py         # Admin authorization
│   │   └── maintenance.py  # Maintenance mode check
│   ├── filters/            # Custom filters
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   └── user.py
│   ├── services/           # Business logic services
│   │   ├── __init__.py
│   │   ├── product_service.py
│   │   ├── order_service.py
│   │   ├── user_service.py
│   │   └── payment_service.py
│   ├── payments/           # Payment provider implementations
│   │   ├── __init__.py
│   │   ├── base.py         # Base payment provider
│   │   ├── manual_upi.py   # Manual UPI verification
│   │   └── automatic.py    # Automatic payment gateways
│   ├── inventory/          # Key inventory management
│   │   ├── __init__.py
│   │   ├── manager.py      # Inventory manager
│   │   └── allocator.py    # Key allocation logic
│   ├── delivery/           # Product delivery system
│   │   ├── __init__.py
│   │   ├── sender.py       # Delivery handler
│   │   └── formatter.py    # Message formatting
│   ├── admin/              # Admin panel logic
│   │   ├── __init__.py
│   │   ├── dashboard.py    # Admin dashboard
│   │   ├── product_manager.py
│   │   ├── key_manager.py
│   │   └── statistics.py
│   ├── database/           # Database operations
│   │   ├── __init__.py
│   │   ├── connection.py   # MongoDB connection
│   │   ├── models.py       # Database models
│   │   └── repositories.py # Data access layer
│   ├── states/             # FSM state definitions
│   │   ├── __init__.py
│   │   └── customer.py
│   └── utils/              # Utility functions
│       ├── __init__.py
│       ├── formatters.py
│       ├── validators.py
│       └── helpers.py
├── config.py               # Configuration management
├── main.py                 # Application entry point
├── requirements.txt        # Python dependencies
├── .env.example           # Environment variables template
├── ARCHITECTURE.md        # This file
└── README.md              # Project documentation
```

---

## Database Schema

### Collections Overview

1. **users** - User information and profiles
2. **products** - Product catalog and configurations
3. **plans** - Subscription plans for products
4. **keys** - Key inventory
5. **orders** - Order records
6. **payments** - Payment transactions
7. **settings** - Global bot settings
8. **resellers** - Reseller accounts (optional)
9. **broadcasts** - Broadcast message history
10. **admin_logs** - Admin activity logs

---

### Collection: users

```python
{
    "_id": ObjectId,
    "telegram_id": Int,  # Unique Telegram user ID
    "username": String,  # Telegram username (optional)
    "first_name": String,
    "last_name": String,
    "is_admin": Boolean,
    "is_blocked": Boolean,
    "is_reseller": Boolean,
    "total_orders": Int,
    "total_spending": Decimal,
    "created_at": DateTime,
    "updated_at": DateTime,
    "last_active": DateTime
}
```

**Indexes:**
- Unique index on `telegram_id`
- Index on `username`
- Index on `is_reseller`

---

### Collection: products

```python
{
    "_id": ObjectId,
    "name": String,
    "description": String,
    "image_url": String,  # Telegram file_id or URL
    "image_file_id": String,
    "status": String,  # active, disabled
    "display_order": Int,
    "delivery_instructions": String,
    "created_at": DateTime,
    "updated_at": DateTime,
    "apk_file_id": String,  # Latest APK
    "apk_version": String,
    "setup_video_file_id": String,
    "setup_video_url": String,
    "setup_document_file_id": String,
    "payment_settings": {
        "upi_enabled": Boolean,
        "custom_payment": Boolean
    }
}
```

**Indexes:**
- Index on `status`
- Index on `display_order`

---

### Collection: plans

```python
{
    "_id": ObjectId,
    "product_id": ObjectId,
    "name": String,  # e.g., "12 Hours", "1 Day", "7 Days"
    "duration_hours": Int,
    "price": Decimal,
    "currency": String,  # INR
    "status": String,  # active, disabled
    "key_format": String,  # Format template for keys
    "created_at": DateTime,
    "updated_at": DateTime
}
```

**Indexes:**
- Index on `product_id`
- Compound index on `product_id` and `status`

---

### Collection: keys

```python
{
    "_id": ObjectId,
    "product_id": ObjectId,
    "plan_id": ObjectId,
    "key_value": String,  # The actual key
    "status": String,  # available, sold, invalid, reserved
    "order_id": ObjectId,  # Reference to order when sold
    "reserved_at": DateTime,
    "sold_at": DateTime,
    "created_at": DateTime
}
```

**Indexes:**
- Unique index on `key_value`
- Index on `product_id`
- Index on `plan_id`
- Index on `status`
- Compound index on `product_id`, `plan_id`, and `status`

---

### Collection: orders

```python
{
    "_id": ObjectId,
    "order_id": String,  # Human-readable order ID (e.g., KS487001)
    "user_id": ObjectId,
    "telegram_id": Int,
    "product_id": ObjectId,
    "plan_id": ObjectId,
    "key_id": ObjectId,  # Allocated key
    "key_value": String,  # Delivered key (for reference)
    "amount": Decimal,
    "currency": String,
    "status": String,  # pending, paid, delivered, cancelled, failed
    "payment_method": String,  # manual_upi, automatic_gateway
    "payment_mode": String,  # manual, automatic
    "payment_provider_snapshot": Object,  # Payment config at order time
    "created_at": DateTime,
    "updated_at": DateTime,
    "paid_at": DateTime,
    "delivered_at": DateTime,
    "expiry_date": DateTime,  # For subscription keys
    "delivery_history": [Object]  # Track all delivery attempts
}
```

**Indexes:**
- Unique index on `order_id`
- Index on `user_id`
- Index on `telegram_id`
- Index on `status`
- Index on `created_at`

---

### Collection: payments

```python
{
    "_id": ObjectId,
    "order_id": ObjectId,
    "user_id": ObjectId,
    "telegram_id": Int,
    "amount": Decimal,
    "currency": String,
    "payment_method": String,
    "payment_mode": String,
    "utr": String,  # UPI transaction reference
    "payment_screenshot_file_id": String,
    "status": String,  # pending, approved, rejected, expired
    "verified_by": ObjectId,  # Admin user ID (for manual verification)
    "verified_at": DateTime,
    "gateway_transaction_id": String,  # For automatic payments
    "gateway_response": Object,  # Full gateway response
    "expiry_time": DateTime,
    "created_at": DateTime,
    "updated_at": DateTime
}
```

**Indexes:**
- Unique index on `utr` (to prevent duplicate UTRs)
- Index on `order_id`
- Index on `status`
- Index on `expiry_time`

---

### Collection: settings

```python
{
    "_id": ObjectId,
    "key": String,  # Unique setting key
    "value": Any,   # Setting value (string, number, object, etc.)
    "description": String,
    "updated_at": DateTime
}
```

**Common Settings:**
- `shop_name`
- `welcome_message`
- `maintenance_message`
- `current_payment_mode`
- `upi_id`
- `payee_name`
- `qr_code_file_id`
- `payment_instructions`
- `official_channel`
- `support_username`

**Indexes:**
- Unique index on `key`

---

### Collection: resellers

```python
{
    "_id": ObjectId,
    "user_id": ObjectId,
    "telegram_id": Int,
    "reseller_code": String,  # Unique reseller code
    "balance": Decimal,
    "discount_percentage": Decimal,
    "status": String,  # active, suspended, pending
    "approved_by": ObjectId,
    "approved_at": DateTime,
    "created_at": DateTime,
    "updated_at": DateTime
}
```

**Indexes:**
- Unique index on `reseller_code`
- Index on `telegram_id`
- Index on `status`

---

### Collection: broadcasts

```python
{
    "_id": ObjectId,
    "admin_id": ObjectId,
    "message_type": String,  # text, photo, video, document
    "content": String,
    "file_id": String,
    "total_recipients": Int,
    "sent_count": Int,
    "failed_count": Int,
    "blocked_count": Int,
    "status": String,  # completed, partial, failed
    "created_at": DateTime,
    "completed_at": DateTime
}
```

**Indexes:**
- Index on `created_at`
- Index on `status`

---

### Collection: admin_logs

```python
{
    "_id": ObjectId,
    "admin_id": ObjectId,
    "telegram_id": Int,
    "action": String,  # e.g., "approve_payment", "add_product"
    "entity_type": String,  # e.g., "order", "product"
    "entity_id": ObjectId,
    "details": Object,
    "ip_address": String,
    "created_at": DateTime
}
```

**Indexes:**
- Index on `admin_id`
- Index on `action`
- Index on `created_at`

---

## System Architecture

### 1. Layered Architecture

```
┌─────────────────────────────────────┐
│      Telegram Interface Layer       │
│  (Handlers, Keyboards, Messages)    │
└─────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│         Business Logic Layer        │
│     (Services, Payment, Inventory)  │
└─────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│         Data Access Layer           │
│        (Repositories, Models)       │
└─────────────────────────────────────┘
                 ↓
┌─────────────────────────────────────┐
│           Database Layer            │
│            (MongoDB)                 │
└─────────────────────────────────────┘
```

### 2. Customer Purchase Flow

```
1. User starts bot
   ↓
2. Display main menu
   ↓
3. User selects "Purchase Products"
   ↓
4. Display available products
   ↓
5. User selects product
   ↓
6. Display available plans/prices
   ↓
7. User selects plan
   ↓
8. Create order (pending status)
   ↓
9. Display payment screen (QR code, UPI ID, amount)
   ↓
10. User submits UTR + optional screenshot
    ↓
11. Forward to admin verification group
    ↓
12. Admin approves/rejects payment
    ↓
13. If approved:
    - Allocate key from inventory
    - Mark order as paid
    - Deliver key + files
    - Update order status to delivered
```

### 3. Payment Verification Flow

**Manual Mode:**
```
User submits UTR → Store in DB → Forward to admins → Admin approves → Key delivery
```

**Automatic Mode:**
```
Payment initiated → Gateway response → Webhook received → Verify transaction → Key delivery
```

### 4. Key Allocation Flow

```
1. Lock key reservation
2. Find available key for product_id + plan_id
3. Mark key as reserved
4. Complete payment verification
5. Mark key as sold and link to order
6. If payment fails, release reservation
```

### 5. Admin Panel Flow

```
Admin opens panel → Verify authorization → Display dashboard → Navigate to sections
```

---

## Key Design Decisions

### 1. MongoDB vs PostgreSQL
**Decision: MongoDB**

**Reasons:**
- Flexible schema for dynamic product configurations
- Better for storing payment provider snapshots
- Easier to evolve as requirements change
- Native JSON support for complex objects
- Good performance for read-heavy operations

### 2. Async/Await Architecture
**Decision: Full async using Motor**

**Reasons:**
- Aiogram 3.x is async-first
- Better performance under concurrent requests
- Non-blocking I/O for database operations
- Efficient handling of multiple simultaneous users

### 3. Modular Payment System
**Decision: Provider-based architecture**

**Reasons:**
- Easy to add new payment methods
- Switch between providers without code changes
- Store payment configuration snapshots per order
- Independent testing of payment providers

### 4. State Management
**Decision: Aiogram FSM + Database persistence**

**Reasons:**
- FSM for short-term user interactions
- Database for persistent order and payment state
- Recovery from bot restarts
- No loss of pending orders

### 5. File Storage
**Decision: Telegram file_id storage**

**Reasons:**
- No external storage costs
- Fast delivery through Telegram
- Automatic CDN by Telegram
- Simplified deployment

### 6. Idempotent Operations
**Decision: Check-before-act pattern**

**Reasons:**
- Prevent duplicate key delivery
- Prevent duplicate payment approval
- Safe admin button clicks
- Transaction-safe operations

---

## Security Considerations

### 1. Admin Authorization
- Check Telegram user ID against allowlist
- Admin operations require explicit authorization
- Log all admin actions

### 2. Payment Security
- Never trust user-submitted UTR
- Manual verification requires admin approval
- No automatic key delivery without verified payment
- Store payment provider snapshots

### 3. Key Inventory Security
- Atomic key allocation
- Transaction-safe operations
- Prevent double-spending of keys
- Proper error handling for out-of-stock scenarios

### 4. Environment Variables
- All secrets in .env file
- Never commit .env to version control
- .env.example provided as template
- Runtime validation of required config

### 5. Rate Limiting
- Telegram API rate limiting compliance
- Chunked broadcast messages
- Delay between broadcast chunks

### 6. Input Validation
- Validate all user inputs
- Sanitize file uploads
- Validate payment amounts
- Check product and plan existence

### 7. Error Handling
- Graceful error handling
- User-friendly error messages
- Detailed error logging
- No sensitive data in error messages

---

## Scalability Considerations

### 1. Database Indexing
- Proper indexes on frequently queried fields
- Compound indexes for complex queries
- Regular index maintenance

### 2. Async Operations
- Non-blocking database operations
- Concurrent order processing
- Efficient payment verification

### 3. Caching
- Cache frequently accessed settings
- Cache product configurations
- TTL-based cache invalidation

### 4. Connection Pooling
- MongoDB connection pooling
- Reuse connections
- Proper connection management

---

## Development Phases

### Phase 1: Core Shop
- Bot initialization
- Welcome interface
- Product management
- Subscription plans
- Key inventory
- UPI QR payment
- Manual payment verification
- Admin approval
- Automatic key delivery
- APK and tutorial delivery
- Customer order history

### Phase 2: Advanced Administration
- Complete admin dashboard
- Statistics
- Broadcast system
- Customer management
- Advanced inventory management
- Global payment controls
- Maintenance controls

### Phase 3: Automation
- Automatic payment provider integration
- Webhook handling
- Automatic payment verification
- Automatic delivery
- Payment provider switching

### Phase 4: Advanced Features
- Reseller system
- Advanced analytics
- Promotional discounts
- Referral system
- Coupon management
- Advanced customer management
