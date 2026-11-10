from flask import Flask, render_template
from pymongo.errors import PyMongoError

import helpers
from config import Config
from db import get_db
from routes.contacts import bp as contacts_bp
from routes.orders import bp as orders_bp
from routes.products import bp as products_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.jinja_env.filters["inr"] = helpers.inr
    app.jinja_env.filters["dt"] = helpers.fmt_dt
    app.jinja_env.filters["pretty"] = helpers.pretty_json
    app.jinja_env.globals["dig"] = helpers.dig
    app.jinja_env.globals["status_class"] = helpers.status_class

    app.register_blueprint(products_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(contacts_bp)

    @app.route("/")
    def dashboard():
        db = get_db()
        counts = {
            name: db[name].estimated_document_count()
            for name in ("products", "orders", "contacts")
        }

        rev = list(db.orders.aggregate([
            {"$match": {"status": {"$nin": ["Cancelled", "Returned"]}}},
            {"$group": {"_id": None, "total": {"$sum": "$billing.grand_total"}}},
        ]))
        revenue = rev[0]["total"] if rev else 0

        by_status = list(db.orders.aggregate([
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]))

        low_stock = db.products.count_documents({"inventory.total_stock": {"$gt": 0, "$lte": 10}})
        out_stock = db.products.count_documents({"inventory.total_stock": {"$lte": 0}})
        recent = list(db.orders.find().sort("order_date", -1).limit(8))

        return render_template(
            "dashboard.html", counts=counts, revenue=revenue, by_status=by_status,
            low_stock=low_stock, out_stock=out_stock, recent=recent, active="dashboard",
        )

    @app.errorhandler(404)
    def not_found(err):
        return render_template("404.html", active=""), 404

    @app.errorhandler(PyMongoError)
    def db_error(err):
        return render_template("error.html", error=str(err), active=""), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)