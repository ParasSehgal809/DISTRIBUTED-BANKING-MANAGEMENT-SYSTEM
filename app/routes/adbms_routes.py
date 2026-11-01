from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.core.security import login_required, roles_required, get_current_user
from app.core.lock_manager import dlm
from app.core.deadlock_detector import deadlock_detector
from app.core.recovery_manager import RecoveryManager
from app.core.two_phase_commit import TwoPhaseCommitCoordinator
from app.core.catalog import GlobalCatalog
from app.config import BRANCHES, ROLE_ADMIN

adbms_bp = Blueprint("adbms", __name__, url_prefix="/adbms-lab")

@adbms_bp.route("/")
@login_required
def lab_home():
    # 1. Lock Manager State
    active_locks = dlm.get_active_locks()

    # 2. Deadlock WFG State
    wfg_state = deadlock_detector.get_graph_state()

    # 3. Recovery State
    recovery_status = RecoveryManager.get_recovery_status()

    # 4. Accounts list for 2PC sandbox
    accounts = GlobalCatalog.reconstruct_all_accounts()

    return render_template(
        "adbms_lab.html",
        active_locks=active_locks,
        wfg_state=wfg_state,
        recovery_status=recovery_status,
        accounts=accounts,
        branches=BRANCHES
    )

# --- Lock Manager Endpoints ---

@adbms_bp.route("/lock/acquire", methods=["POST"])
@login_required
def acquire_lock():
    data = request.form
    tx_id = data.get("tx_id", "MANUAL-TX").strip()
    resource_id = data.get("resource_id", "").strip()
    lock_type = data.get("lock_type", "X").strip()

    success, msg = dlm.acquire_lock(tx_id, resource_id, lock_type, timeout=1.5)
    if success:
        flash(f"Lock acquired: {msg}", "success")
    else:
        flash(f"Lock Conflict / Timed Out: {msg}", "danger")
    return redirect(url_for("adbms.lab_home"))

@adbms_bp.route("/lock/clear", methods=["POST"])
@login_required
def clear_locks():
    dlm.clear_all_locks()
    flash("All active locks released.", "info")
    return redirect(url_for("adbms.lab_home"))

# --- Deadlock Endpoints ---

@adbms_bp.route("/deadlock/simulate", methods=["POST"])
@login_required
def simulate_deadlock():
    state = deadlock_detector.simulate_deadlock_scenario()
    flash("Deadlock scenario generated! Circular wait established between TX-DEADLOCK-A and TX-DEADLOCK-B.", "warning")
    return redirect(url_for("adbms.lab_home"))

@adbms_bp.route("/deadlock/resolve", methods=["POST"])
@login_required
def resolve_deadlock():
    resolutions = deadlock_detector.resolve_deadlocks()
    if resolutions:
        for r in resolutions:
            flash(f"Deadlock Resolved: Aborted victim {r['victim_tx']} ({r['policy_used']}). Released {r['locks_released']} locks.", "success")
    else:
        flash("No deadlocks detected in Wait-For Graph.", "info")
    return redirect(url_for("adbms.lab_home"))

@adbms_bp.route("/deadlock/clear", methods=["POST"])
@login_required
def clear_wfg():
    deadlock_detector.clear_graph()
    dlm.clear_all_locks()
    flash("Wait-For Graph cleared.", "info")
    return redirect(url_for("adbms.lab_home"))

# --- Recovery Endpoints ---

@adbms_bp.route("/recovery/inject-crash", methods=["POST"])
@login_required
def inject_crash():
    res = RecoveryManager.inject_simulated_crash_wal()
    flash(f"Crash simulated! Injected in-doubt transaction {res['synthetic_tx_id']}. Run Recovery to test REDO/UNDO.", "warning")
    return redirect(url_for("adbms.lab_home"))

@adbms_bp.route("/recovery/run", methods=["POST"])
@login_required
def run_recovery():
    res = RecoveryManager.run_recovery()
    flash(res["message"], "success")
    return redirect(url_for("adbms.lab_home"))
