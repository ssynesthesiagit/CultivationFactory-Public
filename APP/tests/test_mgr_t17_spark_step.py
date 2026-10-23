"""Spark Step's owned self-Gather movement and source reconciliation."""
import json
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto_support import ME, _engine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
SPARK = "TAL_LIGHTNING_SPARK_STEP"
GATHER = "TAL_LIGHTNING_GATHER_CHARGE"
LIGHTNING = "tianxia.sphere.lightning"


def _bundle(*, cl=4, spark=True):
    bases = [key for key, row in AUTHORITY.items()
             if row.get("sphere_id") == LIGHTNING and row.get("kind") == "base_ability"]
    talents = [*bases, GATHER, *([SPARK] if spark else [])]
    sheet = {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": cl},
             "spheres_and_talents": {"sphere_record_ids": [LIGHTNING],
                                     "learned_talent_record_ids": talents}}
    return compile_character(sheet, actor_id=ME)


def _intent(candidate, *, targets=None):
    return ActionIntent(intent_id="spark-step-gather", decision_id=candidate.decision_id,
                        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                        actor_id=ME, target_ids=tuple(targets if targets is not None else candidate.target_ids),
                        destination=candidate.destination, option_ids=candidate.option_ids)


def test_spark_step_source_reconciliation_keeps_only_the_unimplemented_range_clause():
    row = AUTHORITY[SPARK]
    assert row["source"]["text_sha256"] == "d409e4af61961b046cced3d466f8d97c2fa8822c67c8ed5bfe900da0867e635e"
    assert row["effects"][0]["distance_ft"] == 5
    assert row["riders"] == ["If you move at least 10 feet on your turn before using Lightning Lash, you may increase Lightning Lash’s range by 10 feet for that attack."]


def test_spark_step_owns_only_its_optional_self_gather_move():
    owned = _engine(_bundle(cl=4), foe_at=(7, 6))
    me = owned.state.actors[ME]
    start = me.position
    gather = next(candidate for candidate in owned.legal_candidates()
                  if candidate.display_name.startswith("Gather Charge") and candidate.target_ids == (ME,))
    owned.execute_intent(_intent(gather))
    assert me.position != start
    assert owned.grid.distance_ft(start, me.position) <= 5
    assert "spark_step_ignore_oa_from" not in me.turn_flags

    unowned = _engine(_bundle(cl=4, spark=False), foe_at=(7, 6))
    other = unowned.state.actors[ME]
    start = other.position
    gather = next(candidate for candidate in unowned.legal_candidates()
                  if candidate.display_name.startswith("Gather Charge") and candidate.target_ids == (ME,))
    unowned.execute_intent(_intent(gather))
    assert other.position == start
