"""Centralized SQLite storage engine.

Exposes a motor/pymongo-compatible async API over per-collection tables:
    db.users.find_one({...})
    db.orders.insert_one(doc) -> result.inserted_id
    db.keys.find_one_and_update(...)

Features: in-memory cache, per-collection asyncio locks, atomic SQLite
writes (single transaction per collection save), 6-hourly JSON backups.
"""

import asyncio
import copy
import json
import logging
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "store.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups", "automatic")
BACKUP_INTERVAL = 6 * 3600          # 6 hours
BACKUP_KEEP = 30                    # retention

COLLECTIONS = [
    "users", "products", "plans", "keys", "orders", "payments",
    "settings", "resellers", "admin_logs", "tutorial", "counters",
    "broadcasts", "payverify_logs", "wallet_txns", "redeem_codes",
]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ser(v):
    if isinstance(v, datetime):
        return {"__dt__": v.isoformat()}
    if isinstance(v, dict):
        return {k: _ser(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_ser(x) for x in v]
    return v


def _des(v):
    if isinstance(v, dict):
        if set(v.keys()) == {"__dt__"}:
            return datetime.fromisoformat(v["__dt__"])
        return {k: _des(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_des(x) for x in v]
    return v


def _get_path(doc: Dict, dotted: str):
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _set_path(doc: Dict, dotted: str, value, create=True):
    parts = dotted.split(".")
    cur = doc
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            if not create:
                return
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _match(doc: Dict, flt: Dict) -> bool:
    if not flt:
        return True
    for key, cond in flt.items():
        exists, val = _get_path(doc, key)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, operand in cond.items():
                if op == "$ne":
                    if exists and val == operand:
                        return False
                elif op == "$gt":
                    if not (exists and val is not None and val > operand):
                        return False
                elif op == "$gte":
                    if not (exists and val is not None and val >= operand):
                        return False
                elif op == "$lt":
                    if not (exists and val is not None and val < operand):
                        return False
                elif op == "$lte":
                    if not (exists and val is not None and val <= operand):
                        return False
                elif op == "$in":
                    if not (exists and val in operand):
                        return False
                elif op == "$exists":
                    if exists != bool(operand):
                        return False
                elif op == "$regex":
                    if not exists or val is None:
                        return False
                    flags = re.IGNORECASE if cond.get("$options") == "i" else 0
                    if not re.search(str(operand), str(val), flags):
                        return False
                else:
                    return False
        else:
            if not exists or val != cond:
                return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key: str, direction: int = 1):
        self._docs.sort(
            key=lambda d: (d.get(key) is None, d.get(key)),
            reverse=(direction < 0),
        )
        return self

    def limit(self, n: int):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: Optional[int] = None):
        docs = self._docs if length is None else self._docs[:length]
        return [copy.deepcopy(d) for d in docs]

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._docs:
            raise StopAsyncIteration
        return copy.deepcopy(self._docs.pop(0))


class _Result:
    def __init__(self, inserted_id=None, modified=0, deleted=0, upserted=None):
        self.inserted_id = inserted_id
        self.modified_count = modified
        self.deleted_count = deleted
        self.upserted_id = upserted


