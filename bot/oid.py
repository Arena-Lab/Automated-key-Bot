"""Minimal ObjectId-compatible ID generator.
Replaces bson.ObjectId now that pymongo is removed.
IDs are plain strings - any format is accepted on lookup."""

import time
import secrets


def _gen() -> str:
    # 8 bytes timestamp + 12 bytes random, hex -> 24 chars (ObjectId layout)
    return f"{int(time.time()):08x}{secrets.token_hex(12)}"


def ObjectId(oid=None):
    """Drop-in replacement for bson.ObjectId in this codebase:
    - ObjectId()        -> new unique 24-hex id (str)
    - ObjectId(value)   -> the id as a plain string (any format accepted)
    Stored _id values are plain strings, so equality just works."""
    if oid is None:
        return _gen()
    return str(oid)
