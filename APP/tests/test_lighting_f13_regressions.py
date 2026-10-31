"""Every batch-z failure must remain covered when compiler reference prose is absent."""
import json

import pytest

from combat import factory_compiler
from tests.lighting_darkness_support import synthetic_darkness_rules
from tests.test_lighting_senses import (
    test_worked_example_e11_pure_darkness_clips_every_sense as check_pure_darkness,
)
from tests.test_lighting_zones import (
    test_a_printed_suppression_lifts_the_cap_for_the_viewer_it_names as check_suppression,
    test_the_capped_square_is_dark_for_every_creature_that_stands_in_it as check_cap,
    test_worked_example_e10_the_field_keeps_the_torch_and_the_area_resolves_it as check_torch,
)


@pytest.mark.parametrize("check", [check_pure_darkness, check_torch, check_cap, check_suppression],
                         ids=["pure-darkness", "torch-cap", "occupied-square-cap", "printed-suppression"])
def test_lighting_darkness_survives_redacted_reference_inputs(tmp_path, monkeypatch, check):
    # Force the public-export failure even when running against owner reference
    # files. Retain all mechanical data: only reference text is replaced.
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    authority["mechanics"]["DARK_BASE_DARKNESS"]["description"] = ["Redacted description."]
    authority["mechanics"]["DARK_BASE_DARKNESS"]["riders"] = []
    path = tmp_path / "redacted-lighting-authority.json"
    path.write_text(json.dumps(authority))
    rules = {**factory_compiler._rules_text(),
             "TAL_DARK_PURE_DARKNESS": "### Redacted talent\nRedacted description.",
             "TAL_DARK_PITCH_BLACK": "### Redacted talent\nRedacted description."}
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", path)
    monkeypatch.setattr(factory_compiler, "_RULES_TEXT_CACHE", rules)

    with synthetic_darkness_rules(tmp_path, monkeypatch):
        if check is check_suppression:
            check(tmp_path, monkeypatch)
        else:
            check(tmp_path)

    assert factory_compiler.TYPED_AUTHORITY == path
    assert factory_compiler._rules_text() == rules
