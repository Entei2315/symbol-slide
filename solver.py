"""Core game engine, validator, BFS solver, hint engine, and level generator for Symbol Slide."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import math
from pathlib import Path
import random
from typing import Any, Literal

SYMBOLS: tuple[str, ...] = ("diamond", "circle", "star", "cross", "pentagon", "triangle")
DIRECTIONS: dict[str, tuple[int, int]] = {
    "U": (-1, 0),
    "D": (1, 0),
    "L": (0, -1),
    "R": (0, 1),
}
VALID_SLIDE_MODES: tuple[str, ...] = ("full_slide", "single_step")

Coord = tuple[int, int]
State = tuple[Coord, ...]
Direction = Literal["U", "D", "L", "R"]
SlideMode = Literal["full_slide", "single_step"]


@dataclass(frozen=True)
class Move:
    """Represents a single orthogonal slide of a symbol tile."""

    symbol: str
    direction: str
    from_pos: Coord
    to_pos: Coord

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "from_pos": [self.from_pos[0], self.from_pos[1]],
            "to_pos": [self.to_pos[0], self.to_pos[1]],
        }


@dataclass(frozen=True)
class Level:
    """Immutable representation of a Symbol Slide level."""

    id: str
    name: str
    rows: int
    cols: int
    slide_mode: str
    walls: frozenset[Coord]
    symbols: tuple[str, ...]
    initial_state: State
    goal_state: State
    difficulty: str = "medium"
    optimal_moves: int | None = None
    par_moves: int | None = None


@dataclass
class SolveResult:
    """Result returned by the BFS solver."""

    solvable: bool
    optimal_moves: int | None
    path: list[Move]
    states_explored: int
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "solvable": self.solvable,
            "optimal_moves": self.optimal_moves,
            "path": [move.to_dict() for move in self.path],
            "states_explored": self.states_explored,
            "truncated": self.truncated,
        }


def _parse_coord(raw: Any, label: str) -> Coord:
    if (
        not isinstance(raw, (list, tuple))
        or len(raw) != 2
        or not isinstance(raw[0], int)
        or not isinstance(raw[1], int)
        or isinstance(raw[0], bool)
        or isinstance(raw[1], bool)
    ):
        raise ValueError(f"{label} must be a [row, col] integer pair, got {raw!r}")
    return (raw[0], raw[1])


def _in_bounds(pos: Coord, rows: int, cols: int) -> bool:
    return 0 <= pos[0] < rows and 0 <= pos[1] < cols


def validate_level(data: dict[str, Any]) -> list[str]:
    """Validate a raw level dictionary and return a list of error strings."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Level data must be a dictionary."]

    rows = data.get("rows")
    cols = data.get("cols")
    if not isinstance(rows, int) or isinstance(rows, bool) or not (3 <= rows <= 6):
        errors.append(f"'rows' must be an integer between 3 and 6, got {rows!r}.")
    if not isinstance(cols, int) or isinstance(cols, bool) or not (3 <= cols <= 6):
        errors.append(f"'cols' must be an integer between 3 and 6, got {cols!r}.")

    slide_mode = data.get("slide_mode", "full_slide")
    if slide_mode not in VALID_SLIDE_MODES:
        errors.append(
            f"'slide_mode' must be one of {VALID_SLIDE_MODES}, got {slide_mode!r}."
        )

    tiles = data.get("tiles")
    targets = data.get("targets")
    if not isinstance(tiles, dict) or not tiles:
        errors.append("'tiles' must be a non-empty dictionary mapping symbol -> [row, col].")
    if not isinstance(targets, dict) or not targets:
        errors.append("'targets' must be a non-empty dictionary mapping symbol -> [row, col].")

    if errors:
        return errors

    assert isinstance(rows, int) and isinstance(cols, int)
    assert isinstance(tiles, dict) and isinstance(targets, dict)

    tile_keys = set(tiles.keys())
    target_keys = set(targets.keys())
    if tile_keys != target_keys:
        errors.append(
            f"'tiles' symbols {sorted(tile_keys)} must match 'targets' symbols {sorted(target_keys)}."
        )

    if not (2 <= len(tile_keys) <= 6):
        errors.append(f"Level must have between 2 and 6 symbol tiles, got {len(tile_keys)}.")

    unknown_symbols = (tile_keys | target_keys) - set(SYMBOLS)
    if unknown_symbols:
        errors.append(
            f"Unknown symbol(s): {sorted(unknown_symbols)}. Allowed: {list(SYMBOLS)}."
        )

    walls_raw = data.get("walls", [])
    if not isinstance(walls_raw, list):
        errors.append("'walls' must be a list of [row, col] pairs.")
        walls_raw = []

    wall_set: set[Coord] = set()
    for idx, raw_wall in enumerate(walls_raw):
        try:
            pos = _parse_coord(raw_wall, f"walls[{idx}]")
            if not _in_bounds(pos, rows, cols):
                errors.append(f"Wall {pos} is out of bounds for {rows}x{cols} grid.")
            elif pos in wall_set:
                errors.append(f"Duplicate wall at {pos}.")
            wall_set.add(pos)
        except ValueError as exc:
            errors.append(str(exc))

    tile_positions: dict[Coord, str] = {}
    parsed_tiles: dict[str, Coord] = {}
    for sym, raw_pos in tiles.items():
        try:
            pos = _parse_coord(raw_pos, f"tiles[{sym!r}]")
            if not _in_bounds(pos, rows, cols):
                errors.append(f"Tile {sym!r} at {pos} is out of bounds for {rows}x{cols}.")
            if pos in wall_set:
                errors.append(f"Tile {sym!r} overlaps wall at {pos}.")
            if pos in tile_positions:
                errors.append(
                    f"Tile {sym!r} overlaps tile {tile_positions[pos]!r} at {pos}."
                )
            tile_positions[pos] = sym
            parsed_tiles[sym] = pos
        except ValueError as exc:
            errors.append(str(exc))

    target_positions: dict[Coord, str] = {}
    parsed_targets: dict[str, Coord] = {}
    for sym, raw_pos in targets.items():
        try:
            pos = _parse_coord(raw_pos, f"targets[{sym!r}]")
            if not _in_bounds(pos, rows, cols):
                errors.append(f"Target {sym!r} at {pos} is out of bounds for {rows}x{cols}.")
            if pos in wall_set:
                errors.append(f"Target {sym!r} overlaps wall at {pos}.")
            if pos in target_positions:
                errors.append(
                    f"Target {sym!r} overlaps target {target_positions[pos]!r} at {pos}."
                )
            target_positions[pos] = sym
            parsed_targets[sym] = pos
        except ValueError as exc:
            errors.append(str(exc))

    if not errors and parsed_tiles == parsed_targets:
        errors.append("Initial 'tiles' positions must differ from 'targets' (already solved).")

    return errors


