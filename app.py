from datetime import datetime

from flask import Flask, render_template, request
from pymongo.errors import PyMongoError

import helpers
import stats
from config import Config
from db import get_db
from routes.contacts import bp as contacts_bp
from routes.orders import bp as orders_bp
from routes.products import bp as products_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.jinja_env.filters["inr"] = helpers.inr
    app.jinja_env.filters["inr_short"] = helpers.inr_short
    app.jinja_env.filters["dt"] = helpers.fmt_dt
    app.jinja_env.filters["pretty"] = helpers.pretty_json
    app.jinja_env.globals["dig"] = helpers.dig
    app.jinja_env.globals["status_class"] = helpers.status_class

    app.register_blueprint(products_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(contacts_bp)

    @app.context_processor
    def inject_globals():
        return {
            "app_name": Config.APP_NAME,
            "owner_name": Config.OWNER_NAME,
            "year": datetime.now().year,
        }

    @app.route("/")
    def dashboard():
        s, at = stats.get_stats(force=request.args.get("refresh") == "1")
        recent = list(get_db()["orders"].find().sort("order_date", -1).limit(8))
        return render_template(
            "dashboard.html", s=s, updated=datetime.fromtimestamp(at),
            recent=recent, active="dashboard",
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