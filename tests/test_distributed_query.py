import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import unittest
from app.core.distributed_query import DistributedQueryProcessor
from app.database.seed_data import seed_database

class TestDistributedQuery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_database()

    def test_distributed_partitioned_aggregation(self):
        """Tests that local partial sums from all branches sum to global liquidity."""
        res = DistributedQueryProcessor.execute_distributed_aggregation()
        self.assertIn("global_metrics", res)
        self.assertIn("branch_reductions", res)

        global_sum = res["global_metrics"]["total_bank_liquidity"]
        branch_sum = sum(b["local_sum"] for b in res["branch_reductions"])
        self.assertAlmostEqual(global_sum, branch_sum)

        self.assertTrue(len(res["execution_plan"]) >= 4)

    def test_predicate_pushdown_search(self):
        """Tests that high-value query filters accounts at the branch node."""
        res = DistributedQueryProcessor.execute_global_account_search(min_balance=30000.0)
        self.assertGreater(len(res["results"]), 0)
        for r in res["results"]:
            self.assertGreaterEqual(r["balance"], 30000.0)

if __name__ == "__main__":
    unittest.main()
