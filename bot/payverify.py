"""Auto payment verification via Gmail IMAP.

Vendored & adapted from https://github.com/MatrixRobots/Fampay-payment-gateway
(payment_template package). MongoDB repository, QR generation and env-coupled
config were removed — this bot uses its own SQLite store and QR images.

How it works:
  1. Each order gets a unique purpose note (e.g. ``KS-20261113-AB12CD``)
     embedded in the UPI ``tn=`` parameter of the payment URI / QR.
  2. When the customer pays, FamApp/bank sends a credit-alert email to the
     configured Gmail inbox.
  3. ``GmailService`` polls that inbox over IMAP-SSL, parses incoming payment
     emails, and matches on purpose-note + amount (fallback: amount-only within
     a 10-minute window for UPI apps that strip the note).
  4. ``find_matching_payments`` returns GmailMessage matches; the caller is
     responsible for persisting verification logs (message-id dedup) and
     approving the order.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import os
import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email import policy
from email.message import Message
from email.utils import parsedate_to_datetime


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PayVerifyConfig:
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_username: str = ""
    imap_app_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_sender_filter: str = "no-reply@famapp.in"
    default_upi_id: str = ""
    payee_name: str = "Key Shop"
    purpose_prefix: str = "KS"
    lookback_hours: int = 12
    order_expiry_minutes: int = 30
    poll_interval_seconds: int = 25

    @classmethod
    def from_env(cls) -> "PayVerifyConfig":
        return cls(
            imap_host=os.getenv("IMAP_HOST", "imap.gmail.com").strip() or "imap.gmail.com",
            imap_port=int(os.getenv("IMAP_PORT", "993") or 993),
            imap_username=os.getenv("IMAP_USERNAME", "").strip(),
            imap_app_password=os.getenv("IMAP_APP_PASSWORD", "").strip(),
            imap_mailbox=os.getenv("IMAP_MAILBOX", "INBOX").strip() or "INBOX",
            imap_sender_filter=os.getenv(
                "IMAP_SENDER_FILTER", "no-reply@famapp.in").strip() or "no-reply@famapp.in",
            default_upi_id=os.getenv("DEFAULT_UPI_ID", "").strip(),
            payee_name=os.getenv("PAYEE_NAME", "Key Shop").strip() or "Key Shop",
            purpose_prefix=(os.getenv("PURPOSE_PREFIX", "KS").strip().upper() or "KS"),
            lookback_hours=int(os.getenv("GMAIL_LOOKBACK_HOURS", "12") or 12),
            order_expiry_minutes=int(os.getenv("PAYMENT_EXPIRY_MINUTES", "30") or 30),
            poll_interval_seconds=int(os.getenv("PAYVERIFY_POLL_SECONDS", "25") or 25),
        )

    @property
    def configured(self) -> bool:
        return bool(self.imap_username and self.imap_app_password and self.default_upi_id)


# ---------------------------------------------------------------------------
# Small helpers (from upstream utils.py / purpose.py)
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_amount(value) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("amount must be a valid number.") from exc
    if amount <= 0:
        raise ValueError("amount must be greater than zero.")
    return amount


def format_amount(amount: Decimal) -> str:
    text = format(amount.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def generate_purpose(prefix: str) -> str:
    cleaned = "".join(ch for ch in prefix.upper() if ch.isalnum()) or "KS"
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits)
                     for _ in range(6))
    return f"{cleaned}-{utcnow().strftime('%Y%m%d')}-{suffix}"


def build_upi_uri(upi_id: str, payee_name: str, amount: Decimal, purpose: str) -> str:
    from urllib.parse import quote
    return (
        f"upi://pay?pa={quote(upi_id)}&pn={quote(payee_name)}"
        f"&am={format_amount(amount)}&cu=INR&tn={quote(purpose)}"
    )


# ---------------------------------------------------------------------------
# Gmail / IMAP parsing (from upstream gmail.py)
# ---------------------------------------------------------------------------

INCOMING_SUBJECT_RE = re.compile(r"you received ₹.* in your ", re.IGNORECASE)
INCOMING_BODY_RE = re.compile(r"you have successfully received", re.IGNORECASE)
OUTGOING_SUBJECT_RE = re.compile(r"your payment of ₹.* is successful", re.IGNORECASE)
OUTGOING_BODY_RE = re.compile(r"you have successfully paid", re.IGNORECASE)
AMOUNT_RE = re.compile(r"₹\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
UTR_RE = re.compile(
    r"(?:utr|transaction\s*(?:id|ref(?:erence)?)|txn\s*(?:id|ref)|"
    r"bank\s*ref(?:erence)?|ref\s*(?:no\.?|number|id))"
    r"[^\d]{0,25}(\d{9,18})", re.IGNORECASE)


class GmailError(Exception):
    pass


@dataclass(slots=True)
class GmailMessage:
    message_id: str
    subject: str
    body: str
    timestamp: datetime
    purpose: str | None
    amount: Decimal | None
    utr: str | None = None

    @property
    def is_incoming_payment(self) -> bool:
        subject = self.subject.strip()
        body = self.body.strip()
        if OUTGOING_SUBJECT_RE.search(subject) or OUTGOING_BODY_RE.search(body):
            return False
        if not INCOMING_SUBJECT_RE.search(subject):
            return False
        if not INCOMING_BODY_RE.search(body):
            return False
        return self.purpose is not None


class GmailService:
    """Lightweight Gmail-over-IMAP payment email matcher (stdlib only)."""

    def __init__(self, config: PayVerifyConfig) -> None:
        self._config = config
        prefix = re.escape((config.purpose_prefix or "KS").upper())
        # purpose format: PREFIX-YYYYMMDD-XXXXXX  (8+6 alnum)
        self._purpose_re = re.compile(rf"\b{prefix}-[A-Z0-9]{{8}}-[A-Z0-9]{{6}}\b")

    # -- connection ---------------------------------------------------------

    def _connect(self) -> imaplib.IMAP4_SSL:
        try:
            client = imaplib.IMAP4_SSL(self._config.imap_host, self._config.imap_port)
        except Exception as exc:
            raise GmailError(
                f"Cannot connect to IMAP {self._config.imap_host}:{self._config.imap_port}"
            ) from exc
        try:
            status, _ = client.login(
                self._config.imap_username, self._config.imap_app_password)
        except imaplib.IMAP4.error as exc:
            raise GmailError("Gmail IMAP login failed — check IMAP_USERNAME / IMAP_APP_PASSWORD.") from exc
        if status != "OK":
            raise GmailError("IMAP login failed.")
        return client

    # -- parsing ------------------------------------------------------------

    @staticmethod
    def _decode_bytes(value: bytes | None) -> str:
        if not value:
            return ""
        return value.decode("utf-8", errors="replace")

    @staticmethod
    def _extract_text(message: Message) -> str:
        if message.is_multipart():
            parts = []
            for part in message.walk():
                if part.get_content_disposition() == "attachment":
                    continue
                if not part.get_content_type().startswith("text/"):
                    continue
                try:
                    text = part.get_content()
                except Exception:
                    text = GmailService._decode_bytes(part.get_payload(decode=True))
                if text:
                    parts.append(str(text))
            return "\n".join(parts)
        try:
            content = message.get_content()
        except Exception:
            content = GmailService._decode_bytes(message.get_payload(decode=True))
        return str(content) if content is not None else ""

    @staticmethod
    def _parse_amount(text: str) -> Decimal | None:
        match = AMOUNT_RE.search(text)
        if not match:
            return None
        try:
            return Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _parse_timestamp(message: Message) -> datetime:
        date_header = message.get("Date")
        if date_header:
            try:
                ts = parsedate_to_datetime(date_header)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts.astimezone(timezone.utc)
            except Exception:
                pass
        return utcnow()

    def _parse_message(self, raw: bytes, seq_id: str) -> GmailMessage:
        message = email.message_from_bytes(raw, policy=policy.default)
        subject = str(message.get("Subject", ""))
        body = self._extract_text(message)
        combined = f"{subject}\n{body}"
        purpose_match = self._purpose_re.search(combined)
        utr_match = UTR_RE.search(combined)
        # stable dedup id: RFC Message-ID header (seq numbers shift between
        # sessions and would cause false dedup hits)
        msg_id = (message.get("Message-ID") or "").strip() or seq_id
        return GmailMessage(
            message_id=msg_id,
            subject=subject,
            body=body,
            timestamp=self._parse_timestamp(message),
            purpose=purpose_match.group(0) if purpose_match else None,
            amount=self._parse_amount(combined),
            utr=utr_match.group(1) if utr_match else None,
        )

    # -- mailbox scan ---------------------------------------------------------

    def search_incoming_payments(self, *, lookback_hours: int,
                                 max_results: int = 25) -> list[GmailMessage]:
        cutoff = utcnow() - timedelta(hours=lookback_hours)
        since_date = cutoff.astimezone(timezone.utc).date().strftime("%d-%b-%Y")

        client = self._connect()
        try:
            status, _ = client.select(self._config.imap_mailbox)
            if status != "OK":
                raise GmailError(f"Cannot select mailbox '{self._config.imap_mailbox}'.")
            status, data = client.search(
                None, "FROM", self._config.imap_sender_filter, "SINCE", since_date)
            if status != "OK":
                raise GmailError("Unable to query Gmail IMAP.")

            parsed: list[GmailMessage] = []
            for msg_id in (data[0].split() if data and data[0] else []):
                try:
                    status, fetched = client.fetch(msg_id, "(RFC822)")
                except imaplib.IMAP4.error:
                    continue
                if status != "OK":
                    continue
                raw = next((p[1] for p in fetched
                            if isinstance(p, tuple) and len(p) >= 2), None)
                if not raw:
                    continue
                try:
                    parsed.append(self._parse_message(raw, msg_id.decode("ascii", "ignore")))
                except Exception:
                    continue
            parsed.sort(key=lambda m: m.timestamp, reverse=True)
            return parsed[:max_results]
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                client.logout()
            except Exception:
                pass

    def match_messages(
        self, messages: list[GmailMessage], *, order_created_at: datetime,
        expected_purpose: str, expected_amount: Decimal,
    ) -> GmailMessage | None:
        """Match pre-fetched messages against one order (no IMAP I/O)."""
        cutoff = utcnow() - timedelta(hours=self._config.lookback_hours)
        created = ensure_utc(order_created_at)
        fallback_cutoff = created + timedelta(minutes=10)

        for m in messages:
            if m.timestamp < cutoff or m.timestamp < created:
                continue
            if not m.is_incoming_payment:
                continue
            if m.purpose != expected_purpose or m.amount != expected_amount:
                continue
            return m

        for m in messages:
            if m.timestamp < created or m.timestamp > fallback_cutoff:
                continue
            if m.purpose:
                continue
            if OUTGOING_SUBJECT_RE.search(m.subject) or OUTGOING_BODY_RE.search(m.body):
                continue
            if not INCOMING_SUBJECT_RE.search(m.subject) \
                    or not INCOMING_BODY_RE.search(m.body):
                continue
            if m.amount != expected_amount:
                continue
            return m

        return None


# ---------------------------------------------------------------------------
# Async wrapper — imaplib is blocking, always call via asyncio.to_thread
# ---------------------------------------------------------------------------

async def find_matching_payments(config: PayVerifyConfig, candidates) -> dict:
    """Batch match: ONE mailbox scan for many orders.

    candidates: iterable of (key, order_created_at, expected_purpose,
    expected_amount). Returns {key: GmailMessage}. A Gmail message can only
    be claimed by one candidate per call (first match wins)."""
    svc = GmailService(config)
    messages = await asyncio.to_thread(
        svc.search_incoming_payments, lookback_hours=config.lookback_hours)
    out: dict = {}
    claimed: set = set()
    for key, created, purpose, amount in candidates:
        msg = svc.match_messages(
            messages, order_created_at=created, expected_purpose=purpose,
            expected_amount=parse_amount(amount))
        if msg and msg.message_id not in claimed:
            claimed.add(msg.message_id)
            out[key] = msg
    return out
