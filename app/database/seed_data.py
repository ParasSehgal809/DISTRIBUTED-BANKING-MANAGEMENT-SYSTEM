import sqlite3
import hashlib
from app.config import BRANCHES
from app.database.connection import get_coordinator_connection, get_branch_connection
from app.database.schema import init_all_databases

def hash_password(password: str) -> str:
    """PBKDF2 SHA-256 password hashing."""
    salt = b"adbms_salt_distributed_banking"
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000).hex()

def seed_database():
    """Seeds realistic banking data across central coordinator and branch databases."""
    # Ensure fresh tables
    init_all_databases()

    coord_conn = get_coordinator_connection()
    branch_conns = {b_id: get_branch_connection(b_id) for b_id in BRANCHES}

    try:
        # 1. Seed Branches into Coordinator
        for b_id, b in BRANCHES.items():
            coord_conn.execute(
                """INSERT OR REPLACE INTO branches (branch_id, name, code, city, db_filename, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (b_id, b["name"], b["code"], b["city"], b["db_filename"], b["status"])
            )

        # 2. Seed RBAC Users into Coordinator
        users = [
            ("USR-001", "admin", "admin@bank.com", hash_password("admin123"), "ADMIN", None, None),
            ("USR-002", "mgr_downtown", "manager.downtown@bank.com", hash_password("manager123"), "BRANCH_MANAGER", "BR001", None),
            ("USR-003", "mgr_midtown", "manager.midtown@bank.com", hash_password("manager123"), "BRANCH_MANAGER", "BR002", None),
            ("USR-004", "mgr_uptown", "manager.uptown@bank.com", hash_password("manager123"), "BRANCH_MANAGER", "BR003", None),
            ("USR-005", "teller_downtown", "teller.downtown@bank.com", hash_password("teller123"), "TELLER", "BR001", None),
            ("USR-006", "alice", "alice@customer.com", hash_password("customer123"), "CUSTOMER", "BR001", "CUST-101"),
            ("USR-007", "bob", "bob@customer.com", hash_password("customer123"), "CUSTOMER", "BR001", "CUST-102"),
            ("USR-008", "charlie", "charlie@customer.com", hash_password("customer123"), "CUSTOMER", "BR002", "CUST-103"),
            ("USR-009", "diana", "diana@customer.com", hash_password("customer123"), "CUSTOMER", "BR002", "CUST-104"),
            ("USR-010", "evan", "evan@customer.com", hash_password("customer123"), "CUSTOMER", "BR003", "CUST-105"),
        ]
        for u in users:
            coord_conn.execute(
                """INSERT OR REPLACE INTO global_users 
                   (user_id, username, email, password_hash, role, branch_id, customer_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""", u
            )

        # 3. Seed Vertical Fragment 1: Central Identity (customers_global)
        customers_global = [
            ("CUST-101", "Alice Morgan", "alice@customer.com", "+1-555-0101", "PASSPORT", "P987123", "742 Evergreen Terrace, Downtown"),
            ("CUST-102", "Bob Henderson", "bob@customer.com", "+1-555-0102", "SSN", "987-65-4321", "123 Elm Street, Downtown"),
            ("CUST-103", "Charlie Davis", "charlie@customer.com", "+1-555-0103", "DRIVERS_LICENSE", "DL-44812", "456 Maple Avenue, Midtown"),
            ("CUST-104", "Diana Prince", "diana@customer.com", "+1-555-0104", "PASSPORT", "P441998", "88 Innovation Blvd, Midtown"),
            ("CUST-105", "Evan Wright", "evan@customer.com", "+1-555-0105", "SSN", "123-45-6789", "99 Wall Street, Uptown"),
            ("CUST-106", "Fiona Gallagher", "fiona@customer.com", "+1-555-0106", "DRIVERS_LICENSE", "DL-99120", "12 Broadway St, Uptown")
        ]
        for cg in customers_global:
            coord_conn.execute(
                """INSERT OR REPLACE INTO customers_global
                   (customer_id, full_name, email, phone, gov_id_type, gov_id_number, home_address)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""", cg
            )

        # 4. Seed Vertical Fragment 2: Local Financial Profiles (customers_local on respective branches)
        # Allocation rule: CUST-101, 102 -> BR001; CUST-103, 104 -> BR002; CUST-105, 106 -> BR003
        local_profiles = {
            "BR001": [
                ("CUST-101", "VERIFIED", 760, "Senior Software Engineer", 125000.0, "LOW"),
                ("CUST-102", "VERIFIED", 690, "Marketing Consultant", 85000.0, "LOW")
            ],
            "BR002": [
                ("CUST-103", "VERIFIED", 720, "Financial Analyst", 95000.0, "LOW"),
                ("CUST-104", "VERIFIED", 810, "Enterprise Architect", 185000.0, "LOW")
            ],
            "BR003": [
                ("CUST-105", "VERIFIED", 640, "Startup Founder", 72000.0, "MEDIUM"),
                ("CUST-106", "PENDING", 580, "Freelance Designer", 42000.0, "HIGH")
            ]
        }
        for b_id, profiles in local_profiles.items():
            b_conn = branch_conns[b_id]
            for p in profiles:
                b_conn.execute(
                    """INSERT OR REPLACE INTO customers_local
                       (customer_id, kyc_status, credit_score, occupation, annual_income, risk_rating)
                       VALUES (?, ?, ?, ?, ?, ?)""", p
                )
            b_conn.commit()

        # 5. Seed Horizontal Fragment: Accounts allocated to respective Branch Nodes
        accounts_data = [
            # Branch BR001 (Downtown)
            ("ACC-1001", "CUST-101", "BR001", "SAVINGS", 15450.00),
            ("ACC-1002", "CUST-101", "BR001", "CHECKING", 3200.00),
            ("ACC-1003", "CUST-102", "BR001", "SAVINGS", 8900.00),

            # Branch BR002 (Midtown)
            ("ACC-2001", "CUST-103", "BR002", "SAVINGS", 24800.00),
            ("ACC-2002", "CUST-104", "BR002", "BUSINESS", 150000.00),
            ("ACC-2003", "CUST-104", "BR002", "SAVINGS", 45000.00),

            # Branch BR003 (Uptown)
            ("ACC-3001", "CUST-105", "BR003", "BUSINESS", 62500.00),
            ("ACC-3002", "CUST-106", "BR003", "SAVINGS", 2100.00),
            ("ACC-3003", "CUST-102", "BR003", "SAVINGS", 11300.00) # Bob maintains account in Uptown too
        ]

        for acc_num, cust_id, b_id, acc_type, bal in accounts_data:
            # Insert in central directory
            coord_conn.execute(
                """INSERT OR REPLACE INTO global_account_directory
                   (account_number, customer_id, branch_id, account_type, status)
                   VALUES (?, ?, ?, ?, 'ACTIVE')""",
                (acc_num, cust_id, b_id, acc_type)
            )

            # Insert in branch horizontal fragment
            b_conn = branch_conns[b_id]
            b_conn.execute(
                """INSERT OR REPLACE INTO accounts
                   (account_number, customer_id, branch_id, account_type, balance, status)
                   VALUES (?, ?, ?, ?, ?, 'ACTIVE')""",
                (acc_num, cust_id, b_id, acc_type, bal)
            )

            # Insert initial deposit transaction in local ledger
            b_conn.execute(
                """INSERT OR REPLACE INTO transactions
                   (tx_id, global_tx_id, account_number, type, amount, balance_after, description)
                   VALUES (?, ?, ?, 'DEPOSIT', ?, ?, 'Initial Account Opening Deposit')""",
                (f"TX-INIT-{acc_num}", None, acc_num, bal, bal)
            )
            b_conn.commit()

        # 6. Seed Sample Loans in Coordinator
        loans = [
            ("LOAN-801", "CUST-101", "BR001", "ACC-1001", 25000.0, 25000.0, 5.5, 36, "APPROVED", "Home Solar Renovation", "admin", "Approved based on high credit score 760 and solid assets."),
            ("LOAN-802", "CUST-105", "BR003", "ACC-3001", 50000.0, 0.0, 8.2, 48, "PENDING", "Tech Hardware Inventory Purchase", None, "Awaiting branch manager verification."),
            ("LOAN-803", "CUST-104", "BR002", "ACC-2002", 100000.0, 100000.0, 4.8, 60, "DISBURSED", "Commercial Office Expansion", "admin", "Disbursed via distributed 2PC transaction.")
        ]
        for l in loans:
            coord_conn.execute(
                """INSERT OR REPLACE INTO global_loans
                   (loan_id, customer_id, branch_id, account_number, requested_amount, approved_amount, interest_rate, duration_months, status, purpose, reviewed_by, review_comments)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", l
            )

        # 7. Seed Initial Audit Log
        coord_conn.execute(
            """INSERT INTO audit_logs (actor_username, actor_role, action, branch_id, details)
               VALUES ('SYSTEM', 'ADMIN', 'SYSTEM_BOOTSTRAP', 'GLOBAL', 'Distributed Banking System initialized with 3 branch nodes and coordinator catalog.')"""
        )

        coord_conn.commit()
        print("[+] Seeded coordinator catalog and all 3 branch nodes successfully.")

    finally:
        coord_conn.close()
        for b_conn in branch_conns.values():
            b_conn.close()

if __name__ == "__main__":
    seed_database()
