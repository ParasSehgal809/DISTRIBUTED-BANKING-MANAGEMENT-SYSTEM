from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.core.security import login_required, roles_required, get_current_user
from app.core.catalog import GlobalCatalog
from app.config import BRANCHES, ROLE_ADMIN, ROLE_BRANCH_MANAGER
from app.database.connection import get_branch_connection, get_coordinator_connection

branch_bp = Blueprint("branch", __name__, url_prefix="/branches")

@branch_bp.route("/")
@login_required
def list_branches():
    summary = GlobalCatalog.get_system_summary()
    return render_template("branches.html", branches=summary["branch_stats"], total_balance=summary["total_balance"])

@branch_bp.route("/<branch_id>")
@login_required
def inspect_branch(branch_id: str):
    if branch_id not in BRANCHES:
        flash("Branch node not found.", "danger")
        return redirect(url_for("branch.list_branches"))

    b_meta = BRANCHES[branch_id]
    b_conn = get_branch_connection(branch_id)
    try:
        # Fetch accounts (Horizontal Fragment)
        cur = b_conn.cursor()
        cur.execute("SELECT * FROM accounts ORDER BY account_number ASC")
        accounts = [dict(r) for r in cur.fetchall()]

        # Fetch local KYC profiles (Vertical Fragment)
        cur.execute("SELECT * FROM customers_local ORDER BY customer_id ASC")
        profiles = [dict(r) for r in cur.fetchall()]

        # Fetch local transactions
        cur.execute("SELECT * FROM transactions ORDER BY timestamp DESC LIMIT 25")
        transactions = [dict(r) for r in cur.fetchall()]

        # Fetch local participant WAL
        cur.execute("SELECT * FROM branch_wal ORDER BY timestamp DESC LIMIT 15")
        wal_logs = [dict(r) for r in cur.fetchall()]

        total_balance = sum(a["balance"] for a in accounts)

        return render_template(
            "branch_detail.html",
            branch=b_meta,
            accounts=accounts,
            profiles=profiles,
            transactions=transactions,
            wal_logs=wal_logs,
            total_balance=total_balance
        )
    finally:
        b_conn.close()

@branch_bp.route("/<branch_id>/toggle-status", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN)
def toggle_status(branch_id: str):
    if branch_id in BRANCHES:
        curr = BRANCHES[branch_id]["status"]
        new_status = "OFFLINE" if curr == "ONLINE" else "ONLINE"
        BRANCHES[branch_id]["status"] = new_status

        # Update in coordinator branches table
        coord_conn = get_coordinator_connection()
        try:
            coord_conn.execute("UPDATE branches SET status = ? WHERE branch_id = ?", (new_status, branch_id))
            coord_conn.commit()
        finally:
            coord_conn.close()

        flash(f"Branch {branch_id} status changed to {new_status}", "info")
    return redirect(url_for("branch.inspect_branch", branch_id=branch_id))
