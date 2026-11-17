"""Reseller core services - USDT wallets, ledger, redeem codes, pricing.

All reseller money is USDT stored as INTEGER CENTS (usd_cents = USDT * 100)
to avoid floating-point errors. Customer shop stays INR - never mix.
"""

import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import bot.svc as svc
from bot.oid import ObjectId


def usdt_parse(text) -> Optional[int]:
    """Parse '3.50' / '$3.5' / '3' -> cents int. None if invalid."""
    try:
        t = str(text).strip().replace("$", "").replace(",", "")
        if not t:
            return None
        v = float(t)
        if v < 0:
            return None
        return int(round(v * 100))
    except (ValueError, TypeError):
        return None


def usdt_fmt(cents) -> str:
    try:
        c = int(cents or 0)
    except (TypeError, ValueError):
        c = 0
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}${c // 100}.{c % 100:02d}"


# ---------------- settings ----------------

RES_DEFAULTS = {
    "reseller_enabled": True,
    "reseller_apps_enabled": True,
    "reseller_purchases_enabled": True,
    "reseller_codes_enabled": True,
    "reseller_individual_pricing": True,
    "reseller_stats_enabled": True,
    "reseller_min_enabled": True,
    "reseller_min_cents": 30000,           # $300.00 initial (editable)
    "reseller_min_scope": "all",           # 'all' recharges | 'first' qualification only
    "reseller_allow_negative": False,
}

_BOOL_KEYS = {k for k, v in RES_DEFAULTS.items() if isinstance(v, bool)}


async def rsettings(db) -> Dict[str, Any]:
    s = await svc.get_settings(db)
    out = dict(RES_DEFAULTS)
    for k in RES_DEFAULTS:
        if k in s:
            out[k] = s[k]
    # coerce bools (settings stored as strings sometimes)
    for k in _BOOL_KEYS:
        v = out[k]
        if isinstance(v, str):
            out[k] = v.lower() in ("1", "true", "yes", "on")
    return out


async def rset(db, key: str, value):
    await db.settings.update_one({"key": key},
        {"$set": {"key": key, "value": value, "updated_at": svc.now_utc()}},
        upsert=True)
    svc.invalidate_settings()


async def toggle_rsetting(db, key: str) -> bool:
    rs = await rsettings(db)
    new = not bool(rs.get(key))
    await rset(db, key, new)
    return new


# ---------------- resellers ----------------

async def get_reseller(db, telegram_id: int) -> Optional[Dict]:
    return await db.resellers.find_one({"telegram_id": telegram_id})


async def is_active_reseller(db, telegram_id: int) -> Optional[Dict]:
    r = await get_reseller(db, telegram_id)
    if r and r.get("status") == "active":
        return r
    return None


# ---------------- pricing ----------------
# Global default: plan.reseller_price_cents (set by admin per plan).
# Individual override: reseller.price_overrides[plan_id_str] = cents.
# Resolution: override -> global plan price -> None (not configured).

async def plan_price_cents(db, reseller: Optional[Dict], plan: Dict) -> Optional[int]:
    pid = str(plan["_id"])
    if reseller and reseller.get("price_overrides"):
        ov = reseller["price_overrides"].get(pid)
        if ov is not None:
            return int(ov)
    g = plan.get("reseller_price_cents")
    if g is not None:
        return int(g)
    return None


async def set_global_price(db, plan_id, cents: int):
    await db.plans.update_one({"_id": plan_id},
        {"$set": {"reseller_price_cents": int(cents),
                  "updated_at": svc.now_utc()}})


async def set_override(db, reseller_oid, plan_id, cents: Optional[int]):
    """cents=None removes the override (back to global)."""
    pid = str(plan_id)
    r = await db.resellers.find_one({"_id": reseller_oid})
    ov = dict(r.get("price_overrides") or {})
    if cents is None:
        ov.pop(pid, None)
    else:
        ov[pid] = int(cents)
    await db.resellers.update_one({"_id": reseller_oid},
        {"$set": {"price_overrides": ov, "updated_at": svc.now_utc()}})


# ---------------- wallet ledger ----------------

async def _txn(db, reseller_tid: int, ttype: str, amount_cents: int,
               balance_after: int, note: str = "", ref: str = "",
               admin_id=None):
    await db.wallet_txns.insert_one({
        "txn_id": f"TXN{ObjectId()}",
        "telegram_id": reseller_tid,
        "type": ttype,
        "amount_cents": int(amount_cents),
        "balance_after_cents": int(balance_after),
        "note": note, "ref": ref,
        "admin_id": admin_id,
        "created_at": svc.now_utc(),
    })


async def wallet_credit(db, reseller: Dict, cents: int, ttype: str,
                        note: str = "", ref: str = "", admin_id=None,
                        enforce_min: bool = False) -> Optional[int]:
    """Atomically credit wallet + ledger. Returns new balance or None if
    min-recharge rule blocks it."""
    rs = await rsettings(db)
    if enforce_min and rs.get("reseller_min_enabled") and \
            rs.get("reseller_min_scope") == "all" and \
            cents < int(rs.get("reseller_min_cents", 0)):
        return None
    tid = reseller["telegram_id"]
    res = await db.resellers.find_one_and_update(
        {"_id": reseller["_id"]},
        {"$inc": {"balance_cents": int(cents)},
         "$set": {"updated_at": svc.now_utc()}})
    new_bal = int((res or {}).get("balance_cents", 0))
    await _txn(db, tid, ttype, cents, new_bal, note, ref, admin_id)
    return new_bal


async def wallet_debit(db, reseller: Dict, cents: int, ttype: str,
                       note: str = "", ref: str = "") -> Optional[int]:
    """Atomic debit - fails (returns None) if balance < cents or would go
    negative (unless admin enabled negative balances)."""
    cents = int(cents)
    rs = await rsettings(db)
    allow_neg = bool(rs.get("reseller_allow_negative"))
    flt = {"_id": reseller["_id"]}
    if not allow_neg:
        flt["balance_cents"] = {"$gte": cents}
    res = await db.resellers.find_one_and_update(
        flt, {"$inc": {"balance_cents": -cents},
              "$set": {"updated_at": svc.now_utc()}})
    if not res:
        return None
    new_bal = int(res.get("balance_cents", 0))
    await _txn(db, reseller["telegram_id"], ttype, -cents, new_bal, note, ref)
    return new_bal


async def wallet_adjust(db, reseller: Dict, cents: int, ttype: str,
                        note: str, admin_id) -> Optional[int]:
    """Admin credit(+)/debit(-). Returns new balance or None if debit
    would exceed balance (and negatives disabled)."""
    if cents >= 0:
        return await wallet_credit(db, reseller, cents, ttype, note,
                                   admin_id=admin_id, enforce_min=False)
    return await wallet_debit(db, reseller, -cents, ttype, note)


# ---------------- redeem codes ----------------

def _gen_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "R-" + "".join(secrets.choice(alphabet) for _ in range(10))


async def gen_codes(db, cents: int, count: int, expires_at=None,
                    note: str = "") -> list:
    """Generate unique unused codes. Returns list of code strings."""
    out = []
    existing = {d.get("code") for d in
                await db.redeem_codes.find({}).to_list(5000)}
    while len(out) < count:
        c = _gen_code()
        if c in existing:
            continue
        existing.add(c)
        await db.redeem_codes.insert_one({
            "code": c, "amount_cents": int(cents),
            "status": "unused",
            "expires_at": expires_at,
            "created_at": svc.now_utc(), "note": note,
        })
        out.append(c)
    return out


async def redeem_code(db, reseller: Dict, code: str):
    """Atomic redeem. Returns (ok, message, new_balance)."""
    rs = await rsettings(db)
    if not rs.get("reseller_codes_enabled"):
        return False, "🔒 Redeem codes are currently disabled.", None
    code = (code or "").strip().upper()
    doc = await db.redeem_codes.find_one({"code": code})
    if not doc:
        return False, "❌ Invalid redeem code.", None
    if doc.get("status") == "redeemed":
        return False, "❌ This code was already redeemed.", None
    if doc.get("status") == "revoked":
        return False, "❌ This code has been revoked.", None
    exp = doc.get("expires_at")
    if exp and exp < svc.now_utc():
        return False, "❌ This code has expired.", None
    # atomic claim: only succeeds if still 'unused'
    res = await db.redeem_codes.find_one_and_update(
        {"_id": doc["_id"], "status": "unused"},
        {"$set": {"status": "redeemed",
                  "redeemed_by": reseller["telegram_id"],
                  "redeemed_at": svc.now_utc()}})
    if not res:
        return False, "❌ This code was already redeemed.", None
    # min recharge rule on codes
    cents = int(doc.get("amount_cents", 0))
    if rs.get("reseller_min_enabled") and rs.get("reseller_min_scope") == "all" \
            and cents < int(rs.get("reseller_min_cents", 0)):
        # refund the claim - code goes back to unused
        await db.redeem_codes.update_one({"_id": doc["_id"]},
            {"$set": {"status": "unused"},
             "$unset": {"redeemed_by": "", "redeemed_at": ""}})
        return False, (f"❌ This code (${usdt_fmt(cents)}) is below the "
                       f"minimum recharge of {usdt_fmt(rs.get('reseller_min_cents'))}."), None
    bal = await wallet_credit(db, reseller, cents, "redeem",
                              note=f"Code {code}", ref=code)
    return True, f"✅ Code redeemed! Credited {usdt_fmt(cents)}.", bal


# ---------------- reseller purchase ----------------

async def reseller_buy(db, reseller: Dict, product: Dict, plan: Dict,
                       price_cents: int):
    """Atomic-ish purchase: allocate key -> debit wallet -> order+txn.
    Returns (ok, order_or_err, key_or_none, new_balance).
    Caller must hold a per-user lock for full safety."""
    rs = await rsettings(db)
    if not rs.get("reseller_purchases_enabled"):
        return False, "🔒 Reseller purchases are currently disabled.", None, None
    if reseller.get("status") != "active":
        return False, "🚫 Your reseller account is not active.", None, None

    # 1. stock check
    if await svc.stock_for_plan(db, plan["_id"]) <= 0:
        return False, "🔴 Out of stock for this plan.", None, None

    # 2. allocate key atomically (shared inventory with customer shop)
    key = await svc.allocate_key(db, plan["_id"])
    if not key:
        return False, "🔴 Out of stock for this plan.", None, None

    # 3. debit wallet atomically (fails -> release key)
    bal = await wallet_debit(db, reseller, price_cents, "purchase",
                             note=f"{product.get('name','')} - {plan.get('name','')}")
    if bal is None:
        await svc.release_order_key(db, {"key_id": key["_id"]})
        return False, "💸 Insufficient wallet balance.", None, None

    # 4. order record (USDT price, no INR 'amount' so revenue stats unaffected)
    order_id = await svc.next_order_id(db)
    order = {
        "order_id": order_id,
        "telegram_id": reseller["telegram_id"],
        "product_id": product["_id"], "plan_id": plan["_id"],
        "product_name": product.get("name", ""),
        "plan_name": plan.get("name", ""),
        "key_id": key["_id"], "key_value": key.get("key_value"),
        "status": "paid", "source": "reseller",
        "price_usdt_cents": int(price_cents),
        "created_at": svc.now_utc(), "updated_at": svc.now_utc(),
        "paid_at": svc.now_utc(),
    }
    order["_id"] = ObjectId()
    await db.orders.insert_one(order)
    return True, order, key, bal
