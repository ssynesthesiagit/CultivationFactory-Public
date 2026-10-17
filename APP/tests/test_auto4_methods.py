"""Public test documentation omitted."""
import pytest

from combat import typed_reactions as reactions
from tests import test_riders_c4 as C4
from tests.h1_support import ROOT  # noqa: F401  (documents where the authority under test is read from)

FOCUS = "resource:core.martial_focus"
CINDER, CHAIN = "ASH_BASE_CINDER_BRAND", "TAL_CHAINS_CHAIN_LASH_BASE"
SWAY, ACTIVE = "TAL_DRUNKEN_STYLE_SWAYING_GUARD", "SHIELD_BASE_ACTIVE_DEFENSE"
RETIRED = (CHAIN, CINDER, "SWORD_BASE_SWORD_BEYOND_HAND", "SWORD_BASE_SWORD_IN_HAND", "TAL_SPACE_SPATIAL_EDGE",
           "TAL_YIN_MARKING_A_CREATURE")
# printed lines the table cannot resolve, so they stay on the button
WATER_LASH_LEFT = "Replace one attack when you take the Attack action, or use an action if you do not have attacks to replace."


# ------------------------------------------------------------------ 1. the retired rider lines
@pytest.mark.parametrize("mid", RETIRED)
def test_retired_rider_lines_leave_the_built_record_fully_typed(mid):
    """The authority row is FULL: every printed line of these headings is resolved by the typing."""
    mechanic = C4.mech(mid)
    assert mechanic["riders"] == [], f"{mid} still records GM rider lines"
    assert mechanic["coverage"] == "FULL"
    assert mechanic["effects"] or mechanic.get("options") or mechanic.get("split_into")


def _no_rider_button(mid, prefix):
    """The compiled buttons for ``prefix``, with an assertion that they carry no GM rider line."""
    engine = C4.fight(C4.bundle(mid), foe=C4.bundle("SWORD_BASE_SWORD_BEYOND_HAND", actor_id=C4.FOE, cl=5))
    actions = [engine.action_catalog[a] for a in engine.state.actors[C4.ME].action_ids
               if engine.action_catalog[a].display_name.startswith(prefix)]
    assert actions, f"{mid} compiled no {prefix} action"
    return actions


def test_cinder_brand_no_longer_shows_a_gm_rider_and_still_brands_its_target():
    """Cinder Brand: "Hit: ... apply Ashen Brand" and "Once per turn when Cinder Brand hits, choose one: ..." are the
    record's own mark and four typed options; the button must stop claiming the GM has work to do, and the brand and the
    chosen rider must still land on a hit."""
    actions = _no_rider_button(CINDER, "Cinder Brand")
    assert len(actions) == 4, [a.display_name for a in actions]
    assert all(not (a.parameters["typed"].get("riders") or []) for a in actions)

    engine = C4.fight(C4.bundle(CINDER), foe=C4.bundle("SWORD_BASE_SWORD_BEYOND_HAND", actor_id=C4.FOE, cl=5))
    foe = engine.state.actors[C4.FOE]
    from tests.test_riders_c15 import force_d20
    force_d20(engine, 20, actor_id=C4.ME, reason="ATTACK")
    events = C4.use(engine, "Cinder Brand: Reduce Healing", target=C4.FOE)
    assert any("ashen" in c.condition_id.lower() for c in foe.conditions.values()), "Ashen Brand was not applied"
    assert C4.payloads(events, "DAMAGE_COMMITTED")
    assert any(m.target_field == "healing_reduction" and m.value == f"minus:{engine.state.actors[C4.ME].proficiency_bonus}"
               for m in foe.modifiers.values()), "Reduce Healing rider did not land"


def test_chain_lash_no_longer_shows_a_gm_rider_and_still_pulls_its_target():
    """Chain Lash: the printed "Once per turn when Chain Lash hits, choose one minor link effect" is this record's five
    typed options, and the Realm damage table is the typed damage row."""
    actions = _no_rider_button(CHAIN, "Chain Lash")
    assert len(actions) == 5, [a.display_name for a in actions]
    assert all(not (a.parameters["typed"].get("riders") or []) for a in actions)
    assert all(a.parameters["typed"]["effects"][0]["attack_kind"] == "cultivation_ranged" for a in actions)

    engine = C4.fight(C4.bundle(CHAIN), foe=C4.bundle("SWORD_BASE_SWORD_BEYOND_HAND", actor_id=C4.FOE, cl=5))
    foe = engine.state.actors[C4.FOE]
    before = (foe.position.x, foe.position.y)
    C4.use(engine, "Chain Lash: Pull 5 Feet", target=C4.FOE)
    assert (foe.position.x, foe.position.y) != before or not foe.active  # pulled toward the caster, or it died first