def level_from_dict(data: dict[str, Any]) -> Level:
    """Validate and construct a Level instance from a dictionary."""
    errors = validate_level(data)
    if errors:
        raise ValueError("; ".join(errors))

    symbols = tuple(sorted(data["tiles"].keys()))
    walls = frozenset(_parse_coord(w, "wall") for w in data.get("walls", []))
    initial_state = tuple(_parse_coord(data["tiles"][s], f"tiles[{s}]") for s in symbols)
    goal_state = tuple(_parse_coord(data["targets"][s], f"targets[{s}]") for s in symbols)

    return Level(
        id=str(data.get("id", "custom")),
        name=str(data.get("name", "Untitled")),
        rows=int(data["rows"]),
        cols=int(data["cols"]),
        slide_mode=str(data.get("slide_mode", "full_slide")),
        walls=walls,
        symbols=symbols,
        initial_state=initial_state,
        goal_state=goal_state,
        difficulty=str(data.get("difficulty", "medium")),
        optimal_moves=data.get("optimal_moves"),
        par_moves=data.get("par_moves"),
    )


def state_from_tiles_dict(level: Level, tiles: dict[str, list[int]]) -> State:
    """Convert a {symbol: [row, col]} mapping into a canonical State tuple."""
    if set(tiles.keys()) != set(level.symbols):
        raise ValueError(
            f"Tile symbols {sorted(tiles.keys())} do not match level symbols {list(level.symbols)}."
        )
    coords: list[Coord] = []
    seen: set[Coord] = set()
    for sym in level.symbols:
        pos = _parse_coord(tiles[sym], f"tiles[{sym!r}]")
        if not _in_bounds(pos, level.rows, level.cols):
            raise ValueError(f"Tile {sym!r} position {pos} out of bounds.")
        if pos in level.walls:
            raise ValueError(f"Tile {sym!r} position {pos} is on a wall.")
        if pos in seen:
            raise ValueError(f"Duplicate tile position {pos}.")
        seen.add(pos)
        coords.append(pos)
    return tuple(coords)


