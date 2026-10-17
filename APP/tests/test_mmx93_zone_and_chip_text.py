"""An area's log lines say which area, where it sits and how long it lasts, and a condition chip
never shows a bare index number (owner 2026-10-03: hunts 96 #1/#2, hunt 98 #1).

Both defects were player-facing text: two areas of one kind ended with the same line, an area
appeared with no location or duration, and a condition chip could be labelled with the counter
that ends its internal id. Nothing here recalculates a fight outcome -- the tests read the real
journal of a real fight and run it through the real fight-log composer and the real projector.
"""
import pytest

from combat.gate2_runtime_models import Position, ZoneState
from combat.gate5_service import CombatService
from combat.history_feed import format_history_feed
from combat.presentation import _condition_label
from tests import test_tabletop_hunt6 as H
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act
from tests.test_lock8_movement_steps import portable

STEAL = "TAL_SCOUNDREL_STEAL_MOMENTUM"
SAND = "SAND_BASE_SCOURING_HAND"
AREA = "Smoke Veil"
TALISMAN = "tianxia.talent.talismans.qi_storage_talisman"


def _zone(engine, owner, center, cells, zone_id, duration=10):
    """A real area record, recorded the way the engine records one (combat/zones.py:250)."""
    zone = ZoneState(
        zone_id=zone_id, source_definition_id=next(iter(engine.action_catalog)),
        owner_id=owner, center=Position(**center), radius_cells=0,
        affected_cells=tuple(Position(x=x, y=y) for x, y in cells),
        concentration_link=False, created_round=engine.state.round_number, duration_rounds=duration,
        trigger_profile={"kind": "TYPED", "name": AREA, "numbers": {}, "triggers": []},
    )
    engine.state.zones[zone.zone_id] = zone
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=owner,
                         payload={"zone": zone.model_dump(mode="json")})
    return zone


def _summarised(service, table, mid):
    """The real journal of a real fight, read by the real fight-log composer."""
    engine = service._load_session(mid).engine
    actors, definitions = table._names_for(mid, engine)
    return format_history_feed(
        [event.model_dump(mode="json") for event in engine.events], [],
        pre_state=None, post_state={}, actor_names=actors, definition_names=definitions,
    )


def _zone_lines(feed, created):
    rows = [row["summary"] for row in feed if row.get("event_type") == ("ZONE_CREATED" if created else "ZONE_REMOVED")]
    assert rows, "the fight recorded no area lines"
    return rows


def test_area_creation_line_says_where_it_sits_and_how_long_it_lasts(monkeypatch, tmp_path):
    service, table, mid, left, right = portable(tmp_path, STEAL, SAND, left_at=(2, 6), right_at=(4, 4))
    names = service._load_session(mid).engine.state.actors[left].display_name

    def build(engine):
        _zone(engine, left, {"x": 4, "y": 5}, [(4, 5), (4, 6), (4, 7)], "zone:mmx93.creation")

    H.on_hold(monkeypatch, build)
    assert act(table, mid, H.HOLD)["status"] == "COMMITTED"

    (line,) = _zone_lines(_summarised(service, table, mid), created=True)
    # what it is, who made it, where it is, how big, how long -- all in one line.
    assert line.startswith(f"{names} created the {AREA} area around (4, 5).")
    assert "3 squares" in line
    assert "10 rounds" in line


def test_each_ended_area_is_named_by_the_fighter_who_made_it():
    """The two areas of hunt 96 P01, as the journal recorded them: one name, two creators."""
    records = []
    for index, (zone_id, creator, x, y) in enumerate((
        ("zone:fec9fac0", "tabik", 8, 0), ("zone:14926a84", "lingfeng", 4, 7),
    )):
        zone = {"zone_id": zone_id, "owner_id": creator, "center": {"x": x, "y": y},
                "affected_cells": [{"x": x, "y": y}], "duration_rounds": 10,
                "trigger_profile": {"kind": "TYPED", "name": AREA, "numbers": {}, "triggers": []}}
        records.append({"sequence": index + 1, "event_type": "ZONE_CREATED", "actor_id": creator,
                        "target_ids": [], "source_definition_id": "action:tabik.smoke_veil",
                        "payload": {"zone": zone}})
    for index, (zone_id, creator) in enumerate((("zone:fec9fac0", "tabik"), ("zone:14926a84", "lingfeng"))):
        records.append({"sequence": len(records) + 1, "event_type": "ZONE_REMOVED", "actor_id": creator,
                        "target_ids": [], "source_definition_id": "action:tabik.smoke_veil",
                        "payload": {"zone_id": zone_id, "reason": "DURATION_ENDED"}})
    feed = format_history_feed(records, [], pre_state=None, post_state={},
                               actor_names={"tabik": "Tabik Damu", "lingfeng": "Lingfeng Ironclad"},
                               definition_names={})

    # Each creation line says who made it, where it is and how long it lasts (hunt 96 #2).
    created = [row["summary"] for row in feed if row["event_type"] == "ZONE_CREATED"]
    assert len(created) == 2
    assert len(set(created)) == 2, "the two areas were announced identically"
    assert created[0].startswith("Tabik Damu created the Smoke Veil area around (8, 0).")
    assert created[1].startswith("Lingfeng Ironclad created the Smoke Veil area around (4, 7).")
    assert all("10 rounds" in line for line in created), created

    # Each end line says which of the two it was (hunt 96 #1).
    ended = [row["summary"] for row in feed if row["event_type"] == "ZONE_REMOVED"]
    assert len(ended) == 2
    assert "The Smoke Veil area Tabik Damu created around (8, 0) ended" in ended[0]
    assert "The Smoke Veil area Lingfeng Ironclad created around (4, 7) ended" in ended[1]
    assert len(set(ended)) == 2


