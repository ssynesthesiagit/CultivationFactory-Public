from .service import CharacterCreationExecutionService
from .stage1_first_compile import compile_once_stage1_first


CharacterCreationExecutionService._compile_once = compile_once_stage1_first

__all__ = ["CharacterCreationExecutionService"]