def tiles_dict_from_state(level: Level, state: State) -> dict[str, list[int]]:
    """Convert a canonical State tuple into a JSON-serializable {symbol: [row, col]} dict."""
    return {
        sym: [state[idx][0], state[idx][1]]
        for idx, sym in enumerate(level.symbols)
    }


def slide_tile(
    level: Level,
    state: State,
    symbol_idx: int,
    direction: str,
) -> tuple[State, Coord]:
    """Slide a single tile orthogonally according to level.slide_mode."""
    if direction not in DIRECTIONS:
        raise ValueError(f"Invalid direction {direction!r}. Expected one of {list(DIRECTIONS)}.")
    if not (0 <= symbol_idx < len(level.symbols)):
        raise IndexError(f"symbol_idx {symbol_idx} out of range.")

    dr, dc = DIRECTIONS[direction]
    r, c = state[symbol_idx]
    occupied = set(state)
    occupied.remove((r, c))

    if level.slide_mode == "single_step":
        nr, nc = r + dr, c + dc
        if (
            0 <= nr < level.rows
            and 0 <= nc < level.cols
            and (nr, nc) not in level.walls
            and (nr, nc) not in occupied
        ):
            r, c = nr, nc
    else:
        while True:
            nr, nc = r + dr, c + dc
            if (
                0 <= nr < level.rows
                and 0 <= nc < level.cols
                and (nr, nc) not in level.walls
                and (nr, nc) not in occupied
            ):
                r, c = nr, nc
            else:
                break

    new_pos = (r, c)
    if new_pos == state[symbol_idx]:
        return state, new_pos

    new_state_list = list(state)
    new_state_list[symbol_idx] = new_pos
    return tuple(new_state_list), new_pos


def _heuristic(state: State, goal: State, slide_mode: str) -> int:
    """Admissible and consistent lower bound on remaining moves to goal."""
    total = 0
    if slide_mode == "single_step":
        for (r, c), (tr, tc) in zip(state, goal):
            total += abs(r - tr) + abs(c - tc)
        return total

    for (r, c), (tr, tc) in zip(state, goal):
        if r != tr and c != tc:
            total += 2
        elif r != tr or c != tc:
            total += 1
    return total


def _reconstruct_path(
    parent: dict[State, tuple[State, Move]],
    end_state: State,
) -> list[Move]:
    path: list[Move] = []
    cursor = end_state
    while cursor in parent:
        prev_state, prev_move = parent[cursor]
        path.append(prev_move)
        cursor = prev_state
    path.reverse()
    return path


