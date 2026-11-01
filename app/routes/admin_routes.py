from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.core.security import login_required, get_current_user, roles_required, log_audit_event
from app.core.catalog import GlobalCatalog
from app.database.connection import get_coordinator_connection, get_all_branch_connections
from app.database.seed_data import seed_database
from app.config import ROLE_ADMIN, BRANCHES

admin_bp = Blueprint("admin", __name__)

@admin_bp.route("/")
@login_required
def dashboard():
    summary = GlobalCatalog.get_system_summary()
    user = get_current_user()

    # Fetch recent coordinator WAL entries
    coord_conn = get_coordinator_connection()
    try:
        cur = coord_conn.cursor()
        cur.execute("SELECT * FROM coordinator_wal ORDER BY created_at DESC LIMIT 6")
        recent_2pc = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 8")
        audit_logs = [dict(r) for r in cur.fetchall()]
    finally:
        coord_conn.close()

    # Fetch recent transactions across branches
    recent_transactions = []
    for b_id, b_meta in BRANCHES.items():
        b_conn = get_all_branch_connections()[b_id]
        try:
            b_cur = b_conn.cursor()
            b_cur.execute("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 4")
            for t in b_cur.fetchall():
                t_dict = dict(t)
                t_dict["branch_id"] = b_id
                t_dict["branch_name"] = b_meta["name"]
                t_dict["branch_color"] = b_meta["color"]
                recent_transactions.append(t_dict)
        finally:
            b_conn.close()

    recent_transactions.sort(key=lambda x: x["timestamp"], reverse=True)
    recent_transactions = recent_transactions[:8]

    return render_template(
        "index.html",
        summary=summary,
        user=user,
        recent_2pc=recent_2pc,
        audit_logs=audit_logs,
        recent_transactions=recent_transactions,
        branches=summary["branch_stats"]
    )

@admin_bp.route("/audit-logs")
@login_required
def audit_logs():
    coord_conn = get_coordinator_connection()
    try:
        cur = coord_conn.cursor()
        cur.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 100")
        logs = [dict(r) for r in cur.fetchall()]
        return render_template("audit_logs.html", logs=logs)
    finally:
        coord_conn.close()

@admin_bp.route("/reset-system", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def reset_system():
    """Reseeds all distributed databases back to pristine initial state."""
    user = get_current_user()
    try:
        seed_database()
        log_audit_event(user["username"], user["role"], "SYSTEM_RESET", "Reinitialized all central and branch databases with seed data.")
        flash("Distributed databases successfully reseeded to initial state!", "success")
    except Exception as e:
        flash(f"Error resetting database: {e}", "danger")
    return redirect(url_for("admin.dashboard"))
