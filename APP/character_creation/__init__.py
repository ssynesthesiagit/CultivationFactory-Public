"""Creation contracts can be imported without initializing the whole service."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import CharacterCreationExecutionService

__all__ = ["CharacterCreationExecutionService"]


def __getattr__(name: str):
    if name == "CharacterCreationExecutionService":
        from .service import CharacterCreationExecutionService

        globals()[name] = CharacterCreationExecutionService
        return CharacterCreationExecutionService
    if name == "compile_once_stage1_first":
        from .stage1_first_compile import compile_once_stage1_first

        return compile_once_stage1_first
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
