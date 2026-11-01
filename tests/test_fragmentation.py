import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import unittest
from app.core.catalog import GlobalCatalog
from app.database.seed_data import seed_database

class TestFragmentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_database()

    def test_horizontal_fragmentation_isolation(self):
        """Verify each branch DB only holds accounts belonging to its branch_id."""
        b1_accounts = GlobalCatalog.reconstruct_all_accounts(branch_filter="BR001")
        self.assertTrue(len(b1_accounts) > 0)
        for acc in b1_accounts:
            self.assertEqual(acc["branch_id"], "BR001")

        b2_accounts = GlobalCatalog.reconstruct_all_accounts(branch_filter="BR002")
        self.assertTrue(len(b2_accounts) > 0)
        for acc in b2_accounts:
            self.assertEqual(acc["branch_id"], "BR002")

    def test_horizontal_reconstruction_union(self):
        """Verify distributed UNION ALL combines accounts across all branches."""
        all_accounts = GlobalCatalog.reconstruct_all_accounts()
        b1_accounts = GlobalCatalog.reconstruct_all_accounts(branch_filter="BR001")
        b2_accounts = GlobalCatalog.reconstruct_all_accounts(branch_filter="BR002")
        b3_accounts = GlobalCatalog.reconstruct_all_accounts(branch_filter="BR003")

        self.assertEqual(len(all_accounts), len(b1_accounts) + len(b2_accounts) + len(b3_accounts))

    def test_vertical_reconstruction_join(self):
        """Verify customer reconstruction joins central demographics with branch financial profile."""
        cust = GlobalCatalog.reconstruct_customer("CUST-101")
        self.assertIsNotNone(cust)
        # From Central Fragment
        self.assertEqual(cust["full_name"], "Alice Morgan")
        self.assertEqual(cust["gov_id_type"], "PASSPORT")
        # From Branch Fragment
        self.assertEqual(cust["credit_score"], 760)
        self.assertEqual(cust["kyc_status"], "VERIFIED")
        self.assertEqual(cust["primary_branch_id"], "BR001")

if __name__ == "__main__":
    unittest.main()
