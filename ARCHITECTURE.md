# Telegram Digital Key Shop Bot - Architecture

## Overview

Production-oriented Telegram bot for selling digital keys. Customers buy products through inline keyboards, pay by UPI QR, and receive keys automatically after Gmail/IMAP payment detection confirms the transaction.

Payment verification is automatic-only. There is no manual UTR submission, screenshot upload, or admin approve/reject payment workflow.

## Stack

- Python 3.10+
- Aiogram 3.x
- SQLite via `bot/store.py` (document-style collections with a Mongo-like async API)
- `qrcode` + Pillow for per-order UPI QR images
- Gmail IMAP (stdlib `imaplib`) for payment alert matching

## Project Structure

```text
main.py                  # Bot startup, middleware, background jobs
config.py                # Environment-backed configuration
bot/
  payverify.py           # Gmail/IMAP payment parser and matcher
  svc.py                 # Order, payment, inventory, and delivery services
  store.py               # SQLite persistence and backups
  ui.py                  # Keyboard builders
  fsm.py                 # Admin/reseller FSM states
  middleware.py          # User upsert, blocklist, maintenance mode
  oid.py                 # ObjectId-compatible string IDs
  rsvc.py                # Reseller wallet, codes, and pricing
  handlers/
    customer.py          # Customer catalog, checkout, orders, files
    admin.py             # Admin dashboard and management
    reseller.py          # Reseller router aggregation
    reseller_shop.py     # Reseller storefront/wallet panel
    reseller_admin.py    # Reseller administration
```

## Persistence

`bot/store.py` exposes collection-style access (`db.orders`, `db.payments`, etc.) backed by SQLite tables. Documents are stored as JSON with datetime serialization. The store provides:

- per-collection asyncio locks
- atomic collection snapshots on writes
- in-memory mirrors for fast reads
- scheduled JSON backups under `backups/automatic/`

Important collections:

- `users` — Telegram profiles, block state
- `products`, `plans`, `keys` — catalog and inventory
- `orders`, `payments` — purchase and payment lifecycle
- `payverify_logs` — Gmail message deduplication
- `settings` — runtime shop settings
- `resellers`, `wallet_txns`, `redeem_codes` — reseller system
- `admin_logs`, `broadcasts`, `tutorial`, `counters`

Existing records are preserved; schema changes are additive document fields only.

## Automatic Payment Flow

1. `customer.cb_plan` creates or reuses a pending order for the same user/plan.
2. `payverify.generate_purpose` creates a unique note such as `KS-20261113-AB12CD`.
3. `payverify.build_upi_uri` embeds amount, payee, and purpose into a `upi://` URI.
4. The bot sends a QR image plus a cancel-payment button.
5. Order fields `verify_purpose`, `verify_created_at`, `verify_expires_at`, `verify_status`, and `upi_uri` are persisted; `payments.expiry_time` is aligned to the verify window.
6. `payment_verify_job` polls Gmail when `PayVerifyConfig.configured` is true.
7. `find_matching_payments` performs one mailbox scan and matches candidates by purpose+amount, then amount-only within the fallback window.
8. A matched Gmail message is recorded in `payverify_logs` to prevent duplicate verification.
9. `svc.mark_order_paid` atomically marks the order paid and allocates a key.
10. `svc.deliver_order` sends the key, product files, instructions, and links.
11. An audit message is sent to `PAYMENT_VERIFICATION_GROUP_ID` when configured.

## Order Lifecycle

- `pending` — awaiting automatic payment detection or cancellation/expiry
- `paid` — payment matched; key allocated
- `delivered` — key and files sent successfully
- `expired` / `cancelled` — unpaid order closed

Historical records may contain legacy statuses/fields; they are retained for compatibility.

## Security and Reliability

- Admin routes are guarded by `ADMIN_IDS`
- Per-user purchase locks prevent duplicate concurrent orders
- Payment approval is idempotent (`status: pending` precondition)
- Key allocation uses atomic `find_one_and_update`
- Gmail dedup uses stable RFC `Message-ID` values
- Failed customer delivery releases the key back to stock and keeps the order payable/paid for retry paths
- Blocked users are silently ignored by middleware

## Configuration

See `.env.example`. Automatic verification requires:

- `IMAP_USERNAME`
- `IMAP_APP_PASSWORD`
- `DEFAULT_UPI_ID`

Optional: `PAYEE_NAME`, `IMAP_*` overrides, `PURPOSE_PREFIX`, `PAYMENT_EXPIRY_MINUTES`, `PAYVERIFY_POLL_SECONDS`, `GMAIL_LOOKBACK_HOURS`, and `PAYMENT_VERIFICATION_GROUP_ID`.
