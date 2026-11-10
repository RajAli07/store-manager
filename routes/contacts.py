from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from pymongo.errors import DuplicateKeyError

from config import Config
from db import get_db
from helpers import (FormReader, dig, find_by_id, new_id, paginate,
                     pretty_json, regex_filter, tidy, unflatten)

bp = Blueprint("contacts", __name__, url_prefix="/contacts")

SORTS = {
    "name": [("name", 1)],
    "points": [("membership.points", -1)],
    "wallet": [("membership.wallet_balance", -1)],
}


def coll():
    return get_db()["contacts"]


def orders():
    return get_db()["orders"]


def now():
    return datetime.now(timezone.utc)


def distinct(field):
    return sorted(x for x in coll().distinct(field) if x)


def values_from_doc(c):
    return {
        "name": c.get("name", ""),
        "email": c.get("email", ""),
        "phone": c.get("phone", ""),
        "role": c.get("role", ""),
        "tier": dig(c, "membership.tier", ""),
        "wallet_balance": dig(c, "membership.wallet_balance", ""),
        "points": dig(c, "membership.points", ""),
        "is_prime": "1" if dig(c, "membership.is_prime", False) else "",
        "addresses_json": pretty_json(c.get("addresses", [])),
    }


def parse_form(form):
    r = FormReader(form)

    name = r.text("name")
    email = r.text("email").lower()
    if not name:
        r.errors.append("Name zaroori hai.")
    if not email or "@" not in email:
        r.errors.append("Sahi email daalo.")

    wallet = r.number("wallet_balance", "Wallet balance")
    points = r.number("points", "Points", int)
    addresses = r.json_list("addresses_json", "Addresses")
    if any(not isinstance(a, dict) for a in addresses):
        r.errors.append("Addresses ka har element object hona chahiye.")
        addresses = []

    fields = {
        "name": name,
        "email": email,
        "phone": r.text("phone"),
        "role": r.text("role") or "customer",
        "membership.tier": r.text("tier"),
        "membership.wallet_balance": tidy(wallet),
        "membership.points": points or 0,
        "membership.is_prime": form.get("is_prime") == "1",
        "addresses": addresses,
        "updated_at": now(),
    }
    return fields, r.errors


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    role = request.args.get("role", "")
    tier = request.args.get("tier", "")
    prime = request.args.get("prime", "")
    sort = request.args.get("sort", "name")
    page = request.args.get("page", 1, type=int)

    query = {}
    if q:
        rx = regex_filter(q)
        query["$or"] = [{"name": rx}, {"email": rx}, {"phone": rx}, {"_id": rx}, {"addresses.city": rx}]
    if role:
        query["role"] = role
    if tier:
        query["membership.tier"] = tier
    if prime == "yes":
        query["membership.is_prime"] = True
    elif prime == "no":
        query["membership.is_prime"] = {"$ne": True}

    data = paginate(coll(), query, SORTS.get(sort, SORTS["name"]), page, Config.PAGE_SIZE)
    return render_template(
        "contacts/list.html", data=data, roles=distinct("role"), tiers=distinct("membership.tier"),
        q=q, role=role, tier=tier, prime=prime, sort=sort, active="contacts",
    )


@bp.route("/<doc_id>")
def detail(doc_id):
    c = find_by_id(coll(), doc_id)
    if c is None:
        abort(404)
    cid = c["_id"]
    order_count = orders().count_documents({"customer_id": cid})
    recent = list(orders().find({"customer_id": cid}).sort("order_date", -1).limit(10))
    spent = list(orders().aggregate([
        {"$match": {"customer_id": cid, "status": {"$nin": ["Cancelled", "Returned"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$billing.grand_total"}}},
    ]))
    return render_template(
        "contacts/detail.html", c=c, order_count=order_count, recent=recent,
        spent=spent[0]["total"] if spent else 0, active="contacts",
    )


@bp.route("/new", methods=["GET", "POST"])
def create():
    v = {"role": "customer"}
    if request.method == "POST":
        v = request.form.to_dict()
        fields, errors = parse_form(request.form)
        if not errors and coll().count_documents({"email": fields["email"]}, limit=1):
            errors.append("Is email ka contact pehle se maujood hai.")
        if not errors:
            doc = unflatten(fields)
            doc["created_at"] = now()
            doc["_id"] = request.form.get("_id", "").strip() or new_id("CUS")
            try:
                coll().insert_one(doc)
            except DuplicateKeyError:
                errors.append("Ye ID pehle se use mein hai.")
            else:
                flash("Contact add ho gaya.", "success")
                return redirect(url_for("contacts.detail", doc_id=doc["_id"]))
        for e in errors:
            flash(e, "error")
    return render_template(
        "contacts/form.html", mode="new", v=v, roles=distinct("role"),
        tiers=distinct("membership.tier"), active="contacts",
    )


@bp.route("/<doc_id>/edit", methods=["GET", "POST"])
def edit(doc_id):
    c = find_by_id(coll(), doc_id)
    if c is None:
        abort(404)

    if request.method == "POST":
        v = request.form.to_dict()
        fields, errors = parse_form(request.form)
        if not errors and coll().count_documents({"email": fields["email"], "_id": {"$ne": c["_id"]}}, limit=1):
            errors.append("Is email ka dusra contact pehle se maujood hai.")
        if not errors:
            coll().update_one({"_id": c["_id"]}, {"$set": fields})
            flash("Contact update ho gaya.", "success")
            return redirect(url_for("contacts.detail", doc_id=c["_id"]))
        for e in errors:
            flash(e, "error")
    else:
        v = values_from_doc(c)

    return render_template(
        "contacts/form.html", mode="edit", c=c, v=v, roles=distinct("role"),
        tiers=distinct("membership.tier"), active="contacts",
    )


@bp.route("/<doc_id>/delete", methods=["POST"])
def delete(doc_id):
    c = find_by_id(coll(), doc_id)
    if c is None:
        abort(404)
    n = orders().count_documents({"customer_id": c["_id"]})
    if n:
        flash(f"Delete nahi ho sakta: is contact ke {n} orders hain. Pehle wo orders delete karo.", "error")
        return redirect(url_for("contacts.detail", doc_id=c["_id"]))
    coll().delete_one({"_id": c["_id"]})
    flash(f"'{c.get('name', doc_id)}' delete ho gaya.", "success")
    return redirect(url_for("contacts.index"))