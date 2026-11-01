import json
import time
import uuid
from typing import Dict, List, Optional, Tuple, Any
from app.config import BRANCHES
from app.database.connection import get_coordinator_connection, get_branch_connection
from app.core.catalog import GlobalCatalog
from app.core.lock_manager import dlm

class TwoPhaseCommitCoordinator:
    """
    Two-Phase Commit (2PC) Protocol Coordinator Engine.
    
    Guarantees Distributed Transaction Atomicity across autonomous branch nodes:
      Phase 1 (Prepare):
        - Coordinator writes PREPARING to WAL.
        - Sends PREPARE message to all participant branches.
        - Participants check constraints, acquire Exclusive Locks (Strict 2PL),
          write PREPARED to local WAL, and reply VOTE_COMMIT or VOTE_ABORT.
      Phase 2 (Commit/Abort):
        - If all voted COMMIT: Coordinator writes GLOBAL_COMMIT to WAL and sends COMMIT.
        - If any voted ABORT or timeout: Coordinator writes GLOBAL_ABORT to WAL and sends ABORT.
        - Participants execute updates, write COMMITTED/ABORTED to local WAL, and release locks.
    """

    @staticmethod
    def execute_cross_branch_transfer(
        src_account: str,
        dest_account: str,
        amount: float,
        description: str = "Cross-Branch Funds Transfer",
        actor: str = "SYSTEM",
        failure_simulation: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a distributed transfer between accounts in different branches using 2PC.
        Supports failure simulation:
          - 'FAIL_SRC_PREPARE'
          - 'FAIL_DST_PREPARE'
          - 'FAIL_COORDINATOR_CRASH' (leaves transaction in-doubt)
          - 'INSUFFICIENT_FUNDS'
        """
        tx_id = f"2PC-{uuid.uuid4().hex[:10].upper()}"
        start_time = time.time()
        trace_logs = []

        def log_step(phase: str, actor_node: str, action: str, details: str, status: str = "INFO"):
            trace_logs.append({
                "timestamp": round(time.time() - start_time, 4),
                "phase": phase,
                "node": actor_node,
                "action": action,
                "details": details,
                "status": status # SUCCESS, WARNING, DANGER, INFO
            })

        log_step("INIT", "COORDINATOR", "TRANSACTION_START", 
                 f"Initiating 2PC cross-branch transfer of ${amount:.2f} from {src_account} to {dest_account}")

        # 1. Directory Lookup & Branch Resolution
        src_loc = GlobalCatalog.resolve_account_location(src_account)
        dest_loc = GlobalCatalog.resolve_account_location(dest_account)

        if not src_loc or not dest_loc:
            err = f"Account not found in catalog (Src: {src_loc is not None}, Dst: {dest_loc is not None})"
            log_step("INIT", "COORDINATOR", "CATALOG_ERROR", err, "DANGER")
            return {"success": False, "error": err, "tx_id": tx_id, "trace": trace_logs}

        src_branch = src_loc["branch_id"]
        dest_branch = dest_loc["branch_id"]

        log_step("ROUTING", "COORDINATOR", "BRANCH_RESOLVED", 
                 f"Source: {src_account} on Branch {src_branch} | Destination: {dest_account} on Branch {dest_branch}")

        # 2. Coordinator writes INITIAL record to Central WAL
        coord_conn = get_coordinator_connection()
        try:
            payload = {
                "src_account": src_account, "dest_account": dest_account,
                "src_branch": src_branch, "dest_branch": dest_branch,
                "amount": amount, "description": description, "actor": actor
            }
            coord_conn.execute(
                """INSERT INTO coordinator_wal 
                   (tx_id, tx_type, state, source_branch, dest_branch, source_account, dest_account, amount, payload_json)
                   VALUES (?, 'CROSS_BRANCH_TRANSFER', 'PREPARING', ?, ?, ?, ?, ?, ?)""",
                (tx_id, src_branch, dest_branch, src_account, dest_account, amount, json.dumps(payload))
            )
            coord_conn.commit()
            log_step("PHASE_1_PREPARE", "COORDINATOR", "WAL_LOGGED", 
                     f"Coordinator logged state 'PREPARING' to coordinator_wal table for Tx {tx_id}")
        finally:
            coord_conn.close()

        # -------------------------------------------------------------
        # PHASE 1: PREPARE PHASE
        # -------------------------------------------------------------
        votes = {}

        # 1A. Prepare Source Branch (Debit Participant)
        log_step("PHASE_1_PREPARE", "COORDINATOR -> " + src_branch, "SEND_PREPARE", 
                 f"Sent PREPARE request to debit branch {src_branch}")
        
        if failure_simulation == "FAIL_SRC_PREPARE":
            votes[src_branch] = "VOTE_ABORT"
            log_step("PHASE_1_PREPARE", src_branch, "SIMULATED_FAILURE", 
                     f"Simulated hardware/network failure at source branch {src_branch}!", "DANGER")
        else:
            vote_src, reason_src = TwoPhaseCommitCoordinator._participant_prepare_debit(
                tx_id, src_branch, src_account, amount, log_step
            )
            votes[src_branch] = vote_src

        # 1B. Prepare Destination Branch (Credit Participant)
        if votes[src_branch] == "VOTE_COMMIT":
            log_step("PHASE_1_PREPARE", "COORDINATOR -> " + dest_branch, "SEND_PREPARE", 
                     f"Sent PREPARE request to credit branch {dest_branch}")
            
            if failure_simulation == "FAIL_DST_PREPARE":
                votes[dest_branch] = "VOTE_ABORT"
                log_step("PHASE_1_PREPARE", dest_branch, "SIMULATED_FAILURE", 
                         f"Simulated network timeout at destination branch {dest_branch}!", "DANGER")
            else:
                vote_dst, reason_dst = TwoPhaseCommitCoordinator._participant_prepare_credit(
                    tx_id, dest_branch, dest_account, log_step
                )
                votes[dest_branch] = vote_dst
        else:
            votes[dest_branch] = "VOTE_ABORT"

        # -------------------------------------------------------------
        # COORDINATOR DECISION POINT
        # -------------------------------------------------------------
        all_commit = (votes.get(src_branch) == "VOTE_COMMIT" and votes.get(dest_branch) == "VOTE_COMMIT")
        decision = "GLOBAL_COMMIT" if all_commit else "GLOBAL_ABORT"

        log_step("DECISION", "COORDINATOR", "VOTES_TALLIED", 
                 f"Votes received: {src_branch}={votes.get(src_branch)}, {dest_branch}={votes.get(dest_branch)}. Decision: {decision}",
                 "SUCCESS" if all_commit else "WARNING")

        # Check for simulated coordinator crash before writing commit
        if failure_simulation == "FAIL_COORDINATOR_CRASH":
            log_step("CRASH_INJECTION", "COORDINATOR", "SIMULATED_COORDINATOR_CRASH", 
                     "Coordinator process crashed immediately before writing commit decision! Transaction is left in 'PREPARING' state (In-Doubt).", "DANGER")
            return {
                "success": False,
                "tx_id": tx_id,
                "decision": "IN_DOUBT_CRASHED",
                "message": "Simulated coordinator crash. Transaction in-doubt. Run Crash Recovery to resolve.",
                "trace": trace_logs
            }

        # Write decision to coordinator WAL
        coord_conn = get_coordinator_connection()
        try:
            coord_conn.execute(
                "UPDATE coordinator_wal SET state = ?, updated_at = CURRENT_TIMESTAMP WHERE tx_id = ?",
                (decision, tx_id)
            )
            coord_conn.commit()
            log_step("DECISION", "COORDINATOR", "WAL_DECISION_COMMITTED", 
                     f"Coordinator durably recorded '{decision}' in central WAL.")
        finally:
            coord_conn.close()

        # -------------------------------------------------------------
        # PHASE 2: COMMIT / ABORT PHASE
        # -------------------------------------------------------------
        if decision == "GLOBAL_COMMIT":
            # Apply Debit on Source
            TwoPhaseCommitCoordinator._participant_commit_debit(tx_id, src_branch, src_account, amount, dest_account, dest_branch, log_step)
            # Apply Credit on Dest
            TwoPhaseCommitCoordinator._participant_commit_credit(tx_id, dest_branch, dest_account, amount, src_account, src_branch, log_step)
            
            # Release DLM Locks (Strict 2PL Shrinking Phase)
            dlm.release_locks_for_tx(tx_id)
            log_step("PHASE_2_COMMIT", "DLM", "LOCKS_RELEASED", 
                     f"Strict 2PL: All Exclusive locks released for tx {tx_id}", "SUCCESS")

            # Finalize coordinator WAL
            coord_conn = get_coordinator_connection()
            try:
                coord_conn.execute("UPDATE coordinator_wal SET state = 'COMMITTED' WHERE tx_id = ?", (tx_id,))
                coord_conn.commit()
            finally:
                coord_conn.close()

            log_step("TERMINATION", "COORDINATOR", "TRANSACTION_SUCCESS", 
                     f"2PC Distributed Transaction {tx_id} committed successfully across all nodes.", "SUCCESS")
            return {"success": True, "tx_id": tx_id, "decision": "COMMITTED", "trace": trace_logs}

        else:
            # Abort on Source
            TwoPhaseCommitCoordinator._participant_abort(tx_id, src_branch, src_account, log_step)
            # Abort on Dest
            TwoPhaseCommitCoordinator._participant_abort(tx_id, dest_branch, dest_account, log_step)

            # Release DLM Locks
            dlm.release_locks_for_tx(tx_id)
            log_step("PHASE_2_ABORT", "DLM", "LOCKS_RELEASED", 
                     f"All locks released after transaction abort for {tx_id}", "WARNING")

            # Finalize coordinator WAL
            coord_conn = get_coordinator_connection()
            try:
                coord_conn.execute("UPDATE coordinator_wal SET state = 'ABORTED' WHERE tx_id = ?", (tx_id,))
                coord_conn.commit()
            finally:
                coord_conn.close()

            log_step("TERMINATION", "COORDINATOR", "TRANSACTION_ABORTED", 
                     f"2PC Distributed Transaction {tx_id} aborted cleanly. No balances altered.", "DANGER")
            return {"success": False, "tx_id": tx_id, "decision": "ABORTED", "trace": trace_logs}

    # =========================================================
    # Participant Subroutines (Simulating Branch Database Nodes)
    # =========================================================

    @staticmethod
    def _participant_prepare_debit(tx_id: str, branch_id: str, account_number: str, amount: float, log_step) -> Tuple[str, str]:
        """Participant prepare on debit branch: checks balance, acquires lock, writes PREPARED to local WAL."""
        res_id = f"acc:{account_number}"
        acquired, msg = dlm.acquire_lock(tx_id, res_id, "X", timeout=2.0)
        if not acquired:
            log_step("PHASE_1_PREPARE", branch_id, "LOCK_CONFLICT", f"Failed to acquire Exclusive Lock on {res_id}: {msg}", "DANGER")
            return "VOTE_ABORT", "Lock conflict"

        log_step("PHASE_1_PREPARE", branch_id, "LOCK_ACQUIRED", f"Acquired Exclusive Lock on {res_id}", "SUCCESS")

        b_conn = get_branch_connection(branch_id)
        try:
            cur = b_conn.cursor()
            cur.execute("SELECT balance, status FROM accounts WHERE account_number = ?", (account_number,))
            acc = cur.fetchone()

            if not acc:
                log_step("PHASE_1_PREPARE", branch_id, "ACCOUNT_NOT_FOUND", f"Account {account_number} not found on node", "DANGER")
                return "VOTE_ABORT", "Account not found"

            if acc["status"] != "ACTIVE":
                log_step("PHASE_1_PREPARE", branch_id, "INACTIVE_ACCOUNT", f"Account {account_number} is {acc['status']}", "DANGER")
                return "VOTE_ABORT", "Account is not active"

            if acc["balance"] < amount:
                log_step("PHASE_1_PREPARE", branch_id, "INSUFFICIENT_FUNDS", 
                         f"Balance ${acc['balance']:.2f} < requested ${amount:.2f}", "DANGER")
                return "VOTE_ABORT", "Insufficient funds"

            # Write PREPARED to local branch WAL
            b_conn.execute(
                "INSERT INTO branch_wal (tx_id, state, account_number, delta) VALUES (?, 'PREPARED', ?, ?)",
                (tx_id, account_number, -amount)
            )
            b_conn.commit()
            log_step("PHASE_1_PREPARE", branch_id, "VOTE_COMMIT", 
                     f"Wrote PREPARED to local branch_wal. Voted COMMIT (Balance: ${acc['balance']:.2f})", "SUCCESS")
            return "VOTE_COMMIT", "OK"
        except Exception as e:
            log_step("PHASE_1_PREPARE", branch_id, "ERROR", str(e), "DANGER")
            return "VOTE_ABORT", str(e)
        finally:
            b_conn.close()

    @staticmethod
    def _participant_prepare_credit(tx_id: str, branch_id: str, account_number: str, log_step) -> Tuple[str, str]:
        """Participant prepare on credit branch: checks destination account, acquires lock, writes PREPARED."""
        res_id = f"acc:{account_number}"
        acquired, msg = dlm.acquire_lock(tx_id, res_id, "X", timeout=2.0)
        if not acquired:
            log_step("PHASE_1_PREPARE", branch_id, "LOCK_CONFLICT", f"Failed to acquire Exclusive Lock on {res_id}", "DANGER")
            return "VOTE_ABORT", "Lock conflict"

        log_step("PHASE_1_PREPARE", branch_id, "LOCK_ACQUIRED", f"Acquired Exclusive Lock on {res_id}", "SUCCESS")

        b_conn = get_branch_connection(branch_id)
        try:
            cur = b_conn.cursor()
            cur.execute("SELECT status FROM accounts WHERE account_number = ?", (account_number,))
            acc = cur.fetchone()

            if not acc:
                log_step("PHASE_1_PREPARE", branch_id, "ACCOUNT_NOT_FOUND", f"Destination account {account_number} not found", "DANGER")
                return "VOTE_ABORT", "Account not found"

            if acc["status"] != "ACTIVE":
                log_step("PHASE_1_PREPARE", branch_id, "INACTIVE_ACCOUNT", f"Destination account is {acc['status']}", "DANGER")
                return "VOTE_ABORT", "Account is not active"

            # Write PREPARED to local branch WAL
            b_conn.execute(
                "INSERT INTO branch_wal (tx_id, state, account_number, delta) VALUES (?, 'PREPARED', ?, ?)",
                (tx_id, account_number, 0.0)
            )
            b_conn.commit()
            log_step("PHASE_1_PREPARE", branch_id, "VOTE_COMMIT", 
                     f"Destination account verified. Wrote PREPARED to branch_wal. Voted COMMIT.", "SUCCESS")
            return "VOTE_COMMIT", "OK"
        except Exception as e:
            log_step("PHASE_1_PREPARE", branch_id, "ERROR", str(e), "DANGER")
            return "VOTE_ABORT", str(e)
        finally:
            b_conn.close()

    @staticmethod
    def _participant_commit_debit(tx_id: str, branch_id: str, account_number: str, amount: float, dest_acc: str, dest_branch: str, log_step):
        b_conn = get_branch_connection(branch_id)
        try:
            cur = b_conn.cursor()
            cur.execute("SELECT balance, version FROM accounts WHERE account_number = ?", (account_number,))
            acc = cur.fetchone()
            new_bal = acc["balance"] - amount
            new_version = acc["version"] + 1

            # Update account
            b_conn.execute(
                "UPDATE accounts SET balance = ?, version = ? WHERE account_number = ?",
                (new_bal, new_version, account_number)
            )

            # Insert transaction ledger record
            sub_tx = f"TX-DEB-{tx_id[-6:]}"
            b_conn.execute(
                """INSERT INTO transactions 
                   (tx_id, global_tx_id, account_number, type, amount, balance_after, related_account, related_branch, description)
                   VALUES (?, ?, ?, 'DEBIT', ?, ?, ?, ?, '2PC Cross-Branch Debit')""",
                (sub_tx, tx_id, account_number, amount, new_bal, dest_acc, dest_branch)
            )

            # Update local branch WAL
            b_conn.execute("UPDATE branch_wal SET state = 'COMMITTED' WHERE tx_id = ? AND account_number = ?", (tx_id, account_number))
            b_conn.commit()

            log_step("PHASE_2_COMMIT", branch_id, "DEBIT_APPLIED", 
                     f"Debited ${amount:.2f} from {account_number}. New balance: ${new_bal:.2f}. Updated local WAL to COMMITTED.", "SUCCESS")
        finally:
            b_conn.close()

    @staticmethod
    def _participant_commit_credit(tx_id: str, branch_id: str, account_number: str, amount: float, src_acc: str, src_branch: str, log_step):
        b_conn = get_branch_connection(branch_id)
        try:
            cur = b_conn.cursor()
            cur.execute("SELECT balance, version FROM accounts WHERE account_number = ?", (account_number,))
            acc = cur.fetchone()
            new_bal = acc["balance"] + amount
            new_version = acc["version"] + 1

            # Update account
            b_conn.execute(
                "UPDATE accounts SET balance = ?, version = ? WHERE account_number = ?",
                (new_bal, new_version, account_number)
            )

            # Insert transaction ledger record
            sub_tx = f"TX-CRE-{tx_id[-6:]}"
            b_conn.execute(
                """INSERT INTO transactions 
                   (tx_id, global_tx_id, account_number, type, amount, balance_after, related_account, related_branch, description)
                   VALUES (?, ?, ?, 'CREDIT', ?, ?, ?, ?, '2PC Cross-Branch Credit')""",
                (sub_tx, tx_id, account_number, amount, new_bal, src_acc, src_branch)
            )

            # Update local branch WAL
            b_conn.execute("UPDATE branch_wal SET state = 'COMMITTED' WHERE tx_id = ? AND account_number = ?", (tx_id, account_number))
            b_conn.commit()

            log_step("PHASE_2_COMMIT", branch_id, "CREDIT_APPLIED", 
                     f"Credited ${amount:.2f} to {account_number}. New balance: ${new_bal:.2f}. Updated local WAL to COMMITTED.", "SUCCESS")
        finally:
            b_conn.close()

    @staticmethod
    def _participant_abort(tx_id: str, branch_id: str, account_number: str, log_step):
        try:
            b_conn = get_branch_connection(branch_id)
            try:
                b_conn.execute("UPDATE branch_wal SET state = 'ABORTED' WHERE tx_id = ?", (tx_id,))
                b_conn.commit()
                log_step("PHASE_2_ABORT", branch_id, "ABORT_RECORDED", 
                         f"Participant {branch_id} marked local WAL state as ABORTED for tx {tx_id}", "WARNING")
            finally:
                b_conn.close()
        except Exception as e:
            log_step("PHASE_2_ABORT", branch_id, "ERROR", str(e), "DANGER")

    # =========================================================
    # Intra-Branch Transfer (Local ACID Transaction)
    # =========================================================

    @staticmethod
    def execute_intra_branch_transfer(
        branch_id: str,
        src_account: str,
        dest_account: str,
        amount: float,
        description: str = "Intra-Branch Transfer"
    ) -> Dict[str, Any]:
        """
        Executes a transfer between two accounts located within the SAME branch database.
        Runs as a single local ACID transaction using SQLite savepoint/commit.
        """
        tx_id = f"LOCAL-{uuid.uuid4().hex[:8].upper()}"
        res_src = f"acc:{src_account}"
        res_dst = f"acc:{dest_account}"

        # Acquire DLM locks
        dlm.acquire_lock(tx_id, res_src, "X", timeout=2.0)
        dlm.acquire_lock(tx_id, res_dst, "X", timeout=2.0)

        b_conn = get_branch_connection(branch_id)
        try:
            cur = b_conn.cursor()
            cur.execute("SELECT balance FROM accounts WHERE account_number = ? AND status = 'ACTIVE'", (src_account,))
            src = cur.fetchone()
            cur.execute("SELECT balance FROM accounts WHERE account_number = ? AND status = 'ACTIVE'", (dest_account,))
            dst = cur.fetchone()

            if not src or not dst:
                return {"success": False, "error": "One or both accounts do not exist or are inactive"}

            if src["balance"] < amount:
                return {"success": False, "error": f"Insufficient funds (Balance: ${src['balance']:.2f})"}

            new_src = src["balance"] - amount
            new_dst = dst["balance"] + amount

            # Atomic transaction
            b_conn.execute("UPDATE accounts SET balance = balance - ?, version = version + 1 WHERE account_number = ?", (amount, src_account))
            b_conn.execute("UPDATE accounts SET balance = balance + ?, version = version + 1 WHERE account_number = ?", (amount, dest_account))

            # Ledger records
            b_conn.execute(
                """INSERT INTO transactions (tx_id, global_tx_id, account_number, type, amount, balance_after, related_account, related_branch, description)
                   VALUES (?, ?, ?, 'DEBIT', ?, ?, ?, ?, ?)""",
                (f"TX-LOC-D-{tx_id}", tx_id, src_account, amount, new_src, dest_account, branch_id, description)
            )
            b_conn.execute(
                """INSERT INTO transactions (tx_id, global_tx_id, account_number, type, amount, balance_after, related_account, related_branch, description)
                   VALUES (?, ?, ?, 'CREDIT', ?, ?, ?, ?, ?)""",
                (f"TX-LOC-C-{tx_id}", tx_id, dest_account, amount, new_dst, src_account, branch_id, description)
            )
            b_conn.commit()
            return {"success": True, "tx_id": tx_id, "message": f"Successfully transferred ${amount:.2f} locally within {branch_id}"}
        except Exception as e:
            b_conn.rollback()
            return {"success": False, "error": str(e)}
        finally:
            dlm.release_locks_for_tx(tx_id)
            b_conn.close()
