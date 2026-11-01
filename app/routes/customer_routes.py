import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app.core.security import login_required, roles_required, get_current_user, log_audit_event
from app.core.catalog import GlobalCatalog
from app.config import BRANCHES, ROLE_ADMIN, ROLE_BRANCH_MANAGER, ROLE_TELLER
from app.database.connection import get_coordinator_connection, get_branch_connection

customer_bp = Blueprint("customer", __name__, url_prefix="/customers")

@customer_bp.route("/")
@login_required
def list_customers():
    customers = GlobalCatalog.reconstruct_all_customers()
    return render_template("customers.html", customers=customers, branches=BRANCHES)

@customer_bp.route("/<customer_id>")
@login_required
def view_customer(customer_id: str):
    customer = GlobalCatalog.reconstruct_customer(customer_id)
    if not customer:
        flash("Customer not found.", "danger")
        return redirect(url_for("customer.list_customers"))

    # Fetch accounts belonging to this customer across all branches
    all_accounts = GlobalCatalog.reconstruct_all_accounts()
    customer_accounts = [a for a in all_accounts if a["customer_id"] == customer_id]
    total_wealth = sum(a["balance"] for a in customer_accounts)

    return render_template(
        "customer_detail.html",
        customer=customer,
        accounts=customer_accounts,
        total_wealth=total_wealth,
        branches=BRANCHES
    )

@customer_bp.route("/create", methods=["GET", "POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_BRANCH_MANAGER, ROLE_TELLER)
def create_customer():
    user = get_current_user()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        gov_id_type = request.form.get("gov_id_type", "PASSPORT")
        gov_id_number = request.form.get("gov_id_number", "").strip()
        home_address = request.form.get("home_address", "").strip()
        
        branch_id = request.form.get("branch_id")
        occupation = request.form.get("occupation", "Professional").strip()
        annual_income = float(request.form.get("annual_income", 50000.0))
        credit_score = int(request.form.get("credit_score", 700))

        if branch_id not in BRANCHES:
            flash("Invalid branch selected.", "danger")
            return redirect(url_for("customer.create_customer"))

        customer_id = f"CUST-{uuid.uuid4().hex[:6].upper()}"

        try:
            # 1. Insert Vertical Fragment 1 into Central Coordinator (Identity & Demographics)
            coord_conn = get_coordinator_connection()
            try:
                coord_conn.execute(
                    """INSERT INTO customers_global
                       (customer_id, full_name, email, phone, gov_id_type, gov_id_number, home_address)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (customer_id, full_name, email, phone, gov_id_type, gov_id_number, home_address)
                )
                coord_conn.commit()
            finally:
                coord_conn.close()

            # 2. Insert Vertical Fragment 2 into Designated Branch Node (Financial Profile)
            risk_rating = "LOW" if credit_score > 700 else ("MEDIUM" if credit_score > 600 else "HIGH")
            b_conn = get_branch_connection(branch_id)
            try:
                b_conn.execute(
                    """INSERT INTO customers_local
                       (customer_id, kyc_status, credit_score, occupation, annual_income, risk_rating)
                       VALUES (?, 'VERIFIED', ?, ?, ?, ?)""",
                    (customer_id, credit_score, occupation, annual_income, risk_rating)
                )
                b_conn.commit()
            finally:
                b_conn.close()

            log_audit_event(
                user["username"], user["role"], "CUSTOMER_CREATED",
                f"Created customer {customer_id} ({full_name}) with vertical fragmentation across Coordinator and {branch_id}",
                branch_id
            )

            flash(f"Customer {full_name} ({customer_id}) onboarded successfully! Vertically fragmented across Coordinator and Branch {branch_id}.", "success")
            return redirect(url_for("customer.view_customer", customer_id=customer_id))
        except Exception as e:
            flash(f"Error creating customer: {e}", "danger")

    return render_template("customer_create.html", branches=BRANCHES)

@customer_bp.route("/<customer_id>/kyc-status", methods=["POST"])
@login_required
@roles_required(ROLE_ADMIN, ROLE_BRANCH_MANAGER)
def update_kyc(customer_id: str):
    new_status = request.form.get("kyc_status", "VERIFIED")
    branch_id = request.form.get("branch_id")
    if branch_id in BRANCHES:
        b_conn = get_branch_connection(branch_id)
        try:
            b_conn.execute("UPDATE customers_local SET kyc_status = ? WHERE customer_id = ?", (new_status, customer_id))
            b_conn.commit()
            flash(f"KYC status updated to {new_status} on {branch_id}.", "info")
        finally:
            b_conn.close()
    return redirect(url_for("customer.view_customer", customer_id=customer_id))
