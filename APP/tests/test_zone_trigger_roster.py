"""Zone trigger recipient rosters: reviewed authority data vs compiler policy.

A compiled zone trigger always carries a ``who`` policy. When reviewed authority
states a roster, the compiler also keeps it in the separate ``roster`` key. The
delayed-area recipient seam must honour only that reviewed roster: a compiler's
enemies-only fallback is eligibility policy, not a declaration that a printed
"each creature" packet is hostile-only. The tests build a synthetic compiled
zone (through ``_zone_spec``) so both paths are exercised at the engine/table
level, including a real table commit and reload.
"""

import copy
import json

import pytest

from combat import area_recipient_rules, typed_executor, zones
from combat.factory_compiler import _zone_spec
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_auto_lane1 import ALLY, FOE, ME, _ally_bundle, _bundle, _engine
from tests.test_tabletop_hunt6 import ALLY as TABLE_ALLY, LEFT as TABLE_OWNER, table_fight

SOURCE_PRINTED = "system:test.zone_printed_each_creature"
SOURCE_REVIEWED = "system:test.zone_reviewed_any"
SAVE = {"type": "save", "ability": "con", "applies_to": "target",
        "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target"}], "on_success": []}


def _compiled(owner_id, source, *, reviewed_roster=None):
    """One compiled zone whose action prints "each creature" in its area."""
    trigger = {"on": ["enter"], "effects": [copy.deepcopy(SAVE)]}
    if reviewed_roster:
        trigger["who"] = reviewed_roster  # authority data declares a roster
    typed = {"source": source, "sphere": "test",
             "area": {"shape": "emanation", "size_ft": 10, "explicit_harmful_recipients": "every_creature"},
             "duration": {"kind": "minutes", "amount": 1},
             "numbers": {"pb": 4, "cl": 10, "save_dc": 16},
             "effects": [{"type": "zone", "duration": {"kind": "minutes", "amount": 1}, "triggers": [trigger]}]}
    action = ActionDefinition(source_definition_id=source, display_name="Synthetic Field", owner_id=owner_id,
                              economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                              parameters={"typed": typed})
    mechanic = {"name": "Synthetic Field", "mechanic_id": source,
                "description": ["A creature that enters the area or starts its turn there makes a Constitution saving throw."],
                "effects": typed["effects"]}
    return action, mechanic, typed["numbers"]


def _place(engine, owner_id, source, zone_id, *, reviewed_roster=None):
    """Compile the synthetic zone and put it on the engine's table."""
    action, mechanic, numbers = _compiled(owner_id, source, reviewed_roster=reviewed_roster)
    spec = _zone_spec(action, mechanic, {})
    owner = engine.state.actors[owner_id]
    ctx = typed_executor.Context(engine, owner, action, None, {"numbers": numbers}, [owner], owner, {})
    zone = zones.prospective_zone(ctx, spec, Position(x=owner.position.x, y=owner.position.y), zone_id=zone_id)
    engine.action_catalog[source] = action
    engine.state.zones[zone.zone_id] = zone
    return zone


def _saves(events, source):
    return [event for event in events if event.event_type == "SAVE_ROLLED" and event.source_definition_id == source]


def test_a_compilers_who_policy_is_not_a_reviewed_roster():
    """Printed "each creature", no reviewed roster: the fallback `who` must not narrow the packet to enemies."""
    engine = _engine(_bundle("TAL_ALCHEMY_CALMING_HEART_PILL"), allies=(_ally_bundle(),))
    zone = _place(engine, ME, SOURCE_PRINTED, "zone:test:printed")
    (trigger,) = zone.trigger_profile["triggers"]
    assert trigger["who"] == "hostile"  # the compiler's fallback policy for an enemy trigger
    assert "roster" not in trigger  # ... not a reviewed roster
    ally = engine.state.actors[ALLY]
    assert zones._applies(engine, zone, ally, trigger)
    before = len(engine.events)
    zones.fire_trigger(engine, zone, ally, "enter")
    assert _saves(engine.events[before:], SOURCE_PRINTED)


