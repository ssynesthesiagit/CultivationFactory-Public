from __future__ import annotations

from collections import deque
from typing import Iterable, Literal

from pydantic import Field, model_validator

from .gate2_runtime_models import Position
from .models import StrictModel

FOOTPRINT_SCHEMA = "TianxiaActorFootprint.v1"
FOOTPRINT_PROJECTION_SCHEMA = "TianxiaActorFootprintProjection.v1"


class ActorFootprintDefinition(StrictModel):
    """Immutable combatant footprint authority.

    Coordinates are relative to an actor's stable top-left anchor cell.  This
    definition is mechanical data; token art and CSS scaling cannot modify it.
    """

    schema_name: Literal[FOOTPRINT_SCHEMA] = Field(default=FOOTPRINT_SCHEMA, alias="schema")
    footprint_id: str
    anchor_semantics: Literal["TOP_LEFT"] = "TOP_LEFT"
    width_cells: int = Field(ge=1)
    height_cells: int = Field(ge=1)
    occupied_relative_cells: tuple[Position, ...]
    source_definition_id: str

    @model_validator(mode="after")
    def validate_shape(self) -> "ActorFootprintDefinition":
        cells = tuple((cell.x, cell.y) for cell in self.occupied_relative_cells)
        if not cells:
            raise ValueError("footprint must occupy at least one cell")
        if len(cells) != len(set(cells)):
            raise ValueError("footprint contains duplicate occupied cells")
        if (0, 0) not in set(cells):
            raise ValueError("footprint must include its top-left anchor cell")
        if any(x >= self.width_cells or y >= self.height_cells for x, y in cells):
            raise ValueError("occupied cell falls outside declared footprint bounds")
        if max(x for x, _ in cells) != self.width_cells - 1:
            raise ValueError("footprint width is not normalized to occupied cells")
        if max(y for _, y in cells) != self.height_cells - 1:
            raise ValueError("footprint height is not normalized to occupied cells")

        remaining = set(cells)
        queue: deque[tuple[int, int]] = deque([(0, 0)])
        visited: set[tuple[int, int]] = set()
        while queue:
            cell = queue.popleft()
            if cell in visited or cell not in remaining:
                continue
            visited.add(cell)
            x, y = cell
            queue.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
        if visited != remaining:
            raise ValueError("footprint occupied cells must be orthogonally connected")
        return self

    @classmethod
    def rectangle(
        cls,
        width_cells: int,
        height_cells: int,
        *,
        footprint_id: str,
        source_definition_id: str,
    ) -> "ActorFootprintDefinition":
        return cls(
            footprint_id=footprint_id,
            width_cells=width_cells,
            height_cells=height_cells,
            occupied_relative_cells=tuple(
                Position(x=x, y=y)
                for y in range(height_cells)
                for x in range(width_cells)
            ),
            source_definition_id=source_definition_id,
        )

    @property
    def is_single_cell(self) -> bool:
        return (
            self.width_cells == 1
            and self.height_cells == 1
            and tuple((cell.x, cell.y) for cell in self.occupied_relative_cells) == ((0, 0),)
        )

    def occupied_cells(self, anchor: Position | tuple[int, int]) -> tuple[tuple[int, int], ...]:
        ax, ay = (anchor.x, anchor.y) if isinstance(anchor, Position) else anchor
        return tuple(sorted((ax + cell.x, ay + cell.y) for cell in self.occupied_relative_cells))


class ActorFootprintProjection(StrictModel):
    schema_name: Literal[FOOTPRINT_PROJECTION_SCHEMA] = Field(
        default=FOOTPRINT_PROJECTION_SCHEMA,
        alias="schema",
    )
    footprint_id: str
    source_definition_id: str
    anchor_semantics: Literal["TOP_LEFT"] = "TOP_LEFT"
    anchor_x: int = Field(ge=0)
    anchor_y: int = Field(ge=0)
    width_cells: int = Field(ge=1)
    height_cells: int = Field(ge=1)
    occupied_cells: tuple[Position, ...]
    in_bounds: bool
    collision_free: bool
    mechanics_authoritative: bool
    compatibility_mode: Literal["TYPED", "LEGACY_SINGLE_CELL"]


STANDARD_ACTOR_FOOTPRINT = ActorFootprintDefinition.rectangle(
    1,
    1,
    footprint_id="footprint:standard.1x1",
    source_definition_id="system:combat.footprint.standard_1x1",
)


def standard_actor_footprint() -> ActorFootprintDefinition:
    """Return an independent immutable-value copy for Pydantic default factories."""

    return STANDARD_ACTOR_FOOTPRINT.model_copy(deep=True)


def project_actor_footprint(
    definition: ActorFootprintDefinition,
    anchor: Position,
    *,
    grid_width: int,
    grid_height: int,
    blocked_cells: Iterable[tuple[int, int]] = (),
    occupied_by_other: Iterable[tuple[int, int]] = (),
    mechanics_authoritative: bool,
    compatibility_mode: Literal["TYPED", "LEGACY_SINGLE_CELL"],
) -> ActorFootprintProjection:
    occupied = definition.occupied_cells(anchor)
    blocked = set(blocked_cells)
    other = set(occupied_by_other)
    in_bounds = all(0 <= x < grid_width and 0 <= y < grid_height for x, y in occupied)
    collision_free = in_bounds and not any(cell in blocked or cell in other for cell in occupied)
    return ActorFootprintProjection(
        footprint_id=definition.footprint_id,
        source_definition_id=definition.source_definition_id,
        anchor_x=anchor.x,
        anchor_y=anchor.y,
        width_cells=definition.width_cells,
        height_cells=definition.height_cells,
        occupied_cells=tuple(Position(x=x, y=y) for x, y in occupied),
        in_bounds=in_bounds,
        collision_free=collision_free,
        mechanics_authoritative=mechanics_authoritative,
        compatibility_mode=compatibility_mode,
    )
