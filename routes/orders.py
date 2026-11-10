from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from pymongo.errors import DuplicateKeyError

from config import Config
from db import get_db
from helpers import (FormReader, dig, find_by_id, new_id, paginate,
                     pretty_json, regex_filter, tidy, unflatten)

bp = Blueprint("orders", __name__, url_prefix="/orders")

STATUSES = ["Processing", "Shipped", "Delivered", "Cancelled", "Returned"]

SORTS = {
    "newest": [("order_date", -1)],
    "oldest": [("order_date", 1)],
    "total_high": [("billing.grand_total", -1)],
    "total_low": [("billing.grand_total", 1)],
}


def coll():
    return get_db()["orders"]


def contacts():
    return get_db()["contacts"]


def payment_methods():
    return sorted(m for m in coll().distinct("payment.method") if m)


def now():
    return datetime.now(timezone.utc)


def values_from_doc(o):
    return {
        "customer_id": o.get("customer_id", ""),
        "status": o.get("status", "Processing"),
        "payment_method": dig(o, "payment.method", ""),
        "is_paid": "1" if dig(o, "payment.is_paid", False) else "",
        "shipping_city": dig(o, "shipping.city", ""),
        "shipping_state": dig(o, "shipping.state", ""),
        "shipping_pincode": dig(o, "shipping.pincode", ""),
        "shipping_courier": dig(o, "shipping.courier", ""),
        "sub_total": dig(o, "billing.sub_total", ""),
        "tax_amount": dig(o, "billing.tax_amount", ""),
        "shipping_fee": dig(o, "billing.shipping_fee", ""),
        "items_json": pretty_json(o.get("items", [])),
    }


def parse_form(form):
    r = FormReader(form)

    customer_id = r.text("customer_id")
    status = r.text("status")
    if not customer_id:
        r.errors.append("Customer ID zaroori hai.")
    if status not in STATUSES:
        r.errors.append("Status galat hai.")

    items = r.json_list("items_json", "Items")
    if any(not isinstance(i, dict) for i in items):
        r.errors.append("Items ka har element object hona chahiye.")
        items = []

    sub = r.number("sub_total", "Sub total")
    tax = r.number("tax_amount", "Tax")
    ship = r.number("shipping_fee", "Shipping fee")

    if sub is None:  # khali ho to items ke line_total se nikaalo
        try:
            sub = sum(float(i.get("line_total", 0)) for i in items)
        except (TypeError, ValueError):
            r.errors.append("Items ke line_total number hone chahiye.")
            sub = 0
    tax, ship = tax or 0, ship or 0

    fields = {
        "customer_id": customer_id,
        "status": status,
        "payment.method": r.text("payment_method"),
        "payment.is_paid": form.get("is_paid") == "1",
        "shipping.city": r.text("shipping_city"),
        "shipping.state": r.text("shipping_state"),
        "shipping.pincode": r.text("shipping_pincode"),
        "shipping.courier": r.text("shipping_courier"),
        "billing.sub_total": tidy(sub),
        "billing.tax_amount": tidy(tax),
        "billing.shipping_fee": tidy(ship),
        "billing.grand_total": tidy(sub + tax + ship),
        "items": items,
        "updated_at": now(),
    }
    return fields, r.errors


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    payment = request.args.get("payment", "")
    sort = request.args.get("sort", "newest")
    page = request.args.get("page", 1, type=int)

    query = {}
    if q:
        rx = regex_filter(q)
        query["$or"] = [{"_id": rx}, {"customer_id": rx}, {"shipping.city": rx}]
    if status:
        query["status"] = status
    if payment == "paid":
        query["payment.is_paid"] = True
    elif payment == "pending":
        query["payment.is_paid"] = False

    data = paginate(coll(), query, SORTS.get(sort, SORTS["newest"]), page, Config.PAGE_SIZE)
    return render_template(
        "orders/list.html", data=data, statuses=STATUSES,
        q=q, status=status, payment=payment, sort=sort, active="orders",
    )


@bp.route("/<doc_id>")
def detail(doc_id):
    o = find_by_id(coll(), doc_id)
    if o is None:
        abort(404)
    customer = find_by_id(contacts(), o["customer_id"]) if o.get("customer_id") else None
    return render_template(
        "orders/detail.html", o=o, customer=customer, statuses=STATUSES, active="orders"
    )


@bp.route("/new", methods=["GET", "POST"])
def create():
    v = {"customer_id": request.args.get("customer_id", ""), "status": "Processing"}
    if request.method == "POST":
        v = request.form.to_dict()
        fields, errors = parse_form(request.form)
        if not errors and find_by_id(contacts(), fields["customer_id"]) is None:
            errors.append("Is Customer ID ka contact maujood nahi hai.")
        if not errors:
            doc = unflatten(fields)
            doc["order_date"] = now()
            doc["status_history"] = [{"status": fields["status"], "at": now()}]
            doc["_id"] = request.form.get("_id", "").strip() or new_id("ORD")
            try:
                coll().insert_one(doc)
            except DuplicateKeyError:
                errors.append("Ye Order ID pehle se use mein hai.")
            else:
                flash("Order ban gaya.", "success")
                return redirect(url_for("orders.detail", doc_id=doc["_id"]))
        for e in errors:
            flash(e, "error")
    return render_template(
        "orders/form.html", mode="new", v=v, statuses=STATUSES,
        methods=payment_methods(), active="orders",
    )


@bp.route("/<doc_id>/edit", methods=["GET", "POST"])
def edit(doc_id):
    o = find_by_id(coll(), doc_id)
    if o is None:
        abort(404)

    if request.method == "POST":
        v = request.form.to_dict()
        fields, errors = parse_form(request.form)
        if (not errors and fields["customer_id"] != o.get("customer_id")
                and find_by_id(contacts(), fields["customer_id"]) is None):
            errors.append("Is Customer ID ka contact maujood nahi hai.")
        if not errors:
            update = {"$set": fields}
            if fields["status"] != o.get("status"):
                update["$push"] = {"status_history": {"status": fields["status"], "at": now()}}
            coll().update_one({"_id": o["_id"]}, update)
            flash("Order update ho gaya.", "success")
            return redirect(url_for("orders.detail", doc_id=o["_id"]))
        for e in errors:
            flash(e, "error")
    else:
        v = values_from_doc(o)

    return render_template(
        "orders/form.html", mode="edit", o=o, v=v, statuses=STATUSES,
        methods=payment_methods(), active="orders",
    )


@bp.route("/<doc_id>/status", methods=["POST"])
def set_status(doc_id):
    new_status = request.form.get("status", "")
    if new_status not in STATUSES:
        abort(400)
    o = find_by_id(coll(), doc_id)
    if o is None:
        abort(404)
    if o.get("status") != new_status:
        coll().update_one(
            {"_id": o["_id"]},
            {"$set": {"status": new_status, "updated_at": now()},
             "$push": {"status_history": {"status": new_status, "at": now()}}},
        )
        flash(f"Status badal kar {new_status} kar diya.", "success")
    return redirect(url_for("orders.detail", doc_id=o["_id"]))


@bp.route("/<doc_id>/delete", methods=["POST"])
def delete(doc_id):
    o = find_by_id(coll(), doc_id)
    if o is None:
        abort(404)
    coll().delete_one({"_id": o["_id"]})
    flash(f"Order {o['_id']} delete ho gaya.", "success")
    return redirect(url_for("orders.index"))