@pytest.mark.parametrize("roster,ruling,ally_takes_it", [
    ("any", "enemies", False),      # an owner ruling narrows a roster-declared zone
    ("hostile", "everyone", True),  # ... or widens it
])
def test_an_owner_ruling_outranks_a_reviewed_roster(tmp_path, monkeypatch, roster, ruling, ally_takes_it):
    """Owner rulings are applied before the reviewed roster, for eligibility and the packet."""
    path = tmp_path / "owner-area-rulings.json"
    path.write_text(json.dumps({"abilities": {SOURCE_REVIEWED: {
        "recipients": ruling, "reason": "Owner test ruling"}}}))
    monkeypatch.setattr(area_recipient_rules, "OVERRIDES", path)
    engine = _engine(_bundle("TAL_ALCHEMY_CALMING_HEART_PILL"), allies=(_ally_bundle(),))
    zone = _place(engine, ME, SOURCE_REVIEWED, f"zone:test:ruling-{roster}-{ruling}", reviewed_roster=roster)
    (trigger,) = zone.trigger_profile["triggers"]
    assert trigger["roster"] == roster
    ally = engine.state.actors[ALLY]
    assert zones._applies(engine, zone, ally, trigger) == ally_takes_it
    before = len(engine.events)
    zones.fire_trigger(engine, zone, ally, "enter")
    assert bool(_saves(engine.events[before:], SOURCE_REVIEWED)) is ally_takes_it
    from combat.area_recipients import scoped_area
    packet = scoped_area({"size_ft": 10, "trigger_roster": roster}, [copy.deepcopy(SAVE)],
                         typed={"source": SOURCE_REVIEWED})
    assert packet["harmful_recipient_override"] == ("all" if ally_takes_it else "hostile")


DAMAGING_SAVE = {"type": "save", "ability": "con", "applies_to": "target",
                 "on_fail": [{"type": "damage", "flat": 5, "damage_types": ["force"], "applies_to": "target"}],
                 "on_success": []}


def _roster_zone(owner_id, source, *, triggers=None, move_through=None):
    """A compiled zone plus the action carrying its spec, for area-risk previews.

    The action's area is deliberately unscoped, like reviewed authority data: the
    compiler seals no reviewed roster there, so the delayed-area seam's default is
    enemies-only and only a trigger's own reviewed ``roster`` can widen a packet.
    """
    effect = {"type": "zone", "duration": {"kind": "minutes", "amount": 1}}
    if triggers is not None:
        effect["triggers"] = copy.deepcopy(triggers)
    if move_through is not None:
        effect["move_through"] = copy.deepcopy(move_through)
    effects = [effect]
    typed = {"source": source, "sphere": "test", "area": {"shape": "emanation", "size_ft": 10},
             "duration": {"kind": "minutes", "amount": 1},
             "numbers": {"pb": 4, "cl": 10, "save_dc": 16}, "effects": effects}
    action = ActionDefinition(source_definition_id=source, display_name="Synthetic Field", owner_id=owner_id,
                              economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                              parameters={"typed": typed})
    mechanic = {"name": "Synthetic Field", "mechanic_id": source,
                "description": ["A lasting field."], "effects": effects}
    spec = _zone_spec(action, mechanic, {})
    assert spec is not None
    typed["zone_spec"] = spec
    return action.model_copy(update={"parameters": {"typed": typed}}), spec


def _place_roster_zone(engine, owner_id, source, zone_id, action, spec):
    owner = engine.state.actors[owner_id]
    ctx = typed_executor.Context(engine, owner, action, None, {"numbers": action.parameters["typed"]["numbers"]},
                                 [owner], owner, {})
    zone = zones.prospective_zone(ctx, spec, Position(x=owner.position.x, y=owner.position.y), zone_id=zone_id)
    engine.action_catalog[source] = action
    engine.state.zones[zone.zone_id] = zone
    return zone


def test_a_filtered_trigger_does_not_lend_its_roster_to_another_triggers_packet():
    """Placement risk pairs each surviving trigger with its own packet and roster.

    The zone's first trigger is the compiler's derived enemies-only policy (no
    reviewed roster); the second is reviewed "any". An ally standing inside is
    filtered out of the first trigger, so the preview must read the second
    trigger's own roster instead of pairing the ally's one remaining packet with
    the filtered trigger's roster (which would compute the reviewed "any" harm as
    enemies-only).
    """
    from combat.area_safety import _preview

    engine = _engine(_bundle("TAL_ALCHEMY_CALMING_HEART_PILL"), allies=(_ally_bundle(),))
    source = "system:test.zone_mixed_rosters"
    action, spec = _roster_zone(ME, source, triggers=[
        {"on": ["enter"], "effects": [copy.deepcopy(DAMAGING_SAVE)]},              # derived who: hostile, no roster
        {"on": ["enter"], "who": "any", "effects": [copy.deepcopy(DAMAGING_SAVE)]},  # reviewed roster: any
    ])
    zone = _place_roster_zone(engine, ME, source, "zone:test:mixed", action, spec)
    ally = engine.state.actors[ALLY]
    assert [trigger.get("roster") for trigger in zone.trigger_profile["triggers"]] == [None, "any"]
    assert zones.prospective_effects(engine, zone, ally) == [(zone.trigger_profile["triggers"][1],
                                                              zone.trigger_profile["triggers"][1]["effects"])]

    _, metadata, label = _preview(engine, engine.state.actors[ME], action, engine.state.actors[ME].position)
    # The reviewed "any" trigger exposes the caster and the ally (5 damage each).
    assert metadata["allies_in_area"] == 2
    assert metadata["ally_expected_damage"] == 10
    assert label.startswith("Hits allies too:")

    # Execution delivers the same packet to the ally through the reviewed trigger.
    before = len(engine.events)
    zones.fire_trigger(engine, zone, ally, "enter")
    assert _saves(engine.events[before:], source)


