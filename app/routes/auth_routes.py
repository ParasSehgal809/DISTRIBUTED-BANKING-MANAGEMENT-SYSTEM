from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from app.core.security import authenticate_user, hash_password, log_audit_event
from app.database.connection import get_coordinator_connection

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = authenticate_user(username, password)
        if user:
            session["user"] = {
                "user_id": user["user_id"],
                "username": user["username"],
                "email": user["email"],
                "role": user["role"],
                "branch_id": user["branch_id"],
                "customer_id": user["customer_id"]
            }
            log_audit_event(user["username"], user["role"], "LOGIN", f"User logged in successfully (Role: {user['role']})", user["branch_id"])
            flash(f"Welcome back, {user['username']}! Logged in as {user['role']}.", "success")
            
            next_page = request.args.get("next")
            return redirect(next_page or url_for("admin.dashboard"))
        else:
            flash("Invalid username or password.", "danger")

    return render_template("login.html")

@auth_bp.route("/quick-login/<role>")
def quick_login(role: str):
    """Convenience shortcut for testing/demonstrating different RBAC roles in VS Code."""
    role = role.upper()
    conn = get_coordinator_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM global_users WHERE role = ? LIMIT 1", (role,))
        user = cur.fetchone()
        if user:
            session["user"] = {
                "user_id": user["user_id"],
                "username": user["username"],
                "email": user["email"],
                "role": user["role"],
                "branch_id": user["branch_id"],
                "customer_id": user["customer_id"]
            }
            log_audit_event(user["username"], user["role"], "QUICK_LOGIN_SWITCH", f"Switched active session to {role}", user["branch_id"])
            flash(f"Switched role to {role} ({user['username']})", "info")
        else:
            flash(f"No user found for role {role}", "warning")
    finally:
        conn.close()

    return redirect(request.referrer or url_for("admin.dashboard"))

@auth_bp.route("/logout")
def logout():
    user = session.pop("user", None)
    if user:
        log_audit_event(user["username"], user["role"], "LOGOUT", "User logged out", user.get("branch_id"))
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