def test_water_lash_keeps_only_the_line_the_table_cannot_resolve():
    """Water Lash: "Make a ranged Cultivation Attack", the 60-foot range, the 0 CP cost, the CL damage table and the
    "already Soaked -> 5 feet, no Opportunity Attacks" rider are the record's own typing. The printed "Replace one
    attack when you take the Attack action" is NOT typed (activation economy is a plain action), so that one line stays
    on the button as an honest GM note."""
    assert C4.mech("WATER_BASE_WATER_LASH")["riders"] == [WATER_LASH_LEFT]
    actions = _no_rider_button("WATER_BASE_WATER_LASH", "Water Lash")
    riders = [line for action in actions for line in (action.parameters["typed"].get("riders") or [])]
    assert riders == [WATER_LASH_LEFT], riders
    assert all(action.parameters["typed"]["effects"][0]["attack_kind"] == "cultivation_ranged" for action in actions)
    damage = actions[0].parameters["typed"]["effects"][0]["on_hit"][0]
    assert [step[:3] for step in damage["dice_by_cl"]] == [[1, 4, 1], [5, 10, 2], [11, 16, 3], [17, 20, 4]]


def test_puppet_strike_keeps_only_the_line_the_table_cannot_resolve():
    """Reviewed auto/puppetry resolves the vessel origin; no obsolete GM reminder remains."""
    assert C4.mech("PUPPETRY_BASE_PUPPET_STRIKE")["riders"] == []
    assert C4.mech("PUPPETRY_BASE_PUPPET_STRIKE")["coverage"] == "FULL"
    actions = _no_rider_button("PUPPETRY_BASE_PUPPET_STRIKE", "Puppet Strike")
    riders = {line for action in actions for line in (action.parameters["typed"].get("riders") or [])}
    assert riders == set(), riders
    vessel_action = next(a for a in actions if a.parameters.get("vessel_strike"))
    assert vessel_action.parameters.get("vessel_native_origin")
    hit = vessel_action.parameters["typed"]["effects"][0]["template"][0]["on_hit"]
    assert any(step.get("type") == "mark" and step.get("mark") == "Tension Mark" for step in hit)


def test_sword_beyond_hand_and_spatial_edge_carry_no_gm_rider_line():
    """Sword Beyond Hand / Spatial Edge: the printed attack, damage table and damage-type choice are the typed rows."""
    engine = C4.fight(C4.bundle("SWORD_BASE_SWORD_BEYOND_HAND"), foe=C4.bundle(CINDER, actor_id=C4.FOE, cl=5))
    action = C4.action_id(engine, C4.ME, "Sword Beyond Hand")
    assert not (engine.action_catalog[action].parameters["typed"].get("riders") or [])
    engine = C4.fight(C4.bundle("TAL_SPACE_SPATIAL_EDGE"), foe=C4.bundle(CINDER, actor_id=C4.FOE, cl=5))
    action = C4.action_id(engine, C4.ME, "Spatial Edge")
    assert not (engine.action_catalog[action].parameters["typed"].get("riders") or [])


def test_yin_marking_a_creature_is_typed_by_its_three_split_abilities():
    """Yin's heading prints three ways to place a Waning Mark and splits into three mechanics; the parent compiled
    nothing itself, so its copy of the three sentences only mislabelled the heading."""
    parent = C4.mech("TAL_YIN_MARKING_A_CREATURE")
    assert parent["coverage"] == "FULL" and parent["riders"] == []
    children = parent["split_into"]
    assert len(children) == 3
    assert all(C4.mech(child)["effects"] for child in children)


# ------------------------------------------------------------------ 2. Martial Focus instead of the Reaction
def _guard(*mids):
    """A character owning ``mids``, its Reaction already spent, holding 1 Martial Focus."""
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.armor.shield", "quantity": 1}]}} if ACTIVE in mids else None
    engine = C4.fight(C4.bundle(*mids, kit=kit), foe=C4.bundle("SWORD_BASE_SWORD_BEYOND_HAND", actor_id=C4.FOE, cl=5))
    owner = engine.state.actors[C4.ME]
    owner.reaction_available = False
    owner.resources[FOCUS] = 1
    return engine, owner


def _row(feature_id=SWAY):
    return {"feature_id": feature_id, "name": "Swaying Guard"}


