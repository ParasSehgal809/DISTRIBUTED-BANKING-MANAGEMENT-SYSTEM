import time
from typing import Dict, List, Any, Optional
from app.config import BRANCHES
from app.database.connection import get_coordinator_connection, get_branch_connection

class DistributedQueryProcessor:
    """
    Distributed Query Processing & Optimization Engine.
    
    ADBMS Concepts Implemented:
      1. Query Decomposition: Breaks a global query into subqueries targeting fragments.
      2. Data Localization: Maps global relations (Accounts, Transactions) to physical fragments.
      3. Predicate Pushdown: Evaluates WHERE clauses directly at branch nodes to minimize network transmission.
      4. Distributed Aggregation: Partitions aggregation (SUM, COUNT) locally before computing global aggregate.
      5. Execution Plan Tracking: Visualizes operator trees, network hops, and execution timings.
    """

    @staticmethod
    def execute_global_account_search(min_balance: float = 0.0, account_type: Optional[str] = None) -> Dict[str, Any]:
        """
        Distributed Query: SELECT * FROM Accounts WHERE balance >= :min_balance
        Demonstrates Predicate Pushdown & Horizontal Fragment Reconstruction.
        """
        start_time = time.time()
        plan_steps = []
        plan_steps.append({
            "step": 1,
            "operator": "PARSE_AND_LOCALIZE",
            "node": "COORDINATOR",
            "description": f"Decomposed global query for Accounts with balance >= ${min_balance:.2f}" + (f" and type '{account_type}'" if account_type else ""),
            "duration_ms": round((time.time() - start_time) * 1000, 2)
        })

        subqueries = []
        combined_results = []
        total_bytes = 0

        # Push subquery to all 3 branch nodes in parallel/sequence
        for b_id, b_meta in BRANCHES.items():
            sub_start = time.time()
            sql = "SELECT account_number, customer_id, branch_id, account_type, balance, status, created_at FROM accounts WHERE balance >= ?"
            params = [min_balance]
            if account_type:
                sql += " AND account_type = ?"
                params.append(account_type)

            b_conn = get_branch_connection(b_id)
            try:
                cur = b_conn.cursor()
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
                sub_duration = round((time.time() - sub_start) * 1000, 2)
                row_bytes = len(str(rows).encode("utf-8"))
                total_bytes += row_bytes

                for r in rows:
                    r["branch_name"] = b_meta["name"]
                    r["branch_city"] = b_meta["city"]
                    r["branch_color"] = b_meta["color"]
                combined_results.extend(rows)

                plan_steps.append({
                    "step": len(plan_steps) + 1,
                    "operator": "SCAN_AND_FILTER",
                    "node": f"BRANCH_{b_id} ({b_meta['name']})",
                    "description": f"Executed subquery on local fragment. Found {len(rows)} qualifying rows.",
                    "rows_returned": len(rows),
                    "bytes_transferred": row_bytes,
                    "duration_ms": sub_duration
                })
            finally:
                b_conn.close()

        # Step: Coordinator Distributed Union & Sorting
        union_start = time.time()
        combined_results.sort(key=lambda x: x["balance"], reverse=True)

        # Reconstruct customer names via Join with Coordinator customers_global
        coord_conn = get_coordinator_connection()
        try:
            cur = coord_conn.cursor()
            cur.execute("SELECT customer_id, full_name, email FROM customers_global")
            c_map = {r["customer_id"]: dict(r) for r in cur.fetchall()}
            for acc in combined_results:
                cust = c_map.get(acc["customer_id"], {})
                acc["customer_name"] = cust.get("full_name", "Unknown")
                acc["customer_email"] = cust.get("email", "")
        finally:
            coord_conn.close()

        plan_steps.append({
            "step": len(plan_steps) + 1,
            "operator": "MATERIALIZE_AND_UNION",
            "node": "COORDINATOR",
            "description": f"Merged {len(combined_results)} rows from all branch fragments. Augmented with customer demographics.",
            "duration_ms": round((time.time() - union_start) * 1000, 2)
        })

        total_time = round((time.time() - start_time) * 1000, 2)

        return {
            "query_type": "DISTRIBUTED_HORIZONTAL_UNION",
            "total_execution_time_ms": total_time,
            "total_rows": len(combined_results),
            "total_bytes_transferred": total_bytes,
            "execution_plan": plan_steps,
            "results": combined_results
        }

    @staticmethod
    def execute_distributed_aggregation() -> Dict[str, Any]:
        """
        Distributed Query: SELECT SUM(balance), AVG(balance), COUNT(*), MIN(balance), MAX(balance) FROM Accounts
        Demonstrates Partitioned Distributed Aggregation:
          - Coordinator sends local aggregate requests to each branch.
          - Each branch calculates SUM and COUNT locally (Local Reduction).
          - Coordinator computes:
              Global_Sum = SUM(Local_Sum)
              Global_Count = SUM(Local_Count)
              Global_Avg = Global_Sum / Global_Count
        """
        start_time = time.time()
        plan_steps = []
        plan_steps.append({
            "step": 1,
            "operator": "QUERY_DECOMPOSITION",
            "node": "COORDINATOR",
            "description": "Decomposed global aggregation into local branch reductions: SUM(balance) and COUNT(*)",
            "duration_ms": 0.1
        })

        branch_reductions = []
        total_bytes = 0

        for b_id, b_meta in BRANCHES.items():
            b_start = time.time()
            b_conn = get_branch_connection(b_id)
            try:
                cur = b_conn.cursor()
                cur.execute(
                    """SELECT COUNT(*) AS local_count,
                              COALESCE(SUM(balance), 0.0) AS local_sum,
                              COALESCE(MIN(balance), 0.0) AS local_min,
                              COALESCE(MAX(balance), 0.0) AS local_max
                       FROM accounts WHERE status = 'ACTIVE'"""
                )
                r = dict(cur.fetchone())
                r["branch_id"] = b_id
                r["branch_name"] = b_meta["name"]
                r["branch_color"] = b_meta["color"]
                r["local_avg"] = round(r["local_sum"] / r["local_count"], 2) if r["local_count"] > 0 else 0.0
                branch_reductions.append(r)

                bytes_sent = len(str(r).encode())
                total_bytes += bytes_sent

                plan_steps.append({
                    "step": len(plan_steps) + 1,
                    "operator": "LOCAL_AGGREGATION",
                    "node": f"BRANCH_{b_id}",
                    "description": f"Calculated local partial sum (${r['local_sum']:,.2f}) and count ({r['local_count']})",
                    "duration_ms": round((time.time() - b_start) * 1000, 2),
                    "bytes_transferred": bytes_sent
                })
            finally:
                b_conn.close()

        # Coordinator Final Reduction
        coord_start = time.time()
        global_count = sum(r["local_count"] for r in branch_reductions)
        global_sum = sum(r["local_sum"] for r in branch_reductions)
        global_min = min(r["local_min"] for r in branch_reductions) if branch_reductions else 0.0
        global_max = max(r["local_max"] for r in branch_reductions) if branch_reductions else 0.0
        global_avg = round(global_sum / global_count, 2) if global_count > 0 else 0.0

        plan_steps.append({
            "step": len(plan_steps) + 1,
            "operator": "GLOBAL_REDUCTION",
            "node": "COORDINATOR",
            "description": f"Combined branch partial sums into Global Sum (${global_sum:,.2f}) and Global Avg (${global_avg:,.2f})",
            "duration_ms": round((time.time() - coord_start) * 1000, 2)
        })

        total_time = round((time.time() - start_time) * 1000, 2)

        return {
            "query_type": "DISTRIBUTED_PARTITIONED_AGGREGATION",
            "total_execution_time_ms": total_time,
            "total_bytes_transferred": total_bytes,
            "global_metrics": {
                "total_accounts": global_count,
                "total_bank_liquidity": global_sum,
                "average_account_balance": global_avg,
                "minimum_balance": global_min,
                "maximum_balance": global_max
            },
            "branch_reductions": branch_reductions,
            "execution_plan": plan_steps
        }

    @staticmethod
    def execute_global_transaction_audit(keyword: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Distributed Query across all Branch Transaction Ledgers:
        Finds transactions matching optional description/account keywords across all branches.
        """
        start_time = time.time()
        plan_steps = []
        all_txs = []
        total_bytes = 0

        plan_steps.append({
            "step": 1,
            "operator": "PARSE_QUERY",
            "node": "COORDINATOR",
            "description": f"Audit query searching for '{keyword or 'ALL'}' across all branch transaction ledgers.",
            "duration_ms": 0.1
        })

        for b_id, b_meta in BRANCHES.items():
            b_start = time.time()
            sql = "SELECT * FROM transactions"
            params = []
            if keyword:
                sql += " WHERE description LIKE ? OR account_number LIKE ? OR tx_id LIKE ?"
                kw = f"%{keyword}%"
                params = [kw, kw, kw]
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            b_conn = get_branch_connection(b_id)
            try:
                cur = b_conn.cursor()
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
                for r in rows:
                    r["branch_id"] = b_id
                    r["branch_name"] = b_meta["name"]
                    r["branch_color"] = b_meta["color"]
                all_txs.extend(rows)
                b_bytes = len(str(rows).encode())
                total_bytes += b_bytes

                plan_steps.append({
                    "step": len(plan_steps) + 1,
                    "operator": "SCAN_LEDGER",
                    "node": f"BRANCH_{b_id}",
                    "description": f"Retrieved {len(rows)} ledger entries.",
                    "duration_ms": round((time.time() - b_start) * 1000, 2),
                    "bytes_transferred": b_bytes
                })
            finally:
                b_conn.close()

        # Merge and sort at coordinator
        all_txs.sort(key=lambda x: x["timestamp"], reverse=True)
        all_txs = all_txs[:limit]

        plan_steps.append({
            "step": len(plan_steps) + 1,
            "operator": "MERGE_SORT",
            "node": "COORDINATOR",
            "description": f"Merged and sorted {len(all_txs)} global transaction events.",
            "duration_ms": 0.2
        })

        return {
            "query_type": "DISTRIBUTED_LEDGER_AUDIT",
            "total_execution_time_ms": round((time.time() - start_time) * 1000, 2),
            "total_bytes_transferred": total_bytes,
            "total_records": len(all_txs),
            "execution_plan": plan_steps,
            "transactions": all_txs
        }
