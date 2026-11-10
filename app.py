from flask import Flask, render_template
from pymongo.errors import PyMongoError
from routes.products import bp as products_bp

import helpers
from config import Config
from db import get_db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.jinja_env.filters["inr"] = helpers.inr
    app.jinja_env.filters["dt"] = helpers.fmt_dt
    app.jinja_env.filters["pretty"] = helpers.pretty_json
    app.jinja_env.globals["dig"] = helpers.dig
    app.register_blueprint(products_bp)
    

    @app.route("/")
    def dashboard():
        db = get_db()
        counts = {
            name: db[name].estimated_document_count()
            for name in ("products", "orders", "contacts")
        }
        return render_template("dashboard.html", counts=counts, active="dashboard")

    @app.errorhandler(PyMongoError)
    def db_error(err):
        return render_template("error.html", error=str(err), active=""), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)