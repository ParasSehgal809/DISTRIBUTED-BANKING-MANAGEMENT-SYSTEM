import hashlib
from functools import wraps
from flask import session, redirect, url_for, flash, request, abort, jsonify
from app.config import (
    ROLE_ADMIN, ROLE_BRANCH_MANAGER, ROLE_TELLER, ROLE_CUSTOMER, VALID_ROLES
)
from app.database.connection import get_coordinator_connection

SALT = b"adbms_salt_distributed_banking"

def hash_password(password: str) -> str:
    """PBKDF2 SHA-256 password hashing."""
    return hashlib.pbkdf2_hmac("sha256", password.encode(), SALT, 100000).hex()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password matches stored hash."""
    return hash_password(plain_password) == hashed_password

def authenticate_user(username: str, plain_password: str):
    """Authenticate user against global_users directory."""
    conn = get_coordinator_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT user_id, username, email, password_hash, role, branch_id, customer_id
               FROM global_users WHERE username = ? OR email = ?""",
            (username, username)
        )
        user = cur.fetchone()
        if user and verify_password(plain_password, user["password_hash"]):
            return dict(user)
        return None
    finally:
        conn.close()

def get_current_user():
    """Returns the currently logged-in user session or None."""
    if "user" in session:
        return session["user"]
    return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not get_current_user():
            if request.is_json:
                return jsonify({"error": "Unauthorized", "message": "Please log in to continue"}), 401
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def roles_required(*allowed_roles):
    """RBAC decorator restricting route to specific roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user = get_current_user()
            if not user:
                if request.is_json:
                    return jsonify({"error": "Unauthorized"}), 401
                flash("Please log in first.", "warning")
                return redirect(url_for("auth.login"))
            if user.get("role") not in allowed_roles:
                if request.is_json:
                    return jsonify({"error": "Forbidden", "message": f"Requires one of: {allowed_roles}"}), 403
                flash("Access Denied: You do not have permission for this module.", "danger")
                return redirect(url_for("admin.dashboard"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def log_audit_event(actor_username: str, actor_role: str, action: str, details: str, branch_id: str = None):
    """Logs an audit entry into central coordinator audit_logs."""
    conn = get_coordinator_connection()
    try:
        conn.execute(
            """INSERT INTO audit_logs (actor_username, actor_role, action, branch_id, details)
               VALUES (?, ?, ?, ?, ?)""",
            (actor_username, actor_role, action, branch_id or "GLOBAL", details)
        )
        conn.commit()
    except Exception as e:
        print(f"[!] Audit log error: {e}")
    finally:
        conn.close()
