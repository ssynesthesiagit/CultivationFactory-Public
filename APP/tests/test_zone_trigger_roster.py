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

from combat import typed_executor, zones
from combat.factory_compiler import _zone_spec
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_auto_lane1 import ALLY, ME, _ally_bundle, _bundle, _engine
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
