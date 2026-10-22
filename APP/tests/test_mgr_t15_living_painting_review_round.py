"""Living Painting review round: Serpent grip scope and AI Crane Passage admission."""
from types import SimpleNamespace

from combat.ext import painting_forms
from combat.gate4_context import build_decision_context
from tests.test_mgr_t14_sol_subpath_living_painting import FEATURE, create
from tests.test_mgr_t15_living_painting_passage import crane_turn
from tests.worker2_support import OWNER, ALLY, FOE, fixture, settle, turn

OTHER = "actor:factory.worker2-foe1"


def _action(engine, form, name):
    rows = [a for key, a in engine.action_catalog.items()
            if form in key and getattr(a, "display_name", None) == name]
    assert len(rows) == 1, name
    return rows[0]


def test_serpent_grip_blocks_strike_on_other_creature_but_keeps_help(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=6, owner_features=[FEATURE], named=True, extra_foes=1,
        seed="LIVING-PAINTING-GRIP-HELP", positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 5},
        FOE: {"x": 4, "y": 6}},
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    aid = create(combat, table, mid, "serpent", "FORCE")
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    serpent = engine.state.actors[aid]
    engine._apply_condition(engine.state.actors[FOE], painting_forms.GRAPPLED, "summon.living_painting_serpent.grapple",
                            aid, expires_on=None, data={"escape_dc": 10, "reach_ft": 5, "escape_save": "STR"})
    assert painting_forms.grappling(engine, serpent)
    help_action = _action(engine, "serpent", "Help")
    strike = _action(engine, "serpent", "Painted Strike")
    other = SimpleNamespace(target_ids=(OTHER,), destination=None)
    held = SimpleNamespace(target_ids=(FOE,), destination=None)
    # Help is not a Painted Strike, so the grip leaves it offered against another enemy.
    assert painting_forms.serpent_candidates(engine, serpent, other, help_action) is None
    # The grip still forbids Painted Strike against anyone but the grappled creature.
    assert painting_forms.serpent_candidates(engine, serpent, other, strike) is False
    assert painting_forms.serpent_candidates(engine, serpent, held, strike) is None


def test_automatic_crane_decision_context_offers_painted_passage(tmp_path):
    combat, table, mid, aid = crane_turn(tmp_path)
    engine = combat._load_session(mid).engine
    policy, _ = combat.policies.for_actor(aid)
    context = build_decision_context(engine, policy, for_ai=True)
    offered = [c for c in context.legal_candidates if c.destination is not None
               and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Painted Passage"]
    assert offered