class Collection:
    def __init__(self, store: "Store", name: str):
        self.store = store
        self.name = name

    @property
    def _data(self) -> Dict:
        return self.store.data[self.name]

    # ---------- reads ----------

    async def find_one(self, flt=None, projection=None):
        flt = flt or {}
        for doc in self._data.values():
            if _match(doc, flt):
                d = copy.deepcopy(doc)
                return self._project(d, projection)
        return None

    def find(self, flt=None, projection=None):
        flt = flt or {}
        docs = [copy.deepcopy(d) for d in self._data.values() if _match(d, flt)]
        return _Cursor(docs)

    async def count_documents(self, flt=None):
        flt = flt or {}
        return sum(1 for d in self._data.values() if _match(d, flt))

    async def find_one_and_update(self, flt, update, upsert=False,
                                  return_document=None):
        async with self.store.lock_for(self.name):
            for doc in self._data.values():
                if _match(doc, flt):
                    self._apply_update(doc, update)
                    await self.store._save(self.name)
                    return copy.deepcopy(doc)
            if upsert:
                new_doc = self._build_upsert(flt, update)
                self._data[new_doc["_id"]] = new_doc
                await self.store._save(self.name)
                return copy.deepcopy(new_doc)
            return None

    # ---------- writes ----------

    async def insert_one(self, doc):
        async with self.store.lock_for(self.name):
            doc = copy.deepcopy(doc)
            if "_id" not in doc or doc["_id"] is None:
                from bot.oid import ObjectId
                doc["_id"] = ObjectId()
            self._data[str(doc["_id"])] = doc
            await self.store._save(self.name)
            r = _Result(inserted_id=doc["_id"])
            return r

    async def insert_many(self, docs):
        async with self.store.lock_for(self.name):
            ids = []
            from bot.oid import ObjectId
            for doc in docs:
                doc = copy.deepcopy(doc)
                if "_id" not in doc or doc["_id"] is None:
                    doc["_id"] = ObjectId()
                self._data[str(doc["_id"])] = doc
                ids.append(doc["_id"])
            await self.store._save(self.name)
            return _Result()

    async def update_one(self, flt, update, upsert=False):
        async with self.store.lock_for(self.name):
            for doc in self._data.values():
                if _match(doc, flt):
                    before = copy.deepcopy(doc)
                    self._apply_update(doc, update)
                    if doc != before:
                        await self.store._save(self.name)
                        return _Result(modified=1)
                    return _Result(modified=0)
            if upsert:
                new_doc = self._build_upsert(flt, update)
                self._data[str(new_doc["_id"])] = new_doc
                await self.store._save(self.name)
                return _Result(modified=0, upserted=new_doc["_id"])
            return _Result(modified=0)

    async def update_many(self, flt, update):
        async with self.store.lock_for(self.name):
            n = 0
            for doc in self._data.values():
                if _match(doc, flt):
                    before = copy.deepcopy(doc)
                    self._apply_update(doc, update)
                    if doc != before:
                        n += 1
            if n:
                await self.store._save(self.name)
            return _Result(modified=n)

    async def delete_one(self, flt):
        async with self.store.lock_for(self.name):
            for key, doc in list(self._data.items()):
                if _match(doc, flt):
                    del self._data[key]
                    await self.store._save(self.name)
                    return _Result(deleted=1)
            return _Result(deleted=0)

    async def delete_many(self, flt):
        async with self.store.lock_for(self.name):
            keys = [k for k, d in self._data.items() if _match(d, flt)]
            for k in keys:
                del self._data[k]
            if keys:
                await self.store._save(self.name)
            return _Result(deleted=len(keys))

    async def replace_one(self, flt, doc, upsert=False):
        async with self.store.lock_for(self.name):
            for key, old in self._data.items():
                if _match(old, flt):
                    doc = copy.deepcopy(doc)
                    doc["_id"] = old["_id"]
                    self._data[key] = doc
                    await self.store._save(self.name)
                    return _Result(modified=1)
            if upsert:
                doc = copy.deepcopy(doc)
                from bot.oid import ObjectId
                doc.setdefault("_id", ObjectId())
                self._data[str(doc["_id"])] = doc
                await self.store._save(self.name)
            return _Result(modified=0)

    def aggregate(self, pipeline):
        """Minimal pipeline support: $match + $group($sum) only."""
        docs = [copy.deepcopy(d) for d in self._data.values()]
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if _match(d, stage["$match"])]
            elif "$group" in stage:
                g = stage["$group"]
                key = g.get("_id")
                acc = g.get("total") or g.get("t")
                if acc and "$sum" in acc:
                    field = acc["$sum"].lstrip("$")
                    total = sum(float(d.get(field) or 0) for d in docs)
                    docs = [{"_id": None, "total": total, "t": total}]
                else:
                    docs = [{"_id": None}]
            elif "$sort" in stage:
                for k, v in stage["$sort"].items():
                    docs.sort(key=lambda d: d.get(k) or 0, reverse=(v < 0))
            elif "$limit" in stage:
                docs = docs[: stage["$limit"]]
        return _Cursor(docs)

    # ---------- internals ----------

    @staticmethod
    def _project(doc, projection):
        if not projection:
            return doc
        include = any(v for k, v in projection.items() if k != "_id" and v)
        if include:
            return {k: v for k, v in doc.items()
                    if projection.get(k) or (k == "_id" and projection.get("_id", 1))}
        return {k: v for k, v in doc.items() if k not in projection or projection[k] == 0}

    @staticmethod
    def _apply_update(doc, update):
        for op, fields in update.items():
            if op == "$set":
                for k, v in fields.items():
                    _set_path(doc, k, _des(copy.deepcopy(v)))
            elif op == "$setOnInsert":
                pass  # handled at insert time only
            elif op == "$inc":
                for k, v in fields.items():
                    exists, cur = _get_path(doc, k)
                    _set_path(doc, k, (cur or 0) + v)
            elif op == "$push":
                for k, v in fields.items():
                    exists, cur = _get_path(doc, k)
                    if not isinstance(cur, list):
                        cur = []
                        _set_path(doc, k, cur)
                    cur.append(_des(copy.deepcopy(v)))
            elif op == "$unset":
                for k in fields:
                    parts = k.split(".")
                    cur = doc
                    for p in parts[:-1]:
                        cur = cur.get(p, {}) if isinstance(cur, dict) else {}
                    if isinstance(cur, dict):
                        cur.pop(parts[-1], None)

    def _build_upsert(self, flt, update):
        from bot.oid import ObjectId
        doc = {"_id": ObjectId(), "created_at": _now()}
        for k, v in (flt or {}).items():
            if not k.startswith("$") and not isinstance(v, dict):
                _set_path(doc, k, v)
        for op in ("$set", "$setOnInsert"):
            for k, v in (update.get(op) or {}).items():
                _set_path(doc, k, _des(copy.deepcopy(v)))
        for k, v in (update.get("$inc") or {}).items():
            _set_path(doc, k, v)
        return doc


