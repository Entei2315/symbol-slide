"""FastMCP server for Symbol Slide level generation, validation, solving, and persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

import solver

LEVELS_PATH = Path(__file__).resolve().parent / "levels.json"

mcp = FastMCP("symbol-slide")


@mcp.tool
def validate_and_solve_level(level_data: dict[str, Any]) -> dict[str, Any]:
    """Validate a Symbol Slide level layout and solve it via exact BFS."""
    errors = solver.validate_level(level_data)
    if errors:
        return {
            "valid": False,
            "errors": errors,
            "solvable": False,
            "optimal_moves": None,
            "solution_path": [],
            "states_explored": 0,
            "truncated": False,
        }

    level = solver.level_from_dict(level_data)
    result = solver.solve_bfs(level)
    return {
        "valid": True,
        "errors": [],
        "solvable": result.solvable,
        "optimal_moves": result.optimal_moves,
        "solution_path": [move.to_dict() for move in result.path],
        "states_explored": result.states_explored,
        "truncated": result.truncated,
    }


@mcp.tool
def generate_verified_level(
    rows: int = 4,
    cols: int = 4,
    num_tiles: int = 3,
    wall_count: int = 2,
    slide_mode: str = "full_slide",
    min_optimal_moves: int = 5,
    seed: int | None = None,
    level_id: str = "custom-level",
    name: str = "Custom Puzzle",
    difficulty: str = "medium",
) -> dict[str, Any]:
    """Generate a guaranteed-solvable level verified by BFS with exact optimal_moves."""
    return solver.generate_level(
        rows=rows,
        cols=cols,
        num_tiles=num_tiles,
        wall_count=wall_count,
        slide_mode=slide_mode,
        min_optimal_moves=min_optimal_moves,
        seed=seed,
        level_id=level_id,
        name=name,
        difficulty=difficulty,
    )


@mcp.tool
def list_saved_levels() -> list[dict[str, Any]]:
    """List summaries of all saved levels in levels.json."""
    levels = solver.load_levels(LEVELS_PATH)
    return [
        {
            "id": lvl.get("id"),
            "name": lvl.get("name"),
            "difficulty": lvl.get("difficulty", "medium"),
            "rows": lvl.get("rows"),
            "cols": lvl.get("cols"),
            "slide_mode": lvl.get("slide_mode", "full_slide"),
            "num_tiles": len(lvl.get("tiles", {})),
            "optimal_moves": lvl.get("optimal_moves"),
            "par_moves": lvl.get("par_moves"),
        }
        for lvl in levels
    ]


@mcp.tool
def save_verified_level(level_data: dict[str, Any], overwrite: bool = False) -> dict[str, Any]:
    """Verify solvability via BFS and save a level into levels.json."""
    errors = solver.validate_level(level_data)
    if errors:
        return {"saved": False, "errors": errors, "solvable": False}

    level = solver.level_from_dict(level_data)
    result = solver.solve_bfs(level)
    if not result.solvable or result.optimal_moves is None:
        return {
            "saved": False,
            "errors": ["Level is unsolvable and cannot be saved."],
            "solvable": False,
            "truncated": result.truncated,
        }

    verified_entry = {
        **level_data,
        "slide_mode": level.slide_mode,
        "optimal_moves": result.optimal_moves,
        "par_moves": level_data.get("par_moves") or result.optimal_moves,
    }

    levels = solver.load_levels(LEVELS_PATH)
    existing_idx = next(
        (i for i, item in enumerate(levels) if item.get("id") == verified_entry.get("id")),
        None,
    )
    if existing_idx is not None:
        if not overwrite:
            return {
                "saved": False,
                "errors": [f"Level id {verified_entry.get('id')!r} already exists (set overwrite=True)."],
                "solvable": True,
                "optimal_moves": result.optimal_moves,
            }
        levels[existing_idx] = verified_entry
    else:
        levels.append(verified_entry)

    solver.save_levels(levels, LEVELS_PATH)
    return {
        "saved": True,
        "id": verified_entry.get("id"),
        "optimal_moves": result.optimal_moves,
        "total_levels": len(levels),
    }


@mcp.tool
def verify_all_levels() -> dict[str, Any]:
    """Validate and solve every level in levels.json to confirm solvability and exact par."""
    levels = solver.load_levels(LEVELS_PATH)
    results: list[dict[str, Any]] = []
    all_valid = True

    for lvl in levels:
        lvl_id = lvl.get("id")
        errors = solver.validate_level(lvl)
        if errors:
            all_valid = False
            results.append(
                {
                    "id": lvl_id,
                    "valid": False,
                    "solvable": False,
                    "errors": errors,
                }
            )
            continue

        parsed = solver.level_from_dict(lvl)
        solve_res = solver.solve_bfs(parsed)
        stored_opt = lvl.get("optimal_moves")
        par_matches = stored_opt == solve_res.optimal_moves
        ok = solve_res.solvable and par_matches
        if not ok:
            all_valid = False

        results.append(
            {
                "id": lvl_id,
                "valid": True,
                "solvable": solve_res.solvable,
                "optimal_moves": solve_res.optimal_moves,
                "stored_optimal_moves": stored_opt,
                "par_matches": par_matches,
                "states_explored": solve_res.states_explored,
            }
        )

    return {
        "total": len(levels),
        "all_valid": all_valid,
        "results": results,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000, path="/mcp")
