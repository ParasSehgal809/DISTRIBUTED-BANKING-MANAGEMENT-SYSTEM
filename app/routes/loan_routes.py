import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.core.security import login_required, roles_required, get_current_user, log_audit_event
from app.core.catalog import GlobalCatalog
from app.config import BRANCHES, ROLE_ADMIN, ROLE_BRANCH_MANAGER
from app.database.connection import get_coordinator_connection, get_branch_connection

loan_bp = Blueprint("loan", __name__, url_prefix="/loans")

@loan_bp.route("/")
@login_required
def list_loans():
    coord_conn = get_coordinator_connection()
    try:
        cur = coord_conn.cursor()
        cur.execute(
            """SELECT l.*, c.full_name, c.email 
               FROM global_loans l 
               JOIN customers_global c ON l.customer_id = c.customer_id
               ORDER BY l.created_at DESC"""
        )
        loans = [dict(r) for r in cur.fetchall()]
        for l in loans:
            b_info = BRANCHES.get(l["branch_id"], {})
            l["branch_name"] = b_info.get("name", l["branch_id"])
            l["branch_color"] = b_info.get("color", "gray")

        return render_template("loans.html", loans=loans, branches=BRANCHES)
    finally:
        coord_conn.close()

@loan_bp.route("/apply", methods=["GET", "POST"])
@login_required
def apply_loan():
    user = get_current_user()
    if request.method == "POST":
        customer_id = request.form.get("customer_id")
        account_number = request.form.get("account_number")
        requested_amount = float(request.form.get("requested_amount", 0.0))
        purpose = request.form.get("purpose", "").strip()
        duration_months = int(request.form.get("duration_months", 36))
        interest_rate = float(request.form.get("interest_rate", 6.5))

        loc = GlobalCatalog.resolve_account_location(account_number)
        if not loc:
            flash("Account not found.", "danger")
            return redirect(url_for("loan.apply_loan"))

        branch_id = loc["branch_id"]
        loan_id = f"LOAN-{uuid.uuid4().hex[:6].upper()}"

        coord_conn = get_coordinator_connection()
        try:
            coord_conn.execute(
                """INSERT INTO global_loans 
                   (loan_id, customer_id, branch_id, account_number, requested_amount, interest_rate, duration_months, status, purpose)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
                (loan_id, customer_id, branch_id, account_number, requested_amount, interest_rate, duration_months, purpose)
            )
            coord_conn.commit()
            log_audit_event(user["username"], user["role"], "LOAN_APPLIED", f"Loan {loan_id} applied for ${requested_amount:.2f} by {customer_id}", branch_id)
            flash(f"Loan application {loan_id} submitted! Pending distributed credit review.", "success")
            return redirect(url_for("loan.evaluate_loan", loan_id=loan_id))
        finally:
            coord_conn.close()

    customers = GlobalCatalog.reconstruct_all_customers()
    accounts = GlobalCatalog.reconstruct_all_accounts()
    return render_template("loan_apply.html", customers=customers, accounts=accounts, branches=BRANCHES)

@loan_bp.route("/evaluate/<loan_id>")
@login_required
def evaluate_loan(loan_id: str):
    """
    Distributed Credit Evaluation:
    Coordinator executes subqueries across all branch databases to aggregate customer's
    total liquidity, calculate debt-to-asset ratio, and fetch financial risk score.
    """
    coord_conn = get_coordinator_connection()
    try:
        cur = coord_conn.cursor()
        cur.execute(
            """SELECT l.*, c.full_name, c.email, c.phone 
               FROM global_loans l 
               JOIN customers_global c ON l.customer_id = c.customer_id 
               WHERE l.loan_id = ?""",
            (loan_id,)
        )
        loan = cur.fetchone()
        if not loan:
            flash("Loan not found.", "danger")
            return redirect(url_for("loan.list_loans"))
        loan = dict(loan)
    finally:
        coord_conn.close()

    customer_id = loan["customer_id"]
    customer = GlobalCatalog.reconstruct_customer(customer_id)

    # Distributed Query: Aggregate customer's accounts and balances across all 3 branch nodes
    all_accounts = GlobalCatalog.reconstruct_all_accounts()
    customer_accounts = [a for a in all_accounts if a["customer_id"] == customer_id]
    total_bank_holdings = sum(a["balance"] for a in customer_accounts)

    # Automated Risk Evaluation
    credit_score = customer.get("credit_score", 600)
    annual_income = customer.get("annual_income", 0.0)
    debt_to_income_ratio = round((loan["requested_amount"] / (annual_income or 1)) * 100, 1)

    eligibility = "RECOMMENDED" if (credit_score >= 680 and total_bank_holdings > (loan["requested_amount"] * 0.15)) else "REQUIRES_REVIEW"

    return render_template(
        "loan_evaluate.html",
        loan=loan,
        customer=customer,
        accounts=customer_accounts,
        total_holdings=total_bank_holdings,
        debt_to_income_ratio=debt_to_income_ratio,
        eligibility=eligibility,
        branches=BRANCHES
    )

@loan_bp.route("/<loan_id>/action", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_BRANCH_MANAGER)
def loan_action(loan_id: str):
    user = get_current_user()
    action = request.form.get("action") # 'APPROVE', 'REJECT', 'DISBURSE'
    comments = request.form.get("comments", "").strip()

    coord_conn = get_coordinator_connection()
    try:
        cur = coord_conn.cursor()
        cur.execute("SELECT * FROM global_loans WHERE loan_id = ?", (loan_id,))
        loan = cur.fetchone()
        if not loan:
            flash("Loan record not found.", "danger")
            return redirect(url_for("loan.list_loans"))
        loan = dict(loan)

        if action == "APPROVE":
            approved_amount = float(request.form.get("approved_amount", loan["requested_amount"]))
            coord_conn.execute(
                """UPDATE global_loans 
                   SET status = 'APPROVED', approved_amount = ?, reviewed_by = ?, review_comments = ?
                   WHERE loan_id = ?""",
                (approved_amount, user["username"], comments, loan_id)
            )
            coord_conn.commit()
            log_audit_event(user["username"], user["role"], "LOAN_APPROVED", f"Loan {loan_id} approved for ${approved_amount:.2f}", loan["branch_id"])
            flash(f"Loan {loan_id} approved for ${approved_amount:.2f}!", "success")

        elif action == "REJECT":
            coord_conn.execute(
                """UPDATE global_loans 
                   SET status = 'REJECTED', reviewed_by = ?, review_comments = ?
                   WHERE loan_id = ?""",
                (user["username"], comments, loan_id)
            )
            coord_conn.commit()
            log_audit_event(user["username"], user["role"], "LOAN_REJECTED", f"Loan {loan_id} rejected. Reason: {comments}", loan["branch_id"])
            flash(f"Loan {loan_id} marked as REJECTED.", "info")

        elif action == "DISBURSE":
            # Disburse funds into the customer's account on their branch
            amount = loan["approved_amount"] or loan["requested_amount"]
            b_id = loan["branch_id"]
            acc_num = loan["account_number"]

            b_conn = get_branch_connection(b_id)
            try:
                cur_b = b_conn.cursor()
                cur_b.execute("SELECT balance, version FROM accounts WHERE account_number = ?", (acc_num,))
                acc = cur_b.fetchone()
                new_bal = acc["balance"] + amount

                b_conn.execute("UPDATE accounts SET balance = ?, version = version + 1 WHERE account_number = ?", (new_bal, acc_num))
                b_conn.execute(
                    """INSERT INTO transactions (tx_id, global_tx_id, account_number, type, amount, balance_after, description)
                       VALUES (?, NULL, ?, 'LOAN_DISBURSE', ?, ?, ?)""",
                    (f"DISB-{loan_id}", acc_num, amount, new_bal, f"Disbursement for {loan_id}")
                )
                b_conn.commit()
            finally:
                b_conn.close()

            coord_conn.execute("UPDATE global_loans SET status = 'DISBURSED' WHERE loan_id = ?", (loan_id,))
            coord_conn.commit()

            log_audit_event(user["username"], user["role"], "LOAN_DISBURSED", f"Disbursed ${amount:.2f} for loan {loan_id} to {acc_num}", b_id)
            flash(f"Loan {loan_id} disbursed! ${amount:.2f} credited to account {acc_num} in branch {b_id}.", "success")

    finally:
        coord_conn.close()

    return redirect(url_for("loan.list_loans"))