def solve_bfs(
    level: Level,
    start_state: State | None = None,
    max_states: int = 250_000,
    use_heuristic: bool = True,
) -> SolveResult:
    """Find the exact shortest move sequence from start_state to level.goal_state."""
    start = start_state if start_state is not None else level.initial_state
    if start == level.goal_state:
        return SolveResult(
            solvable=True,
            optimal_moves=0,
            path=[],
            states_explored=1,
            truncated=False,
        )

    num_symbols = len(level.symbols)

    if use_heuristic:
        h0 = _heuristic(start, level.goal_state, level.slide_mode)
        buckets: dict[int, deque[tuple[int, State]]] = {h0: deque([(0, start)])}
        min_f = h0
        g_score: dict[State, int] = {start: 0}
        parent: dict[State, tuple[State, Move]] = {}

        while buckets:
            while min_f not in buckets:
                min_f += 1
            bucket = buckets[min_f]
            g, curr = bucket.popleft()
            if not bucket:
                del buckets[min_f]

            if g > g_score.get(curr, -1):
                continue

            if curr == level.goal_state:
                path = _reconstruct_path(parent, curr)
                return SolveResult(
                    solvable=True,
                    optimal_moves=len(path),
                    path=path,
                    states_explored=len(g_score),
                    truncated=False,
                )

            next_g = g + 1
            for idx in range(num_symbols):
                from_pos = curr[idx]
                sym = level.symbols[idx]
                for direction in ("U", "D", "L", "R"):
                    nxt, to_pos = slide_tile(level, curr, idx, direction)
                    if to_pos == from_pos:
                        continue
                    prev_best = g_score.get(nxt)
                    if prev_best is not None and next_g >= prev_best:
                        continue

                    g_score[nxt] = next_g
                    parent[nxt] = (
                        curr,
                        Move(
                            symbol=sym,
                            direction=direction,
                            from_pos=from_pos,
                            to_pos=to_pos,
                        ),
                    )
                    if len(g_score) >= max_states:
                        return SolveResult(
                            solvable=False,
                            optimal_moves=None,
                            path=[],
                            states_explored=len(g_score),
                            truncated=True,
                        )
                    f = next_g + _heuristic(nxt, level.goal_state, level.slide_mode)
                    if f in buckets:
                        buckets[f].append((next_g, nxt))
                    else:
                        buckets[f] = deque([(next_g, nxt)])
                    if f < min_f:
                        min_f = f

        return SolveResult(
            solvable=False,
            optimal_moves=None,
            path=[],
            states_explored=len(g_score),
            truncated=False,
        )

    queue: deque[State] = deque([start])
    visited: set[State] = {start}
    parent = {}

    while queue:
        curr = queue.popleft()
        for idx in range(num_symbols):
            from_pos = curr[idx]
            sym = level.symbols[idx]
            for direction in ("U", "D", "L", "R"):
                nxt, to_pos = slide_tile(level, curr, idx, direction)
                if to_pos == from_pos or nxt in visited:
                    continue

                move = Move(
                    symbol=sym,
                    direction=direction,
                    from_pos=from_pos,
                    to_pos=to_pos,
                )
                if nxt == level.goal_state:
                    parent[nxt] = (curr, move)
                    path = _reconstruct_path(parent, nxt)
                    return SolveResult(
                        solvable=True,
                        optimal_moves=len(path),
                        path=path,
                        states_explored=len(visited) + 1,
                        truncated=False,
                    )

                visited.add(nxt)
                parent[nxt] = (curr, move)
                if len(visited) >= max_states:
                    return SolveResult(
                        solvable=False,
                        optimal_moves=None,
                        path=[],
                        states_explored=len(visited),
                        truncated=True,
                    )
                queue.append(nxt)

    return SolveResult(
        solvable=False,
        optimal_moves=None,
        path=[],
        states_explored=len(visited),
        truncated=False,
    )


def get_hint(
    level: Level,
    current_tiles: dict[str, list[int]],
    max_states: int = 250_000,
) -> dict[str, Any]:
    """Compute the optimal next move from the given tile positions."""
    state = state_from_tiles_dict(level, current_tiles)
    if state == level.goal_state:
        return {
            "solvable": True,
            "solved": True,
            "next_move": None,
            "remaining_moves": 0,
            "truncated": False,
        }

    result = solve_bfs(level, start_state=state, max_states=max_states)
    return {
        "solvable": result.solvable,
        "solved": False,
        "next_move": result.path[0].to_dict() if result.path else None,
        "remaining_moves": result.optimal_moves,
        "truncated": result.truncated,
    }


def compute_star_thresholds(optimal_moves: int) -> dict[str, int]:
    """Compute 3-star and 2-star move thresholds from optimal_moves."""
    return {
        "three_star": optimal_moves,
        "two_star": optimal_moves + max(2, math.ceil(optimal_moves * 0.35)),
    }


