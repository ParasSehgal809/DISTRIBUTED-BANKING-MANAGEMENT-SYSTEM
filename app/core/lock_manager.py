import time
import threading
import uuid
from typing import Dict, List, Optional, Set, Tuple
from app.database.connection import get_coordinator_connection

class LockEntry:
    def __init__(self, lock_id: str, resource_id: str, tx_id: str, lock_type: str, granted_at: float):
        self.lock_id = lock_id
        self.resource_id = resource_id
        self.tx_id = tx_id
        self.lock_type = lock_type # 'S' (Shared) or 'X' (Exclusive)
        self.granted_at = granted_at

class DistributedLockManager:
    """
    Distributed Lock Manager (DLM) implementing Strict Two-Phase Locking (Strict 2PL).
    
    Strict 2PL Properties:
      1. Growing Phase: A transaction may obtain locks, but cannot release any lock.
      2. Shrinking Phase: All locks held by a transaction are held until the transaction
         terminates (COMMIT or ABORT), then released simultaneously.
      3. Guarantees Strict Serializability and eliminates cascading aborts.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DistributedLockManager, cls).__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self):
        self.mutex = threading.Lock()
        # resource_id -> list of LockEntry
        self.resource_locks: Dict[str, List[LockEntry]] = {}
        # tx_id -> set of resource_ids held
        self.tx_locks: Dict[str, Set[str]] = {}
        # Wait queue: resource_id -> list of waiting requests (tx_id, lock_type, event)
        self.wait_queues: Dict[str, List[Dict]] = {}

    def acquire_lock(self, tx_id: str, resource_id: str, lock_type: str = "X", timeout: float = 3.0) -> Tuple[bool, str]:
        """
        Attempts to acquire a Shared ('S') or Exclusive ('X') lock on a resource.
        Adheres to compatibility matrix:
               Requested: S     X
           Held S:        YES   NO
           Held X:        NO    NO
        """
        lock_type = lock_type.upper()
        if lock_type not in ("S", "X"):
            return False, f"Invalid lock type: {lock_type}"

        start_time = time.time()
        while time.time() - start_time < timeout:
            with self.mutex:
                current_locks = self.resource_locks.get(resource_id, [])
                
                # Check compatibility
                can_grant = False
                if not current_locks:
                    can_grant = True
                else:
                    # Check if all holders belong to the same transaction
                    same_tx = all(le.tx_id == tx_id for le in current_locks)
                    if same_tx:
                        can_grant = True
                    elif lock_type == "S":
                        # S lock can be shared if all current locks are also S
                        if all(le.lock_type == "S" for le in current_locks):
                            can_grant = True

                if can_grant:
                    # Grant lock
                    lock_id = f"LCK-{uuid.uuid4().hex[:8]}"
                    entry = LockEntry(lock_id, resource_id, tx_id, lock_type, time.time())
                    
                    if resource_id not in self.resource_locks:
                        self.resource_locks[resource_id] = []
                    self.resource_locks[resource_id].append(entry)

                    if tx_id not in self.tx_locks:
                        self.tx_locks[tx_id] = set()
                    self.tx_locks[tx_id].add(resource_id)

                    # Persist lock to coordinator table
                    self._persist_lock(lock_id, resource_id, tx_id, lock_type)
                    return True, f"Lock {lock_type} granted on {resource_id} for tx {tx_id}"

            # Brief backoff before retry
            time.sleep(0.05)

        return False, f"Lock acquisition timed out on {resource_id} (held by other transactions)"

    def release_locks_for_tx(self, tx_id: str) -> int:
        """
        Strict 2PL Shrinking Phase:
        Releases ALL locks held by this transaction in one atomic operation upon COMMIT or ABORT.
        """
        with self.mutex:
            resources = self.tx_locks.pop(tx_id, set())
            released_count = 0

            for res in resources:
                if res in self.resource_locks:
                    before_len = len(self.resource_locks[res])
                    self.resource_locks[res] = [le for le in self.resource_locks[res] if le.tx_id != tx_id]
                    released_count += (before_len - len(self.resource_locks[res]))
                    if not self.resource_locks[res]:
                        del self.resource_locks[res]

            # Clear from coordinator database table
            self._remove_persisted_locks(tx_id)
            return released_count

    def get_active_locks(self) -> List[Dict]:
        """Returns a list of all currently active locks."""
        with self.mutex:
            result = []
            for res_id, entries in self.resource_locks.items():
                for le in entries:
                    result.append({
                        "lock_id": le.lock_id,
                        "resource_id": le.resource_id,
                        "tx_id": le.tx_id,
                        "lock_type": le.lock_type,
                        "granted_at": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(le.granted_at)),
                        "duration_sec": round(time.time() - le.granted_at, 2)
                    })
            return result

    def get_resource_holders(self, resource_id: str) -> List[str]:
        """Returns list of tx_ids holding locks on a resource."""
        with self.mutex:
            entries = self.resource_locks.get(resource_id, [])
            return [le.tx_id for le in entries]

    def _persist_lock(self, lock_id: str, resource_id: str, tx_id: str, lock_type: str):
        try:
            conn = get_coordinator_connection()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO global_locks (lock_id, resource_id, tx_id, lock_type, owner)
                       VALUES (?, ?, ?, ?, ?)""",
                    (lock_id, resource_id, tx_id, lock_type, tx_id)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[!] DLM persist error: {e}")

    def _remove_persisted_locks(self, tx_id: str):
        try:
            conn = get_coordinator_connection()
            try:
                conn.execute("DELETE FROM global_locks WHERE tx_id = ?", (tx_id,))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[!] DLM remove error: {e}")

    def clear_all_locks(self):
        """Emergency reset for demonstration/lab purposes."""
        with self.mutex:
            self.resource_locks.clear()
            self.tx_locks.clear()
            self.wait_queues.clear()
            conn = get_coordinator_connection()
            try:
                conn.execute("DELETE FROM global_locks")
                conn.commit()
            finally:
                conn.close()

# Singleton instance
dlm = DistributedLockManager()
