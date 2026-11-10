"""MMX105 (round 24, live 42e43e14): the engine's square probe must never reach a plug-in hook as if it were a
creature.

A fog projection asks "can this viewer see this empty square?" by passing a lightweight stand-in through the
ordinary perception policy (combat/senses.py perceives_cell). That probe is handed to every masked_conditions
subscriber. ``combat.ext.calamity_eyes.unseen_gives_no_advantage`` read ``attacker.team_id`` off it, so every
square of every viewer's view raised AttributeError; ext.run caught and logged each one, and the live service
wrote 292,774 lines in three hours. A square can never own a printed rule, so the fix is to skip the probe
(senses.is_creature) and to guard the whole hook point so no plug-in can raise on it again.

The printed rule is unchanged for real creatures: three open Eyes still take the Advantage away from an unseen
attacker (tests/test_riders_c7.py) and the table still resolves fog-of-war the same way.
"""
import logging

import pytest

from combat import ext, senses
from combat.gate2_runtime_models import Position

from tests.r1i_service_support import SECOND
from tests.test_effect_durations import _fight

ME, AN = "actor:factory.durations_me", "actor:factory.durations_ally"


def _engine():
    engine, me, other = _fight("PROBEGUARD")
    return engine, me, other


def _subscriber_name(function):
    return f"{function.__module__}.{function.__name__}"


#: One printed condition per entry, tried ALONE on its own fighter. A masked_conditions hook is free to skip a
#: creature carrying none of its conditions -- the Stars rule does exactly that, which is how
#: ``stars.marked_not_invisible`` read ``other.team_id`` off a square without any test noticing: the first version
#: of this guard passed only plain fighters, so the hook returned early at that skip and the raising line was
#: never reached. Each condition must be alone because these hooks branch on an ``or``: a second condition (the
#: Stars rule's "cannot benefit from Invisible at all" seal) can satisfy the chain and hide the very line that
#: raises, so carrying them together makes the guard pass on a bug. The guard is only real if it hands a hook a
#: creature in a state that rule would actually act on, one rule at a time.
_RULE_CONDITIONS = ("condition:typed.invisible", "condition:typed.constellation_prison", "Stellar Mark")


def _carrying(condition):
    """A fresh fighter carrying exactly ``condition``, facing a fresh enemy, on its own engine."""
    from combat.typed_executor import mark_condition_id

    engine, me, foe = _engine()
    condition_id = mark_condition_id(condition, foe.entity_id) if condition == "Stellar Mark" else condition
    engine._apply_condition(me, condition_id, "test:probe-guard", foe.entity_id, expires_on="UNTIL_REMOVED")
    return engine, me, foe


# ------------------------------------------------------------------------------------- the shape the engine really passes
def test_the_probe_carries_exactly_the_documented_fields():
    probe = senses.cell_probe(Position(x=4, y=5))
    assert set(vars(probe)) == set(senses.PROBE_FIELDS)
    assert probe.entity_id == "perception:cell" and probe.position == Position(x=4, y=5)
    assert probe.conditions == {} and probe.perception_cell is True
    # The contract those fields imply: a real fighter has all of this and more, a square has none of it.
    engine, me, foe = _engine()
    assert senses.is_creature(me) and senses.is_creature(foe)
    assert not senses.is_creature(probe) and not senses.is_creature(None)


def test_perceives_cell_really_hands_that_probe_to_the_hook(caplog):
    """The documented fields are only a promise if the engine passes exactly this object."""
    engine, me, _ = _engine()
    ext._load()
    seen = []
    spy = lambda engine_, attacker, target: seen.append((attacker, target)) or None
    hooks = list(ext._HOOKS["masked_conditions"])
    ext._HOOKS["masked_conditions"] = [*hooks, spy]
    try:
        with caplog.at_level(logging.WARNING, logger="combat.ext"):
            senses.perceives_cell(engine, me, Position(x=4, y=5))
    finally:
        ext._HOOKS["masked_conditions"] = hooks
    assert len(seen) == 1 and seen[0][0] is me  # the viewer is a real fighter ...
    assert set(vars(seen[0][1])) == set(senses.PROBE_FIELDS)  # ... and the square is the documented probe


