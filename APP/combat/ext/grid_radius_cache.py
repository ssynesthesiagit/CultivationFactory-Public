"""Shared radius entry point used by character_runtime_adapter's area resolvers.

SquareGrid now owns exact, bounded geometry reuse natively. Delegate normally
so subclasses and existing instance overrides retain their geometry contract.
"""
from ..gate2_grid import SquareGrid
from ..gate2_runtime_models import Position


def cells_in_radius(grid: SquareGrid, center: Position, radius_cells: int) -> tuple[Position, ...]:
    """Return the grid's exact row-major radius cells without replacing methods."""
    return grid.cells_in_radius(center, radius_cells)
