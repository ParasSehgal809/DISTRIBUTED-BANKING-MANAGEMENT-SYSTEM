import json
import time
from typing import Dict, List, Any
from app.config import BRANCHES
from app.database.connection import get_coordinator_connection, get_branch_connection
from app.core.lock_manager import dlm

class RecoveryManager:
    """
    Distributed Database Recovery & WAL Replay Engine.
    
    ADBMS Concepts Implemented:
      1. Write-Ahead Logging (WAL) protocol: Updates are logged before applying to database.
      2. 2PC Crash Recovery:
         - If Coordinator logged 'GLOBAL_COMMIT': REDO phase forces commit on all branch participants.
         - If Coordinator crashed during 'PREPARING' (no commit record): UNDO phase forces abort.
         - Resolves In-Doubt transactions at participant nodes.
      3. Orphaned Lock Cleanup: Releases any dangling locks left behind after node recovery.
    """

    @staticmethod
    def get_recovery_status() -> Dict[str, Any]:
        """Inspects Coordinator WAL and all Branch WALs for pending or in-doubt transactions."""
        coord_conn = get_coordinator_connection()
        coordinator_records = []
        try:
            cur = coord_conn.cursor()
            cur.execute("SELECT * FROM coordinator_wal ORDER BY created_at DESC LIMIT 20")
            coordinator_records = [dict(r) for r in cur.fetchall()]
        finally:
            coord_conn.close()

        branch_records: Dict[str, List[Dict]] = {}
        for b_id in BRANCHES.keys():
            b_conn = get_branch_connection(b_id)
            try:
                b_cur = b_conn.cursor()
                b_cur.execute("SELECT * FROM branch_wal ORDER BY timestamp DESC LIMIT 20")
                branch_records[b_id] = [dict(r) for r in b_cur.fetchall()]
            finally:
                b_conn.close()

        # Check for in-doubt transactions
        in_doubt = []
        for cr in coordinator_records:
            if cr["state"] in ("PREPARING", "INIT"):
                in_doubt.append({
                    "tx_id": cr["tx_id"],
                    "state": cr["state"],
                    "type": cr["tx_type"],
                    "created_at": cr["created_at"],
                    "recommendation": "UNDO (Rollback and mark ABORTED)"
                })

        return {
            "coordinator_wal": coordinator_records,
            "branch_wal": branch_records,
            "in_doubt_transactions": in_doubt,
            "system_clean": len(in_doubt) == 0
        }

    @staticmethod
    def run_recovery() -> Dict[str, Any]:
        """
        Executes the Crash Recovery Algorithm:
          Phase 1: Analysis - Identifies all incomplete transactions in WAL.
          Phase 2: Redo - Re-applies committed transactions not yet finalized.
          Phase 3: Undo - Rolls back all uncommitted / in-doubt transactions.
        """
        recovery_log = []
        actions_taken = []

        coord_conn = get_coordinator_connection()
        try:
            cur = coord_conn.cursor()
            cur.execute("SELECT * FROM coordinator_wal WHERE state IN ('PREPARING', 'INIT', 'COMMITTING')")
            unresolved = [dict(r) for r in cur.fetchall()]

            for tx in unresolved:
                tx_id = tx["tx_id"]
                state = tx["state"]

                if state == "COMMITTING":
                    # REDO: Coordinator had decided to commit! Enforce commit on all branches.
                    recovery_log.append(f"[REDO] Transaction {tx_id} was COMMITTING. Enforcing completion.")
                    RecoveryManager._enforce_redo(tx, coord_conn)
                    actions_taken.append({
                        "tx_id": tx_id,
                        "action": "REDO_COMMIT",
                        "reason": "Coordinator log had reached commit state before crash"
                    })
                else:
                    # UNDO: Coordinator crashed during prepare without commit decision. Must abort!
                    recovery_log.append(f"[UNDO] Transaction {tx_id} in '{state}' state. Forcing GLOBAL_ABORT.")
                    RecoveryManager._enforce_undo(tx, coord_conn)
                    actions_taken.append({
                        "tx_id": tx_id,
                        "action": "UNDO_ABORT",
                        "reason": "Coordinator crashed during PREPARE phase before commit decision"
                    })

            # Check participant branch WALs for dangling PREPARED states
            for b_id in BRANCHES.keys():
                b_conn = get_branch_connection(b_id)
                try:
                    b_cur = b_conn.cursor()
                    b_cur.execute("SELECT * FROM branch_wal WHERE state = 'PREPARED'")
                    dangling = [dict(r) for r in b_cur.fetchall()]
                    for dw in dangling:
                        dw_tx = dw["tx_id"]
                        # In-doubt resolution: Query coordinator for final outcome
                        cur.execute("SELECT state FROM coordinator_wal WHERE tx_id = ?", (dw_tx,))
                        c_state_row = cur.fetchone()
                        c_state = c_state_row["state"] if c_state_row else "UNKNOWN"

                        if c_state == "COMMITTED":
                            b_conn.execute("UPDATE branch_wal SET state = 'COMMITTED' WHERE wal_id = ?", (dw["wal_id"],))
                            recovery_log.append(f"[REDO] Participant {b_id} resolved in-doubt tx {dw_tx} to COMMITTED based on coordinator log.")
                        else:
                            b_conn.execute("UPDATE branch_wal SET state = 'ABORTED' WHERE wal_id = ?", (dw["wal_id"],))
                            recovery_log.append(f"[UNDO] Participant {b_id} resolved in-doubt tx {dw_tx} to ABORTED.")
                    b_conn.commit()
                finally:
                    b_conn.close()

            # Clean up all dangling locks in DLM
            dlm.clear_all_locks()
            recovery_log.append("[DLM] Cleared all active locks and restored lock registry.")

        finally:
            coord_conn.close()

        return {
            "success": True,
            "actions_taken": actions_taken,
            "recovery_log": recovery_log,
            "message": f"Recovery completed. Handled {len(actions_taken)} incomplete transactions."
        }

    @staticmethod
    def _enforce_redo(tx: Dict, coord_conn):
        """Forces completion of a partially committed transaction."""
        tx_id = tx["tx_id"]
        # Update coordinator WAL
        coord_conn.execute("UPDATE coordinator_wal SET state = 'COMMITTED' WHERE tx_id = ?", (tx_id,))
        coord_conn.commit()

        # Update branch participants
        for b_id in [tx["source_branch"], tx["dest_branch"]]:
            if b_id:
                b_conn = get_branch_connection(b_id)
                try:
                    b_conn.execute("UPDATE branch_wal SET state = 'COMMITTED' WHERE tx_id = ?", (tx_id,))
                    b_conn.commit()
                finally:
                    b_conn.close()

    @staticmethod
    def _enforce_undo(tx: Dict, coord_conn):
        """Rolls back an incomplete transaction."""
        tx_id = tx["tx_id"]
        coord_conn.execute("UPDATE coordinator_wal SET state = 'ABORTED' WHERE tx_id = ?", (tx_id,))
        coord_conn.commit()

        for b_id in [tx["source_branch"], tx["dest_branch"]]:
            if b_id:
                b_conn = get_branch_connection(b_id)
                try:
                    b_conn.execute("UPDATE branch_wal SET state = 'ABORTED' WHERE tx_id = ?", (tx_id,))
                    b_conn.commit()
                finally:
                    b_conn.close()

    @staticmethod
    def inject_simulated_crash_wal() -> Dict[str, Any]:
        """Creates a synthetic in-doubt transaction simulating coordinator crash right after Phase 1."""
        synthetic_tx = f"CRASH-SIM-{int(time.time())}"
        coord_conn = get_coordinator_connection()
        try:
            coord_conn.execute(
                """INSERT INTO coordinator_wal 
                   (tx_id, tx_type, state, source_branch, dest_branch, source_account, dest_account, amount, payload_json)
                   VALUES (?, 'CROSS_BRANCH_TRANSFER', 'PREPARING', 'BR001', 'BR002', 'ACC-1001', 'ACC-2001', 500.0, '{}')""",
                (synthetic_tx,)
            )
            coord_conn.commit()
        finally:
            coord_conn.close()

        # Insert PREPARED in both participant branches
        for b_id, acc in [("BR001", "ACC-1001"), ("BR002", "ACC-2001")]:
            b_conn = get_branch_connection(b_id)
            try:
                b_conn.execute(
                    "INSERT INTO branch_wal (tx_id, state, account_number, delta) VALUES (?, 'PREPARED', ?, 0)",
                    (synthetic_tx, acc)
                )
                b_conn.commit()
            finally:
                b_conn.close()

        # Hold a lock on ACC-1001
        dlm.acquire_lock(synthetic_tx, "acc:ACC-1001", "X")

        return {
            "synthetic_tx_id": synthetic_tx,
            "message": "Injected synthetic crashed transaction. State is 'PREPARING' in coordinator WAL, 'PREPARED' in participants, and lock is held. Run Recovery to resolve."
        }