# ------------------------------------------------------------------------------------- the guard: no subscriber may raise
def test_every_masked_conditions_subscriber_survives_the_engine_probe_shape(caplog):
    engine, me, foe = _engine()
    ext._load()
    subscribers = list(ext._HOOKS["masked_conditions"])
    assert subscribers, "no masked_conditions subscriber is registered; the guard would be vacuous"
    probe = senses.cell_probe(Position(x=4, y=5))
    # The only two shapes the engine passes (senses.py:262 and senses.py:409): two real fighters, or a real
    # viewer and one visible square. The viewer is never a probe and never None, so those are not tested here.
    # Each shape is tried with a plain fighter and again with a fighter carrying one printed condition (see
    # _RULE_CONDITIONS), so a hook that skips a conditionless creature is still reached.
    fights = [(engine, me, foe)] + [_carrying(condition) for condition in _RULE_CONDITIONS]
    failed = []
    with caplog.at_level(logging.WARNING, logger="combat.ext"):
        for function in subscribers:
            for engine_, attacker, target_fighter in fights:
                for target in (target_fighter, probe):
                    try:
                        function(engine_, attacker, target)
                    except Exception as exc:  # noqa: BLE001 -- the guard reports, it does not raise
                        failed.append(f"{_subscriber_name(function)}: {type(exc).__name__}: {exc}")
    assert not failed, "a masked_conditions subscriber cannot handle the engine's square probe:\n" + "\n".join(failed)
    assert [r for r in caplog.records if r.name == "combat.ext"] == []


def test_every_darkness_lifted_subscriber_survives_the_engine_probe_shape(caplog):
    """The other per-probe hook point: zones._lifted passes a square to it while a darkness area is in the way."""
    engine, me, foe = _engine()
    from combat import zones

    ext._load()
    subscribers = list(ext._HOOKS.get("darkness_lifted", []))
    if not subscribers:
        pytest.skip("no darkness_lifted subscriber is registered")
    probe = senses.cell_probe(Position(x=4, y=5))
    zone = zones.ZoneState(zone_id="zone:probe", source_definition_id="test:darkness", owner_id=me.entity_id,
                           center=Position(x=4, y=5), radius_cells=3,
                           affected_cells=(Position(x=4, y=5), Position(x=4, y=6)),
                           concentration_link=False, created_round=1, active=True,
                           trigger_profile={"name": "Darkness", "visual": {"darkness": True}})
    failed = []
    with caplog.at_level(logging.WARNING, logger="combat.ext"):
        for function in subscribers:
            for viewer, seen in ((me, foe), (me, probe)):
                try:
                    function(engine, zone, viewer, seen)
                except Exception as exc:  # noqa: BLE001
                    failed.append(f"{_subscriber_name(function)}: {type(exc).__name__}: {exc}")
    assert not failed, "a darkness_lifted subscriber cannot handle the engine's square probe:\n" + "\n".join(failed)
    assert [r for r in caplog.records if r.name == "combat.ext"] == []


def test_a_fog_projection_logs_no_failing_hook(caplog):
    """The live symptom: a whole board of squares, one warning line each."""
    engine, me, _ = _engine()
    ext._load()
    with caplog.at_level(logging.WARNING, logger="combat.ext"):
        seen = senses.perception(engine, me)
    assert [r for r in caplog.records if r.name == "combat.ext"] == []
    assert not [e for e in engine.events if e.event_type == "GM_RIDER" and "failed:" in str((e.payload or {}).get("rider"))]
    assert seen["cells"] and me.entity_id in seen["creatures"]


# ------------------------------------------------------------------------------------- the printed rule still holds for real creatures
def test_three_open_eyes_still_take_an_unseen_attackers_advantage_away():
    from tests.test_riders_c7 import ME as EYES_ME, _eyes

    engine, me, foe = _eyes([])
    engine._apply_condition(foe, "condition:typed.invisible", "test:invisible", EYES_ME, expires_on="UNTIL_REMOVED")
    invisible = {iid for iid, c in foe.conditions.items() if c.condition_id == "condition:typed.invisible"}
    assert invisible, "the test's own Invisible condition did not land"
    # The attacker's own attack: the printed "no Advantage from being unseen" is a real mask, not a skip.
    masks = senses.masked_conditions(engine, foe, me)          # foe attacks me
    assert masks.get(foe.entity_id, set()) & invisible
    assert me.entity_id == EYES_ME