class Store:
    """In-memory mirror of all JSON collections with durable writes."""

    def __init__(self):
        self.data: Dict[str, Dict] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._write_lock = asyncio.Lock()
        self._meta_lock = asyncio.Lock()

    # attributes for each collection
    def __init_subclass__(cls):
        pass

    def __getattr__(self, name):
        # db.users -> Collection; any name allowed (created on demand)
        if name.startswith("_"):
            raise AttributeError(name)
        coll = Collection(self, name)
        object.__setattr__(self, name, coll)
        return coll

    def lock_for(self, name: str) -> asyncio.Lock:
        if name not in self._locks:
            self._locks[name] = asyncio.Lock()
        return self._locks[name]

    # ---------- lifecycle ----------

    async def init(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        self._conn = await asyncio.to_thread(self._connect)
        for name in COLLECTIONS:
            self.data[name] = {}
            self._locks[name] = asyncio.Lock()
            await asyncio.to_thread(self._load_collection, name)

    def _connect(self):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS docs ("
            "collection TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, "
            "PRIMARY KEY (collection, id))"
        )
        conn.commit()
        return conn

    def _load_collection(self, name):
        rows = self._conn.execute(
            "SELECT id, data FROM docs WHERE collection = ?", (name,)
        ).fetchall()
        for _id, blob in rows:
            try:
                self.data[name][_id] = _des(json.loads(blob))
            except Exception as e:
                logger.error("Bad row in %s/%s: %s", name, _id, e)

    # ---------- writes ----------

    async def _save(self, name: str):
        """Atomic write: serialize collection -> single SQLite transaction."""
        async with self._write_lock:
            payload = [(k, json.dumps(_ser(v), ensure_ascii=False))
                       for k, v in self.data[name].items()]
            try:
                def _write():
                    with self._conn:
                        self._conn.execute(
                            "DELETE FROM docs WHERE collection = ?", (name,))
                        self._conn.executemany(
                            "INSERT INTO docs (collection, id, data) VALUES (?,?,?)",
                            [(name, k, d) for k, d in payload])
                await asyncio.to_thread(_write)
            except Exception as e:
                logger.error("Failed to save %s: %s", name, e)

    # ---------- backups ----------

    async def backup_now(self, tag: str = "snapshot") -> Optional[str]:
        """Snapshot all collections to backups/automatic/<ts>_<tag>/"""
        stamp = _now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(BACKUP_DIR, f"{stamp}_{tag}")
        os.makedirs(dest, exist_ok=True)

        def _snap():
            for name in self.data:
                payload = {k: _ser(v) for k, v in self.data[name].items()}
                with open(os.path.join(dest, f"{name}.json"), "w",
                          encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
        await asyncio.to_thread(_snap)
        self._prune_backups()
        return dest

    def _prune_backups(self):
        try:
            snaps = sorted(
                (d for d in os.listdir(BACKUP_DIR)
                 if os.path.isdir(os.path.join(BACKUP_DIR, d))),
                reverse=True)
            for old in snaps[BACKUP_KEEP:]:
                shutil.rmtree(os.path.join(BACKUP_DIR, old), ignore_errors=True)
        except Exception:
            pass

    async def backup_loop(self):
        while True:
            await asyncio.sleep(BACKUP_INTERVAL)
            try:
                await self.backup_now("auto")
                logger.info("Automatic backup completed")
            except Exception as e:
                logger.error("Backup failed: %s", e)

    async def close(self):
        if getattr(self, "_conn", None):
            await asyncio.to_thread(self._conn.close)
            self._conn = None


# ---------- compat shim: drop-in for old Database.get_db() ----------

_store_instance: Optional[Store] = None


async def init_store() -> Store:
    global _store_instance
    _store_instance = Store()
    await _store_instance.init()
    return _store_instance


def get_store() -> Store:
    if _store_instance is None:
        raise RuntimeError("Store not initialized")
    return _store_instance


class Database:
    """Compatibility facade - handlers keep calling Database.get_db()."""

    @classmethod
    def get_db(cls):
        return get_store()

    @classmethod
    async def connect(cls):
        await init_store()

    @classmethod
    async def ensure_indexes(cls):
        pass

    @classmethod
    async def close(cls):
        pass
