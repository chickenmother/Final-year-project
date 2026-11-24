"""Tests for the WS3.4 leaderboard store (L on Cloud X)."""
import tempfile
import unittest
from pathlib import Path

from common.leaderboard import Leaderboard, LeaderboardError


class LeaderboardTests(unittest.TestCase):
    def setUp(self):
        self.board = Leaderboard(":memory:")

    def tearDown(self):
        self.board.close()

    def test_empty_store(self):
        self.assertEqual(self.board.count(), 0)
        self.assertEqual(self.board.top(10), [])

    def test_submit_returns_rank_and_rows(self):
        result = self.board.submit({"name": "ann", "score": 120,
                                    "workload": "medium"})
        self.assertEqual(result["rank"], 1)
        self.assertEqual(result["entry_id"], 1)
        self.assertEqual(result["rows"][0]["name"], "ann")
        self.assertEqual(result["rows"][0]["score"], 120)
        self.assertEqual(self.board.count(), 1)

    def test_order_by_score_then_time(self):
        self.board.submit({"name": "low", "score": 10})
        self.board.submit({"name": "high", "score": 900})
        self.board.submit({"name": "high2", "score": 900})
        rows = self.board.top(5)
        self.assertEqual([row["name"] for row in rows], ["high", "high2", "low"])
        # equal scores keep submission order
        self.assertLessEqual(rows[0]["created"], rows[1]["created"])

    def test_rank_counts_higher_scores(self):
        self.board.submit({"name": "a", "score": 50})
        result = self.board.submit({"name": "b", "score": 40})
        self.assertEqual(result["rank"], 2)
        best = self.board.submit({"name": "c", "score": 60})
        self.assertEqual(best["rank"], 1)

    def test_limit_is_clamped(self):
        for index in range(60):
            self.board.submit({"name": f"p{index}", "score": index})
        self.assertEqual(len(self.board.top(5)), 5)
        self.assertEqual(len(self.board.top(999)), 50)
        self.assertEqual(len(self.board.top("bad")), 10)

    def test_validation(self):
        with self.assertRaises(LeaderboardError):
            self.board.submit({"score": "abc"})
        with self.assertRaises(LeaderboardError):
            self.board.submit({"score": -5})
        with self.assertRaises(LeaderboardError):
            self.board.submit("not a dict")

    def test_defaults_and_long_names(self):
        result = self.board.submit({"score": 1, "name": "x" * 60})
        self.assertEqual(len(result["rows"][0]["name"]), 24)
        empty = Leaderboard(":memory:")
        row = empty.submit({"score": 7})["rows"][0]
        self.assertEqual(row["name"], "player")
        self.assertEqual(row["source"], "manual")
        empty.close()

    def test_persists_to_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs" / "leaderboard.db"
            first = Leaderboard(path)
            first.submit({"name": "zed", "score": 42})
            first.close()
            again = Leaderboard(path)
            self.assertEqual(again.count(), 1)
            self.assertEqual(again.top(1)[0]["name"], "zed")
            again.reset()
            self.assertEqual(again.count(), 0)
            again.close()


if __name__ == "__main__":
    unittest.main()