HEALING = {"type": "healing", "flat": 3, "applies_to": "target"}


def test_a_hostile_roster_bounds_the_harm_but_not_a_sibling_benefit():
    """A mixed packet under a reviewed hostile roster harms enemies; its benefit reaches everyone inside.

    ``recipients`` is the roster a packet's non-harmful rows may reach
    (``typed_executor._area_recipient_matches``), while ``harmful_recipients`` is
    the harm. The no-ruling roster branch used to narrow both to "hostile",
    unlike the owner-ruling and unscoped mixed branches, so a healing/buff row in
    the same packet could not reach an ally inside the area.
    """
    from combat.area_recipients import harmful_area_subject_allowed, scoped_area
    from combat.typed_executor import _area_targets

    effects = [copy.deepcopy(DAMAGING_SAVE), copy.deepcopy(HEALING)]
    packet = scoped_area({"size_ft": 10, "trigger_roster": "hostile"}, effects, typed={"source": SOURCE_REVIEWED})
    assert packet["harmful_recipients"] == "hostile"
    assert packet["harmful_recipient_override"] == "hostile"
    assert packet["recipients"] == "all"  # the sibling benefit is not narrowed to enemies
    assert packet["include_self"] is True and packet["exclude_self"] is False

    engine = _engine(_bundle("TAL_ALCHEMY_CALMING_HEART_PILL"), allies=(_ally_bundle(),))
    me, ally, foe = (engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE])
    members = _area_targets(engine, me, me.position, packet, typed={"effects": effects})
    assert {actor.entity_id for actor in members} >= {ally.entity_id, foe.entity_id}
    # The harm stays enemies-only for the same packet.
    assert harmful_area_subject_allowed(me, ally, packet, DAMAGING_SAVE) is False
    assert harmful_area_subject_allowed(me, foe, packet, DAMAGING_SAVE) is True


def _compiled_mixed(owner_id, source):
    """A compiled zone with a printed "each creature" area, one harmful and one ally benefit trigger."""
    harm = {"on": ["enter"], "effects": [copy.deepcopy(SAVE)]}
    benefit = {"on": ["enter"], "who": "ally", "effects": [copy.deepcopy(HEALING)]}
    effects = [{"type": "zone", "duration": {"kind": "minutes", "amount": 1}, "triggers": [harm, benefit]}]
    typed = {"source": source, "sphere": "test",
             "area": {"shape": "emanation", "size_ft": 10, "explicit_harmful_recipients": "every_creature"},
             "duration": {"kind": "minutes", "amount": 1},
             "numbers": {"pb": 4, "cl": 10, "save_dc": 16}, "effects": effects}
    action = ActionDefinition(source_definition_id=source, display_name="Synthetic Field", owner_id=owner_id,
                              economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                              parameters={"typed": typed})
    mechanic = {"name": "Synthetic Field", "mechanic_id": source,
                "description": ["A creature that enters the area makes a Constitution saving throw."],
                "effects": copy.deepcopy(effects)}
    return action, mechanic


def _place_mixed(engine, owner_id, source, zone_id):
    action, mechanic = _compiled_mixed(owner_id, source)
    spec = _zone_spec(action, mechanic, {})
    owner = engine.state.actors[owner_id]
    ctx = typed_executor.Context(engine, owner, action, None, {"numbers": action.parameters["typed"]["numbers"]},
                                 [owner], owner, {})
    zone = zones.prospective_zone(ctx, spec, Position(x=owner.position.x, y=owner.position.y), zone_id=zone_id)
    engine.action_catalog[source] = action
    engine.state.zones[zone.zone_id] = zone
    return zone


