from __future__ import annotations

import heapq
import json
from pathlib import Path
from typing import Any, Iterable

from .gate2_runtime_models import Position


NEIGHBORS = tuple(
    sorted(
        (dx, dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if (dx, dy) != (0, 0)
    )
)


class SquareGrid:
    def __init__(self, document: dict):
        self.width = int(document["width_squares"])
        self.height = int(document["height_squares"])
        self.square_size_ft = int(document["square_size_ft"])
        self.starting_positions = {
            k: Position.model_validate(v)
            for k, v in document["starting_positions"].items()
        }
        self.blocked: set[tuple[int, int]] = set()
        self.cover: set[tuple[int, int]] = set()
        self.qi_hazard: set[tuple[int, int]] = set()
        self.base_movement_cost: dict[tuple[int, int], int] = {}
        for region in document["terrain_regions"]:
            cells = {(int(c["x"]), int(c["y"])) for c in region["cells"]}
            terrain_type = region["terrain_type"]
            if terrain_type == "BLOCKED":
                self.blocked |= cells
            elif terrain_type == "SIMPLE_COVER":
                self.cover |= cells
            elif terrain_type == "QI_HAZARD":
                self.qi_hazard |= cells
            for cell in cells:
                self.base_movement_cost[cell] = int(region["movement_cost"])

    @classmethod
    def load(cls, path: Path) -> "SquareGrid":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _cell_tuple(cell: Position | tuple[int, int]) -> tuple[int, int]:
        return (cell.x, cell.y) if isinstance(cell, Position) else cell

    @classmethod
    def _cell_set(
        cls,
        cells: Iterable[Position | tuple[int, int]],
    ) -> set[tuple[int, int]]:
        if isinstance(cells, set) and all(
            isinstance(cell, tuple) and len(cell) == 2 for cell in cells
        ):
            return cells
        return {cls._cell_tuple(cell) for cell in cells}

    @staticmethod
    def footprint_cells(
        anchor: Position | tuple[int, int],
        footprint: Any | None = None,
    ) -> tuple[tuple[int, int], ...]:
        anchor_t = (anchor.x, anchor.y) if isinstance(anchor, Position) else anchor
        if footprint is None:
            return (anchor_t,)
        return tuple(footprint.occupied_cells(anchor_t))

    def in_bounds(self, cell: tuple[int, int]) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def placement_legal(
        self,
        anchor: Position | tuple[int, int],
        *,
        footprint: Any | None = None,
        occupied_cells: Iterable[Position | tuple[int, int]] = (),
    ) -> bool:
        cells = self.footprint_cells(anchor, footprint)
        occupied = self._cell_set(occupied_cells)
        return all(
            self.in_bounds(cell)
            and cell not in self.blocked
            and cell not in occupied
            for cell in cells
        )

    def distance_cells(
        self,
        a: Position | tuple[int, int],
        b: Position | tuple[int, int],
    ) -> int:
        ax, ay = self._cell_tuple(a)
        bx, by = self._cell_tuple(b)
        return max(abs(ax - bx), abs(ay - by))

    def distance_ft(
        self,
        a: Position | tuple[int, int],
        b: Position | tuple[int, int],
    ) -> int:
        return self.distance_cells(a, b) * self.square_size_ft

    def distance_between_cell_sets(
        self,
        a_cells: Iterable[Position | tuple[int, int]],
        b_cells: Iterable[Position | tuple[int, int]],
    ) -> int:
        left = self._cell_set(a_cells)
        right = self._cell_set(b_cells)
        if not left or not right:
            raise ValueError("distance requires two non-empty cell sets")
        return min(self.distance_cells(a, b) for a in left for b in right)

    def distance_between_cell_sets_ft(
        self,
        a_cells: Iterable[Position | tuple[int, int]],
        b_cells: Iterable[Position | tuple[int, int]],
    ) -> int:
        return self.distance_between_cell_sets(a_cells, b_cells) * self.square_size_ft

    def _step_legal(
        self,
        current: tuple[int, int],
        nxt: tuple[int, int],
        occupied_cells: set[tuple[int, int]],
        footprint: Any | None,
    ) -> bool:
        if not self.placement_legal(
            nxt,
            footprint=footprint,
            occupied_cells=occupied_cells,
        ):
            return False
        dx, dy = nxt[0] - current[0], nxt[1] - current[1]
        if dx and dy:
            # A diagonal translation is legal only when the complete footprint
            # could occupy both orthogonal intermediate anchor placements. This
            # prevents any edge of a multi-cell creature from clipping a corner.
            side_a = (current[0] + dx, current[1])
            side_b = (current[0], current[1] + dy)
            if not self.placement_legal(
                side_a,
                footprint=footprint,
                occupied_cells=occupied_cells,
            ):
                return False
            if not self.placement_legal(
                side_b,
                footprint=footprint,
                occupied_cells=occupied_cells,
            ):
                return False
        return True

    def step_legal(
        self,
        current: Position | tuple[int, int],
        nxt: Position | tuple[int, int],
        *,
        occupied_cells: Iterable[Position | tuple[int, int]] = (),
        footprint: Any | None = None,
    ) -> bool:
        current_t = self._cell_tuple(current)
        next_t = self._cell_tuple(nxt)
        dx, dy = next_t[0] - current_t[0], next_t[1] - current_t[1]
        if (dx, dy) not in NEIGHBORS:
            return False
        return self._step_legal(
            current_t,
            next_t,
            self._cell_set(occupied_cells),
            footprint,
        )

    def movement_step_multiplier(
        self,
        current: Position | tuple[int, int],
        nxt: Position | tuple[int, int],
        *,
        footprint: Any | None = None,
        difficult_cells: set[tuple[int, int]] | None = None,
    ) -> int:
        current_cells = set(self.footprint_cells(current, footprint))
        next_cells = set(self.footprint_cells(nxt, footprint))
        entered = next_cells - current_cells
        evaluated = entered or next_cells
        difficult = difficult_cells or set()
        multiplier = 1
        for cell in evaluated:
            multiplier = max(multiplier, self.base_movement_cost.get(cell, 1))
            if cell in difficult:
                multiplier = max(multiplier, 2)
        return multiplier

    def shortest_path(
        self,
        start: Position,
        goal: Position,
        *,
        occupied: Iterable[Position | tuple[int, int]] = (),
        occupied_cells: Iterable[Position | tuple[int, int]] | None = None,
        difficult_cells: set[tuple[int, int]] | None = None,
        max_cost_ft: int | None = None,
        footprint: Any | None = None,
    ) -> tuple[tuple[Position, ...], int] | None:
        start_t, goal_t = (start.x, start.y), (goal.x, goal.y)
        occupied_t = self._cell_set(occupied)
        if occupied_cells is not None:
            occupied_t |= self._cell_set(occupied_cells)
        difficult = difficult_cells or set()
        if not self.placement_legal(
            start_t,
            footprint=footprint,
            occupied_cells=(),
        ):
            return None
        if not self.placement_legal(
            goal_t,
            footprint=footprint,
            occupied_cells=occupied_t,
        ):
            return None
        queue: list[tuple[int, int, int, tuple[int, int]]] = [
            (0, start_t[1], start_t[0], start_t)
        ]
        best = {start_t: 0}
        previous: dict[tuple[int, int], tuple[int, int]] = {}
        while queue:
            cost, _, _, cell = heapq.heappop(queue)
            if cost != best[cell]:
                continue
            if cell == goal_t:
                path = [cell]
                while path[-1] != start_t:
                    path.append(previous[path[-1]])
                path.reverse()
                return tuple(Position(x=x, y=y) for x, y in path), cost
            for dx, dy in NEIGHBORS:
                nxt = (cell[0] + dx, cell[1] + dy)
                if not self._step_legal(cell, nxt, occupied_t, footprint):
                    continue
                multiplier = self.movement_step_multiplier(
                    cell,
                    nxt,
                    footprint=footprint,
                    difficult_cells=difficult,
                )
                if multiplier <= 0:
                    continue
                new_cost = cost + self.square_size_ft * multiplier
                if max_cost_ft is not None and new_cost > max_cost_ft:
                    continue
                if new_cost < best.get(nxt, 10**9):
                    best[nxt] = new_cost
                    previous[nxt] = cell
                    heapq.heappush(queue, (new_cost, nxt[1], nxt[0], nxt))
        return None

    def reachable(
        self,
        start: Position,
        *,
        movement_ft: int,
        occupied: Iterable[Position | tuple[int, int]] = (),
        occupied_cells: Iterable[Position | tuple[int, int]] | None = None,
        difficult_cells: set[tuple[int, int]] | None = None,
        footprint: Any | None = None,
    ) -> dict[Position, tuple[tuple[Position, ...], int]]:
        start_t = (start.x, start.y)
        occupied_t = self._cell_set(occupied)
        if occupied_cells is not None:
            occupied_t |= self._cell_set(occupied_cells)
        difficult = difficult_cells or set()
        if not self.placement_legal(start_t, footprint=footprint):
            return {}

        queue: list[tuple[int, int, int, tuple[int, int]]] = [
            (0, start_t[1], start_t[0], start_t)
        ]
        best = {start_t: 0}
        previous: dict[tuple[int, int], tuple[int, int]] = {}
        while queue:
            cost, _, _, cell = heapq.heappop(queue)
            if cost != best[cell]:
                continue
            for dx, dy in NEIGHBORS:
                nxt = (cell[0] + dx, cell[1] + dy)
                if not self._step_legal(cell, nxt, occupied_t, footprint):
                    continue
                multiplier = self.movement_step_multiplier(
                    cell,
                    nxt,
                    footprint=footprint,
                    difficult_cells=difficult,
                )
                if multiplier <= 0:
                    continue
                new_cost = cost + self.square_size_ft * multiplier
                if new_cost > movement_ft:
                    continue
                if new_cost < best.get(nxt, 10**9):
                    best[nxt] = new_cost
                    previous[nxt] = cell
                    heapq.heappush(queue, (new_cost, nxt[1], nxt[0], nxt))

        results: dict[Position, tuple[tuple[Position, ...], int]] = {}
        for goal_t, cost in best.items():
            if goal_t == start_t:
                continue
            path = [goal_t]
            while path[-1] != start_t:
                path.append(previous[path[-1]])
            path.reverse()
            goal = Position(x=goal_t[0], y=goal_t[1])
            results[goal] = (
                tuple(Position(x=x, y=y) for x, y in path),
                cost,
            )
        return results

    @staticmethod
    def compress_path(path: tuple[Position, ...]) -> tuple[Position, ...]:
        if len(path) <= 2:
            return path
        compressed = [path[0]]
        last_dx = path[1].x - path[0].x
        last_dy = path[1].y - path[0].y
        for i in range(1, len(path) - 1):
            dx = path[i + 1].x - path[i].x
            dy = path[i + 1].y - path[i].y
            if (dx, dy) != (last_dx, last_dy):
                compressed.append(path[i])
                last_dx, last_dy = dx, dy
        compressed.append(path[-1])
        return tuple(compressed)

    def ray_cells(self, start: Position, end: Position) -> tuple[tuple[int, int], ...]:
        x0, y0, x1, y1 = start.x, start.y, end.x, end.y
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        cells = []
        while True:
            cells.append((x0, y0))
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy
        return tuple(cells)

    def line_of_sight(
        self,
        start: Position,
        end: Position,
        *,
        obscured_cells: set[tuple[int, int]] | None = None,
    ) -> bool:
        ray = self.ray_cells(start, end)
        for cell in ray[1:-1]:
            if cell in self.blocked:
                return False
            if obscured_cells and cell in obscured_cells:
                return False
        if obscured_cells and (
            (start.x, start.y) in obscured_cells
            or (end.x, end.y) in obscured_cells
        ):
            return False
        return True

    def line_of_sight_between_cell_sets(
        self,
        a_cells: Iterable[Position | tuple[int, int]],
        b_cells: Iterable[Position | tuple[int, int]],
        *,
        obscured_cells: set[tuple[int, int]] | None = None,
    ) -> bool:
        left = sorted(self._cell_set(a_cells))
        right = sorted(self._cell_set(b_cells))
        return any(
            self.line_of_sight(
                Position(x=ax, y=ay),
                Position(x=bx, y=by),
                obscured_cells=obscured_cells,
            )
            for ax, ay in left
            for bx, by in right
        )

    def cover_bonus(self, start: Position, end: Position) -> int:
        return (
            2
            if any(
                cell in self.cover
                for cell in self.ray_cells(start, end)[1:-1]
            )
            else 0
        )

    def cover_bonus_between_cell_sets(
        self,
        attacker_cells: Iterable[Position | tuple[int, int]],
        target_cells: Iterable[Position | tuple[int, int]],
        *,
        obscured_cells: set[tuple[int, int]] | None = None,
    ) -> int:
        # The attacker may use any legal sight line from its occupied footprint
        # to any exposed target cell. Cover applies only when every available
        # legal line crosses typed cover geometry.
        bonuses: list[int] = []
        for ax, ay in sorted(self._cell_set(attacker_cells)):
            for bx, by in sorted(self._cell_set(target_cells)):
                start = Position(x=ax, y=ay)
                end = Position(x=bx, y=by)
                if self.line_of_sight(
                    start,
                    end,
                    obscured_cells=obscured_cells,
                ):
                    bonuses.append(self.cover_bonus(start, end))
        return min(bonuses) if bonuses else 0

    def cells_in_radius(self, center: Position, radius_cells: int) -> tuple[Position, ...]:
        return self.cells_in_radius_of_cells((center,), radius_cells)

    def cells_in_radius_of_cells(
        self,
        centers: Iterable[Position | tuple[int, int]],
        radius_cells: int,
    ) -> tuple[Position, ...]:
        center_cells = self._cell_set(centers)
        if not center_cells:
            return ()
        cells = []
        for y in range(self.height):
            for x in range(self.width):
                if min(
                    max(abs(x - cx), abs(y - cy))
                    for cx, cy in center_cells
                ) <= radius_cells:
                    cells.append(Position(x=x, y=y))
        return tuple(cells)
