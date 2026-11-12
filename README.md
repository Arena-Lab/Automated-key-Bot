# Premium Telegram Digital Key Shop Bot

A production-grade Telegram bot for selling digital keys with UPI payments, key inventory management, automated delivery, and a complete admin panel.

## Features

### Customer Features
- 🛍️ Browse products with images and descriptions
- ⏱️ Multiple subscription plans per product (custom durations & prices)
- 💳 UPI QR code payment with order tracking
- 🔢 UTR submission + payment screenshot upload
- 🔑 Automatic key delivery after payment approval
- 📱 APK file, setup video & instructions delivered automatically
- 📦 Order history and My Keys section
- 📥 Re-download previously purchased files

### Admin Features
- ⚜️ Full admin dashboard via Telegram
- 📊 Statistics (users, orders, revenue, inventory)
- 🛍️ Product CRUD with images, APK, videos, instructions
- ⏱️ Plan management (name, duration, price, enable/disable)
- 🔑 Key inventory: single add, bulk add, TXT/CSV file upload
- 💰 Payment management: switch manual/automatic mode, update UPI/QR
- ✅ Payment approval/rejection with admin verification group
- 📢 Broadcast text/photo/video/document to all users
- 👥 Customer management (view, block/unblock)
- 🔧 Maintenance mode toggle
- 📝 All shop settings editable from panel (no code changes)
- 📋 Admin activity logging

### Architecture
- **Python 3.10+** with **Aiogram 3.x**
- **MongoDB** with Motor (async driver)
- Modular structure: handlers, services, repositories, payments, inventory
- FSM-based multi-step flows
- Idempotent payment approval & key allocation
- Payment provider snapshots per order

## Project Structure

```
├── main.py                  # Entry point
├── config.py                # Configuration from env vars
├── seed.py                  # Optional demo data seeder
├── requirements.txt
├── .env.example
├── ARCHITECTURE.md          # Detailed architecture & DB schema
└── bot/
    ├── handlers/            # customer.py, admin.py, admin_products.py,
    │                        # admin_keys.py, admin_extra.py
    ├── keyboards/           # Inline keyboard builders
    ├── middlewares/         # Auth & maintenance middleware
    ├── filters/             # Admin/user authorization filters
    ├── services/            # Business logic (user, product, order, payment)
    ├── payments/            # Payment providers (manual UPI, auto gateway stub)
    ├── inventory/           # Key manager & atomic allocator
    ├── delivery/            # Delivery sender & message formatter
    ├── database/            # connection.py, models.py, repositories.py
    ├── states/              # FSM states
    └── utils/               # Validators & helpers
```

## Setup

### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=your_telegram_user_id
DATABASE_URL=mongodb://localhost:27017
DATABASE_NAME=key_shop_bot
UPI_ID=yourname@upi
PAYEE_NAME=Your Shop Name
PAYMENT_VERIFICATION_GROUP_ID=-1001234567890  # optional admin group
SHOP_NAME=My Key Shop
OFFICIAL_CHANNEL=@your_channel
SUPPORT_USERNAME=@your_support
```

**Get your Telegram user ID:** message [@userinfobot](https://t.me/userinfobot) on Telegram.

### 3. Start MongoDB

```bash
# Local MongoDB must be running, or use MongoDB Atlas:
DATABASE_URL=mongodb+srv://user:pass@cluster.mongodb.net/
```

### 4. Run

```bash
# Optional: seed demo product
python seed.py

# Start bot
python main.py
```

## First-Time Setup Flow

1. Start the bot → `/start`
2. As admin: `/admin` → Manage Products → Add Product
3. Edit the product → Manage Plans → Add Plan(s)
4. Manage Keys → Add Single Key / Bulk Add / Upload File
   - Format: `product_id plan_id key_value` (IDs shown in plans view)
5. Payment Management → Update UPI Details / QR Code
6. Customers can now purchase!

## Payment Verification

### Manual Mode (default)
1. Customer pays via UPI and submits UTR (+ optional screenshot)
2. Request forwarded to `PAYMENT_VERIFICATION_GROUP_ID` (or admins)
3. Admin clicks ✅ Approve → key allocated & delivered automatically
4. Admin clicks ❌ Reject → customer notified

### Automatic Mode
Architecture is ready in `bot/payments/automatic.py` — implement a real
gateway (Razorpay/PhonePe) by extending `BasePaymentProvider` and adding
webhook handling. Payment mode can be switched from the admin panel without
code changes.

## Admin Commands

| Command | Description |
|---------|-------------|
| `/admin` | Open admin panel |
| `/stats` | Quick statistics |
| `/payment` | Payment management |
| `/addkeys` | Key management menu |
| `/inventory` | View inventory status |
| `/orders` | Order management |
| `/users` | List recent users |
| `/user <id>` | User details |
| `/block <id>` `/unblock <id>` | Block/unblock user |
| `/broadcast` | Send broadcast |
| `/searchkeys <term>` | Search keys |
| `/maintenance` | Toggle maintenance mode |
| `/help` | Admin help |

## Deployment (Linux VPS)

```bash
# Install Python 3.10+, MongoDB (or use Atlas)
git clone <repo> && cd automated-key-bot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # edit with real values

# Run with systemd or screen/tmux
python main.py
```

Example systemd unit:

```ini
[Unit]
Description=Telegram Key Shop Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/automated-key-bot
ExecStart=/home/ubuntu/automated-key-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Security Notes

- Admin actions restricted to `ADMIN_IDS` via router-level filters
- Payment approval requires pending status (idempotent — safe against double-clicks)
- Keys allocated atomically; never delivered twice
- UTR uniqueness enforced at database level
- Secrets only in `.env` (never commit it)
- All admin actions logged to `admin_logs` collection

## Testing Checklist

- [ ] `/start` shows welcome + menu
- [ ] Add product → add plans → add keys via admin panel
- [ ] Purchase flow: product → plan → payment screen
- [ ] Submit UTR → appears in verification group
- [ ] Approve → customer receives key + files
- [ ] Double-approve doesn't duplicate delivery
- [ ] Reject → customer notified
- [ ] My Keys / My Orders show correct data
- [ ] Maintenance mode blocks customers only
- [ ] Broadcast reaches all non-blocked users
