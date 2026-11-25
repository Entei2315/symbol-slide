"""FastAPI web server for Symbol Slide (http://127.0.0.1:5000)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

import solver

BASE_DIR = Path(__file__).resolve().parent
UI_DIR = BASE_DIR / "UI" / "web"
LEVELS_PATH = BASE_DIR / "levels.json"

app = FastAPI(title="Symbol Slide", version="1.0.0")


class MoveRequest(BaseModel):
    level_id: str
    tiles: dict[str, list[int]]
    symbol: str
    direction: Literal["U", "D", "L", "R"]


class HintRequest(BaseModel):
    level_id: str
    tiles: dict[str, list[int]]


def _get_level_dict(level_id: str) -> dict[str, Any]:
    levels = solver.load_levels(LEVELS_PATH)
    for item in levels:
        if item.get("id") == level_id:
            return item
    raise HTTPException(status_code=404, detail=f"Level {level_id!r} not found.")


def _enrich_level(level_dict: dict[str, Any]) -> dict[str, Any]:
    optimal = level_dict.get("optimal_moves")
    if optimal is None:
        result = solver.solve_bfs(solver.level_from_dict(level_dict))
        optimal = result.optimal_moves
    thresholds = (
        solver.compute_star_thresholds(optimal)
        if isinstance(optimal, int)
        else {"three_star": 0, "two_star": 0}
    )
    return {
        **level_dict,
        "optimal_moves": optimal,
        "par_moves": level_dict.get("par_moves", optimal),
        "star_thresholds": thresholds,
    }


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


@app.get("/styles.css", include_in_schema=False)
def serve_css() -> FileResponse:
    return FileResponse(UI_DIR / "styles.css", media_type="text/css")


@app.get("/func.js", include_in_schema=False)
def serve_js() -> FileResponse:
    return FileResponse(UI_DIR / "func.js", media_type="application/javascript")


@app.get("/api/levels")
def list_levels() -> dict[str, Any]:
    levels = solver.load_levels(LEVELS_PATH)
    return {"levels": [_enrich_level(lvl) for lvl in levels]}


@app.get("/api/levels/{level_id}")
def get_level(level_id: str) -> dict[str, Any]:
    return _enrich_level(_get_level_dict(level_id))


@app.post("/api/move")
def post_move(req: MoveRequest) -> dict[str, Any]:
    level_dict = _get_level_dict(req.level_id)
    level = solver.level_from_dict(level_dict)
    if req.symbol not in level.symbols:
        raise HTTPException(status_code=400, detail=f"Unknown symbol {req.symbol!r} for level.")

    try:
        state = solver.state_from_tiles_dict(level, req.tiles)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sym_idx = level.symbols.index(req.symbol)
    from_pos = state[sym_idx]
    next_state, to_pos = solver.slide_tile(level, state, sym_idx, req.direction)

    return {
        "moved": to_pos != from_pos,
        "from_pos": [from_pos[0], from_pos[1]],
        "to_pos": [to_pos[0], to_pos[1]],
        "tiles": solver.tiles_dict_from_state(level, next_state),
        "solved": next_state == level.goal_state,
    }


@app.post("/api/hint")
def post_hint(req: HintRequest) -> dict[str, Any]:
    level_dict = _get_level_dict(req.level_id)
    level = solver.level_from_dict(level_dict)
    try:
        return solver.get_hint(level, req.tiles)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5000)
