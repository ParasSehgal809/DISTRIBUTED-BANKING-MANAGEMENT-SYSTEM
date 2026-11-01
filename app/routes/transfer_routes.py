from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.core.security import login_required, get_current_user, log_audit_event
from app.core.catalog import GlobalCatalog
from app.core.two_phase_commit import TwoPhaseCommitCoordinator
from app.config import BRANCHES

transfer_bp = Blueprint("transfer", __name__, url_prefix="/transfer")

@transfer_bp.route("/", methods=["GET", "POST"])
@login_required
def transfer_page():
    user = get_current_user()
    all_accounts = GlobalCatalog.reconstruct_all_accounts()

    execution_result = None

    if request.method == "POST":
        src_account = request.form.get("src_account", "").strip()
        dest_account = request.form.get("dest_account", "").strip()
        amount = float(request.form.get("amount", 0.0))
        description = request.form.get("description", "Transfer").strip()
        failure_simulation = request.form.get("failure_simulation") or None

        if src_account == dest_account:
            flash("Source and destination accounts must be different.", "warning")
            return redirect(url_for("transfer.transfer_page"))

        if amount <= 0:
            flash("Transfer amount must be greater than zero.", "warning")
            return redirect(url_for("transfer.transfer_page"))

        src_loc = GlobalCatalog.resolve_account_location(src_account)
        dest_loc = GlobalCatalog.resolve_account_location(dest_account)

        if not src_loc or not dest_loc:
            flash("One or both accounts do not exist in the bank directory.", "danger")
            return redirect(url_for("transfer.transfer_page"))

        # Check transaction type: Intra-Branch vs Cross-Branch
        is_cross_branch = (src_loc["branch_id"] != dest_loc["branch_id"])

        if not is_cross_branch and not failure_simulation:
            # Intra-Branch Local ACID Transaction
            result = TwoPhaseCommitCoordinator.execute_intra_branch_transfer(
                branch_id=src_loc["branch_id"],
                src_account=src_account,
                dest_account=dest_account,
                amount=amount,
                description=description
            )
            if result.get("success"):
                log_audit_event(
                    user["username"], user["role"], "LOCAL_TRANSFER",
                    f"Transferred ${amount:.2f} locally in branch {src_loc['branch_id']} from {src_account} to {dest_account}",
                    src_loc["branch_id"]
                )
                flash(f"Local transfer completed successfully! Tx: {result.get('tx_id')}", "success")
            else:
                flash(f"Local transfer failed: {result.get('error')}", "danger")
            execution_result = {"is_cross_branch": False, "result": result}
        else:
            # Cross-Branch Distributed Two-Phase Commit (2PC) Transaction
            result = TwoPhaseCommitCoordinator.execute_cross_branch_transfer(
                src_account=src_account,
                dest_account=dest_account,
                amount=amount,
                description=description,
                actor=user["username"],
                failure_simulation=failure_simulation
            )
            log_audit_event(
                user["username"], user["role"], "2PC_TRANSFER",
                f"2PC cross-branch transfer of ${amount:.2f} ({src_loc['branch_id']} -> {dest_loc['branch_id']}). Decision: {result.get('decision')}",
                "GLOBAL"
            )
            if result.get("success"):
                flash(f"Two-Phase Commit succeeded! Global Tx {result.get('tx_id')} committed across branches {src_loc['branch_id']} and {dest_loc['branch_id']}.", "success")
            else:
                flash(f"Two-Phase Commit terminated with {result.get('decision')}. Tx: {result.get('tx_id')}", "warning")
            execution_result = {"is_cross_branch": True, "result": result}

    return render_template(
        "transfer.html",
        accounts=all_accounts,
        branches=BRANCHES,
        execution_result=execution_result
    )

@transfer_bp.route("/api/execute", methods=["POST"])
@login_required
def api_execute():
    """JSON API endpoint for programmatic transfer execution & 2PC simulation."""
    data = request.get_json() or {}
    src_account = data.get("src_account")
    dest_account = data.get("dest_account")
    amount = float(data.get("amount", 0.0))
    desc = data.get("description", "API Transfer")
    failure = data.get("failure_simulation")

    user = get_current_user()
    result = TwoPhaseCommitCoordinator.execute_cross_branch_transfer(
        src_account=src_account,
        dest_account=dest_account,
        amount=amount,
        description=desc,
        actor=user["username"],
        failure_simulation=failure
    )
    return jsonify(result)
