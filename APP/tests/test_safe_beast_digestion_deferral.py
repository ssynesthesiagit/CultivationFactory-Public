"""The printed downtime record must not masquerade as combat damage reduction."""
import json
from pathlib import Path

from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from tests.h1_support import sheet

RECORD = "foundation.beast_echo_marrow_v0_2A.safe_beast_digestion"


def test_downtime_burden_reduction_has_no_combat_effect():
    mechanic = json.loads(Path(TYPED_AUTHORITY).read_text())["mechanics"][RECORD]
    assert mechanic["effects"] == []
    assert mechanic["coverage"] == "RIDERS_ONLY"
    assert mechanic["riders"] == ["out-of-combat: deferred to the main-game window"]


def test_digestion_does_not_create_combat_action_or_reduction():
    bundle = compile_character(sheet([RECORD]), actor_id="actor:digestion.control")
    assert not any(row.get("parameters", {}).get("typed", {}).get("source") == RECORD
                   for row in bundle["action_catalog"])
    assert not any(row.get("feature_id") == RECORD
                   for row in bundle["typed_passives"] + bundle["typed_reactions"])
