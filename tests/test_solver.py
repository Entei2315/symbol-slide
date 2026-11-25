"""Automated tests for Symbol Slide engine, BFS solver, generator, levels.json, and MCP tools."""

from __future__ import annotations

from pathlib import Path
import time
import unittest

import server
import solver


class SolverUnitTests(unittest.TestCase):
    def test_full_slide_stops_at_wall_border_and_tile(self) -> None:
        raw = {
            "id": "t-slide",
            "name": "Slide Test",
            "rows": 4,
            "cols": 4,
            "slide_mode": "full_slide",
            "walls": [[0, 3]],
            "tiles": {"diamond": [0, 0], "circle": [2, 0]},
            "targets": {"diamond": [0, 2], "circle": [3, 3]},
        }
        level = solver.level_from_dict(raw)
        # diamond is index 1 ('circle' is 0, 'diamond' is 1 sorted)
        d_idx = level.symbols.index("diamond")
        c_idx = level.symbols.index("circle")

        # Slide diamond Right: hits wall at [0, 3], stops at [0, 2]
        nxt, to_pos = solver.slide_tile(level, level.initial_state, d_idx, "R")
        self.assertEqual(to_pos, (0, 2))
        self.assertEqual(nxt[d_idx], (0, 2))

        # Slide diamond Down from [0, 0]: hits circle at [2, 0], stops at [1, 0]
        nxt2, to_pos2 = solver.slide_tile(level, level.initial_state, d_idx, "D")
        self.assertEqual(to_pos2, (1, 0))

        # Slide circle Right: hits grid border at col 3
        nxt3, to_pos3 = solver.slide_tile(level, level.initial_state, c_idx, "R")
        self.assertEqual(to_pos3, (2, 3))

    def test_single_step_moves_one_cell_only(self) -> None:
        raw = {
            "id": "t-step",
            "name": "Step Test",
            "rows": 3,
            "cols": 3,
            "slide_mode": "single_step",
            "walls": [[0, 1]],
            "tiles": {"diamond": [0, 0], "circle": [2, 2]},
            "targets": {"diamond": [2, 0], "circle": [0, 2]},
        }
        level = solver.level_from_dict(raw)
        d_idx = level.symbols.index("diamond")

        # Blocked by wall at [0, 1]
        _, to_pos = solver.slide_tile(level, level.initial_state, d_idx, "R")
        self.assertEqual(to_pos, (0, 0))

        # Moves exactly 1 cell Down
        _, to_pos2 = solver.slide_tile(level, level.initial_state, d_idx, "D")
        self.assertEqual(to_pos2, (1, 0))

    def test_bfs_exact_optimality_and_hint_progression(self) -> None:
        raw = {
            "id": "t-bfs",
            "name": "BFS Test",
            "rows": 3,
            "cols": 3,
            "slide_mode": "full_slide",
            "walls": [[1, 1]],
            "tiles": {"diamond": [0, 0], "circle": [2, 2]},
            "targets": {"diamond": [0, 2], "circle": [2, 0]},
        }
        level = solver.level_from_dict(raw)
        res = solver.solve_bfs(level)
        self.assertTrue(res.solvable)
        self.assertEqual(res.optimal_moves, 2)
        self.assertEqual(len(res.path), 2)

        # Follow hints step by step
        curr_tiles = dict(raw["tiles"])
        for expected_rem in (2, 1):
            hint = solver.get_hint(level, curr_tiles)
            self.assertTrue(hint["solvable"])
            self.assertEqual(hint["remaining_moves"], expected_rem)
            mv = hint["next_move"]
            curr_tiles[mv["symbol"]] = mv["to_pos"]

        final_hint = solver.get_hint(level, curr_tiles)
        self.assertTrue(final_hint["solved"])
        self.assertEqual(final_hint["remaining_moves"], 0)

    def test_heuristic_matches_unweighted_bfs(self) -> None:
        fixtures = [
            {
                "id": "h-3x3",
                "name": "3x3 Eq",
                "rows": 3,
                "cols": 3,
                "slide_mode": "full_slide",
                "walls": [[1, 0]],
                "tiles": {"diamond": [0, 0], "circle": [2, 2]},
                "targets": {"diamond": [2, 0], "circle": [1, 1]},
            },
            {
                "id": "h-4x4",
                "name": "4x4 Eq",
                "rows": 4,
                "cols": 4,
                "slide_mode": "full_slide",
                "walls": [[0, 2], [1, 2], [3, 2]],
                "tiles": {"diamond": [3, 0], "circle": [2, 3], "star": [0, 1]},
                "targets": {"diamond": [0, 0], "circle": [2, 2], "star": [0, 1]},
            },
        ]
        for raw in fixtures:
            lvl = solver.level_from_dict(raw)
            res_h = solver.solve_bfs(lvl, use_heuristic=True)
            res_u = solver.solve_bfs(lvl, use_heuristic=False)
            self.assertEqual(res_h.solvable, res_u.solvable)
            self.assertEqual(res_h.optimal_moves, res_u.optimal_moves)

    def test_unsolvable_detection(self) -> None:
        raw = {
            "id": "t-unsolvable",
            "name": "Boxed In",
            "rows": 3,
            "cols": 3,
            "slide_mode": "full_slide",
            "walls": [[0, 1], [1, 0]],
            "tiles": {"diamond": [0, 0], "circle": [2, 2]},
            "targets": {"diamond": [2, 0], "circle": [0, 2]},
        }
        level = solver.level_from_dict(raw)
        res = solver.solve_bfs(level)
        self.assertFalse(res.solvable)
        self.assertIsNone(res.optimal_moves)
        self.assertFalse(res.truncated)

    def test_generate_level_respects_constraints(self) -> None:
        lvl_dict = solver.generate_level(
            rows=4,
            cols=4,
            num_tiles=3,
            wall_count=3,
            slide_mode="full_slide",
            min_optimal_moves=5,
            seed=42,
            level_id="gen-test",
            name="Gen Test",
        )
        self.assertEqual(solver.validate_level(lvl_dict), [])
        self.assertGreaterEqual(lvl_dict["optimal_moves"], 5)
        parsed = solver.level_from_dict(lvl_dict)
        res = solver.solve_bfs(parsed)
        self.assertTrue(res.solvable)
        self.assertEqual(res.optimal_moves, lvl_dict["optimal_moves"])

    def test_levels_json_campaign_integrity_and_hint_speed(self) -> None:
        levels_path = Path(__file__).resolve().parent.parent / "levels.json"
        self.assertTrue(levels_path.exists(), "levels.json must exist")
        levels = solver.load_levels(levels_path)
        self.assertEqual(len(levels), 12)

        report = server.verify_all_levels()
        self.assertTrue(report["all_valid"], f"Invalid levels in levels.json: {report}")

        # Verify hint latency stays fast (<0.5s) even on the largest 6x6 level
        last_level = solver.level_from_dict(levels[-1])
        t0 = time.perf_counter()
        hint = solver.get_hint(last_level, levels[-1]["tiles"])
        elapsed = time.perf_counter() - t0
        self.assertTrue(hint["solvable"])
        self.assertLess(elapsed, 0.5)

    def test_mcp_tools_smoke(self) -> None:
        summaries = server.list_saved_levels()
        self.assertEqual(len(summaries), 12)
        check = server.validate_and_solve_level(
            {
                "id": "smoke",
                "name": "Smoke",
                "rows": 3,
                "cols": 3,
                "slide_mode": "full_slide",
                "walls": [[1, 1]],
                "tiles": {"diamond": [0, 0], "circle": [2, 2]},
                "targets": {"diamond": [0, 2], "circle": [2, 0]},
            }
        )
        self.assertTrue(check["valid"])
        self.assertTrue(check["solvable"])
        self.assertEqual(check["optimal_moves"], 2)


if __name__ == "__main__":
    unittest.main()
