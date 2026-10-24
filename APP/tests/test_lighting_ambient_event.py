"""LIGHTS2 root fix: the table owner's mid-fight light is one recorded fight event, not a side file.

The lead's four required tests come first (a replay/verify parity test, the indoor_level test, the GM-only test, and the
no-file-changed test). The remaining tests pin each F7 defect that the side file caused, so none can return.
"""
import hashlib
from pathlib import Path

import pytest

from combat.lighting import ambient
from combat.match_ambient import AMBIENT_EVENT, AMBIENT_KIND, normalize_ambient, validate_ambient_binding
from combat.gate2_runtime_models import ActionIntent
from combat.tabletop import TabletopError
from tests.auto11_service_support import play
from tests.lighting_support import ALLY, FOE, OWNER, ambient_light, fight, light, map_document

DAY = ambient_light("day")
DARKVISION = [{"sense": "darkvision", "range_ft": 60}]
POSITIONS = {OWNER: {"x": 2, "y": 2}, ALLY: {"x": 3, "y": 2}, FOE: {"x": 9, "y": 2}}


def _event_types(engine):
    return [getattr(event, "event_type", None) or event.get("event_type") for event in engine.events]


def _files(root: Path):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


# Lead test 1: set night mid-fight, save, reload, and replay/verify give the identical state hash.
def test_a_mid_fight_night_is_one_recorded_event_that_replays_to_the_same_state(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document, senses=[], ally_senses=DARKVISION, positions=POSITIONS)
    play(table, mid, table.state(mid)["menu"]["end_turn"], answer=None)
    before = combat._load_session(mid).engine.events[:]
    table.set_match_ambient(mid, {"time_of_day": "night"})

    engine = combat._load_session(mid).engine
    assert _event_types(engine)[len(before):] == [AMBIENT_EVENT], "the change must be the one new recorded event"
    assert engine.state.ambient_override == {"time_of_day": "night"}
    assert ambient(engine)["time_of_day"] == "night"

    live = engine.state.model_dump(mode="json")
    reloaded = type(combat)(combat.source_root, combat.userdata_root)._load_session(mid)
    assert reloaded.engine.state.model_dump(mode="json") == live, "a cold reload must rebuild the same state"
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"
    assert combat.verify(mid)["status"] == combat.replay(mid)["status"] == "PASS"


# Lead test 2: an arena with indoor_level keeps roofed squares at that level after a GM sets only time_of_day.
def test_setting_only_the_time_keeps_the_arena_indoor_level(tmp_path):
    document = map_document(20, 12, ambient=ambient_light("day", indoor_level="dark"), lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document)
    assert ambient(combat._load_session(mid).engine)["indoor_level"] == 0

    table.set_match_ambient(mid, {"time_of_day": "night"})

    engine = combat._load_session(mid).engine
    assert ambient(engine)["indoor_level"] == 0, "the authored indoor level must survive a time-only change"
    assert ambient(engine)["time_of_day"] == "night"


# Lead test 3: the endpoint refuses non-GM callers.
# The app has no GM identity; the enforced boundary is that a fighter's intent cannot carry the light change.
def test_a_fighter_intent_cannot_carry_the_light_change(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, _table, mid = fight(tmp_path, document)
    engine = combat._load_session(mid).engine
    binding = {"kind": AMBIENT_KIND, "payload": {"time_of_day": "night"}}
    from combat.canonical import canonical_sha256
    fighter = ActionIntent(intent_id="fighter:1", decision_id="fighter-choice:v1", candidate_id=canonical_sha256(binding),
                           state_version=engine.state.state_version, actor_id=engine.state.current_actor_id)
    with pytest.raises(ValueError, match="cannot carry a fighter action"):
        validate_ambient_binding(engine, fighter, binding)


def test_the_light_change_is_refused_for_an_unknown_setting(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    _combat, table, mid = fight(tmp_path, document)
    with pytest.raises(TabletopError) as refused:
        table.set_match_ambient(mid, {"time_of_day": "noon"})
    assert refused.value.code == "TABLETOP_AMBIENT_INVALID" and refused.value.status_code == 400


# Lead test 4: no file other than the event log changes in the match directory.
def test_the_light_change_writes_no_file_but_the_event_log(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document)
    root = combat._match_dir(mid)
    before = _files(root)

    table.set_match_ambient(mid, {"time_of_day": "night"})

    after = _files(root)
    changed = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
    assert not [name for name in after if "Ambient" in name], "no side file may exist"
    assert after["Arena_Battlefield.json"] == before["Arena_Battlefield.json"], "the sealed arena must not change"
    assert changed, "the event must be recorded somewhere"
    assert "Arena_Battlefield.json" not in changed and not any("Ambient" in name for name in changed)


# F7 defect: an ambient edit after recorded events was refused with a 409 lock (no longer needed: it is a recorded decision).
def test_a_change_after_recorded_events_is_recorded_not_refused(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, table, mid = fight(tmp_path, document)
    play(table, mid, table.state(mid)["menu"]["end_turn"], answer=None)
    table.set_match_ambient(mid, {"time_of_day": "night"})
    assert combat._load_session(mid).engine.state.ambient_override["time_of_day"] == "night"


# F7 defect: a corrupt side file was ignored. There is no side file now, so the corrupt bytes can't reach the light.
def test_the_light_reads_only_the_arena_and_the_recorded_settings(tmp_path):
    document = map_document(20, 12, ambient=DAY, lights=[light(8, 6)])
    combat, _table, mid = fight(tmp_path, document)
    (combat._match_dir(mid) / "Ambient_Override.json").write_text('{"time_of_day": "noon"}', encoding="utf-8")
    assert ambient(combat._load_session(mid).engine)["time_of_day"] == "day"


def test_normalize_keeps_only_the_settings_the_gm_gave():
    assert normalize_ambient({"time_of_day": "night"}) == {"time_of_day": "night"}
    assert normalize_ambient({"level": "dim"}) == {"level": 1}
    with pytest.raises(ValueError):
        normalize_ambient({})