def test_martial_focus_pays_for_swaying_guard_when_the_reaction_is_already_spent():
    """"You may expend Martial Focus to use Swaying Guard without spending your Reaction." Before this the table could
    only spend the Reaction, so the printed option was a GM ruling and the button never appeared."""
    engine, owner = _guard(SWAY)
    rows = reactions._rows(engine, owner.entity_id, "reaction_economy")
    assert any(row.get("grant") == "focus_instead" and (row.get("pay") or {}).get("resource_id") == FOCUS for row in rows)
    assert reactions.reaction_waived(engine, owner, _row()) is True  # preview spends nothing
    assert owner.resources[FOCUS] == 1
    reactions._open(engine, _row(), owner, (), "TEST_FOCUS_INSTEAD")
    reactions.spend_reaction(engine, owner, _row())
    assert owner.resources[FOCUS] == 0, "the printed Martial Focus cost was not paid"
    assert not owner.reaction_available  # it was already spent, and stays spent


def test_swaying_guard_honours_its_printed_limit_on_the_paid_use():
    """Swaying Guard's printed sentence adds "Once you do so, you cannot use Swaying Guard again until the start of
    your next turn", so all further uses are refused until that turn actually starts."""
    engine, owner = _guard(SWAY, SWAY)
    owner.resources[FOCUS] = 2
    assert reactions.reaction_waived(engine, owner, _row()) is True
    reactions._open(engine, _row(), owner, (), "TEST_FOCUS_INSTEAD")
    reactions.spend_reaction(engine, owner, _row())
    assert owner.resources[FOCUS] == 1
    assert reactions.reaction_waived(engine, owner, _row()) is False, "the printed once-per-next-turn limit was ignored"

    engine.end_turn()
    while engine.state.current_actor_id != owner.entity_id:
        engine.end_turn()
    owner.reaction_available = False
    owner.resources[FOCUS] = 1
    assert reactions.reaction_waived(engine, owner, _row()) is True


def test_the_limit_is_read_from_the_data_not_from_the_ability():
    """Shield's Active Defense prints the same Focus sentence with NO extra limit, so one paid use per Focus is correct
    there; the same grant with no pay.once_per_round is not throttled."""
    engine, owner = _guard(ACTIVE)
    owner.resources[FOCUS] = 2
    row = {"feature_id": ACTIVE, "name": "Active Defense"}
    grants = [g for g in reactions._rows(engine, owner.entity_id, "reaction_economy") if g.get("grant") == "focus_instead"]
    assert grants and not (grants[0].get("pay") or {}).get("once_per_round")
    for _ in range(2):
        assert reactions.reaction_waived(engine, owner, row) is True
        reactions._open(engine, row, owner, (), "TEST_FOCUS_INSTEAD")
        reactions.spend_reaction(engine, owner, row)
    assert owner.resources[FOCUS] == 0


def test_ai_prefers_the_ordinary_reaction_while_it_is_available():
    """AI defaults to its Reaction; the player's selectable alternative is covered at table level."""
    engine = C4.fight(C4.bundle(SWAY), foe=C4.bundle("SWORD_BASE_SWORD_BEYOND_HAND", actor_id=C4.FOE, cl=5))
    owner = engine.state.actors[C4.ME]
    owner.resources[FOCUS] = 1
    assert reactions.reaction_waived(engine, owner, _row()) is False
    reactions._open(engine, _row(), owner, (), "TEST_FOCUS_INSTEAD")
    reactions.spend_reaction(engine, owner, _row())
    assert owner.resources[FOCUS] == 1 and not owner.reaction_available


def test_without_martial_focus_the_reaction_stays_unavailable():
    engine, owner = _guard(SWAY)
    owner.resources[FOCUS] = 0
    assert reactions.reaction_waived(engine, owner, _row()) is False


def test_the_grant_answers_only_its_own_printed_reaction():
    engine, owner = _guard(SWAY)
    other = {"feature_id": "TAL_DRUNKEN_STYLE_LAUGHING_AT_CERTAIN_DEATH", "name": "Laughing at Certain Death"}
    assert reactions.reaction_waived(engine, owner, _row()) is True
    assert reactions.reaction_waived(engine, owner, other) is False


def test_active_defense_is_covered_by_the_same_grant():
    """Shield's Active Defense prints the same sentence; one grant, two abilities, no code per ability."""
    engine, owner = _guard(ACTIVE)
    row = {"feature_id": ACTIVE, "name": "Active Defense"}
    assert reactions.reaction_waived(engine, owner, row) is True
    reactions._open(engine, row, owner, (), "TEST_FOCUS_INSTEAD")
    reactions.spend_reaction(engine, owner, row)
    assert owner.resources[FOCUS] == 0
