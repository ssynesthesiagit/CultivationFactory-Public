"""Lighting S4: AI darkness tactics (docs/specs/LIGHTING_SPEC.md §9, §10 S4).

The AI reads light only through what its creature perceives. Weights default to 0, so no
existing fight changes unless a Dao carries a light lean.
"""
import pytest

from factory_authoring.sphere_dao import _DARKNESS_AFFINITY, _light_levers, character_dao, controller_policy
from combat.ai_observation import KnownSquare
from combat.lighting import seen_level
from tests.lighting_darkness_support import darkness_rules  # noqa: F401  (fixture)
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, map_document
from tests.worker2_support import candidate, reload, settle


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


def _context_for(combat, mid, document):
    """The owner's AI decision context, with the policy exactly as controller_policy emitted and validated it."""
    from combat.gate4_context import build_decision_context
    from combat.gate4_models import LocalControllerPolicy
    session = combat._load_session(mid)
    return session, build_decision_context(session.engine, LocalControllerPolicy.model_validate(document), for_ai=True)


def test_light_levers_survive_policy_validation_into_the_turn_planner(night):
    """B2: sphere_dao's merge of _light_levers reaches the validated policy and the TurnPlan, with no hand injection."""
    from combat.ai_tactics import TurnPlan
    dark_dao = character_dao({"tianxia.sphere.dark": 10})
    document = controller_policy(dark_dao, OWNER)
    weights = document["tactic_weights"]
    default = dark_dao["trigram_pressure"]["natural"][0]["trigram"]
    assert weights["darkness"] >= 1 and weights["unseen_ground"] == weights["darkness"] // 2
    assert {k: weights[k] for k in ("darkness", "unseen_ground")} == {
        k: v for k, v in _light_levers(dark_dao, default).items() if k in ("darkness", "unseen_ground")}
    combat, mid = night
    session, context = _context_for(combat, mid, document)
    assert context.policy.tactic_weights["darkness"] == weights["darkness"]
    assert context.policy.tactic_weights["unseen_ground"] == weights["unseen_ground"]
    foe = session.engine.state.actors[FOE]
    # The foe stands in Dark that the owner perceives (Blindsight, E8): the policy's darkness weight pays the position term.
    assert TurnPlan(context).light_position_value(foe.position) == weights["darkness"]
    # No-lean Dao: controller_policy adds no light keys at all.
    plain = controller_policy(character_dao({"tianxia.sphere.life": 5, "tianxia.sphere.guardian": 3}), OWNER)
    assert not {"darkness", "unseen_ground", "brightness"} & set(plain.get("tactic_weights", {}))


def test_bright_ground_penalty_counts_only_foes_this_creature_perceives(night):
    """B3: a hidden foe within 60 ft does not move the bright-ground position value; a perceived one does."""
    from combat.ai_tactics import TurnPlan, _xyz
    combat, mid = night
    _, context = _context(combat, mid, darkness=4)
    context.policy.tactic_weights["brightness"] = 2
    plan = TurnPlan(context)
    foe = next(a for a in plan.foes if a.entity_id == FOE)
    near = (foe.position.x, foe.position.y, foe.position.z)
    far = (foe.position.x + 13, foe.position.y, foe.position.z)   # 65 ft: beyond the 60 ft line-of-sight reading
    plan.squares[near] = KnownSquare(position=near, known=True, light=2, cover=0, difficult=False, objective=False, hazard=False)
    plan.squares[far] = KnownSquare(position=far, known=True, light=2, cover=0, difficult=False, objective=False, hazard=False)
    assert _xyz(near) == near
    plan.perceived_ids = set()
    assert plan.light_position_value(near) == 2          # hidden foe: no penalty
    plan.perceived_ids = {FOE}
    assert plan.light_position_value(near) == 2 - 2      # perceived foe in reach: -(darkness // 2)
    assert plan.light_position_value(far) == 2           # perceived foe beyond 60 ft: no penalty


def test_dark_position_term_needs_the_square_inside_the_owners_sense_reach(night):
    """B4: a Dark square the creature does not perceive earns no darkness term, only the unseen_ground cost."""
    from combat.ai_tactics import TurnPlan
    combat, mid = night
    _, context = _context(combat, mid, darkness=3)
    context.policy.tactic_weights["unseen_ground"] = 1
    plan = TurnPlan(context)
    plan.squares[(1, 2, 0)] = KnownSquare(position=(1, 2, 0), known=False, light=0, cover=0, difficult=False,
                                          objective=False, hazard=False)
    assert plan.light_position_value((1, 2, 0)) == -4


def _square(light, known=True):
    return KnownSquare(position=(1, 2, 0), known=known, cover=0, difficult=False, objective=False, hazard=False,
                       light=light)


