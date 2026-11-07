"""Areas an ability leaves on the map (owner 2026-09-27 playtest: Ashfall "had nothing under it"; "we need a visual
layer to show terrain effects"): Ashfall's Ash Terrain, and an Ashfall talent that fires on a foe entering it or
starting its turn inside (combat/zones.py, combat/rules/terrain.json)."""

from pathlib import Path

from combat import zones
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position

ROOT = Path(__file__).resolve().parents[1]
OWNER = "actor:factory.ashen"
SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Qi Cultivation", "key_ability": "CON"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 30}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
        "speed": {"walking_ft": 30}, "technique_save_dc": 30, "technique_attack_bonus": 8,
    },
    "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.ash"],
                            "learned_talent_record_ids": ["ASH_BASE_ASHFALL", "ASH_TAL_SOOT_IN_LUNGS"]},
}


def _engine() -> Gate2Engine:
    bundle = compile_character(SHEET, actor_id=OWNER)
    engine = Gate2Engine(ROOT, match_seed="ZONES", typed_bundles=(bundle,),
                       roster_setup={"primary_actor_ids": [OWNER, AN], "team_by_actor": {OWNER: "team:a", AN: "team:b"},
                                     "starting_positions": {OWNER: {"x": 3, "y": 6}, AN: {"x": 14, "y": 6}}})
    engine.typed_control_modes = {OWNER: "LOCAL_AUTO"}  # these tests exercise the AI's unchosen shape
    return engine


