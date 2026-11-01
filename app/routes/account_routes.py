import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.core.security import login_required, roles_required, get_current_user, log_audit_event
from app.core.catalog import GlobalCatalog
from app.core.lock_manager import dlm
from app.config import BRANCHES, ROLE_ADMIN, ROLE_BRANCH_MANAGER, ROLE_TELLER
from app.database.connection import get_coordinator_connection, get_branch_connection

account_bp = Blueprint("account", __name__, url_prefix="/accounts")

@account_bp.route("/")
@login_required
def list_accounts():
    branch_filter = request.args.get("branch")
    accounts = GlobalCatalog.reconstruct_all_accounts(branch_filter=branch_filter)
    return render_template(
        "accounts.html",
        accounts=accounts,
        branches=BRANCHES,
        current_branch_filter=branch_filter
    )

@account_bp.route("/<account_number>")
@login_required
def view_account(account_number: str):
    account = GlobalCatalog.get_account_from_branch(account_number)
    if not account:
        flash("Account not found.", "danger")
        return redirect(url_for("account.list_accounts"))

    # Fetch customer details
    customer = GlobalCatalog.reconstruct_customer(account["customer_id"])

    # Fetch transaction history from local branch ledger
    b_id = account["branch_id"]
    b_conn = get_branch_connection(b_id)
    transactions = []
    try:
        cur = b_conn.cursor()
        cur.execute(
            """SELECT * FROM transactions WHERE account_number = ? 
               ORDER BY timestamp DESC LIMIT 50""",
            (account_number,)
        )
        transactions = [dict(r) for r in cur.fetchall()]
    finally:
        b_conn.close()

    return render_template(
        "account_detail.html",
        account=account,
        customer=customer,
        transactions=transactions,
        branch=BRANCHES.get(b_id, {})
    )

@account_bp.route("/open", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_BRANCH_MANAGER, ROLE_TELLER)
def open_account():
    user = get_current_user()
    if request.method == "POST":
        customer_id = request.form.get("customer_id")
        branch_id = request.form.get("branch_id")
        account_type = request.form.get("account_type", "SAVINGS")
        initial_deposit = float(request.form.get("initial_deposit", 0.0))

        if branch_id not in BRANCHES:
            flash("Invalid branch selected.", "danger")
            return redirect(url_for("account.open_account"))

        # Verify customer exists in central coordinator
        coord_conn = get_coordinator_connection()
        try:
            cur = coord_conn.cursor()
            cur.execute("SELECT customer_id, full_name FROM customers_global WHERE customer_id = ?", (customer_id,))
            cust = cur.fetchone()
            if not cust:
                flash(f"Customer {customer_id} not found in central catalog.", "danger")
                return redirect(url_for("account.open_account"))
        finally:
            coord_conn.close()

        # Generate Account Number: ACC-<branch_code_number>-<random 4 digits>
        acc_num = f"ACC-{BRANCHES[branch_id]['code'].split('-')[1]}{uuid.uuid4().hex[:4].upper()}"

        # 1. Write to Global Account Directory on Coordinator
        coord_conn = get_coordinator_connection()
        try:
            coord_conn.execute(
                """INSERT INTO global_account_directory (account_number, customer_id, branch_id, account_type, status)
                   VALUES (?, ?, ?, ?, 'ACTIVE')""",
                (acc_num, customer_id, branch_id, account_type)
            )
            coord_conn.commit()
        finally:
            coord_conn.close()

        # 2. Allocate and write Horizontal Fragment to target Branch Database
        b_conn = get_branch_connection(branch_id)
        try:
            b_conn.execute(
                """INSERT INTO accounts (account_number, customer_id, branch_id, account_type, balance, status)
                   VALUES (?, ?, ?, ?, ?, 'ACTIVE')""",
                (acc_num, customer_id, branch_id, account_type, initial_deposit)
            )
            if initial_deposit > 0:
                b_conn.execute(
                    """INSERT INTO transactions (tx_id, global_tx_id, account_number, type, amount, balance_after, description)
                       VALUES (?, NULL, ?, 'DEPOSIT', ?, ?, 'Initial Opening Deposit')""",
                    (f"TX-INIT-{acc_num}", acc_num, initial_deposit, initial_deposit)
                )
            b_conn.commit()
        finally:
            b_conn.close()

        log_audit_event(
            user["username"], user["role"], "ACCOUNT_OPENED",
            f"Opened {account_type} account {acc_num} for {customer_id} on branch {branch_id}",
            branch_id
        )

        flash(f"Account {acc_num} opened successfully on {BRANCHES[branch_id]['name']}!", "success")
        return redirect(url_for("account.view_account", account_number=acc_num))

    customers = GlobalCatalog.reconstruct_all_customers()
    return render_template("account_open.html", customers=customers, branches=BRANCHES)