def _talisman_fight(tmp_path):
    from combat.canonical import canonical_sha256
    from combat.factory_compiler import compile_character
    from combat.tabletop_service import TabletopService

    me, foe = "actor:factory.mmx93", "actor:factory.mmx93-foe"
    bundle = compile_character(sheet([TALISMAN], cl=10), actor_id=me, reaction_plan={"ask": True})
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    bundle["bundle_sha256"] = canonical_sha256(unsigned)
    enemy = compile_character(sheet([], cl=10), actor_id=foe)
    unsigned = {key: value for key, value in enemy.items() if key != "bundle_sha256"}
    enemy["bundle_sha256"] = canonical_sha256(unsigned)
    service = CombatService(ROOT, tmp_path)
    slots = next(row["maximum"] for row in bundle["actor_template"]["resources"]
                 if row["resource_id"] == "resource:named.prepared_talismans")
    bundle = service._with_prefight(bundle, {me: ["setup-choice:qi_storage_charges:" + ",".join(["2"] * slots)]})
    table = TabletopService(service, tmp_path)
    mid = service._finish_factory_match(
        [bundle, enemy], [me, foe], {me: "team:factory", foe: "team:opponents"},
        {me: {"x": 3, "y": 6}, foe: {"x": 4, "y": 6}},
        service.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [me], [foe],
        control_modes={me: "MANUAL", foe: "MANUAL"}, match_seed="MMX93",
        display_name="MMX93 chip text", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != me:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return service, table, mid, me


def test_a_condition_chip_never_shows_a_bare_index_number(tmp_path):
    """Hunt 98 #1: a chip could be labelled with the counter that ends its internal id."""
    service, table, mid, me = _talisman_fight(tmp_path)
    raw = service._load_session(mid).engine.state.model_dump(mode="json")
    metadata = service._metadata_readonly(mid, raw)
    catalog, typed_actions = service._catalog_with_factory_fighters(mid)
    # The compact actor view combat/gate5_service.py publishes carries condition ids, not the
    # per-fight records behind them -- so a chip is named from the id alone on that path.
    compact = {**raw, "actors": [
        {**{key: value for key, value in row.items() if key != "conditions"},
         "condition_ids": sorted(condition.get("condition_id", key)
                                 for key, condition in (row.get("conditions") or {}).items())}
        for row in (raw["actors"].values() if isinstance(raw["actors"], dict) else raw["actors"])]}
    projection = service.presenter.project(
        match_id=mid, metadata=metadata, state=compact, catalog=catalog, mode="LIVE",
        typed_actions=typed_actions)
    chips = [chip.display_name for row in projection.actors for chip in row.conditions
             if chip.condition_id.startswith("condition:typed.qi_storage_talisman")]
    assert len(chips) >= 2, "the fighter held no stored talismans to show"
    assert not any(chip.strip().isdigit() for chip in chips), f"a chip was a bare number: {chips}"
    assert all("Qi Storage Talisman" in chip for chip in chips), chips


@pytest.mark.parametrize("condition_id", [
    "condition:typed.qi_storage_talisman:prepared:1",
    "condition:typed.qi_storage_talisman:prepared:11",
])
def test_a_counter_ending_a_condition_id_still_names_the_condition(condition_id):
    label = _condition_label(condition_id)
    assert not label.strip().isdigit(), f"a chip was a bare number: {label}"
    assert "Qi Storage Talisman" in label, label


def test_condition_names_without_a_counter_are_unchanged():
    """The counter rule must not touch the names that were already right."""
    assert _condition_label("condition:typed.stance.demon_seed") == "Demon Seed"
    assert _condition_label("condition:typed.prone") == "Prone"
    assert _condition_label("condition:core.reaction_denied") == "Reaction Denied"
    assert _condition_label("condition:typed.mark.waning_seed.actor:factory.tabik") == "Waning Seed"
    # A per-fight label still wins over the id.
    assert _condition_label("condition:typed.qi_storage_talisman:prepared:3",
                            {"label": "Qi Storage Talisman: 2 CP stored"}) == "Qi Storage Talisman: 2 CP stored"


# ----------------------------------------------------------------- MMX93f1: a lifetime that is true, and a removal the table really committed

ZONE_ID = "zone:mmx93f1.committed"


def test_a_committed_area_ends_and_the_table_feed_still_names_it_after_a_reload(monkeypatch, tmp_path):
    """The removal line where the bug showed: a real area, a real removal, a committed journal, a reload, a poll.

    Both records are the engine's own -- ``_zone`` builds a real ``ZoneState`` and
    ``placed.drop`` is the real removal every area ability uses (combat/ext/seal.py:176) --
    and each is committed by its own table transaction. The area is gone from the fight
    state before the reload, so the end line has to be rebuilt from the journal alone.
    """
    from combat.ext import placed
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT

    service, table, mid, left, right = portable(tmp_path, STEAL, SAND, left_at=(2, 6), right_at=(4, 4))
    creator = service._load_session(mid).engine.state.actors[left].display_name
    phase = {"now": "create"}

    def build(engine):
        if phase["now"] == "create":
            _zone(engine, left, {"x": 4, "y": 5}, [(4, 5), (4, 6), (4, 7)], ZONE_ID)
        else:  # the engine's own removal, of a real area that is really on the map
            placed.drop(engine, engine.state.zones[ZONE_ID], "DURATION_ENDED")

    H.on_hold(monkeypatch, build)
    assert act(table, mid, H.HOLD)["status"] == "COMMITTED"  # 1. the area is created
    (made,) = [event for event in service._load_session(mid).engine.events
               if event.event_type == "ZONE_CREATED" and (event.payload or {}).get("zone", {}).get("zone_id") == ZONE_ID]
    zone = made.payload["zone"]
    assert service._load_session(mid).engine.state.zones[ZONE_ID].active  # it survived its commit

    phase["now"] = "end"
    assert act(table, mid, H.HOLD)["status"] == "COMMITTED"  # 2. and removed by a later one
    engine = service._load_session(mid).engine
    (removed,) = [event for event in engine.events
                  if event.event_type == "ZONE_REMOVED" and (event.payload or {}).get("zone_id") == ZONE_ID]
    assert removed.payload["reason"] == "DURATION_ENDED"
    assert not engine.state.zones[ZONE_ID].active  # really gone, not only logged

    # 3. a fresh load of the saved fight, read through the table's own feed endpoint.
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    (created,) = _zone_lines(table.events(mid, 0)["events"], created=True)
    assert created.startswith(f"{creator} created the {AREA} area around (4, 5).")
    assert "up to 10 rounds" in created, created
    (ended,) = _zone_lines(table.events(mid, 0)["events"], created=False)
    assert f"The {AREA} area {creator} created around (4, 5) ended because its time was up." == ended, ended
    assert zone["zone_id"] == ZONE_ID

    # 4. and the incremental poll the table streams: the same removal, in its own window.
    (polled,) = [row for row in table.events(mid, removed.sequence - 1)["events"]
                 if row.get("event_type") == "ZONE_REMOVED"]
    # The creator is on the removal record itself, so the window still says who; the name and
    # the square come from the creation record, which a later window does not carry (the
    # inherited windowing limitation, recorded as a lock-round item by this lane's report).
    assert polled["summary"].endswith(f"area {creator} created ended because its time was up."), polled["summary"]
    assert "around" not in polled["summary"], polled["summary"]
    assert table.events(mid, removed.sequence)["events"] == []  # the window is spent once read


def test_an_area_line_never_promises_a_lifetime_its_record_cannot_show():
    """A Concentration area and an area with no stated lifetime, through the real composer."""
    from combat.gate2_runtime_models import Position, ZoneState

    def line(zone):
        return format_history_feed(
            [{"sequence": 1, "event_type": "ZONE_CREATED", "actor_id": "tabik", "target_ids": [],
              "source_definition_id": "action:tabik.area",
              "payload": {"zone": zone.model_dump(mode="json")}}],
            [], pre_state=None, post_state={}, actor_names={"tabik": "Tabik Damu"}, definition_names={})[0]["summary"]

    def area(**kwargs):
        return ZoneState(zone_id="zone:mmx93f1", source_definition_id="action:tabik.area", owner_id="tabik",
                         center=Position(x=4, y=5), radius_cells=0, affected_cells=(Position(x=4, y=5),),
                         created_round=1, trigger_profile={"kind": "TYPED", "name": "Still Water", "numbers": {}, "triggers": []},
                         **kwargs)

    held = line(area(concentration_link=True, duration_rounds=10))
    assert "up to 10 rounds" in held
    assert "only while its creator keeps concentrating on it" in held, held
    assert "until the fight ends" not in held

    indefinite = line(area(concentration_link=False, duration_rounds=None))
    assert "It lasts" not in indefinite, f"a lifetime was promised that the record cannot keep: {indefinite}"
    assert "Still Water area around (4, 5)" in indefinite

    single = line(area(concentration_link=False, duration_rounds=1))
    assert "up to 1 round." in single, single
