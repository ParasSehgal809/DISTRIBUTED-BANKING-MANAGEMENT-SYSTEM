import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import unittest
from app.core.two_phase_commit import TwoPhaseCommitCoordinator
from app.core.catalog import GlobalCatalog
from app.database.seed_data import seed_database

class TestTwoPhaseCommit(unittest.TestCase):
    def setUp(self):
        seed_database()

    def test_successful_2pc_transfer(self):
        """Cross-branch transfer should commit on both branches and update balances atomically."""
        src_acc = "ACC-1001" # BR001 ($15,450.00)
        dst_acc = "ACC-2001" # BR002 ($24,800.00)
        transfer_amount = 1000.00

        src_before = GlobalCatalog.get_account_from_branch(src_acc)["balance"]
        dst_before = GlobalCatalog.get_account_from_branch(dst_acc)["balance"]

        result = TwoPhaseCommitCoordinator.execute_cross_branch_transfer(
            src_account=src_acc,
            dest_account=dst_acc,
            amount=transfer_amount,
            description="Test 2PC Commit"
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["decision"], "COMMITTED")

        src_after = GlobalCatalog.get_account_from_branch(src_acc)["balance"]
        dst_after = GlobalCatalog.get_account_from_branch(dst_acc)["balance"]

        self.assertAlmostEqual(src_after, src_before - transfer_amount)
        self.assertAlmostEqual(dst_after, dst_before + transfer_amount)

    def test_2pc_abort_insufficient_funds(self):
        """If source has insufficient balance, 2PC must abort and neither account balance changes."""
        src_acc = "ACC-1001" # BR001
        dst_acc = "ACC-2001" # BR002
        excessive_amount = 9999999.00

        src_before = GlobalCatalog.get_account_from_branch(src_acc)["balance"]
        dst_before = GlobalCatalog.get_account_from_branch(dst_acc)["balance"]

        result = TwoPhaseCommitCoordinator.execute_cross_branch_transfer(
            src_account=src_acc,
            dest_account=dst_acc,
            amount=excessive_amount,
            description="Test 2PC Abort"
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["decision"], "ABORTED")

        src_after = GlobalCatalog.get_account_from_branch(src_acc)["balance"]
        dst_after = GlobalCatalog.get_account_from_branch(dst_acc)["balance"]

        self.assertEqual(src_after, src_before)
        self.assertEqual(dst_after, dst_before)

    def test_2pc_failure_simulation_rollback(self):
        """Simulated participant failure during Phase 1 must trigger global abort and rollback."""
        src_acc = "ACC-1001"
        dst_acc = "ACC-2001"
        transfer_amount = 500.00

        src_before = GlobalCatalog.get_account_from_branch(src_acc)["balance"]
        dst_before = GlobalCatalog.get_account_from_branch(dst_acc)["balance"]

        result = TwoPhaseCommitCoordinator.execute_cross_branch_transfer(
            src_account=src_acc,
            dest_account=dst_acc,
            amount=transfer_amount,
            failure_simulation="FAIL_DST_PREPARE"
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["decision"], "ABORTED")

        src_after = GlobalCatalog.get_account_from_branch(src_acc)["balance"]
        dst_after = GlobalCatalog.get_account_from_branch(dst_acc)["balance"]

        self.assertEqual(src_after, src_before)
        self.assertEqual(dst_after, dst_before)

if __name__ == "__main__":
    unittest.main()