def test_a_stellar_mark_still_takes_ordinary_invisible_away_from_its_bearer():
    """"A target bearing your Stellar Mark cannot benefit from ordinary Invisible against you" (Stars).

    The probe guard above skips a square; this is the rule that must still bite on a real pair. An ordinary
    (unsealed) Invisible on a marked target is the case the guard had to reach to find the crash.
    """
    from combat.ext.stars import marked_not_invisible
    from combat.typed_executor import mark_condition_id

    engine, me, foe = _engine()
    marked = mark_condition_id("Stellar Mark", me.entity_id)
    engine._apply_condition(foe, marked, "test:mark", me.entity_id, expires_on="UNTIL_REMOVED")
    engine._apply_condition(foe, "condition:typed.invisible", "test:invisible", me.entity_id, expires_on="UNTIL_REMOVED")
    invisible = {iid for iid, c in foe.conditions.items() if c.condition_id == "condition:typed.invisible"}
    masks = marked_not_invisible(engine, me, foe)               # the marked target attacks me
    assert masks and masks.get(foe.entity_id, set()) & invisible
    # Nothing is masked for a pair with no Stellar Mark between them: the skip must not over-reach.
    other_engine, other_me, other_foe = _engine()
    other_engine._apply_condition(other_foe, "condition:typed.invisible", "test:invisible",
                                  other_me.entity_id, expires_on="UNTIL_REMOVED")
    assert marked_not_invisible(other_engine, other_me, other_foe) is None


# ------------------------------------------------------------------------------------- the table, where the flood was seen
def test_a_played_table_fight_draws_its_fog_without_failing_a_hook(tmp_path, caplog):
    """The live symptom at the level it happened: a hand-played fight asking the table for its fog of war.

    The table projects every visible square of every living fighter, so on the base commit this logged one
    warning per square per fighter. The fog itself must still be correct, and the fight must still reload and
    replay byte-identically.
    """
    from tests.h49_fog_support import assert_roundtrip, option
    from tests.r1i_service_support import FOE, OWNER, fixture

    combat, table, mid, _send, commit = fixture(
        tmp_path, ["DARK_BASE_DARKNESS"], wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}},
    )
    commit(option(table, mid, "Darkness", {"x": 6, "y": 6})["candidate_id"])
    with caplog.at_level(logging.WARNING, logger="combat.ext"):
        fog = table.state(mid, fog=True)["fog_perception"]
    assert [r for r in caplog.records if r.name == "combat.ext"] == [], "a plug-in hook failed on the table's squares"
    assert fog, "the table drew no fog of war at all"
    # Fog is still decided by the engine: a viewer outside the Darkness still sees its own square.
    assert [3, 6] in fog[OWNER]["cells"]
    assert_roundtrip(combat, tmp_path, mid)   # save, reload and replay still agree


def test_a_table_fighter_who_is_invisible_still_gets_its_fog_drawn(monkeypatch, tmp_path, caplog):
    """The Stars half of the same live symptom, at the level the owner saw it.

    The Open Eyes rule above crashed on every square. The Stellar Mark rule crashed on every square too, but
    only once a fighter was actually Invisible -- which is why it was the smaller of the two log counts and why
    the table test above never found it. An Invisible fighter makes the projection of that fighter's OWN view
    raise, because the rule compared the viewer's team with a square's.

    The condition is put on through a real table commit (the documented ``ext`` event hook, the way
    test_riders_c7 charges a resource), so it is saved, reloaded and replayed like any printed rule's.
    """
    from combat import ext
    from tests.h49_fog_support import assert_roundtrip
    from tests.r1i_service_support import FOE, OWNER, SECOND, fixture

    def go_invisible(fight, event_type, kwargs):
        if event_type == "HOLD_POSITION_COMMITTED" and kwargs["actor_id"] == OWNER:
            fight._apply_condition(fight.state.actors[OWNER], "condition:typed.invisible",
                                   "test:probe-guard", OWNER, expires_on="UNTIL_REMOVED")
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), go_invisible])

    combat, table, mid, _send, commit = fixture(
        tmp_path, [], wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}},
    )
    menu = table.state(mid)["menu"]
    hold = next(g for g in menu["actions"] if g["source_definition_id"] == "system:combat.hold_position")
    commit(hold["options"][0]["candidate_id"])
    saved = combat._load_session(mid).engine.state.actors[OWNER]
    assert [c.condition_id for c in saved.conditions.values()].count("condition:typed.invisible") == 1, \
        "the test's own Invisible did not survive the table commit and reload"

    with caplog.at_level(logging.WARNING, logger="combat.ext"):
        fog = table.state(mid, fog=True)["fog_perception"]
    assert [r for r in caplog.records if r.name == "combat.ext"] == [], \
        "a plug-in hook failed while drawing the fog of an Invisible fighter"
    assert fog[OWNER]["cells"], "an Invisible fighter still sees the board it stands on"
    assert_roundtrip(combat, tmp_path, mid)
