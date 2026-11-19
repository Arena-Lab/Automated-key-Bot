# Telegram Digital Key Shop Bot

A Telegram bot for selling digital keys with automatic UPI payment detection via Gmail/IMAP, key inventory management, automated delivery, reseller wallets, and a Telegram admin panel.

## Features

### Customer
- Browse products and subscription plans
- Per-order UPI QR with exact amount and unique payment reference
- Automatic payment detection from Gmail/IMAP credit alerts
- Automatic key, APK/video, instructions, and link delivery after verified payment
- Order history, key lookup, file resend, and pending-payment cancellation
- Optional reseller program with USDT wallet and redeem codes

### Admin
- Dashboard for products, plans, keys, orders, customers, files, broadcasts, promos, and settings
- Product/plan/key management
- APK, setup video, product links, and how-to-buy video management
- Broadcast and promo messages
- Customer lookup and blocking
- Reseller approvals, wallet adjustments, redeem codes, and pricing
- Automatic payment audit messages in the configured Telegram group

## Payment Flow

1. Customer chooses a product and plan.
2. Bot creates a pending order and sends a QR for the exact INR amount.
3. The QR/UPI URI contains a unique purpose note (for example `KS-20261113-AB12CD`).
4. `bot/payverify.py` polls the configured Gmail inbox over IMAP.
5. Incoming FamApp/bank credit alerts are matched by purpose + amount, with an amount-only fallback window.
6. Matching orders are approved atomically, keys are allocated, and delivery is sent automatically.
7. Duplicate Gmail messages are deduplicated through `payverify_logs`.

There is no manual UTR/screenshot submission or admin payment approval step.

## Requirements

- Python 3.10+
- Telegram bot token from @BotFather
- Gmail account that receives UPI payment alerts
- Gmail App Password with IMAP access

## Setup

```bash
python -m venv venv
venv\Scripts\activate     # Windows
# source venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
copy .env.example .env     # Windows
# cp .env.example .env     # Linux/macOS
```

Edit `.env`:

```env
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=your_numeric_telegram_id

IMAP_USERNAME=your@gmail.com
IMAP_APP_PASSWORD=your_gmail_app_password
DEFAULT_UPI_ID=yourname@upi
PAYEE_NAME=Your Business Name
PAYMENT_VERIFICATION_GROUP_ID=-1001234567890
```

Required for automatic verification:

- `IMAP_USERNAME`
- `IMAP_APP_PASSWORD`
- `DEFAULT_UPI_ID`

Optional tuning:

- `IMAP_HOST`, `IMAP_PORT`, `IMAP_MAILBOX`, `IMAP_SENDER_FILTER`
- `PURPOSE_PREFIX`
- `PAYMENT_EXPIRY_MINUTES`
- `PAYVERIFY_POLL_SECONDS`
- `GMAIL_LOOKBACK_HOURS`

Start the bot:

```bash
python main.py
```

The bot uses SQLite (`data/store.db`) through the compatibility layer in `bot/store.py`. Existing JSON-style documents are preserved; no destructive migration is performed.

## Admin

- `/admin` — main control panel
- `/settings` — shop settings and maintenance controls
- `/adminhelp` — admin command reference
- `/blockuser USER_ID`, `/unblockuser USER_ID`, `/blockedusers` — user moderation

Payment verification is automatic. Admins can monitor orders and payment status under **Orders**, and audit messages are sent to `PAYMENT_VERIFICATION_GROUP_ID` when configured.

## Project Structure

```text
main.py                  # Entry point and background jobs
config.py                # Environment configuration
bot/
  payverify.py           # Gmail/IMAP automatic payment matcher
  svc.py                 # Orders, payments, inventory, delivery services
  store.py               # SQLite-backed document store
  ui.py                  # Inline/reply keyboards
  fsm.py                 # Admin/reseller FSM states
  handlers/
    customer.py          # Customer purchase and order flows
    admin.py             # Admin panel
    reseller.py          # Reseller router aggregation
    reseller_shop.py     # Reseller customer panel
    reseller_admin.py    # Reseller admin panel
  rsvc.py                # Reseller wallet/code/pricing services
```

## Security Notes

- Admin actions are restricted to `ADMIN_IDS`
- Key allocation is atomic and orders are approved idempotently
- Gmail message IDs are deduplicated to prevent repeat delivery
- Secrets belong only in `.env` (never commit it)
- Backups are written under `backups/automatic/`
