import json
from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from pymongo.errors import DuplicateKeyError

from config import Config
from db import get_db
from helpers import dig, find_by_id, paginate, pretty_json, regex_filter

bp = Blueprint("products", __name__, url_prefix="/products")

SORTS = {
    "name": [("name", 1)],
    "price_low": [("pricing.selling_price", 1)],
    "price_high": [("pricing.selling_price", -1)],
    "stock_low": [("inventory.total_stock", 1)],
    "stock_high": [("inventory.total_stock", -1)],
}


def coll():
    return get_db()["products"]


def categories():
    return sorted(c for c in coll().distinct("category") if c)


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


def values_from_doc(p):
    """Edit form ko existing product ki values se bharna."""
    return {
        "sku": p.get("sku", ""),
        "name": p.get("name", ""),
        "category": p.get("category", ""),
        "sub_category": p.get("sub_category", ""),
        "brand": p.get("brand", ""),
        "mrp": dig(p, "pricing.mrp", ""),
        "selling_price": dig(p, "pricing.selling_price", ""),
        "gst_percent": dig(p, "pricing.gst_percent", ""),
        "total_stock": dig(p, "inventory.total_stock", ""),
        "tags": ", ".join(p.get("tags", [])),
        "variants": pretty_json(p.get("variants", [])),
        "warehouses": pretty_json(dig(p, "inventory.warehouses", [])),
    }


def parse_form(form):
    """Form -> (mongo fields, errors). Galat input par errors list bharti hai."""
    errors = []

    def text(name):
        return form.get(name, "").strip()

    def number(name, cast=float):
        raw = text(name)
        if raw == "":
            return None
        try:
            return cast(raw)
        except ValueError:
            errors.append(f"{name} must be a number.")
            return None

    def json_list(name):
        raw = text(name)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            errors.append(f"{name}: invalid JSON ({e.msg}, line {e.lineno}).")
            return []
        if not isinstance(data, list):
            errors.append(f"{name}: must be a list, e.g. [ {{...}} ].")
            return []
        return data

    sku, name = text("sku"), text("name")
    if not sku:
        errors.append("SKU is required.")
    if not name:
        errors.append("Name is required.")

    mrp = number("mrp")
    selling = number("selling_price")
    gst = number("gst_percent")
    stock_input = number("total_stock", int)
    warehouses = json_list("warehouses")
    variants = json_list("variants")

    if mrp is None or selling is None:
        errors.append("Both MRP and selling price are required.")
    elif selling > mrp:
        errors.append("Selling price cannot be higher than MRP.")
    discount = round((mrp - selling) / mrp * 100, 1) if mrp and selling is not None else 0

    if warehouses:
        try:
            total = sum(int(w.get("stock", 0)) for w in warehouses)
        except (AttributeError, TypeError, ValueError):
            errors.append("Each warehouse must be an object with a numeric stock.")
            total = 0
    else:
        total = stock_input or 0

    fields = {
        "sku": sku,
        "name": name,
        "category": text("category"),
        "sub_category": text("sub_category"),
        "brand": text("brand"),
        "pricing.mrp": mrp,
        "pricing.selling_price": selling,
        "pricing.discount_percent": discount,
        "pricing.gst_percent": gst or 0,
        "inventory.warehouses": warehouses,
        "inventory.total_stock": total,
        "inventory.in_stock": total > 0,
        "variants": variants,
        "tags": [t.strip() for t in text("tags").split(",") if t.strip()],
        "updated_at": datetime.now(timezone.utc),
    }
    return fields, errors


@bp.route("/")
def index():
    c = coll()
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    stock = request.args.get("stock", "")
    sort = request.args.get("sort", "name")
    page = request.args.get("page", 1, type=int)

    query = {}
    if q:
        rx = regex_filter(q)
        query["$or"] = [{"name": rx}, {"brand": rx}, {"sku": rx}, {"_id": rx}]
    if category:
        query["category"] = category
    if stock == "in":
        query["inventory.total_stock"] = {"$gt": 0}
    elif stock == "low":
        query["inventory.total_stock"] = {"$gt": 0, "$lte": 10}
    elif stock == "out":
        query["inventory.total_stock"] = {"$lte": 0}

    data = paginate(c, query, SORTS.get(sort, SORTS["name"]), page, Config.PAGE_SIZE)
    return render_template(
        "products/list.html", data=data, categories=categories(),
        q=q, category=category, stock=stock, sort=sort, active="products",
    )


@bp.route("/<doc_id>")
def detail(doc_id):
    p = find_by_id(coll(), doc_id)
    if p is None:
        abort(404)
    return render_template("products/detail.html", p=p, active="products")


@bp.route("/new", methods=["GET", "POST"])
def create():
    v = {}
    if request.method == "POST":
        v = request.form.to_dict()
        fields, errors = parse_form(request.form)
        if not errors and coll().count_documents({"sku": fields["sku"]}, limit=1):
            errors.append("A product with this SKU already exists.")
        if not errors:
            doc = unflatten(fields)
            doc["ratings"] = {"average": 0, "count": 0}
            doc["created_at"] = datetime.now(timezone.utc)
            custom_id = request.form.get("_id", "").strip()
            if custom_id:
                doc["_id"] = custom_id
            try:
                coll().insert_one(doc)
            except DuplicateKeyError:
                errors.append("This ID is already in use.")
            else:
                flash("Product added.", "success")
                return redirect(url_for("products.detail", doc_id=doc["_id"]))
        for e in errors:
            flash(e, "error")
    return render_template(
        "products/form.html", mode="new", v=v, categories=categories(), active="products"
    )


@bp.route("/<doc_id>/edit", methods=["GET", "POST"])
def edit(doc_id):
    c = coll()
    p = find_by_id(c, doc_id)
    if p is None:
        abort(404)

    if request.method == "POST":
        v = request.form.to_dict()
        fields, errors = parse_form(request.form)
        if not errors and c.count_documents({"sku": fields["sku"], "_id": {"$ne": p["_id"]}}, limit=1):
            errors.append("Another product with this SKU already exists.")
        if not errors:
            c.update_one({"_id": p["_id"]}, {"$set": fields})
            flash("Product updated.", "success")
            return redirect(url_for("products.detail", doc_id=p["_id"]))
        for e in errors:
            flash(e, "error")
    else:
        v = values_from_doc(p)

    return render_template(
        "products/form.html", mode="edit", p=p, v=v, categories=categories(), active="products"
    )


@bp.route("/<doc_id>/delete", methods=["POST"])
def delete(doc_id):
    c = coll()
    p = find_by_id(c, doc_id)
    if p is None:
        abort(404)
    c.delete_one({"_id": p["_id"]})
    flash(f"'{p.get('name', doc_id)}' deleted.", "success")
    return redirect(url_for("products.index"))