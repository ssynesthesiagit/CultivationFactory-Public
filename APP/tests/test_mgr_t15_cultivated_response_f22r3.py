"""Regressions for the F22R3 Cultivated Response review findings.

Each test fails on the F22R3 record and passes once its fix is in place. The native CL20 pick is in
test_mgr_t15_cultivated_response.py (it needs that module's native_sheets fixture).
"""
import json

from tests.h1_support import ROOT

SPIRIT = ROOT / "combat/rules/feature_status.d/spirit.json"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"


# F22R3 finding 1: CL20 must not grant the three Disciplines without a save-time pick.
def test_f22r3_1_chosen_abilities_has_no_cl20_auto_grant():
    source = (ROOT / "combat/ext/defensive_disciplines.py").read_text(encoding="utf-8")
    assert "if limit >= len(codes)" not in source
    assert "return [*picked, *(code for code in codes" not in source


# F22R3 finding 2: the status text must describe the save-time pick, not an automatic grant.
def test_f22r3_2_status_describes_the_save_time_pick_at_cl20():
    why = json.loads(SPIRIT.read_text(encoding="utf-8"))["features"][CULTIVATED]["why"]
    assert "grants all three" not in why
    assert "each picked at save time" in why


# F22R3 finding 4: the unused allow_insufficient opt-in is removed from the engine.
def test_f22r3_4_allow_insufficient_opt_in_is_removed():
    for rel in ("combat/typed_reactions.py", "combat/ext/__init__.py"):
        assert "allow_insufficient" not in (ROOT / rel).read_text(encoding="utf-8"), rel
