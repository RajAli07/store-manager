import time
from datetime import datetime

from db import get_db

CACHE_SECONDS = 60
_cache = {"at": 0, "data": None}

DONE = {"$nin": ["Cancelled", "Returned"]}
STOCK = {"$ifNull": ["$inventory.total_stock", 0]}
VALUE = {"$multiply": [{"$ifNull": ["$pricing.selling_price", 0]}, STOCK]}


def _pct(rows, key):
    top = max((r[key] for r in rows), default=0) or 1
    for r in rows:
        r["pct"] = round(r[key] / top * 100)
    return rows


def _first(cursor, default):
    rows = list(cursor)
    return rows[0] if rows else default


def _count_by(coll, field, limit=None):
    pipeline = [{"$group": {"_id": field, "count": {"$sum": 1}}}, {"$sort": {"count": -1}}]
    if limit:
        pipeline.append({"$limit": limit})
    rows = [{"name": r["_id"] or "Unknown", "count": r["count"]} for r in coll.aggregate(pipeline)]
    return _pct(rows, "count")


def compute():
    db = get_db()
    orders, products, contacts = db["orders"], db["products"], db["contacts"]

    totals = _first(orders.aggregate([
        {"$match": {"status": DONE}},
        {"$group": {"_id": None, "revenue": {"$sum": "$billing.grand_total"}, "count": {"$sum": 1}}},
    ]), {"revenue": 0, "count": 0})

    unpaid = _first(orders.aggregate([
        {"$match": {"status": DONE, "payment.is_paid": False}},
        {"$group": {"_id": None, "amount": {"$sum": "$billing.grand_total"}, "count": {"$sum": 1}}},
    ]), {"amount": 0, "count": 0})

    months = list(orders.aggregate([
        {"$match": {"status": DONE, "order_date": {"$type": "date"}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m", "date": "$order_date"}},
            "revenue": {"$sum": "$billing.grand_total"},
            "orders": {"$sum": 1},
        }},
        {"$sort": {"_id": -1}},
        {"$limit": 12},
    ]))
    months.reverse()
    for m in months:
        m["label"] = datetime.strptime(m["_id"], "%Y-%m").strftime("%b %y")
    _pct(months, "revenue")

    top_products = _pct([
        {"sku": r["_id"], "name": r["name"], "qty": r["qty"], "revenue": r["revenue"]}
        for r in orders.aggregate([
            {"$match": {"status": DONE}},
            {"$unwind": "$items"},
            {"$group": {
                "_id": "$items.sku",
                "name": {"$first": "$items.name"},
                "qty": {"$sum": "$items.quantity"},
                "revenue": {"$sum": "$items.line_total"},
            }},
            {"$sort": {"qty": -1}},
            {"$limit": 5},
        ])
    ], "qty")

    cust_rows = list(orders.aggregate([
        {"$match": {"status": DONE}},
        {"$group": {"_id": "$customer_id", "spent": {"$sum": "$billing.grand_total"}, "orders": {"$sum": 1}}},
        {"$sort": {"spent": -1}},
        {"$limit": 5},
    ]))
    names = {c["_id"]: c.get("name") for c in contacts.find(
        {"_id": {"$in": [r["_id"] for r in cust_rows]}}, {"name": 1})}
    top_customers = _pct([
        {"id": r["_id"], "name": names.get(r["_id"]) or r["_id"], "spent": r["spent"], "orders": r["orders"]}
        for r in cust_rows
    ], "spent")

    inv = _first(products.aggregate([
        {"$group": {"_id": None, "units": {"$sum": STOCK}, "value": {"$sum": VALUE}}},
    ]), {"units": 0, "value": 0})

    by_category = _pct([
        {"name": r["_id"] or "Uncategorised", "products": r["products"], "units": r["units"], "value": r["value"]}
        for r in products.aggregate([
            {"$group": {"_id": "$category", "products": {"$sum": 1}, "units": {"$sum": STOCK}, "value": {"$sum": VALUE}}},
            {"$sort": {"value": -1}},
            {"$limit": 8},
        ])
    ], "value")

    restock = list(products.find(
        {"inventory.total_stock": {"$lte": 10}},
        {"name": 1, "sku": 1, "inventory.total_stock": 1},
    ).sort("inventory.total_stock", 1).limit(8))

    n_orders = totals["count"]
    return {
        "kpi": {
            "revenue": totals["revenue"],
            "valid_orders": n_orders,
            "orders": orders.estimated_document_count(),
            "avg_order": totals["revenue"] / n_orders if n_orders else 0,
            "unpaid_amount": unpaid["amount"],
            "unpaid_count": unpaid["count"],
            "products": products.estimated_document_count(),
            "contacts": contacts.estimated_document_count(),
            "prime": contacts.count_documents({"membership.is_prime": True}),
            "stock_units": inv["units"],
            "stock_value": inv["value"],
            "low": products.count_documents({"inventory.total_stock": {"$gt": 0, "$lte": 10}}),
            "out": products.count_documents({"inventory.total_stock": {"$lte": 0}}),
        },
        "months": months,
        "by_status": _count_by(orders, "$status"),
        "by_payment": _count_by(orders, "$payment.method"),
        "top_cities": _count_by(orders, "$shipping.city", limit=5),
        "tiers": _count_by(contacts, "$membership.tier"),
        "top_products": top_products,
        "top_customers": top_customers,
        "by_category": by_category,
        "restock": restock,
    }


def get_stats(force=False):
    if force or _cache["data"] is None or time.time() - _cache["at"] > CACHE_SECONDS:
        _cache["data"] = compute()
        _cache["at"] = time.time()
    return _cache["data"], _cache["at"]