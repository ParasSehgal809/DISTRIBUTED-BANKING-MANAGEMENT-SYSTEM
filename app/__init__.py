import os
import sys
from pathlib import Path
from flask import Flask

BASE_DIR = Path(__file__).resolve().parent.parent

from app.config import SECRET_KEY, PORT, DEBUG, DB_BACKEND
from app.database.schema import init_all_databases
from app.database.seed_data import seed_database
from app.database.connection import get_coordinator_connection
from app.routes.auth_routes import auth_bp
from app.routes.admin_routes import admin_bp
from app.routes.branch_routes import branch_bp
from app.routes.customer_routes import customer_bp
from app.routes.account_routes import account_bp
from app.routes.transfer_routes import transfer_bp
from app.routes.loan_routes import loan_bp
from app.routes.query_routes import query_bp
from app.routes.adbms_routes import adbms_bp

def create_app() -> Flask:
    """Factory creating and configuring the Distributed Banking Flask application."""
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "app" / "templates"),
        static_folder=str(BASE_DIR / "app" / "static")
    )
    app.config["SECRET_KEY"] = SECRET_KEY

    # Auto-initialize and seed databases on initial launch if empty
    try:
        coord_conn = get_coordinator_connection()
        try:
            cur = coord_conn.cursor()
            cur.execute("SELECT COUNT(*) FROM branches")
            row = cur.fetchone()
            count = list(row.values())[0] if isinstance(row, dict) else row[0]
            if count == 0:
                print(f"[*] Bootstrapping {DB_BACKEND.upper()} database cluster...")
                init_all_databases()
                seed_database()
        except Exception:
            print(f"[*] Initializing {DB_BACKEND.upper()} multi-node distributed schemas and demo data...")
            init_all_databases()
            seed_database()
        finally:
            coord_conn.close()
    except Exception as e:
        print(f"[*] Database startup notice: {e}")

    # Register Blueprints for all Modules
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(branch_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(transfer_bp)
    app.register_blueprint(loan_bp)
    app.register_blueprint(query_bp)
    app.register_blueprint(adbms_bp)

    return app

app = create_app()