@account_bp.route("/<account_number>/deposit", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_BRANCH_MANAGER, ROLE_TELLER)
def deposit(account_number: str):
    user = get_current_user()
    amount = float(request.form.get("amount", 0.0))
    if amount <= 0:
        flash("Deposit amount must be positive.", "warning")
        return redirect(url_for("account.view_account", account_number=account_number))

    loc = GlobalCatalog.resolve_account_location(account_number)
    if not loc:
        flash("Account not found.", "danger")
        return redirect(url_for("account.list_accounts"))

    branch_id = loc["branch_id"]
    tx_id = f"DEP-{uuid.uuid4().hex[:8].upper()}"

    # Strict 2PL: Acquire Exclusive lock on account
    dlm.acquire_lock(tx_id, f"acc:{account_number}", "X")

    b_conn = get_branch_connection(branch_id)
    try:
        cur = b_conn.cursor()
        cur.execute("SELECT balance, version FROM accounts WHERE account_number = ?", (account_number,))
        acc = cur.fetchone()
        new_bal = acc["balance"] + amount

        b_conn.execute("UPDATE accounts SET balance = ?, version = version + 1 WHERE account_number = ?", (new_bal, account_number))
        b_conn.execute(
            """INSERT INTO transactions (tx_id, global_tx_id, account_number, type, amount, balance_after, description)
               VALUES (?, NULL, ?, 'DEPOSIT', ?, ?, 'Cash Deposit')""",
            (tx_id, account_number, amount, new_bal)
        )
        b_conn.commit()
        log_audit_event(user["username"], user["role"], "DEPOSIT", f"Deposited ${amount:.2f} into {account_number}", branch_id)
        flash(f"Successfully deposited ${amount:.2f} into {account_number}. New balance: ${new_bal:.2f}", "success")
    finally:
        dlm.release_locks_for_tx(tx_id)
        b_conn.close()

    return redirect(url_for("account.view_account", account_number=account_number))

@account_bp.route("/<account_number>/withdraw", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_BRANCH_MANAGER, ROLE_TELLER)
def withdraw(account_number: str):
    user = get_current_user()
    amount = float(request.form.get("amount", 0.0))
    if amount <= 0:
        flash("Withdrawal amount must be positive.", "warning")
        return redirect(url_for("account.view_account", account_number=account_number))

    loc = GlobalCatalog.resolve_account_location(account_number)
    if not loc:
        flash("Account not found.", "danger")
        return redirect(url_for("account.list_accounts"))

    branch_id = loc["branch_id"]
    tx_id = f"WTH-{uuid.uuid4().hex[:8].upper()}"

    # Strict 2PL: Acquire Exclusive lock on account
    dlm.acquire_lock(tx_id, f"acc:{account_number}", "X")

    b_conn = get_branch_connection(branch_id)
    try:
        cur = b_conn.cursor()
        cur.execute("SELECT balance, version FROM accounts WHERE account_number = ?", (account_number,))
        acc = cur.fetchone()

        if acc["balance"] < amount:
            flash(f"Insufficient funds! Current balance: ${acc['balance']:.2f}", "danger")
            return redirect(url_for("account.view_account", account_number=account_number))

        new_bal = acc["balance"] - amount
        b_conn.execute("UPDATE accounts SET balance = ?, version = version + 1 WHERE account_number = ?", (new_bal, account_number))
        b_conn.execute(
            """INSERT INTO transactions (tx_id, global_tx_id, account_number, type, amount, balance_after, description)
               VALUES (?, NULL, ?, 'WITHDRAWAL', ?, ?, 'Cash Withdrawal')""",
            (tx_id, account_number, amount, new_bal)
        )
        b_conn.commit()
        log_audit_event(user["username"], user["role"], "WITHDRAWAL", f"Withdrew ${amount:.2f} from {account_number}", branch_id)
        flash(f"Successfully withdrew ${amount:.2f} from {account_number}. New balance: ${new_bal:.2f}", "success")
    finally:
        dlm.release_locks_for_tx(tx_id)
        b_conn.close()

    return redirect(url_for("account.view_account", account_number=account_number))
