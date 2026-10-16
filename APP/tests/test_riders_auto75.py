"""AUTO75 (Ash sphere automation): every printed effect this lane moved off the GM's list runs at the table.

AUTO75f1 (review fixes): the turn-start damage is delivered through the ordinary typed path (the
prisoner's own reactions, the printed choice of damage type, the printed anchor, and the caster's
damage riders), the Court's Temporary HP denial follows the area, Rolling Ashfall offers every square
its printed reach allows, and the reminders the table still cannot run say so accurately.

Overrides: authority/typed_mechanics/reviewed_final.d (the Ash rows of review_sw-air.json,
riders_lane1.json, friendly_fire_effect_scopes.json and the new zz_ash_automation.json records),
plug-in combat/ext/ash_talents.py (``periodic_damage_state``, ``move_typed_area``, the
``damage_reduction_bonus`` and ``choice_map_pick`` hooks). The tests drive the real compiled Ash
character through the real engine; nothing here patches a core class.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from combat import ext, typed_reactions, zones
from combat.typed_executor import stored_healing_reductions
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision

sys.path.insert(0, str(Path(__file__).resolve().parent))
c13 = importlib.import_module("test_riders_c13")

ASH = "tianxia.sphere.ash"
MONKEY = "tianxia.sphere.monkey_style"
ME, AN = c13.ME, c13.AN
ROOT = Path(__file__).resolve().parents[1]
STATE = "condition:typed.periodic_damage_state."
RESTRAINED = "condition:typed.restrained"
ZONE_EFFECT = "condition:typed.zone_effect"


def _authority():
    return json.loads(Path(c13.compiler.TYPED_AUTHORITY).read_text(encoding="utf-8"))["mechanics"]


def _doomed(foe):
    foe.saving_throws = {name: -20 for name in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    return foe


def _first(engine, name, **kw):
    return c13._use(engine, name, **kw)


def _state(foe, name):
    return [row for row in foe.conditions.values() if row.condition_id == STATE + name]


def _bury(engine, name, talent):
    _doomed(engine.state.actors[AN])
    _first(engine, talent)
    assert _state(engine.state.actors[AN], name), sorted(r.condition_id for r in engine.state.actors[AN].conditions.values())
    return engine.state.actors[AN]


def _eager(engine):
    """Answer every Reaction the table offers with its first option (the printed reading, no AI preference)."""
    def provider(request):
        options = tuple(request["legal_option_ids"])
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="USE" if options else "DECLINE", option_ids=options), None

    engine.set_reaction_provider(provider)
    return provider


# ---------------------------------------------------------------------------- Ashen Burial: printed turn-start damage
def test_ashen_burial_damages_the_restrained_creature_at_the_start_of_each_of_its_turns():
    """"Failed Save: Restrained by accumulated ash. At the start of each of its turns, take 2d8 Fire, Necrotic, or Psychic
    damage." -- real damage at the creature's turn start (it used to be a GM reminder), and it ends with the effect."""
    engine, me, foe = c13._fight(ASH, ["ASH_TAL_ASHEN_BURIAL"], cl=17)
    _doomed(foe)
    _first(engine, "Ashen Burial")
    assert any(row.condition_id == RESTRAINED for row in foe.conditions.values())
    assert _state(foe, "ashen_burial_damage")
    hp = foe.current_hp
    before = len(engine.events)
    ext.run("turn_start", engine, foe)
    assert 2 <= hp - foe.current_hp <= 16, hp - foe.current_hp
    assert not [e for e in engine.events[before:] if e.event_type == "GM_RIDER"]
    assert [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED"]


def test_cremation_prison_deals_its_fire_and_necrotic_damage_at_the_start_of_each_turn():
    """"take 2d8 Fire damage and 2d8 Necrotic damage at the start of each turn" -- two real damage packets."""
    engine, me, foe = c13._fight(ASH, ["ASH_TAL_CREMATION_PRISON"], cl=17)
    _doomed(foe)
    _first(engine, "Cremation Prison")
    assert _state(foe, "cremation_prison_damage")
    hp = foe.current_hp
    before = len(engine.events)
    ext.run("turn_start", engine, foe)
    committed = [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED"]
    assert len(committed) == 2 and {e.payload["damage_type"] for e in committed} == {"FIRE", "NECROTIC"}
    assert 4 <= hp - foe.current_hp <= 32
    assert not [e for e in engine.events[before:] if e.event_type == "GM_RIDER"]


def test_ashen_burial_damage_ends_with_the_repeat_saving_throw_that_ends_the_effect():
    """"Repeat the saving throw at the end of each turn, ending the effect on a success." """
    engine, me, foe = c13._fight(ASH, ["ASH_TAL_ASHEN_BURIAL"], cl=17)
    _doomed(foe)
    _first(engine, "Ashen Burial")
    assert _state(foe, "ashen_burial_damage")
    foe.saving_throws = {name: 30 for name in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}  # the repeat save succeeds
    engine._expire_typed_for_checkpoint("END_OF_TURN", foe.entity_id)
    ext.run("turn_end", engine, foe)   # the group that owns the repeat save collects its recorded companions
    assert not [row for row in foe.conditions.values() if row.condition_id.startswith(STATE)]
    hp = foe.current_hp
    ext.run("turn_start", engine, foe)
    assert foe.current_hp == hp


# ------------------------------------------------------------------- AUTO75f1: the damage is delivered like any other
def _prisoned_victim():
    """A hostile creature buried by Ashen Burial that owns its own "when you take damage" reaction
    (Peach-Thief Escape, the sphere's only "You take damage" reaction), so the table can answer it."""
    from combat.gate4_engine import Gate4ControllerEngine

    burial = c13._bundle(ASH, ["ASH_TAL_ASHEN_BURIAL"], cl=17)
    thief = c13.t._bundle(MONKEY, ["TAL_MONKEY_STYLE_PEACH_THIEF_ESCAPE"], {"starting_kit": {"items": []}},
                          cl=17, actor_id="actor:factory.thief")
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO75f1", typed_bundles=(burial, thief),
                                   roster_setup={"primary_actor_ids": [ME, "actor:factory.thief"],
                                                 "team_by_actor": {ME: "team:a", "actor:factory.thief": "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6},
                                                                         "actor:factory.thief": {"x": 5, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine, engine.state.actors[ME], engine.state.actors["actor:factory.thief"]


def test_the_turn_start_damage_lets_the_prisoners_own_reactions_answer_it():
    """AUTO75f1 finding 1: the new turn-start damage used to commit with no intent, so nothing that answers
    damage ever saw it. "A creature takes damage" is answered here exactly as it is by a spell."""
    engine, me, victim = _prisoned_victim()
    _doomed(victim)
    _eager(engine)
    me.action_available = me.bonus_action_available = me.reaction_available = True
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and c.display_name == "Ashen Burial")
    engine.execute_intent(ActionIntent(intent_id="a75-bury", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids, option_ids=candidate.option_ids))
    victim.reaction_available = True
    before = len(engine.events)
    ext.run("turn_start", engine, victim)
    assert [e for e in engine.events[before:]
            if e.event_type == "REACTION_RESOLVED"
            and e.source_definition_id == "TAL_MONKEY_STYLE_PEACH_THIEF_ESCAPE"
            and e.payload["checkpoint"] == "DAMAGE_APPLICATION"]


@pytest.mark.parametrize("modifier,expected", [(("damage_resistance", "FIRE"), "NECROTIC"),
                                               (("damage_resistance", "FIRE"), "PSYCHIC"),
                                               (None, None)])
def test_the_turn_start_damage_picks_the_listed_damage_type_that_lands_hardest(modifier, expected):
    """AUTO75f1 finding 4: "2d8 Fire, Necrotic, or Psychic damage" is a choice of type, not always the first
    name in the list. A Fire-immune creature gets Necrotic; one that is also weak to Psychic gets Psychic."""
    engine, me, foe = c13._fight(ASH, ["ASH_TAL_ASHEN_BURIAL"], cl=17)
    if modifier and expected == "NECROTIC":
        engine._add_modifier(foe, "test:resist", modifier[0], "SET", modifier[1], "TEST", expires_on="UNTIL_REMOVED")
    elif modifier:
        engine._add_modifier(foe, "test:resist", "damage_resistance", "SET", "FIRE", "TEST", expires_on="UNTIL_REMOVED")
        engine._add_modifier(foe, "test:weak", "damage_vulnerability", "SET", "PSYCHIC", "TEST", expires_on="UNTIL_REMOVED")
    _bury(engine, "ashen_burial_damage", "Ashen Burial")
    before = len(engine.events)
    ext.run("turn_start", engine, foe)
    committed = [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED"]
    assert len(committed) == 1
    if expected:
        assert committed[0].payload["damage_type"] == expected, committed[0].payload
    else:
        assert committed[0].payload["damage_type"] in {"FIRE", "NECROTIC", "PSYCHIC"}


def test_the_turn_start_damage_needs_the_printed_condition_it_hangs_on():
    """AUTO75f1 finding 4: "Restrained by accumulated ash. At the start of each of its turns, take ..." -- the
    damage belongs to that state, so a creature that is no longer Restrained (or never became so) takes none."""
    engine, me, foe = c13._fight(ASH, ["ASH_TAL_ASHEN_BURIAL"], cl=17)
    foe = _bury(engine, "ashen_burial_damage", "Ashen Burial")
    for instance, row in list(foe.conditions.items()):
        if row.condition_id == RESTRAINED:
            del foe.conditions[instance]
    before = len(engine.events)
    ext.run("turn_start", engine, foe)
    assert not [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED"]
    assert foe.current_hp > 0


def test_a_prisoner_killed_by_the_turn_start_damage_still_triggers_the_casters_drop_to_zero_rider():
    """AUTO75f1 finding 1: the damage-dealt riders downstream of a packet run for this damage too
    ("A creature within 60 feet drops to 0 HP" -- Ashes of the Fallen grants its Remnant)."""
    engine, me, foe = c13._fight(ASH, ["ASH_TAL_ASHEN_BURIAL", "tianxia.talent.ash.ashes_of_the_fallen"], cl=17, foe_hp=8)
    _bury(engine, "ashen_burial_damage", "Ashen Burial")
    _eager(engine)
    me.reaction_available = True
    before = len(engine.events)
    ext.run("turn_start", engine, foe)
    assert not foe.active
    assert [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED" and e.payload["hp_damage"] > 0]
    assert [e for e in engine.events[before:] if e.event_type == "REACTION_RESOLVED"
            and e.source_definition_id == "tianxia.talent.ash.ashes_of_the_fallen"
            and e.payload["checkpoint"] == "ANY_DROP_TO_ZERO"]
    assert me.resources["resource:named.remnant"] == 1


def test_ashen_burial_and_cremation_prison_leave_no_gm_reminder_and_are_full():
    for mechanic in ("ASH_TAL_ASHEN_BURIAL", "ASH_TAL_CREMATION_PRISON"):
        record = _authority()[mechanic]
        assert record["riders"] == [], record["riders"]
        assert record["coverage"] == "FULL"


def test_the_turn_start_damage_state_survives_a_table_commit_and_reload(tmp_path):
    """AUTO75f1 finding 7: the stored state holds only printed numbers and names, so a committed fight
    reopens with the same pending turn-start damage."""
    # A save DC of 30 is out of a d20's reach, so the prisoner is Restrained whatever it rolls. Nothing is
    # poked into the live engine here: the journal is the whole truth a reload replays.
    persistence, session = c13._persisted(tmp_path, c13._bundle(ASH, ["ASH_TAL_ASHEN_BURIAL"], cl=17, dc=30), "AUTO75f1-state")
    _submit(session, "Ashen Burial")
    loaded = persistence.load_match(session.match_id).engine
    foe = loaded.state.actors[AN]
    assert _state(foe, "ashen_burial_damage"), sorted(r.condition_id for r in foe.conditions.values())
    row = _state(foe, "ashen_burial_damage")[0]
    assert row.expires_on == "CONCENTRATION_END"
    assert row.data["requires_condition"] == "restrained"
    assert [r["damage_types"] for r in row.data["rows"]] == [["fire", "necrotic", "psychic"]]
    assert all(isinstance(value, int) for r in row.data["rows"] for value in r["dice"].values() if value is not None)
    before = len(loaded.events)
    ext.run("turn_start", loaded, foe)
    assert [e for e in loaded.events[before:] if e.event_type == "DAMAGE_COMMITTED"]


def _submit(session, name, target=AN):
    c13._submit(session, name, target)


# ---------------------------------------------------------------------------- Court of the Last Ember
@pytest.mark.parametrize("option,condition", [("Smothered", "condition:typed.smothered"),
                                              ("No Reactions", "condition:typed.reaction_denied")])
def test_court_of_the_last_ember_saves_when_an_enemy_starts_its_turn_inside_not_when_it_is_made(tmp_path, option, condition):
    """Use real turn-boundary choice transport; a direct zone call auto-picks."""
    from tests.auto_worker1_support import fight, act, reload, settle, RIGHT
    combat, table, mid = fight(tmp_path, ["tianxia.talent.ash.court_of_the_last_ember"], cl=17)
    settle(lambda answers: act(table, mid, "Court of the Last Ember", answers))
    engine = reload(combat, mid)
    assert not [e for e in engine.events if e.event_type == "SAVE_ROLLED"]
    assert not any(r.condition_id == condition for r in engine.state.actors[RIGHT].conditions.values())
    before = len(engine.events)
    settle(lambda answers: act(table, mid, "end", answers),
           lambda _: ["smothered" if option == "Smothered" else "reactions"])
    engine = reload(combat, mid)
    assert [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED"]
    assert any(r.condition_id == condition for r in engine.state.actors[RIGHT].conditions.values())


def test_court_of_the_last_ember_damages_an_enemy_that_fails_its_start_of_turn_save():
    """Failed Save: take 2d8 Fire, Necrotic, or Psychic damage (the Elemental Damage option)."""
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.court_of_the_last_ember"], cl=17, foe_at=(4, 7))
    _doomed(foe)
    _first(engine, "Court of the Last Ember", contains=True, target=None)
    hp = foe.current_hp
    before = len(engine.events)
    zones.on_turn_start(engine, foe)
    committed = [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED"]
    assert len(committed) == 1 and 2 <= hp - foe.current_hp <= 16
    assert committed[0].payload["damage_type"] in {"FIRE", "NECROTIC", "PSYCHIC"}
    assert not [e for e in engine.events[before:] if e.event_type == "GM_RIDER"]


def test_court_of_the_last_ember_reduces_healing_by_the_proficiency_bonus_after_a_successful_save():
    """Successful Save: Healing received is reduced by your Proficiency Bonus until the start of its next turn."""
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.court_of_the_last_ember"], cl=17, foe_at=(4, 7))
    foe.saving_throws = {name: 30 for name in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    _first(engine, "Court of the Last Ember", contains=True, target=None)
    before = len(engine.events)
    zones.on_turn_start(engine, foe)
    assert [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED"]
    assert not [e for e in engine.events[before:] if e.event_type == "DAMAGE_COMMITTED"]
    assert [(m.target_field, m.value) for m in foe.modifiers.values()] == \
        [("healing_reduction", f"minus:{me.proficiency_bonus}")]
    assert stored_healing_reductions(engine, foe, 10) == 10 - me.proficiency_bonus


def _court(foe_at=(4, 7)):
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.court_of_the_last_ember"], cl=17, foe_at=foe_at)
    _first(engine, "Court of the Last Ember", contains=True, target=None)
    return engine, me, foe


def _temp_hp_refused(engine, foe):
    """Try to give the foe 5 Temporary HP: True when the Court refused and said so."""
    foe.temporary_hp = 0
    before = len(engine.events)
    engine._grant_temp_hp(foe, 5, "test:tempo", AN)
    return (foe.temporary_hp == 0
            and [e for e in engine.events[before:] if e.event_type == "PASSIVE_TRIGGERED"])


def test_court_of_the_last_ember_denies_temporary_hit_points_to_the_enemies_inside_it():
    """"Enemies: cannot gain Temporary HP" -- while they stand in the Court."""
    engine, me, foe = _court()
    assert _temp_hp_refused(engine, foe)


def test_the_temporary_hp_denial_ends_when_an_enemy_leaves_the_court_and_returns_with_it():
    engine, me, foe = _court()
    start = foe.position
    foe.position = Position(x=15, y=11)
    zones.on_moved(engine, foe, start, foe.position)
    assert not [row for row in foe.conditions.values() if row.condition_id == ZONE_EFFECT]
    assert not _temp_hp_refused(engine, foe)
    assert foe.temporary_hp == 5
    start = foe.position
    foe.position = Position(x=4, y=7)
    zones.on_moved(engine, foe, start, foe.position)
    assert _temp_hp_refused(engine, foe)


def test_the_temporary_hp_denial_follows_the_area_when_it_is_moved_and_ends_with_concentration():
    engine, me, foe = _court()
    zone = next(z for z in zones.typed_zones(engine) if "court_of_the_last_ember" in z.source_definition_id)
    zone.center = Position(x=15, y=11)
    zone.affected_cells = zones._cells(engine, zone.center, {"size_ft": zone.trigger_profile.get("size_ft"),
                                                             "shape": zone.trigger_profile.get("shape"),
                                                             "spreads": zone.trigger_profile.get("spreads")})
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=me.entity_id,
                         payload={"zone": zone.model_dump(mode="json")})
    zones.sync_inside(engine, zone.source_definition_id)
    assert not _temp_hp_refused(engine, foe)          # the enemy is no longer in the ash
    zone.center = Position(x=3, y=6)
    zone.affected_cells = zones._cells(engine, zone.center, {"size_ft": zone.trigger_profile.get("size_ft"),
                                                             "shape": zone.trigger_profile.get("shape"),
                                                             "spreads": zone.trigger_profile.get("spreads")})
    zones.sync_inside(engine, zone.source_definition_id)
    assert _temp_hp_refused(engine, foe)
    engine._end_concentration(me, "TEST")
    assert not _temp_hp_refused(engine, foe)


def test_court_reviewed_rules_are_continuous_and_choices_are_per_failed_save():
    row = _authority()["tianxia.talent.ash.court_of_the_last_ember"]
    assert row["riders"] == [] and row["options"] == []
    assert row["effects"][0]["triggers"][0]["effects"][0]["on_fail"][0]["type"] == "rider_menu"
    assert len(row["effects"][0]["inside"]) == 2


# ---------------------------------------------------------------------------- Heaven-Cremating Ashstorm
def test_heaven_cremating_ashstorm_smothers_a_creature_that_fails_its_save():
    """"Failed Save: Take 12d10 Fire, Necrotic, or Psychic damage and become Smothered until the end of your next turn." """
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.heaven_cremating_ashstorm"], cl=17)
    _doomed(foe)
    events = _first(engine, "Heaven-Cremating Ashstorm")
    assert [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    assert any(row.condition_id == "condition:typed.smothered" for row in foe.conditions.values())
    assert _authority()["tianxia.talent.ash.heaven_cremating_ashstorm"]["riders"] == []


# ---------------------------------------------------------------------------- Rolling Ashfall
def _ashfall(engine, destination=(4, 6)):
    c13._answers(engine, {})
    _first(engine, "Ashfall", target=None, destination=destination)
    return next(z for z in engine.state.zones.values() if z.trigger_profile.get("name") == "Ashfall")


def test_rolling_ashfall_moves_the_area_to_the_square_the_owner_picks_and_says_how_far_it_went():
    """"As a Bonus Action, move one of your Ashfall areas up to 20 feet." """
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.rolling_ashfall"], cl=17)
    zone = _ashfall(engine)
    before = (zone.center.x, zone.center.y)
    before_cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    requested = c13._answers(engine, {"rolling_ashfall": lambda options: [options[-1]]})
    events = _first(engine, "Rolling Ashfall", target=None)
    moved = engine.state.zones[zone.zone_id]
    assert (moved.center.x, moved.center.y) != before
    asked = [r for r in requested if "move_area_to" in r["reaction_source_id"]]
    assert len(asked) == 1
    (question,) = asked
    picked = question["choice_trigger"]["preferred"][0]
    landed = (int(picked.split(":")[1].split(",")[0]), int(picked.split(":")[1].split(",")[1]))
    assert (moved.center.x, moved.center.y) == landed
    assert engine.grid.distance_ft(Position(x=before[0], y=before[1]), moved.center) <= 20
    assert {(cell.x, cell.y) for cell in moved.affected_cells} != before_cells
    assert [e for e in events if e.event_type == "ZONE_CREATED"]
    assert not [e for e in events if e.event_type == "GM_RIDER"]
    assert [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("log")]


def test_rolling_ashfall_offers_every_legal_square_within_twenty_feet():
    """AUTO75f1 finding 3: the printed reach is 20 feet, so every square within 20 feet of the area is offered
    (5, 10, 15 and 20 feet, and off-ray offsets such as two squares across and one down) -- not just the eight
    adjacent ones -- and an area may land on a square something is standing on."""
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.rolling_ashfall"], cl=17, foe_at=(6, 6))
    zone = _ashfall(engine)
    start = (zone.center.x, zone.center.y)      # the zone object is moved in place, so keep where it began
    asked = c13._answers(engine, {})
    _first(engine, "Rolling Ashfall", target=None)
    (question,) = [r for r in asked if r["reaction_source_id"].endswith("move_area_to:rolling_ashfall")]
    options = list(question["legal_option_ids"])
    labels = question["choice_trigger"]["labels"]
    grid = engine.grid
    reach = 20 // grid.square_size_ft
    legal = {(c.x, c.y) for c in grid.cells_in_radius(Position(x=start[0], y=start[1]), reach)
             if (c.x, c.y) != start and 0 <= c.x < grid.width and 0 <= c.y < grid.height}
    offered = {(int(o.split(":")[1].split(",")[0]), int(o.split(":")[1].split(",")[1])) for o in options}
    assert offered == legal, sorted(legal ^ offered)[:5]
    assert (start[0] + 2, start[1] + 1) in offered, "an off-ray offset must be reachable"
    assert (start[0] + 4, start[1]) in offered, "20 feet must be reachable"
    assert {grid.distance_ft(Position(x=start[0], y=start[1]), Position(x=x, y=y)) for x, y in offered} == {5, 10, 15, 20}
    for option in options:
        x, y = int(option.split(":")[1].split(",")[0]), int(option.split(":")[1].split(",")[1])
        feet = grid.distance_ft(Position(x=start[0], y=start[1]), Position(x=x, y=y))
        assert labels[option] == f"Move Ashfall centred on {start[0]},{start[1]} to {x},{y} ({feet} feet)", labels[option]
    assert (foe.position.x, foe.position.y) in offered, "an area moves: nothing standing there refuses it"


def test_rolling_ashfall_is_asked_on_a_players_turn_with_every_legal_square_as_a_button():
    """AUTO75f1 finding 9 / checklist 9: a player is asked, through the same bounded choice transport, and the
    prompt names the ability, what it moves and where; an AI answers by itself."""
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.rolling_ashfall"], cl=17)
    zone = _ashfall(engine)
    seen = []

    def provider(request):
        options = tuple(request["legal_option_ids"])
        picked = options[3:4] if "move_area_to" in request["reaction_source_id"] else options
        if "move_area_to" in request["reaction_source_id"]:
            seen.append((request, picked[0]))
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="USE" if picked else "DECLINE", option_ids=picked), None

    engine.set_reaction_provider(provider)
    _first(engine, "Rolling Ashfall", target=None)
    (question, picked), = seen
    trigger = question["choice_trigger"]
    assert trigger["name"].startswith("Rolling Ashfall")
    assert trigger["prompt"].startswith("Rolling Ashfall:") and "up to 20 feet" in trigger["prompt"]
    assert f"affecting {me.display_name}" in trigger["prompt"]
    assert question["protected_target_id"] == ME
    assert len(question["legal_option_ids"]) > 8
    # The label names the area that moves by where it stands now, so a caster with two Ashfalls sees which one.
    assert trigger["labels"][picked].startswith("Move Ashfall centred on 4,6 to "), trigger["labels"][picked]
    assert "up to 20 feet" in trigger["prompt"] and "Ashfall centred on 4,6" in trigger["prompt"], trigger["prompt"]
    assert (zone.center.x, zone.center.y) == (int(picked.split(":")[1].split(",")[0]), int(picked.split(":")[1].split(",")[1]))


def test_rolling_ashfall_tells_its_own_areas_apart_by_where_each_one_is():
    """AUTO75r1 finding 2: two Ashfall areas share one printed name, so the "which one moves" menu says where
    each one is and the player picks by location -- the menu is a decision, not a list of identical buttons."""
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.rolling_ashfall"], cl=17)
    c13._answers(engine, {})
    _first(engine, "Ashfall", target=None, destination=(4, 6))
    _first(engine, "Ashfall", target=None, destination=(12, 6))
    areas = sorted((z for z in engine.state.zones.values() if z.trigger_profile.get("name") == "Ashfall"),
                   key=lambda z: z.zone_id)
    assert len(areas) == 2
    before = {z.zone_id: (z.center.x, z.center.y) for z in areas}
    seen = []

    def provider(request):
        source = str(request["reaction_source_id"])
        if not source.startswith("choice:needle."):
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=source, selection="DECLINE", option_ids=()), None
        labels = request["choice_trigger"]["labels"]
        options = list(request["legal_option_ids"])
        if source.endswith("which_area:rolling_ashfall"):
            seen.append((request, labels))
            chosen = [option for option in options if labels[option] == "Ashfall centred on 12,6"]
        else:
            chosen = options[:1]
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=source,
                                selection="USE" if chosen else "DECLINE", option_ids=tuple(chosen)), None

    engine.set_reaction_provider(provider)
    events = _first(engine, "Rolling Ashfall", target=None)
    assert len(seen) == 1
    (question, labels) = seen[0]
    assert set(labels) == {z.zone_id for z in areas}
    assert set(labels.values()) == {"Ashfall centred on 4,6", "Ashfall centred on 12,6"}, labels
    assert len(set(labels.values())) == len(areas), "two areas of one kind must be told apart by location"
    for option, text in labels.items():   # every button says where its own area is
        assert text == f"Ashfall centred on {before[option][0]},{before[option][1]}", text
    moved = next(z for z in areas if labels[z.zone_id] == "Ashfall centred on 12,6")
    left = next(z for z in areas if z.zone_id != moved.zone_id)
    after = engine.state.zones[moved.zone_id]
    assert (after.center.x, after.center.y) != before[moved.zone_id]
    assert engine.grid.distance_ft(Position(x=12, y=6), after.center) <= 20, "the area chosen by location is the one that moved"
    assert (engine.state.zones[left.zone_id].center.x, engine.state.zones[left.zone_id].center.y) == before[left.zone_id]
    said = [e.payload["log"] for e in events if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("log")]
    assert said and said[0].startswith(f"{me.display_name} moves Ashfall from 12,6 to "), said


def test_rolling_ashfall_says_so_when_there_is_no_ashfall_area_to_move():
    """"you have no area of that kind to move" is the whole answer when the caster owns none."""
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.rolling_ashfall"], cl=17)
    c13._answers(engine, {})
    before = len(engine.events)
    _first(engine, "Rolling Ashfall", target=None)
    lines = [e.payload["rider"] for e in engine.events[before:] if e.event_type == "GM_RIDER"]
    assert len(lines) == 1 and "no area of that kind to move" in lines[0], lines
    assert _authority()["tianxia.talent.ash.rolling_ashfall"]["riders"] == []
    names = {row["display_name"] for row in c13._bundle(ASH, ["tianxia.talent.ash.rolling_ashfall"], cl=17)["action_catalog"]}
    assert "Rolling Ashfall" in names


def test_a_moved_ashfall_area_survives_a_table_commit_and_reload(tmp_path):
    persistence, session = c13._persisted(tmp_path, c13._bundle(ASH, ["tianxia.talent.ash.rolling_ashfall"], cl=17), "AUTO75f1-ashfall")
    c13._answers(session.engine, {})
    _submit(session, "Ashfall at 4,6", target=None)
    zone = next(z for z in session.engine.state.zones.values() if z.trigger_profile.get("name") == "Ashfall")
    asked = c13._answers(session.engine, {"move_area_to:rolling_ashfall": lambda options: [options[-1]]})
    session.engine.set_reaction_provider(session.engine._gate4_reaction_provider)
    _submit(session, "Rolling Ashfall", target=None)
    landed = (session.engine.state.zones[zone.zone_id].center.x, session.engine.state.zones[zone.zone_id].center.y)
    assert landed != (4, 6)
    loaded = persistence.load_match(session.match_id).engine
    kept = loaded.state.zones[zone.zone_id]
    assert (kept.center.x, kept.center.y) == landed
    assert [(c.x, c.y) for c in kept.affected_cells] == [(c.x, c.y) for c in session.engine.state.zones[zone.zone_id].affected_cells]


def _declining():
    """A table that answers every question with "Leave it here": the transport's own decline."""
    def provider(request):
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="DECLINE", option_ids=()), None
    return provider


def test_the_advertised_leave_it_here_leaves_the_ashfall_area_exactly_where_it_is():
    """AUTO75r1 finding 1: the destination picker says "press Esc to leave it where it is", so declining it
    must leave the area alone -- not drop it on the first square offered (ash_talents.py used cells[0])."""
    from combat import choice_presentation

    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.rolling_ashfall"], cl=17)
    zone = _ashfall(engine)
    before = (zone.center.x, zone.center.y)
    before_cells = [(cell.x, cell.y) for cell in zone.affected_cells]
    asked = c13._answers(engine, {"move_area_to:rolling_ashfall": lambda options: None})
    events = _first(engine, "Rolling Ashfall", target=None)
    (question,) = [r for r in asked if r["reaction_source_id"].endswith("move_area_to:rolling_ashfall")]
    # The way out has to be one the transport accepts: the client only enables Esc when allow_decline is true
    # (static/tabletop/tabletop.js mapPickChoice/cancelMapPick, and askChoice's hidden decline button), and
    # choice_checkpoints.validate rejects a decline the choice did not offer.
    assert question["extension_choice"]["allow_decline"] is True
    kept = engine.state.zones[zone.zone_id]
    assert (kept.center.x, kept.center.y) == before, "declining the destination must not move the area"
    assert [(cell.x, cell.y) for cell in kept.affected_cells] == before_cells
    assert not [e for e in events if e.event_type == "ZONE_CREATED"], "a cancelled move publishes nothing"
    lines = [e.payload["rider"] for e in events if e.event_type == "GM_RIDER"]
    assert len(lines) == 1 and f"leave Ashfall centred on {before[0]},{before[1]} where it is" in lines[0], lines
    # The same question published for the table, exactly as TabletopService._reaction_prompt publishes it
    # (tabletop_service.py:1125): a map choice whose way out the client will act on.
    trigger = question["choice_trigger"]
    published = choice_presentation.space_choice(
        {"title": "Rolling Ashfall", "reaction": trigger["name"],
         "choice": {"options": [{"id": option} for option in question["legal_option_ids"]],
                    "minimum": 1, "maximum": 1,
                    "allow_decline": question["extension_choice"]["allow_decline"],
                    "space_positions": trigger.get("space_positions")}},
        {"reactor_id": me.entity_id, "reaction_source_id": question["reaction_source_id"], "choice_trigger": trigger},
        engine)
    picker = published["choice"].get("map_pick")
    assert picker and picker["cancel_label"] == "Leave it here", picker
    assert "Esc" in picker["instruction"] and published["choice"]["allow_decline"] is True
    assert len(published["choice"]["options"]) == len(question["legal_option_ids"])


def test_declining_which_ashfall_area_moves_leaves_both_where_they_are():
    """The first of the two questions is a way out too: a caster with two areas can back out of the move."""
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.rolling_ashfall"], cl=17)
    c13._answers(engine, {})
    _first(engine, "Ashfall", target=None, destination=(4, 6))
    _first(engine, "Ashfall", target=None, destination=(12, 6))
    areas = sorted((z for z in engine.state.zones.values() if z.trigger_profile.get("name") == "Ashfall"),
                   key=lambda z: z.zone_id)
    before = {z.zone_id: (z.center.x, z.center.y) for z in areas}
    asked = c13._answers(engine, {"move_area_to:which_area:rolling_ashfall": lambda options: None})
    events = _first(engine, "Rolling Ashfall", target=None)
    (which,) = [r for r in asked if r["reaction_source_id"].endswith("which_area:rolling_ashfall")]
    assert which["extension_choice"]["allow_decline"] is True
    assert [r for r in asked if r["reaction_source_id"].endswith("move_area_to:rolling_ashfall")] == [], (
        "a caster who backs out of the first question is not asked for a square")
    assert {z.zone_id: (engine.state.zones[z.zone_id].center.x, engine.state.zones[z.zone_id].center.y)
            for z in areas} == before
    assert not [e for e in events if e.event_type == "ZONE_CREATED"]
    lines = [e.payload["rider"] for e in events if e.event_type == "GM_RIDER"]
    assert len(lines) == 1 and "leave your Ashfall areas where they are" in lines[0], lines


def test_a_cancelled_ashfall_move_commits_and_reloads_with_the_area_where_it_was(tmp_path):
    """AUTO75r1 finding 1: the cancellation is a real committed answer, not an abandoned prompt -- the
    controller journal closes its transaction and the area reloads where it was."""
    persistence, session = c13._persisted(tmp_path, c13._bundle(ASH, ["tianxia.talent.ash.rolling_ashfall"], cl=17),
                                          "AUTO75r1-ashfall-cancel")
    c13._answers(session.engine, {})
    _submit(session, "Ashfall at 4,6", target=None)
    zone = next(z for z in session.engine.state.zones.values() if z.trigger_profile.get("name") == "Ashfall")
    before = (zone.center.x, zone.center.y)
    before_cells = [(cell.x, cell.y) for cell in zone.affected_cells]
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.display_name == "Rolling Ashfall" and c.actor_id == ME)
    session.submit_intent(ActionIntent(intent_id=f"i-cancel-{candidate.state_version}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination),
                          primary_decision_record=None, reaction_provider=_declining())
    assert session.verify()["controller_open_transactions"] == []
    kept = session.engine.state.zones[zone.zone_id]
    assert (kept.center.x, kept.center.y) == before
    assert [(cell.x, cell.y) for cell in kept.affected_cells] == before_cells
    reloaded = persistence.load_match(session.match_id).engine.state.zones[zone.zone_id]
    assert (reloaded.center.x, reloaded.center.y) == before
    assert [(cell.x, cell.y) for cell in reloaded.affected_cells] == before_cells


# ---------------------------------------------------------------------------- Ash Ward
def _hit(engine, target_id=ME, flat=20, tag="a"):
    """A real unarmed hit on ``target_id`` from the foe, so the printed reaction path runs."""
    import importlib

    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    action = ActionDefinition(source_definition_id=f"action:auto75.{tag}", display_name="Ash Ward probe", owner_id=AN,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=500,
                              parameters={"typed": {"effects": [{"type": "attack", "attack_kind": "unarmed", "on_hit": [
                                  {"type": "damage", "applies_to": "target", "flat": flat, "damage_types": ["bludgeoning"]}],
                                  "on_miss": []}],
                                  "numbers": {"pb": 4, "save_dc": 16, "attack_bonus": 100, "cl": 17, "key_mod": 3},
                                  "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[action.source_definition_id] = action
    engine.state.actors[AN].action_ids = (action.source_definition_id,)
    engine.state.actors[AN].action_available = True
    before = len(engine.events)
    importlib.import_module("test_reaction_effects_r6")._use(engine, AN, action, target_id)
    return engine.events[before:]


def test_ash_ward_reduces_the_triggering_damage_and_adds_your_proficiency_bonus_in_ash_terrain():
    """"Reduce the triggering damage: 1d8 + Path key ability modifier ... If the protected creature stands inside Ash
    Terrain, Smoke, or a Fire effect, add your Proficiency Bonus to the reduction." """
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.ash_ward"], cl=17, foe_at=(4, 7))
    _eager(engine)
    plain_hp = me.current_hp
    plain = _hit(engine, tag="plain")
    assert [e for e in plain if e.event_type == "REACTION_RESOLVED"]
    taken_plain = plain_hp - me.current_hp

    _first(engine, "Ashfall", target=None, destination=(4, 6))
    me.position = type(me.position)(x=4, y=6)
    _eager(engine)
    ash_hp = me.current_hp
    in_ash = _hit(engine, tag="ash")
    taken_ash = ash_hp - me.current_hp
    assert taken_ash < taken_plain, (taken_plain, taken_ash)
    assert _authority()["tianxia.talent.ash.ash_ward"]["riders"] == []


def test_ash_ward_is_inert_for_a_reaction_that_is_not_its_own():
    from combat.ext import ash_talents

    engine, me, foe = c13._fight(ASH, [], cl=17, foe_at=(4, 7))
    _first(engine, "Ashfall", target=None, destination=(4, 6))
    me.position = type(me.position)(x=4, y=6)
    assert ash_talents.ward_terrain_bonus(engine, me, me, foe, {"feature_id": "TAL_SOME_OTHER_WARD"}) is None


# ---------------------------------------------------------------------------- retired rider lines
def test_the_lines_the_table_already_runs_are_no_longer_shown_to_the_gm():
    for mechanic in ("ASH_BASE_CINDER_BRAND", "ASH_TAL_CINDER_BURST", "tianxia.talent.ash.ashen_wasteland"):
        record = _authority()[mechanic]
        assert record["riders"] == [], (mechanic, record["riders"])
        assert record["coverage"] == "FULL"


def test_cinder_burst_halves_its_damage_on_a_successful_save():
    """"Successful Save: Take half damage." """
    engine, me, foe = c13._fight(ASH, ["ASH_TAL_CINDER_BURST"], cl=17)
    foe.saving_throws = {name: 30 for name in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    hp = foe.current_hp
    events = _first(engine, "Cinder Burst")
    assert 0 < hp - foe.current_hp <= 12
    assert not [e for e in events if e.event_type == "GM_RIDER"]


def test_ash_sovereign_incarnation_is_immune_to_being_smothered():
    """"Immunity to Smothered" """
    from combat.typed_executor import condition_immune

    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.ash_sovereign_incarnation"], cl=17)
    _first(engine, "Ash-Sovereign Incarnation", target=None)
    assert condition_immune(engine, me, "smothered")
    other, plain = c13._fight(ASH, [], cl=17)[:2]
    assert not condition_immune(other, plain, "smothered")


# ---------------------------------------------------------------------------- the plug-in is inert for everyone else
def test_ash_talents_is_inert_for_a_character_with_no_ash_row():
    from combat.ext import ash_talents

    engine, me, foe = c13._fight("tianxia.sphere.ritual", [], cl=17)
    assert ash_talents._states(me) == []
    assert ash_talents.in_ash_or_fire(engine, me) is False
    assert ash_talents._areas_of(engine, me, "ASH_BASE_ASHFALL") == []
    assert ash_talents.ward_terrain_bonus(engine, me, foe, None, {"feature_id": "TAL_OTHER"}) is None
    assert ash_talents.destination_map_pick(engine, {"options": [{"id": "cell:1,1"}], "maximum": 1},
                                            {"reaction_source_id": "choice:needle.eat_the_flame"}) is None


def test_rolling_ashfall_map_pick_is_inert_for_any_other_choice():
    from combat.ext import ash_talents

    assert ash_talents.destination_map_pick(None, {}, {"reaction_source_id": "choice:needle.teleport_destination"}) is None
    answer = ash_talents.destination_map_pick(None, {"options": [{"id": "cell:4,6"}], "maximum": 1},
                                            {"reaction_source_id": "choice:needle.move_area_to:rolling_ashfall"})
    assert answer and "highlighted square" in answer["instruction"]


# ---------------------------------------------------------------------------- Ash Clone
def test_ash_clone_brings_the_printed_figure_that_acts_after_its_owner_and_dodges_uncommanded():
    """"Create one humanoid cinder figure. AC 13 + Proficiency Bonus; HP 5 x CL; Speed 30 feet. The clone acts
    immediately after your turn. ... Without a command, it Dodges." """
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.ash_clone"], cl=17)
    c13._answers(engine, {})
    events = _first(engine, "Ash Clone", target=None)
    clone = next(actor for actor in engine.state.actors.values() if actor.summon and actor.summon["group"] == "ash_clone")
    assert clone.armor_class == 13 + me.proficiency_bonus
    assert clone.maximum_hp == 5 * 17
    assert clone.speed_ft == 30
    assert [e for e in events if e.event_type == "SUMMON_APPEARED"]
    assert "Command Ash Clone" in c13._names(engine) or any("Command" in name for name in c13._names(engine))
    from combat import summons

    assert summons.on_turn_start(engine, clone) is True  # no command: it Dodges and its turn passes
    assert any(row.condition_id == "condition:core.dodge" for row in clone.conditions.values())


def test_clone_reviewed_contract_has_flight_and_destruction_terrain():
    from combat.summons import rules
    assert _authority()["tianxia.talent.ash.ash_clone"]["riders"] == []
    traits = rules()["sources"]["tianxia.talent.ash.ash_clone"]["appearance_traits"]
    assert traits["fly_speed_ft"] == 30 and traits["flight_hover"]
    assert traits["destroyed_terrain"]["radius_ft"] == 10
    assert traits["destroyed_terrain"]["until_owner_next_start"]


# ---------------------------------------------------------------------------- Ashen Step
def test_ashen_step_lands_only_in_a_free_visible_square_inside_its_twenty_foot_reach():
    """"Dissolve into cinders and reform in one visible unoccupied space" -- the squares the printed line refuses are
    refused by the table: an occupied square, a wall, and anything past 20 feet."""
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.ashen_step"], cl=17, foe_at=(4, 7))
    c13.t._ready(engine)
    offered = {(c.destination.x, c.destination.y) for c in engine.legal_candidates() if c.display_name.startswith("Ashen Step")}
    assert offered and (foe.position.x, foe.position.y) not in offered
    assert not offered & {(x, y) for x, y in engine.grid.blocked}
    assert max(engine.grid.distance_ft(me.position, type(me.position)(x=x, y=y)) for x, y in offered) <= 20
    _first(engine, "Ashfall", target=None, destination=(3, 6))
    c13.t._ready(engine)
    inside = {(c.destination.x, c.destination.y) for c in engine.legal_candidates() if c.display_name.startswith("Ashen Step")}
    assert inside & {(3, 5), (2, 6), (2, 5)}  # "ignores nonmagical difficult terrain"
    events = _first(engine, "Ashen Step to 3,5", target=None)
    assert [e for e in events if e.event_type == "MOVEMENT_COMMITTED"]
    assert not [e for e in events if e.event_type == "REACTION_WINDOW_OPENED"]  # "does not provoke opportunity attacks"


# ---------------------------------------------------------------- World After the Fire / the Forgotten Age
def test_world_after_the_fire_runs_its_area_rule_and_keeps_only_the_lines_the_table_does_not_run():
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.world_after_the_fire"], cl=17, foe_at=(4, 7))
    _doomed(foe)
    events = _first(engine, "World After the Fire", target=None, destination=(4, 6))
    assert any((row.data or {}).get("rule", {}).get("temp_hp_denied") for row in foe.conditions.values())
    hp = foe.current_hp
    zones.on_turn_start(engine, foe)
    assert hp - foe.current_hp > 0
    riders = _authority()["tianxia.talent.ash.world_after_the_fire"]["riders"]
    assert all(any(word in line for word in ("ignore Ash Terrain", "cannot Dash", "Hide while Lightly Obscured"))
               for line in riders), riders


def test_ashes_of_the_forgotten_age_applies_its_printed_consequences():
    engine, me, foe = c13._fight(ASH, ["tianxia.talent.ash.ashes_of_the_forgotten_age"], cl=17, foe_at=(4, 7))
    _doomed(foe)
    _first(engine, "Ashes of the Forgotten Age", target=None, destination=(4, 6))
    zones.on_turn_start(engine, foe)
    kinds = {row.condition_id for row in foe.conditions.values()}
    assert "condition:typed.smothered" in kinds, sorted(kinds)
    assert "condition:typed.reaction_denied" in kinds, sorted(kinds)
    assert [(m.target_field, m.value) for m in foe.modifiers.values()] == [("healing_reduction", "none")]
    assert stored_healing_reductions(engine, foe, 10) == 0


def test_the_forgotten_age_reminders_name_the_rules_the_table_still_cannot_run():
    """AUTO75f1 finding 5: "Temporary Barriers take double damage" and "Summoned Constructs cannot regenerate"
    are combat rules, not scenery, and "Cannot gain Temporary HP" has no implementation behind it."""
    riders = _authority()["tianxia.talent.ash.ashes_of_the_forgotten_age"]["riders"]
    joined = " ".join(riders)
    assert any(line.strip() == "Cannot gain Temporary HP." for line in riders), riders
    assert "Temporary Barriers inside the area take double damage." in joined
    assert "Summoned Constructs inside the area cannot regenerate." in joined
    assert "scenery" not in joined.lower()
    assert "does not automatically destroy artifacts" in joined


# ---------------------------------------------------------------- AUTO75f1: one owner per reviewed record
def test_the_ash_records_are_each_written_once_in_the_reviewed_files():
    """AUTO75f1 finding 6: a second full definition of a mechanic another reviewer already owns shadows it
    (alphabetical zz_ wins) and adds a "reviewed twice" warning. Each Ash record now has one home."""
    root = ROOT / "authority/typed_mechanics/reviewed_final.d"
    ash_keys = {key for key, record in _authority().items() if record.get("sphere") == ASH}
    homes: dict[str, list[str]] = {}
    for path in sorted(root.glob("*.json")):
        for key in (json.loads(path.read_text(encoding="utf-8")).get("mechanics") or {}):
            if key in ash_keys:
                homes.setdefault(key, []).append(path.name)
    doubled = {key: names for key, names in homes.items() if len(names) > 1}
    assert not doubled, doubled
    shadow = json.loads((root / "zz_ash_automation.json").read_text(encoding="utf-8"))["mechanics"]
    assert set(shadow) == {"ASH_TAL_CINDER_BURST",
                           "tianxia.talent.ash.heaven_cremating_ashstorm"}, sorted(shadow)
    # The reviewed Ash branch moved Ash Clone and Rolling Ashfall; each keeps one home there.
    moved = json.loads((root / "zzzz_a2_ash.json").read_text(encoding="utf-8"))["mechanics"]
    assert {"tianxia.talent.ash.ash_clone", "tianxia.talent.ash.rolling_ashfall"} <= set(moved), sorted(moved)