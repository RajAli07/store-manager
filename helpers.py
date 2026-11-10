import math
import re
import json
import uuid
from datetime import datetime

from bson import ObjectId
from bson.json_util import dumps, loads


def inr(value):
    """12345.5 -> ₹12,345.50 (safe for None / text)"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"₹{value:,.0f}" if value == int(value) else f"₹{value:,.2f}"


def fmt_dt(value):
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %I:%M %p")
    return value if value else "-"


def pretty_json(doc):
    """Poora document readable JSON mein (ObjectId, date sab handle)."""
    return dumps(doc, indent=2, ensure_ascii=False)


def parse_json(text):
    """Edit form se aaya JSON text wapas Python object mein."""
    return loads(text)


def regex_filter(text):
    """User ka search text safe regex mein."""
    return {"$regex": re.escape(text), "$options": "i"}


def find_by_id(coll, doc_id):
    """_id string ho ya ObjectId, dono try karta hai."""
    doc = coll.find_one({"_id": doc_id})
    if doc is None and ObjectId.is_valid(doc_id):
        doc = coll.find_one({"_id": ObjectId(doc_id)})
    return doc


def id_query(coll, doc_id):
    """update/delete ke liye sahi _id wala filter."""
    if coll.count_documents({"_id": doc_id}, limit=1):
        return {"_id": doc_id}
    if ObjectId.is_valid(doc_id):
        return {"_id": ObjectId(doc_id)}
    return {"_id": doc_id}


def paginate(coll, query, sort, page, per_page):
    total = coll.count_documents(query)
    pages = max(1, math.ceil(total / per_page))
    page = min(max(page, 1), pages)
    cursor = coll.find(query).sort(sort).skip((page - 1) * per_page).limit(per_page)
    return {
        "items": list(cursor),
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "start": (page - 1) * per_page + 1 if total else 0,
        "end": min(page * per_page, total),
    }
def dig(doc, path, default=None):
    """dig(p, 'inventory.total_stock', 0) -> field na ho to default, crash nahi."""
    cur = doc
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur

STATUS_CLASS = {
    "Delivered": "ok",
    "Shipped": "warn",
    "Processing": "warn",
    "Cancelled": "bad",
    "Returned": "bad",
}


def status_class(status):
    return STATUS_CLASS.get(status, "")


def tidy(n):
    """5.0 -> 5, 5.456 -> 5.46"""
    if n is None:
        return 0
    n = float(n)
    return int(n) if n.is_integer() else round(n, 2)


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def unflatten(flat):
    """{'pricing.mrp': 5} -> {'pricing': {'mrp': 5}}"""
    out = {}
    for key, val in flat.items():
        parts = key.split(".")
        d = out
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = val
    return out


class FormReader:
    """Form se text / number / JSON list nikalta hai aur errors jama karta hai."""

    def __init__(self, form):
        self.form = form
        self.errors = []

    def text(self, name):
        return self.form.get(name, "").strip()

    def number(self, name, label=None, cast=float):
        raw = self.text(name)
        if raw == "":
            return None
        try:
            return cast(raw)
        except ValueError:
            self.errors.append(f"{label or name} ek number hona chahiye.")
            return None

    def json_list(self, name, label=None):
        label = label or name
        raw = self.text(name)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            self.errors.append(f"{label}: JSON galat hai ({e.msg}, line {e.lineno}).")
            return []
        if not isinstance(data, list):
            self.errors.append(f"{label}: list hona chahiye, jaise [ {{...}} ].")
            return []
        return data