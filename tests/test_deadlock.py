import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import unittest
from app.core.deadlock_detector import deadlock_detector
from app.core.lock_manager import dlm

class TestDeadlockDetector(unittest.TestCase):
    def setUp(self):
        deadlock_detector.clear_graph()
        dlm.clear_all_locks()

    def test_deadlock_cycle_detection(self):
        """Simulate circular wait: T1 -> T2 and T2 -> T1. Detector must identify the cycle."""
        state = deadlock_detector.simulate_deadlock_scenario()
        self.assertTrue(state["has_deadlock"])
        self.assertTrue(len(state["cycles"]) > 0)

    def test_deadlock_resolution_victim_selection(self):
        """Resolution must abort the victim transaction, release locks, and break the cycle."""
        deadlock_detector.simulate_deadlock_scenario()
        resolutions = deadlock_detector.resolve_deadlocks()

        self.assertTrue(len(resolutions) > 0)
        self.assertEqual(resolutions[0]["status"], "ABORTED_AND_RESOLVED")

        # After resolution, no deadlock should remain
        after_state = deadlock_detector.get_graph_state()
        self.assertFalse(after_state["has_deadlock"])

if __name__ == "__main__":
    unittest.main()
