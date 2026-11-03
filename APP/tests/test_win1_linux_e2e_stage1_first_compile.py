from __future__ import annotations

import inspect

from character_creation import CharacterCreationExecutionService
from character_creation.stage1_first_compile import compile_once_stage1_first


def test_production_compile_uses_stage1_first_order() -> None:
    assert CharacterCreationExecutionService._compile_once is compile_once_stage1_first

    source = inspect.getsource(CharacterCreationExecutionService._compile_once)
    stage1_commit = source.index("stage1_commit = stage1.approve_and_commit")
    method_materialization = source.index("method_access_receipt = self._materialize_method_hard_lock")
    stage2_commit = source.index(
        "stage2_validation, stage2_commit, projection = self._stage2_commit"
    )
    projection_callback = source.index(
        "after_commit=build_scratch_projection_inside_stage2_scope"
    )

    assert stage1_commit < method_materialization < stage2_commit < projection_callback


def test_runtime_stage1_first_compiler_carries_private_timing_sink() -> None:
    compiler = CharacterCreationExecutionService._compile_once
    assert "_timing_sink" in inspect.signature(compiler).parameters

    source = inspect.getsource(compiler)
    assert "_timing_sink" in source
    assert '"_timings": _service._compile_timing_receipt(compile_timings)' in source

    # 255c4b21 (overlapping finalize fix) moved the two builds into
    # _compile_twice_in_replay, which _compile_twice runs inside one
    # deterministic replay clock.
    assert "self._compile_twice_in_replay(" in inspect.getsource(CharacterCreationExecutionService._compile_twice)
    twice_source = inspect.getsource(CharacterCreationExecutionService._compile_twice_in_replay)
    assert '"_timing_sink": compile_1_timings' in twice_source
    assert '"_timing_sink": compile_2_timings' in twice_source
