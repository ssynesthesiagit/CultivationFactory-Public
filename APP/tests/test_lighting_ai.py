"""Lighting S4: AI darkness tactics (docs/specs/LIGHTING_SPEC.md §9, §10 S4).

The AI reads light only through what its creature perceives. Weights default to 0, so no
existing fight changes unless a Dao carries a light lean.
"""
import pytest

from factory_authoring.sphere_dao import _DARKNESS_AFFINITY, _light_levers, controller_policy
from combat.ai_observation import KnownSquare
from combat.lighting import seen_level
from tests.lighting_support import FOE, OWNER, ambient_light, fight, map_document


def _dao(*spheres, default="qian"):
    layers = [{"sphere_id": sid, "profile": {"name": sid}} for sid in spheres]
    return {"layers": layers, "primary_sphere": spheres[0] if spheres else None}


def test_dark_dao_leans_dark_and_fire_dao_leans_bright():
    dark = _light_levers(_dao("tianxia.sphere.dark"), "qian")
    fire = _light_levers(_dao("tianxia.sphere.fire"), "qian")
    # qian contributes -1 to the darkness lean only: Dark 6 - 1 = 5. Fire's -2 is its bright lean.
    assert dark == {"darkness": 5, "unseen_ground": 2}
    assert fire == {"brightness": 2}


def test_a_dao_without_a_light_lean_adds_no_keys():
    assert _light_levers(_dao("tianxia.sphere.life"), "qian") == {}


def test_affinity_keys_are_sphere_ids_not_display_names():
    assert all(key.startswith("tianxia.sphere.") for key in _DARKNESS_AFFINITY)


def test_unset_light_is_omitted_from_the_frame_dump():
    square = KnownSquare(position=(1, 2, 0), known=True, cover=0, difficult=False, objective=False, hazard=False)
    assert "light" not in square.model_dump()


def test_set_light_is_kept_and_described():
    square = KnownSquare(position=(1, 2, 0), known=True, cover=0, difficult=False, objective=False, hazard=False, light=0)
    assert square.model_dump()["light"] == 0
    assert "darkness" in square.description()


def _context(combat, mid, *, darkness=None):
    """The owner's AI decision context on a lit fight, optionally with a darkness weight on its policy."""
    from combat.gate4_context import build_decision_context
    session = combat._load_session(mid)
    policy, _ = combat.policies.for_actor(OWNER)
    if darkness is not None:
        policy = policy.model_copy(update={"tactic_weights": {**policy.tactic_weights, "darkness": darkness}})
    return session, build_decision_context(session.engine, policy, for_ai=True)


@pytest.fixture
def night(tmp_path, monkeypatch):
    """A night fight on a map with no lights: every square is Dark, and the foe stands in it."""
    monkeypatch.setenv("CF_COMBAT_AI_SLICES_1_2", "1")
    combat, table, mid = fight(tmp_path, map_document(ambient=ambient_light("night")))
    return combat, mid


def test_known_foe_square_reaches_the_owners_frame_with_its_light(night):
    combat, mid = night
    session, context = _context(combat, mid)
    foe = session.engine.state.actors[FOE]
    frame = context.own_knowledge
    square = next(s for s in frame.squares if tuple(s.position) == tuple(foe.position))
    assert square.known is True
    assert square.light == seen_level(session.engine, session.engine.state.actors[OWNER], foe.position) == 0


def test_every_square_carries_light_only_when_it_is_known(night):
    combat, mid = night
    _, context = _context(combat, mid)
    assert all((s.light is None) == (not s.known) for s in context.own_knowledge.squares)


def test_darkness_attack_term_scales_with_policy_weight(night):
    from combat.ai_tactics import TurnPlan
    combat, mid = night
    _, context = _context(combat, mid, darkness=3)
    plan = TurnPlan(context)
    foe = next(a for a in plan.foes if a.entity_id == FOE)
    # A damaging attack on a foe standing in Dark earns the darkness weight; no other term applies here.
    assert plan.darkness_value({"damage": 1}, foe) == 3


def test_frame_is_deterministic_for_the_same_saved_fight(night):
    combat, mid = night
    _, first = _context(combat, mid)
    _, second = _context(combat, mid)
    assert first.own_knowledge.revision == second.own_knowledge.revision
    assert first.own_knowledge.model_dump() == second.own_knowledge.model_dump()
