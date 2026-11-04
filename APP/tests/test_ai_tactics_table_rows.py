"""Table-level regression: a Tricky turn for a creature holding Battlefield Beheading Line.

The unit walk in ``test_ai_tactics_effect_rows.py`` proves the parser, but the reported bug was the empty menu at
the table. The reviewed talent stores ``on_success: "suppress"`` on an end_effect row; the Tricky planner used to
call ``.get`` on that string while building its own creature profile, so the menu could not be built.
"""
from tests.ai_tiers_native_support import OWNER, fight


def test_tricky_table_turn_survives_the_plain_nested_setting(tmp_path):
    combat, mid, _ = fight(tmp_path, ["tianxia.talent.sabers.battlefield_beheading_line"])
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO", ai_tier="TRICKY")
    context = combat.ai_decision_context(combat._load_session(mid))
    assert context.tactics["tier"] == "TRICKY"
    assert any(c.source_definition_id.endswith("battlefield_beheading_line")
               for c in context.legal_candidates), "the talent was not offered to its Tricky owner"
    assert combat.local_step(mid)["status"] == "COMMITTED"
