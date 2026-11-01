import time
import threading
from typing import Dict, List, Set, Optional, Tuple
from app.core.lock_manager import dlm

class DeadlockDetector:
    """
    Wait-For Graph (WFG) & Deadlock Management Engine.
    
    ADBMS Concepts:
      - Wait-For Graph G = (V, E) where:
          V = Set of active distributed transactions
          E = Directed edge (Ti -> Tj) meaning Ti is waiting for a resource held by Tj.
      - Deadlock Condition: A deadlock exists if and only if G contains a directed cycle.
      - Cycle Detection: Depth-First Search (DFS) traversal with cycle tracing.
      - Deadlock Resolution: Victim selection (youngest/lowest-cost) and transaction abort.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DeadlockDetector, cls).__new__(cls)
                cls._instance._init_detector()
            return cls._instance

    def _init_detector(self):
        self.mutex = threading.Lock()
        # Adjacency list: waiter_tx -> dict of {holder_tx: resource_id}
        self.wait_for_graph: Dict[str, Dict[str, str]] = {}
        # Transaction creation timestamps for victim selection
        self.tx_timestamps: Dict[str, float] = {}
        # Transaction descriptions
        self.tx_metadata: Dict[str, Dict] = {}

    def register_transaction(self, tx_id: str, description: str):
        """Registers an active transaction with a timestamp."""
        with self.mutex:
            if tx_id not in self.tx_timestamps:
                self.tx_timestamps[tx_id] = time.time()
                self.tx_metadata[tx_id] = {
                    "description": description,
                    "created_at": time.strftime('%H:%M:%S')
                }
            if tx_id not in self.wait_for_graph:
                self.wait_for_graph[tx_id] = {}

    def add_wait_dependency(self, waiter_tx: str, holder_tx: str, resource_id: str):
        """Adds directed edge (waiter_tx -> holder_tx) over resource_id."""
        with self.mutex:
            if waiter_tx not in self.wait_for_graph:
                self.wait_for_graph[waiter_tx] = {}
            self.wait_for_graph[waiter_tx][holder_tx] = resource_id

    def remove_wait_dependency(self, waiter_tx: str, holder_tx: str = None):
        """Removes dependency edge(s)."""
        with self.mutex:
            if waiter_tx in self.wait_for_graph:
                if holder_tx:
                    self.wait_for_graph[waiter_tx].pop(holder_tx, None)
                else:
                    self.wait_for_graph[waiter_tx].clear()

    def unregister_transaction(self, tx_id: str):
        """Removes transaction and all incoming/outgoing wait dependencies."""
        with self.mutex:
            self.tx_timestamps.pop(tx_id, None)
            self.tx_metadata.pop(tx_id, None)
            self.wait_for_graph.pop(tx_id, None)
            # Remove any edge pointing to this tx
            for waiter, holders in self.wait_for_graph.items():
                holders.pop(tx_id, None)

    def detect_deadlocks(self) -> List[List[str]]:
        """
        DFS Cycle Detection on Wait-For Graph.
        Returns a list of detected cycles (e.g. [['TX-1', 'TX-2', 'TX-1']]).
        """
        with self.mutex:
            visited = set()
            rec_stack = []
            cycles = []

            def dfs(node: str):
                visited.add(node)
                rec_stack.append(node)

                neighbors = self.wait_for_graph.get(node, {})
                for neighbor in neighbors.keys():
                    if neighbor not in visited:
                        dfs(neighbor)
                    elif neighbor in rec_stack:
                        # Cycle found!
                        cycle_start_idx = rec_stack.index(neighbor)
                        cycle = rec_stack[cycle_start_idx:] + [neighbor]
                        cycles.append(cycle)

                rec_stack.pop()

            all_nodes = list(self.wait_for_graph.keys())
            for n in all_nodes:
                if n not in visited:
                    dfs(n)

            return cycles

    def resolve_deadlocks(self) -> List[Dict]:
        """
        Resolves detected deadlocks by selecting and aborting victim transactions.
        Victim Policy: Youngest Transaction (highest timestamp) to minimize wasted computation.
        """
        cycles = self.detect_deadlocks()
        if not cycles:
            return []

        resolutions = []
        aborted_txs = set()

        for cycle in cycles:
            # Nodes in cycle (excluding duplicate tail)
            cycle_nodes = list(dict.fromkeys(cycle[:-1]))
            
            # Find eligible victims not already aborted
            eligible = [tx for tx in cycle_nodes if tx not in aborted_txs]
            if not eligible:
                continue

            # Select victim: youngest timestamp
            with self.mutex:
                victim = max(eligible, key=lambda tx: self.tx_timestamps.get(tx, 0))
                victim_meta = self.tx_metadata.get(victim, {})

            aborted_txs.add(victim)

            # Abort victim: Release all locks held by victim
            released = dlm.release_locks_for_tx(victim)
            self.unregister_transaction(victim)

            resolutions.append({
                "cycle": " -> ".join(cycle),
                "victim_tx": victim,
                "victim_description": victim_meta.get("description", "Distributed Transfer"),
                "policy_used": "Youngest Transaction (Minimize Wasted Work)",
                "locks_released": released,
                "status": "ABORTED_AND_RESOLVED"
            })

        return resolutions

    def get_graph_state(self) -> Dict:
        """Returns the full Wait-For Graph nodes, edges, and active cycles for UI rendering."""
        with self.mutex:
            nodes = []
            edges = []

            # Collect all unique nodes
            node_ids = set(self.wait_for_graph.keys())
            for holders in self.wait_for_graph.values():
                node_ids.update(holders.keys())

            for nid in node_ids:
                meta = self.tx_metadata.get(nid, {})
                nodes.append({
                    "id": nid,
                    "label": nid,
                    "description": meta.get("description", "Transaction"),
                    "created_at": meta.get("created_at", "N/A"),
                    "locks_held": list(dlm.tx_locks.get(nid, set()))
                })

            for waiter, holders in self.wait_for_graph.items():
                for holder, resource in holders.items():
                    edges.append({
                        "from": waiter,
                        "to": holder,
                        "resource": resource,
                        "label": f"waits for {resource}"
                    })

        cycles = self.detect_deadlocks()
        return {
            "nodes": nodes,
            "edges": edges,
            "has_deadlock": len(cycles) > 0,
            "cycles": [" -> ".join(c) for c in cycles]
        }

    def simulate_deadlock_scenario(self) -> Dict:
        """
        Creates a synthetic 2-party deadlock:
          T1 acquires ACC-1001, then wants ACC-2001
          T2 acquires ACC-2001, then wants ACC-1001
        """
        # Reset any lingering locks
        dlm.clear_all_locks()
        self.clear_graph()

        tx1 = "TX-DEADLOCK-A"
        tx2 = "TX-DEADLOCK-B"

        res1 = "acc:ACC-1001"
        res2 = "acc:ACC-2001"

        # Register
        self.register_transaction(tx1, "Transfer: Alice (ACC-1001) -> Charlie (ACC-2001)")
        # Make TX2 slightly younger
        time.sleep(0.05)
        self.register_transaction(tx2, "Transfer: Charlie (ACC-2001) -> Alice (ACC-1001)")

        # Step 1: TX1 acquires Res1, TX2 acquires Res2
        dlm.acquire_lock(tx1, res1, "X")
        dlm.acquire_lock(tx2, res2, "X")

        # Step 2: TX1 now waits for Res2 (held by TX2)
        self.add_wait_dependency(tx1, tx2, res2)

        # Step 3: TX2 now waits for Res1 (held by TX1) -> DEADLOCK CYCLE!
        self.add_wait_dependency(tx2, tx1, res1)

        return self.get_graph_state()

    def clear_graph(self):
        """Clears all WFG state."""
        with self.mutex:
            self.wait_for_graph.clear()
            self.tx_timestamps.clear()
            self.tx_metadata.clear()

# Singleton instance
deadlock_detector = DeadlockDetector()