def generate_level(
    rows: int,
    cols: int,
    num_tiles: int,
    wall_count: int = 2,
    slide_mode: str = "full_slide",
    min_optimal_moves: int = 4,
    seed: int | None = None,
    max_attempts: int = 300,
    max_states: int = 60_000,
    level_id: str = "generated",
    name: str = "Generated Puzzle",
    difficulty: str = "medium",
) -> dict[str, Any]:
    """Procedurally generate a level and verify solvability via BFS."""
    if not (3 <= rows <= 6 and 3 <= cols <= 6):
        raise ValueError("rows and cols must be between 3 and 6.")
    if not (2 <= num_tiles <= 6):
        raise ValueError("num_tiles must be between 2 and 6.")
    if slide_mode not in VALID_SLIDE_MODES:
        raise ValueError(f"slide_mode must be one of {VALID_SLIDE_MODES}.")
    if wall_count < 0 or wall_count + num_tiles > rows * cols:
        raise ValueError("Too many walls and tiles for the board dimensions.")

    rng = random.Random(seed)
    all_cells = [(r, c) for r in range(rows) for c in range(cols)]
    active_symbols = list(SYMBOLS[:num_tiles])

    best_candidate: dict[str, Any] | None = None
    best_moves = -1

    for _ in range(max_attempts):
        walls = rng.sample(all_cells, wall_count)
        wall_set = set(walls)
        free_cells = [cell for cell in all_cells if cell not in wall_set]

        tile_cells = rng.sample(free_cells, num_tiles)
        base_candidate = {
            "id": level_id,
            "name": name,
            "difficulty": difficulty,
            "rows": rows,
            "cols": cols,
            "slide_mode": slide_mode,
            "walls": [[r, c] for r, c in sorted(walls)],
            "tiles": {sym: [pos[0], pos[1]] for sym, pos in zip(active_symbols, tile_cells)},
            # Temporary goal placeholder to use slide_tile for a guaranteed-solvable forward walk
            "targets": {sym: [pos[0], pos[1]] for sym, pos in zip(active_symbols, rng.sample(free_cells, num_tiles))},
        }
        walk_level = Level(
            id=level_id,
            name=name,
            rows=rows,
            cols=cols,
            slide_mode=slide_mode,
            walls=frozenset(walls),
            symbols=tuple(sorted(active_symbols)),
            initial_state=tuple(tile_cells[active_symbols.index(s)] for s in sorted(active_symbols)),
            goal_state=tuple(tile_cells[active_symbols.index(s)] for s in sorted(active_symbols)),
        )

        walk_state = walk_level.initial_state
        walk_steps = rng.randint(min_optimal_moves + 4, min_optimal_moves * 3 + 8)
        for _step in range(walk_steps):
            valid_next: list[State] = []
            for idx in range(num_tiles):
                for direction in ("U", "D", "L", "R"):
                    nxt, to_pos = slide_tile(walk_level, walk_state, idx, direction)
                    if to_pos != walk_state[idx]:
                        valid_next.append(nxt)
            if not valid_next:
                break
            walk_state = rng.choice(valid_next)

        if walk_state == walk_level.initial_state:
            continue

        candidate = {
            **base_candidate,
            "targets": tiles_dict_from_state(walk_level, walk_state),
        }

        level = level_from_dict(candidate)
        result = solve_bfs(level, max_states=max_states)
        if not result.solvable or result.optimal_moves is None:
            continue

        if result.optimal_moves > best_moves:
            best_moves = result.optimal_moves
            best_candidate = {
                **candidate,
                "optimal_moves": result.optimal_moves,
                "par_moves": result.optimal_moves,
            }

        if result.optimal_moves >= min_optimal_moves:
            return {
                **candidate,
                "optimal_moves": result.optimal_moves,
                "par_moves": result.optimal_moves,
            }

    if best_candidate is not None and min_optimal_moves <= 1:
        return best_candidate

    raise RuntimeError(
        f"Failed to generate solvable {rows}x{cols} level with >= {min_optimal_moves} "
        f"optimal moves in {max_attempts} attempts (best found: {best_moves})."
    )


def load_levels(path: str | Path = "levels.json") -> list[dict[str, Any]]:
    """Load levels list from a JSON file."""
    file_path = Path(path)
    if not file_path.exists():
        return []
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "levels" in payload:
        levels = payload["levels"]
        if not isinstance(levels, list):
            raise ValueError("'levels' in levels.json must be a list.")
        return levels
    if isinstance(payload, list):
        return payload
    raise ValueError("levels.json must be a JSON object with a 'levels' key.")


def save_levels(levels: list[dict[str, Any]], path: str | Path = "levels.json") -> None:
    """Persist levels list to a JSON file."""
    file_path = Path(path)
    payload = {"version": 1, "levels": levels}
    file_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