def _cast(engine: Gate2Engine, suffix: str, at: Position) -> None:
    engine.state.current_slot_index = engine.state.initiative_order.index(OWNER)
    engine.state.current_actor_id = OWNER
    engine._system_start_turn()
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.startswith(suffix) and c.destination is not None and (c.destination.x, c.destination.y) == (at.x, at.y))
    engine.execute_intent(ActionIntent(intent_id="cast", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=OWNER, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_ashfall_leaves_ash_terrain_that_ends_with_its_concentration():
    engine = _engine()
    _cast(engine, "Ashfall", Position(x=13, y=6))  # carries Soot in the Lungs by default (its only talent)
    [zone] = zones.typed_zones(engine)
    profile = zone.trigger_profile
    assert profile["name"] == "Ashfall" and profile["terrain"] == ["ash terrain"] and profile["visual"]["material"] == "ash"
    assert Position(x=13, y=9) in zone.affected_cells and Position(x=13, y=10) not in zone.affected_cells  # a 15-foot radius
    foe = engine.state.actors[AN]
    assert (13, 6) in zones.difficult_cells(engine, foe) and not zones.difficult_cells(engine, engine.state.actors[OWNER])
    engine._end_concentration(engine.state.actors[OWNER], "TEST")
    assert not zones.typed_zones(engine)


def test_a_foe_entering_or_starting_its_turn_inside_meets_soot_in_the_lungs_once_a_turn():
    engine = _engine()
    _cast(engine, "Ashfall", Position(x=13, y=6))  # carries Soot in the Lungs by default (its only talent)
    foe = engine.state.actors[AN]
    [zone] = zones.typed_zones(engine)
    start, foe.position = Position(x=20, y=6), Position(x=13, y=6)
    soot = lambda: [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("trigger") == "Soot in the Lungs"]  # noqa: E731
    through = lambda: [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("moment") == "move_through"]  # noqa: E731
    zones.on_moved(engine, foe, start, foe.position)  # entering (a CON save against DC 30), and 35 feet through Ash Terrain
    assert len(soot()) == 1 and len(through()) == 1
    zones.on_moved(engine, foe, Position(x=20, y=6), foe.position)  # again this turn: nothing more
    assert len(soot()) == 1 and len(through()) == 1
    assert any(c.condition_id.endswith(".smothered") for c in foe.conditions.values())  # DC 30 fails
    assert zone.active


def test_deferred_entry_is_opt_in_and_does_not_move_the_creature_back():
    """A delayed entry can use its endpoint while ordinary callers still check the live square."""
    engine = _engine()
    _cast(engine, "Ashfall", Position(x=13, y=6))
    foe = engine.state.actors[AN]
    start, endpoint = Position(x=20, y=6), Position(x=13, y=6)
    foe.position = Position(x=20, y=5)  # a later effect has already placed it outside
    live = foe.position
    sequence = engine.events[-1].sequence

    zones.on_moved(engine, foe, start, endpoint, forced=True)
    def entries():
        return [e for e in engine.events if e.sequence > sequence
                and e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("moment") == "enter"]

    assert not entries(), "omitted entry_at must retain the existing live-position check"
    zones.on_moved(engine, foe, start, endpoint, forced=True, entry_at=endpoint)
    assert len(entries()) == 1, "the delayed segment still entered the area"
    assert foe.position == live, "processing entry must not undo the later placement"
    zones.on_moved(engine, foe, start, endpoint, forced=True, entry_at=endpoint)
    assert len(entries()) == 1, "the normal once-per-turn entry guard still applies"


def test_the_zone_event_carries_the_whole_zone_for_the_replay():
    from combat.gate2_runtime_models import ZoneState

    engine = _engine()
    _cast(engine, "Ashfall", Position(x=13, y=6))
    created = [e for e in engine.events if e.event_type == "ZONE_CREATED"]
    assert ZoneState.model_validate(created[-1].payload["zone"]).trigger_profile["kind"] == "TYPED"


def test_heavy_obscurement_hides_what_is_inside():
    engine = _engine()
    _cast(engine, "Ashfall", Position(x=13, y=6))
    [zone] = zones.typed_zones(engine)
    zone.trigger_profile["obscured"] = "heavy"
    me, foe = engine.state.actors[OWNER], engine.state.actors[AN]
    assert zones.attack_mode(engine, me, foe) == "DISADVANTAGE"  # the foe stands in the smoke
    assert zones.attack_mode(engine, foe, me) == "ADVANTAGE"  # it attacks out of it
    me.position = Position(x=12, y=6)
    assert zones.attack_mode(engine, me, foe) is None  # both inside


def test_ash_terrain_costs_a_foe_double_movement():
    engine = _engine()
    _cast(engine, "Ashfall", Position(x=13, y=6))
    foe = engine.state.actors[AN]
    engine.state.current_actor_id = AN
    foe.movement_remaining_ft = 30
    reach = {(c.destination.x, c.destination.y): c.movement_cost_ft for c in engine._movement_candidates(foe)}
    assert reach[(14, 7)] == 10 and (14, 9) not in reach or reach.get((14, 9), 0) > 15  # inside the ash every square costs 10 ft


def test_terrain_can_be_laid_where_no_foe_stands_but_the_ai_is_not_offered_it():
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary

    engine = _engine()
    engine.state.current_slot_index = engine.state.initiative_order.index(OWNER)
    engine.state.current_actor_id = OWNER
    engine._system_start_turn()
    empty = [c for c in engine.legal_candidates() if c.display_name.startswith("Ashfall at 4,") and c.metadata.get("empty_area")]
    assert empty  # beside the caster, no foe near
    policy, _ = PolicyLibrary(ROOT).for_actor(OWNER)
    ai = build_decision_context(engine, policy, for_ai=True)
    assert not [c for c in ai.legal_candidates if c.metadata.get("empty_area")]


def test_ai_zone_prediction_indexes_a_long_event_history_once_for_three_zones():
    engine = _engine()
    _cast(engine, "Ashfall", Position(x=13, y=6))
    zone = zones.typed_zones(engine)[0]
    zone.trigger_profile["move_through"] = {"who": "hostile", "min_ft": 10,
                                              "on_fail": [{"type": "damage", "amount": 1}]}
    for suffix in ("second", "third"):
        clone = zone.model_copy(deep=True)
        clone.zone_id = f"{zone.zone_id}:{suffix}"
        engine.state.zones[clone.zone_id] = clone
        engine._append_event("ZONE_CREATED", clone.source_definition_id, actor_id=clone.owner_id,
                             payload={"zone": clone.model_dump(mode="json")})

    class CountedEvents(list):
        iterations = 0

        def __iter__(self):
            for event in super().__iter__():
                self.iterations += 1
                yield event

        def __reversed__(self):
            for event in super().__reversed__():
                self.iterations += 1
                yield event

    noise = engine.events[-1].model_copy(update={"event_type": "UNRELATED_TEST_EVENT"})
    events = CountedEvents([*engine.events, *(noise for _ in range(2000))])
    engine.events = events
    creature = engine.state.actors[AN]
    predict = zones.hazard_test(engine, creature)
    assert predict is not None
    for x in range(8, 38):
        predict(Position(x=x, y=6))

    # One forward index and one backward turn scan, regardless of candidates or zones.
    assert events.iterations <= len(events) * 2


def test_immediate_landing_hazards_exclude_start_only_damage():
    """A safe teleport landing forbids immediate damage, not damage on a later turn."""
    from combat.gate2_runtime_models import ZoneState

    engine = _engine()
    creature = engine.state.actors[AN]
    landing = Position(x=18, y=6)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Ashfall')
    zone = ZoneState(zone_id='test:start-only', source_definition_id=source, owner_id=OWNER,
                     center=landing, radius_cells=0, affected_cells=(landing,),
                     concentration_link=False, created_round=engine.state.round_number,
                     trigger_profile={'kind': 'TYPED', 'shape': 'circle', 'name': 'Later damage',
                                      'triggers': [{'id': 'start', 'name': 'Starting a turn',
                                                    'on': ['start'], 'who': 'any',
                                                    'effects': [{'type': 'damage', 'flat': 1,
                                                                 'damage_types': ['force']}]}]})
    engine.state.zones[zone.zone_id] = zone
    before = engine.state.model_dump(mode='json')
    assert zones.hazard_test(engine, creature, movement_mode='teleport')(landing)
    immediate = zones.hazard_test(engine, creature, movement_mode='teleport', immediate_only=True)
    assert immediate is None or not immediate(landing)
    assert engine.state.model_dump(mode='json') == before
    zone.trigger_profile['triggers'][0]['on'] = ['enter']
    assert zones.hazard_test(engine, creature, movement_mode='teleport', immediate_only=True)(landing)


def test_nonwalking_hazard_queries_keep_line_crossing_and_execution_damage():
    from combat.gate2_runtime_models import ZoneState

    engine = _engine()
    creature = engine.state.actors[AN]
    start, landing = creature.position, Position(x=18, y=6)
    # Execution needs the creating action, as a real persisted zone does.
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == OWNER and a.display_name == 'Ashfall')
    zone = ZoneState(zone_id='test:damage-line', source_definition_id=source, owner_id=OWNER,
                     center=Position(x=16, y=0), radius_cells=0,
                     affected_cells=tuple(Position(x=16, y=y) for y in range(13)),
                     concentration_link=False, created_round=engine.state.round_number,
                     trigger_profile={'kind': 'TYPED', 'shape': 'line', 'name': 'Damaging line',
                                      'triggers': [{'id': 'cross', 'name': 'Crossing the line',
                                                    'on': ['cross'], 'who': 'any',
                                                    'effects': [{'type': 'damage', 'flat': 1,
                                                                 'damage_types': ['force']}]}]})
    engine.state.zones[zone.zone_id] = zone
    before = engine.state.model_dump(mode='json')
    for mode in ('walking', 'teleport', 'forced'):
        hazard = zones.hazard_test(engine, creature, movement_mode=mode)
        assert hazard(landing)
        assert not hazard(Position(x=15, y=6))
    assert engine.state.model_dump(mode='json') == before, 'prediction must stay pure'
    hp = creature.current_hp
    creature.position = landing
    zones.on_moved(engine, creature, start, landing, forced=True)
    assert creature.current_hp == hp - 1, 'forced/teleport execution still resolves applicable crossing effects'


def _zone_specs(sphere: str, talents: list[str]) -> dict[str, dict]:
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": talents}}
    catalog = compile_character(sheet, actor_id=OWNER)["action_catalog"]
    rows = catalog.values() if isinstance(catalog, dict) else catalog
    rows = [row if isinstance(row, dict) else row.model_dump() for row in rows]
    return {row["display_name"]: row["parameters"]["typed"]["zone_spec"] for row in rows
            if (row.get("parameters") or {}).get("typed", {}).get("zone_spec")}


def test_a_strike_that_breaks_the_ground_leaves_a_crater_for_the_scene():
    # Owner 2026-09-27: "cracked earth or other difficult terrain". Falling Star is instant; "The impact area becomes
    # difficult terrain until cleared".
    spec = _zone_specs("tianxia.sphere.stars", ["STARS_TAL_FALLING_STAR"])["Falling Star"]
    assert spec["visual"]["material"] == "crater" and spec["difficult"] == "all" and spec["duration"]["kind"] == "scene"
    assert zones._duration_rounds(spec["duration"]) is None  # the whole fight


def test_a_talent_that_thickens_an_area_makes_it_difficult_terrain_but_one_creatures_penalty_does_not():
    dark = _zone_specs("tianxia.sphere.dark", ["DARK_BASE_DARKNESS", "TAL_DARK_THICK_DARKNESS"])["Darkness"]
    assert dark["difficult"] == "all" and dark["modified_by"] == ["Thick Darkness"]  # "Your Darkness becomes difficult terrain"
    smoke = _zone_specs("tianxia.sphere.smoke", ["SMOKE_BASE_SMOKE_VEIL", "TAL_SMOKE_SOOT_EATS_THE_PATH"])["Smoke Veil"]
    assert "modified_by" not in smoke  # "The creature treats the smoke as difficult terrain until the end of the current turn"


def test_a_domains_printed_start_of_turn_save_becomes_its_trigger():
    """Fight audit 2026-09-29: "When an enemy starts its turn inside the Domain, it makes a Constitution saving throw" was
    in the printed text but not the typing's evidence, so 24 domains and fields had an area but no start-of-turn save."""
    import json

    from combat.factory_compiler import TYPED_AUTHORITY

    mechanics = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
    key = next(k for k, m in mechanics.items() if m["name"] == "Court of the Ninth Grave")
    bundle = compile_character({**SHEET, "spheres_and_talents": {"sphere_record_ids": [mechanics[key]["sphere_id"]],
                                                                 "learned_talent_record_ids": [key]}}, actor_id="actor:factory.domain")
    spec = next((a["parameters"]["typed"].get("zone_spec") for a in bundle["action_catalog"] if key in a["source_definition_id"]), None)
    starts = [row for row in (spec or {}).get("triggers") or [] if "start" in row["on"]]
    assert starts and starts[0]["who"] == "hostile" and any(e["type"] == "save" for e in starts[0]["effects"])