def test_light_position_value_pays_darkness_on_dark_ground_and_costs_unseen_ground(night):
    """B2: a Dark square pays the darkness weight; an unseen square costs unseen_ground times four; Bright pays 0."""
    from combat.ai_tactics import TurnPlan
    combat, mid = night
    session, context = _context(combat, mid, darkness=3)
    context.policy.tactic_weights["unseen_ground"] = 1
    plan = TurnPlan(context)
    plan.squares[(1, 2, 0)] = _square(0)
    assert plan.light_position_value((1, 2, 0)) == 3
    plan.squares[(1, 2, 0)] = _square(2)
    assert plan.light_position_value((1, 2, 0)) == 0
    plan.squares[(1, 2, 0)] = _square(None, known=False)
    assert plan.light_position_value((1, 2, 0)) == -4


def test_creates_darkness_is_true_only_for_a_darkness_row(night):
    """B2: the darkness-maker classification answers from the hook, both ways."""
    from combat.ai_tactics import _creates_darkness
    combat, mid = night
    session = combat._load_session(mid)
    actor = session.engine.state.actors[OWNER]
    maker = type("A", (), {"parameters": {"effects": [{"on_hit": [{"row": "DARK_BASE_DARKNESS"}]}]}})()
    other = type("A", (), {"parameters": {"effects": [{"row": "TAL_DARK_OBFUSCATION"}]}})()
    assert _creates_darkness(session.engine, actor, maker) is True
    assert _creates_darkness(session.engine, actor, other) is False


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
    # senses=[]: the fixture's Darkvision would lift every Dark square to Dim, and these tests read Dark squares.
    # Blindsight is the sense that lets the owner perceive the foe in Dark without raising its level (E8/E11), so the
    # foe stays in the owner's known roster and square light is 0. Without it the foe is not perceived at all.
    combat, table, mid = fight(tmp_path, map_document(ambient=ambient_light("night")), senses=[
        {"sense": "blindsight", "range_ft": 30}],
        positions={OWNER: {"x": 6, "y": 6}, FOE: {"x": 9, "y": 6}})
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


def test_ai_light_policy_answers_darkness_makers_through_the_plugin(night):
    """B3: the darkness-maker answer comes from the light plug-in's hook, not a core id set."""
    from combat import ext
    from combat.ext import lighting  # noqa: F401  (registers the hook)
    action = type("A", (), {"parameters": {"effects": [{"row": "TAL_DARK_PURE_DARKNESS"}]}})()
    plain = type("A", (), {"parameters": {"effects": [{"row": "FIRE_BASE_CONFLAGRATION"}]}})()
    combat, mid = night
    session = combat._load_session(mid)
    actor = session.engine.state.actors[OWNER]
    assert ext.query("ai_light_policy", session.engine, actor, action) == [{"creates_darkness": True}]
    assert ext.query("ai_light_policy", session.engine, actor, plain) == []


@pytest.mark.usefixtures("darkness_rules")
def test_darkvision_inside_named_darkness_is_not_penalised_for_perception(tmp_path):
    """B4: a Darkvision creature standing in named Darkness sees through it, so its Perception check is not made from
    Dim Light. The level stays Dim (E10); only the Dim sight-check penalty is answered by the printed clause."""
    from combat import lighting, senses, zones
    document = map_document(20, 14, ambient=ambient_light("night"))
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=[{"sense": "darkvision", "range_ft": 60}],
                               talents=["DARK_BASE_DARKNESS"],
                               positions={OWNER: {"x": 6, "y": 6}, ALLY: {"x": 9, "y": 6}, FOE: {"x": 2, "y": 2}})
    settle(table, mid, candidate(combat, mid, "Darkness", at=(8, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert zones.pierced_cell(engine, ally, senses.cell_probe(ally.position)) is True
    assert lighting.seen_level(engine, ally, ally.position) == lighting.DIM      # E10: Darkvision still raises to Dim
    assert lighting.perception_mode(engine, ally) == "NORMAL"                    # B4: no Dim penalty on sight Perception


@pytest.mark.usefixtures("darkness_rules")
def test_darkvision_inside_named_darkness_keeps_attack_advantage_not_disadvantage(tmp_path):
    """B4 attack path: the Darkvision creature inside the named Darkness does not get Disadvantage from Dim light."""
    from combat import attack_modes
    document = map_document(20, 14, ambient=ambient_light("night"))
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=[{"sense": "darkvision", "range_ft": 60}],
                               talents=["DARK_BASE_DARKNESS"],
                               positions={OWNER: {"x": 6, "y": 6}, ALLY: {"x": 9, "y": 6}, FOE: {"x": 2, "y": 2}})
    settle(table, mid, candidate(combat, mid, "Darkness", at=(8, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    ally, foe = engine.state.actors[ALLY], engine.state.actors[FOE]
    assert "DISADVANTAGE" not in attack_modes.presentation_modes(engine, ally, foe)


def test_frame_is_deterministic_for_the_same_saved_fight(night):
    combat, mid = night
    _, first = _context(combat, mid)
    _, second = _context(combat, mid)
    assert first.own_knowledge.revision == second.own_knowledge.revision
    assert first.own_knowledge.model_dump() == second.own_knowledge.model_dump()
