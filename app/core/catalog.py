from typing import Dict, List, Optional, Any
from app.config import BRANCHES
from app.database.connection import get_coordinator_connection, get_branch_connection, get_all_branch_connections

class GlobalCatalog:
    """
    Global Data Dictionary (GDD) & Distributed Fragmentation Manager.
    Implements:
      - Horizontal Fragmentation: Accounts & Transactions fragmented across branch DBs.
      - Vertical Fragmentation: Customers split into Central Identity and Branch Financial Profiles.
      - Data Allocation & Directory Routing: Resolves logical entities to physical nodes.
    """

    @staticmethod
    def get_branches() -> List[Dict[str, Any]]:
        """Returns metadata for all registered branch nodes."""
        conn = get_coordinator_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM branches ORDER BY branch_id ASC")
            branches = [dict(r) for r in cur.fetchall()]
            for b in branches:
                b_info = BRANCHES.get(b["branch_id"], {})
                b["color"] = b_info.get("color", "gray")
            return branches
        finally:
            conn.close()

    @staticmethod
    def resolve_account_location(account_number: str) -> Optional[Dict[str, Any]]:
        """
        Directory Routing Lookup:
        Finds which physical branch database hosts the given account's horizontal fragment.
        """
        conn = get_coordinator_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT account_number, customer_id, branch_id, account_type, status, created_at
                   FROM global_account_directory WHERE account_number = ?""",
                (account_number,)
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def reconstruct_customer(customer_id: str) -> Optional[Dict[str, Any]]:
        """
        Vertical Fragmentation Reconstruction:
        Reconstructs a single customer record by performing a Distributed Join:
        Customer = (customers_global ON Coordinator) ⨝ (customers_local ON Branch)
        """
        coord_conn = get_coordinator_connection()
        try:
            # 1. Fetch Vertical Fragment 1 (Identity from Central Coordinator)
            cur = coord_conn.cursor()
            cur.execute("SELECT * FROM customers_global WHERE customer_id = ?", (customer_id,))
            global_frag = cur.fetchone()
            if not global_frag:
                return None
            global_data = dict(global_frag)

            # 2. Search Branch databases for Vertical Fragment 2 (Financial Profile)
            local_data = None
            found_branch = None
            for b_id in BRANCHES.keys():
                b_conn = get_branch_connection(b_id)
                try:
                    b_cur = b_conn.cursor()
                    b_cur.execute("SELECT * FROM customers_local WHERE customer_id = ?", (customer_id,))
                    row = b_cur.fetchone()
                    if row:
                        local_data = dict(row)
                        found_branch = b_id
                        break
                finally:
                    b_conn.close()

            # Merge Vertical Fragments
            result = dict(global_data)
            if local_data:
                result.update(local_data)
                result["primary_branch_id"] = found_branch
            else:
                result["kyc_status"] = "UNKNOWN"
                result["credit_score"] = 650
                result["occupation"] = "N/A"
                result["annual_income"] = 0.0
                result["risk_rating"] = "UNKNOWN"
                result["primary_branch_id"] = None

            return result
        finally:
            coord_conn.close()

    @staticmethod
    def reconstruct_all_customers() -> List[Dict[str, Any]]:
        """
        Distributed Vertical Reconstruction:
        Fetches all Identity fragments from Coordinator, then joins each with
        its corresponding Financial profile from the appropriate Branch node.
        """
        coord_conn = get_coordinator_connection()
        try:
            cur = coord_conn.cursor()
            cur.execute("SELECT * FROM customers_global ORDER BY customer_id ASC")
            global_rows = [dict(r) for r in cur.fetchall()]

            # Fetch local fragments from all branches
            branch_profiles: Dict[str, Dict[str, Any]] = {}
            for b_id in BRANCHES.keys():
                b_conn = get_branch_connection(b_id)
                try:
                    b_cur = b_conn.cursor()
                    b_cur.execute("SELECT * FROM customers_local")
                    for row in b_cur.fetchall():
                        r_dict = dict(row)
                        r_dict["branch_id"] = b_id
                        branch_profiles[r_dict["customer_id"]] = r_dict
                finally:
                    b_conn.close()

            # Perform in-memory distributed JOIN
            reconstructed = []
            for g in global_rows:
                cid = g["customer_id"]
                full_rec = dict(g)
                if cid in branch_profiles:
                    full_rec.update(branch_profiles[cid])
                else:
                    full_rec["kyc_status"] = "PENDING"
                    full_rec["credit_score"] = 600
                    full_rec["occupation"] = "Not Provided"
                    full_rec["annual_income"] = 0.0
                    full_rec["risk_rating"] = "MEDIUM"
                    full_rec["branch_id"] = "NONE"
                reconstructed.append(full_rec)

            return reconstructed
        finally:
            coord_conn.close()

    @staticmethod
    def reconstruct_all_accounts(branch_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Distributed Horizontal Reconstruction (UNION ALL):
        Accounts = Accounts_BR001 ∪ Accounts_BR002 ∪ Accounts_BR003
        Optionally filters for a specific horizontal fragment if branch_filter is set.
        """
        results = []
        target_branches = [branch_filter] if branch_filter and branch_filter in BRANCHES else list(BRANCHES.keys())

        for b_id in target_branches:
            b_conn = get_branch_connection(b_id)
            try:
                cur = b_conn.cursor()
                cur.execute(
                    """SELECT account_number, customer_id, branch_id, account_type, 
                              balance, currency, status, version, created_at 
                       FROM accounts ORDER BY account_number ASC"""
                )
                rows = [dict(r) for r in cur.fetchall()]
                for r in rows:
                    r["branch_name"] = BRANCHES[b_id]["name"]
                    r["branch_color"] = BRANCHES[b_id]["color"]
                results.extend(rows)
            finally:
                b_conn.close()

        # Augment with customer full names from coordinator
        if results:
            coord_conn = get_coordinator_connection()
            try:
                c_cur = coord_conn.cursor()
                c_cur.execute("SELECT customer_id, full_name, email FROM customers_global")
                cust_map = {r["customer_id"]: dict(r) for r in c_cur.fetchall()}
                for acc in results:
                    c_info = cust_map.get(acc["customer_id"], {})
                    acc["customer_name"] = c_info.get("full_name", "Unknown")
                    acc["customer_email"] = c_info.get("email", "")
            finally:
                coord_conn.close()

        return results

    @staticmethod
    def get_account_from_branch(account_number: str) -> Optional[Dict[str, Any]]:
        """Finds account by resolving its branch first, then querying that specific node."""
        loc = GlobalCatalog.resolve_account_location(account_number)
        if not loc:
            return None
        b_id = loc["branch_id"]
        b_conn = get_branch_connection(b_id)
        try:
            cur = b_conn.cursor()
            cur.execute("SELECT * FROM accounts WHERE account_number = ?", (account_number,))
            row = cur.fetchone()
            if row:
                res = dict(row)
                res["branch_name"] = BRANCHES[b_id]["name"]
                return res
            return None
        finally:
            b_conn.close()

    @staticmethod
    def get_system_summary() -> Dict[str, Any]:
        """Calculates global aggregation metrics across all nodes."""
        branches = GlobalCatalog.get_branches()
        branch_stats = []
        total_accounts = 0
        total_balance = 0.0

        for b in branches:
            b_id = b["branch_id"]
            b_conn = get_branch_connection(b_id)
            try:
                cur = b_conn.cursor()
                cur.execute("SELECT COUNT(*) AS cnt, COALESCE(SUM(balance), 0.0) AS total FROM accounts")
                row = cur.fetchone()
                cnt = row["cnt"]
                bal = row["total"]
                total_accounts += cnt
                total_balance += bal
                branch_stats.append({
                    "branch_id": b_id,
                    "name": b["name"],
                    "city": b["city"],
                    "color": b.get("color", "blue"),
                    "account_count": cnt,
                    "total_balance": bal,
                    "status": b["status"]
                })
            finally:
                b_conn.close()

        coord_conn = get_coordinator_connection()
        try:
            cur = coord_conn.cursor()
            cur.execute("SELECT COUNT(*) FROM customers_global")
            total_customers = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM global_loans")
            total_loans = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM coordinator_wal WHERE state = 'COMMITTED'")
            total_2pc_success = cur.fetchone()[0]
        finally:
            coord_conn.close()

        return {
            "branch_stats": branch_stats,
            "total_accounts": total_accounts,
            "total_balance": total_balance,
            "total_customers": total_customers,
            "total_loans": total_loans,
            "total_2pc_success": total_2pc_success
        }
