from __future__ import annotations

import inspect

from character_creation import CharacterCreationExecutionService
from character_creation.stage1_first_compile import compile_once_stage1_first


def test_production_compile_uses_stage1_first_order() -> None:
    assert CharacterCreationExecutionService._compile_once is compile_once_stage1_first

    source = inspect.getsource(CharacterCreationExecutionService._compile_once)
    stage1_commit = source.index("stage1_commit = stage1.approve_and_commit")
    method_materialization = source.index("method_access_receipt = self._materialize_method_hard_lock")
    stage2_commit = source.index("stage2_validation, stage2_commit = self._stage2_commit")

    assert stage1_commit < method_materialization < stage2_commit
