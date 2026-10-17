"""The GM view model validates against the real pinned vendor view schema, un-stubbed.

Reads the bundled Factory archive, so it runs locally and on private CI only; test_future_pipeline_repairs.py keeps a copied
required-key list as the public fallback (Overseer 2026-10-17).
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tests.test_future_pipeline_repairs import command5_view

ARCHIVE = Path(__file__).resolve().parents[1] / "BundledContent" / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
SCHEMA = "HF05ZVK_R1H_Phase2I_HF2/04_SCHEMAS/gm_character_view_model.schema.json"


def test_command5_view_validates_against_the_pinned_view_schema(tmp_path: Path) -> None:
    if not ARCHIVE.is_file():
        pytest.skip("bundled Factory archive is not in this checkout")
    with zipfile.ZipFile(ARCHIVE) as archive:
        schema = json.loads(archive.read(SCHEMA))
    errors = sorted(error.message for error in Draft202012Validator(schema).iter_errors(command5_view(tmp_path)))
    assert errors == []
