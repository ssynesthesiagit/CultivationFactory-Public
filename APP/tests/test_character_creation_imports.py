"""Shared contracts must not depend on an application service import order."""

from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("first", [
    "stage2.service", "character_creation.path_attainment",
    "projector.v3_bridge", "character_creation.service", "character_creation.stage1_first_compile",
])
def test_creation_and_causal_services_import_in_a_fresh_process(first):
    result = subprocess.run(
        [sys.executable, "-c", (
            "import importlib, sys; importlib.import_module(sys.argv[1]); "
            "from character_creation import CharacterCreationExecutionService; "
            "from character_creation.service import CharacterCreationExecutionService as Direct; "
            "from character_creation.stage1_first_compile import compile_once_stage1_first; "
            "assert Direct is CharacterCreationExecutionService; "
            "assert Direct._compile_once is compile_once_stage1_first"
        ), first],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