def test_a_benefit_only_roster_is_not_widened_by_the_areas_printed_harm_scope():
    """A printed "each creature" harm scope is permission for the harm, not for a benefit.

    The area seals ``explicit_harmful_recipients`` "every_creature", which
    ``scoped_area`` turns into an "all" harm policy for any packet it is asked
    about. A healing trigger the reviewed data declared for allies used to be
    run through that seam just because it declared a roster, so the area's harm
    policy set the trigger's eligibility to "any" and an enemy became eligible
    for the ally-only benefit.
    """
    engine = _engine(_bundle("TAL_ALCHEMY_CALMING_HEART_PILL"), allies=(_ally_bundle(),))
    source = "system:test.zone_ally_benefit"
    zone = _place_mixed(engine, ME, source, "zone:test:ally-benefit")
    triggers = zone.trigger_profile["triggers"]
    benefit = next(trigger for trigger in triggers if trigger.get("roster") == "ally")
    harm = next(trigger for trigger in triggers if "roster" not in trigger)
    ally, foe = engine.state.actors[ALLY], engine.state.actors[FOE]

    # The ally-only benefit reaches the ally and not an enemy.
    assert zones._applies(engine, zone, ally, benefit)
    assert not zones._applies(engine, zone, foe, benefit)
    # The harmful trigger still reaches the enemy through the printed "each creature" area.
    assert zones._applies(engine, zone, foe, harm)

    # Placement risk groups the same way: the enemy's exposure is the harm only.
    assert benefit not in [trigger for trigger, _ in zones.prospective_effects(engine, zone, foe)]
    assert harm in [trigger for trigger, _ in zones.prospective_effects(engine, zone, foe)]
    # ... while the ally in the area is exposed to both.
    assert {id(trigger) for trigger, _ in zones.prospective_effects(engine, zone, ally)} == {id(benefit), id(harm)}


def test_a_move_through_only_zone_reaches_the_risk_preview_and_execution():
    """A move-through group is its own possible exposure, not a truncated extra.
    The zone has no enter/start trigger, only a reviewed any-roster move-through
    rule. The preview must pair that rule's packet with its own roster (an ally
    inside is exposed) and execution of the movement must deliver the same save.
    """
    from combat.area_safety import _preview

    engine = _engine(_bundle("TAL_ALCHEMY_CALMING_HEART_PILL"), allies=(_ally_bundle(),))
    source = "system:test.zone_move_through"
    rule = {"min_ft": 0, "who": "any", "roster": "any", "effects": [copy.deepcopy(DAMAGING_SAVE)]}
    action, spec = _roster_zone(ME, source, triggers=[], move_through=rule)
    zone = _place_roster_zone(engine, ME, source, "zone:test:through", action, spec)
    ally = engine.state.actors[ALLY]
    assert zone.trigger_profile["triggers"] == [] and zone.trigger_profile["move_through"]["roster"] == "any"
    assert zones.prospective_effects(engine, zone, ally) == [(zone.trigger_profile["move_through"],
                                                              zone.trigger_profile["move_through"]["effects"])]

    _, metadata, label = _preview(engine, engine.state.actors[ME], action, engine.state.actors[ME].position)
    # The reviewed any-roster rule exposes the caster and the ally (5 damage each).
    assert metadata["allies_in_area"] == 2
    assert metadata["ally_expected_damage"] == 10
    assert label.startswith("Hits allies too:")

    # The same reviewed roster scopes the packet when the ally walks through.
    start = Position(x=ally.position.x, y=ally.position.y + 1)
    before = len(engine.events)
    zones.on_moved(engine, ally, start, ally.position)
    assert [event.actor_id for event in engine.events[before:]
            if event.event_type == "SAVE_ROLLED" and event.source_definition_id == source] == [ALLY]


def test_a_reviewed_roster_and_a_printed_each_creature_zone_survive_a_table_commit_and_reload(tmp_path):
    """Both kinds of compiled trigger keep their recipient meaning through a real table commit and reload."""
    combat, _table, mid = table_fight(tmp_path, ["TAL_ALCHEMY_CALMING_HEART_PILL"])
    session = combat._load_session(mid)
    _place(session.engine, TABLE_OWNER, SOURCE_PRINTED, "zone:test:printed")
    _place(session.engine, TABLE_OWNER, SOURCE_REVIEWED, "zone:test:reviewed", reviewed_roster="any")
    session.mechanical.explicit_snapshot()  # a real table commit

    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    printed = engine.state.zones["zone:test:printed"]
    reviewed = engine.state.zones["zone:test:reviewed"]
    assert printed.trigger_profile["triggers"][0]["who"] == "hostile"
    assert "roster" not in printed.trigger_profile["triggers"][0]
    assert reviewed.trigger_profile["triggers"][0]["roster"] == "any"
    assert type(reviewed.trigger_profile["triggers"][0]["roster"]) is str  # integers and strings only on the wire

    # A reload rebuilds the action catalog from authority; re-attach the two
    # synthetic rows this test compiled (the zones themselves came back from disk).
    for zone, roster in ((printed, None), (reviewed, "any")):
        action, _mechanic, _numbers = _compiled(zone.owner_id, zone.source_definition_id, reviewed_roster=roster)
        engine.action_catalog[zone.source_definition_id] = action
    ally, owner = engine.state.actors[TABLE_ALLY], engine.state.actors[TABLE_OWNER]
    for zone, target in ((printed, ally), (reviewed, owner)):
        before = len(engine.events)
        trigger = zone.trigger_profile["triggers"][0]
        assert zones._applies(engine, zone, target, trigger)
        zones.fire_trigger(engine, zone, target, "enter")
        assert _saves(engine.events[before:], zone.source_definition_id)
