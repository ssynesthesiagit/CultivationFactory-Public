"""Lane 1 of the automation push (owner 2026-09-29: "i want everything we can automated"): combat abilities whose typing
was a GM line only.  Every ability is compiled on a real character and run through the engine; each test fails on the
typing the authority carried before (no action, or an action that changed nothing).

Overrides: authority/typed_mechanics/reviewed_final.d/auto_lane1.json; plug-ins: combat/ext/save_bonus_status.py.
Saves are forced with the sheet's technique DC (16, or 50/-40 where a branch must be taken), attacks always hit (foe AC -50).
"""

import json
from functools import lru_cache
from pathlib import Path

import combat.factory_compiler as factory_compiler
from combat import ext, typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.lane1"
ALLY = "actor:factory.lane1_ally"
FOE = AN


# ------------------------------------------------------------------------------------------------------- harness


@lru_cache(maxsize=4)
def _load_mechanics(path):
    return json.loads(Path(path).read_bytes())["mechanics"]


def _mechanics():
    return _load_mechanics(str(factory_compiler.TYPED_AUTHORITY))  # read at call time: the module attribute may be swapped


def _sheet(mid, *, cl=10, dc=16, foundation=None):
    """A character owning exactly one mechanic (talent, sphere base ability, subpath feature or foundation feature)."""
    mech = _mechanics()[mid]
    sphere, kind = mech.get("sphere_id"), mech.get("kind")
    sheet = {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 30}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8,
        },
    }
    if sphere:
        bases = [k for k, m in _mechanics().items() if m.get("sphere_id") == sphere and m.get("kind") == "base_ability"]
        sheet["spheres_and_talents"] = {"sphere_record_ids": [sphere], "learned_talent_record_ids": [mid],
                                        "automatic_sphere_component_record_ids": bases}
    elif kind == "subpath_feature":
        sheet["path_and_subpath"] = {"path_feature_record_ids": [mid]}
    elif kind == "foundation_feature":
        sheet["foundation"] = foundation or {"foundation_id": mech["foundation_id"], "stage": mech.get("stage") or "Perfected"}
    return sheet


def _bundle(mid, actor_id=ME, **kw):
    return compile_character(_sheet(mid, **kw), actor_id=actor_id)


def _rows(bundle):
    return {row["display_name"]: row for row in bundle["action_catalog"]}


def _engine(bundle, *, allies=()):
    bundles = (bundle, *allies)
    ids = [ME, *(b["actor_id"] for b in allies), AN]
    engine = Gate4ControllerEngine(
        ROOT, match_seed="LANE1", typed_bundles=bundles,
        roster_setup={"primary_actor_ids": ids, "team_by_actor": {ME: "team:a", **{b["actor_id"]: "team:a" for b in allies}, AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, **{b["actor_id"]: {"x": 3, "y": 7} for b in allies}, AN: {"x": 4, "y": 6}}})
    from tests.hunt24_support import finish_direct_setup
    finish_direct_setup(engine)
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[AN].armor_class = -50
    _ready(engine)
    return engine


def _ready(engine):
    me = engine.state.actors[ME]
    engine.state.current_actor_id = ME
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    return me


def _legal(engine):
    return {c.display_name for c in engine.legal_candidates()}


def _use(engine, name, target=None):
    matches = [c for c in engine.legal_candidates() if c.display_name == name]
    assert matches, f"{name!r} is not a legal action; legal: {sorted(_legal(engine))}"
    candidate = matches[0]
    targets = (target,) if target else (candidate.target_ids or ())
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=targets,
                                       destination=candidate.destination))
    return engine.events[before:]


def _payloads(events, event_type):
    return [getattr(e, "payload", None) or {} for e in events if e.event_type == event_type]


def _held(actor, condition_id):
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def _foe_forces_save(engine, target_id, ability, *, condition=None, dc=16):
    """The foe makes ``target_id`` roll a save of ``ability`` against a typed effect that names ``condition``; returns the DC
    the engine rolled against (a save bonus lowers it)."""
    action = next(iter(engine.action_catalog.values()))
    actor, target = engine.state.actors[AN], engine.state.actors[target_id]
    ctx = typed_executor.Context(engine, actor, action, None, {"numbers": {"pb": 4, "save_dc": dc}}, [target], target, {})
    fail = [{"type": "condition", "condition": condition, "applies_to": "target"}] if condition else []
    typed_executor.block_save(ctx, {"type": "save", "ability": ability.lower(), "on_fail": fail, "on_success": []})
    return next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED").payload["dc"]


# ------------------------------------------------------------------------------- timed bonuses to saving throws


def test_calming_heart_pill_adds_one_to_saves_against_charmed_and_frightened():
    """"For 1 hour, the consumer gains +1 to saving throws against the Charmed condition, the Frightened condition ...":
    a Bonus Action that lasts the fight; it was a GM line that changed no roll."""
    engine = _engine(_bundle("TAL_ALCHEMY_CALMING_HEART_PILL"))
    me = engine.state.actors[ME]
    assert _foe_forces_save(engine, ME, "WIS", condition="frightened") == 16  # nothing yet
    events = _use(engine, "Calming Heart Pill", ME)
    assert not me.bonus_action_available
    assert [c.data["rule"]["save_bonus"]["against"] for c in _held(me, "condition:typed.save_bonus")] == [["charmed", "frightened"]]
    assert any(e.event_type == "CONDITION_APPLIED" for e in events)
    assert _foe_forces_save(engine, ME, "WIS", condition="frightened") == 15
    assert _foe_forces_save(engine, ME, "CON", condition="charmed") == 15  # every ability, not one
    assert _foe_forces_save(engine, ME, "WIS", condition="poisoned") == 16  # a save against something else is not covered
    assert _foe_forces_save(engine, ME, "DEX") == 16  # a bare save (no condition named) is not covered either


def test_warding_talisman_adds_one_to_the_chosen_ability_only():
    """"+1 to saving throws using the chosen ability; only one Warding Talisman per creature": one option per ability, the
    newer talisman replacing the older."""
    bundle = _bundle("tianxia.talent.talismans.warding_talisman")
    names = [n for n in _rows(bundle) if n.startswith("Warding Talisman")]
    assert names == [f"Warding Talisman: {a}" for a in ("Strength", "Dexterity", "Constitution", "Intelligence", "Wisdom", "Charisma")]
    engine = _engine(bundle)
    me = engine.state.actors[ME]
    assert _foe_forces_save(engine, ME, "DEX") == 16
    _use(engine, "Warding Talisman: Dexterity", ME)
    assert _foe_forces_save(engine, ME, "DEX") == 15
    assert _foe_forces_save(engine, ME, "DEX", condition="prone") == 15  # any effect, not a named one
    assert _foe_forces_save(engine, ME, "STR") == 16
    _ready(engine)
    _use(engine, "Warding Talisman: Strength", ME)
    assert len(_held(me, "condition:typed.save_bonus")) == 1  # "only one Warding Talisman per creature"
    assert _foe_forces_save(engine, ME, "STR") == 15
    assert _foe_forces_save(engine, ME, "DEX") == 16


def test_a_saving_throw_bonus_does_not_leak_between_creatures():
    engine = _engine(_bundle("TAL_ALCHEMY_CALMING_HEART_PILL"))
    _use(engine, "Calming Heart Pill", ME)
    assert _foe_forces_save(engine, AN, "WIS", condition="frightened") == 16  # the foe never drank it
    assert ext.run("save", None, engine.state.actors[AN], "WIS", {"frightened"}) == []


# ----------------------------------------------- ending an opposing effect with a check against its DC (end_effect)


def _ally_bundle():
    return _bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY)  # any character will do: it is only the one being helped


def _put(engine, holder_id, condition, by, source_id):
    engine._apply_condition(engine.state.actors[holder_id], f"condition:typed.{condition}", source_id, by, expires_on="UNTIL_REMOVED")


def _put_modifier(engine, holder_id, field, value, by, source_id):
    engine.state.current_actor_id = by  # a modifier is filed under whoever's turn it is
    engine._add_modifier(engine.state.actors[holder_id], source_id, field, "ADD", value, "ALWAYS", expires_on="UNTIL_REMOVED")
    engine.state.current_actor_id = ME


def _own_action(engine, name):
    return next(key for key, action in engine.action_catalog.items() if getattr(action, "display_name", "") == name)


def test_silence_breaking_note_is_offered_only_against_a_silence_a_foe_put_on_someone():
    """"Choose one Silence effect ... within range": nothing to choose from is no choice; an ally's own effect is not opposing."""
    engine = _engine(_bundle("tianxia.talent.music.silence_breaking_note"), allies=(_ally_bundle(),))
    assert "Silence-Breaking Note" not in _legal(engine)
    _put(engine, ALLY, "silenced", ALLY, "action:test.self_silence")
    assert "Silence-Breaking Note" not in _legal(engine)
    _put(engine, ALLY, "silenced", FOE, "action:test.foe_silence")
    assert "Silence-Breaking Note" in _legal(engine)


def test_silence_breaking_note_ends_the_silence_on_a_success_and_leaves_it_on_a_failure():
    """"Make a Music Check against the opposing effect's Cultivation Save DC. Success: End the effect. Failure: The effect
    remains."  The DC is the technique's own (here the caster's sheet DC stands in for the foe's: the lookup is by the action
    that put the condition on); DC 15 when nothing states one."""
    for dc, ends in ((-40, True), (50, False)):
        engine = _engine(_bundle("tianxia.talent.music.silence_breaking_note", dc=dc), allies=(_ally_bundle(),))
        _put(engine, ALLY, "silenced", FOE, _own_action(engine, "Silence-Breaking Note"))
        events = _use(engine, "Silence-Breaking Note", ALLY)
        (rolled,) = _payloads(events, "CHECK_ROLLED")
        assert rolled["dc"] == dc and rolled["skill"] == "Music Check" and rolled["success"] is ends
        assert bool(_held(engine.state.actors[ALLY], "condition:typed.silenced")) is not ends
    engine = _engine(_bundle("tianxia.talent.music.silence_breaking_note"), allies=(_ally_bundle(),))
    _put(engine, ALLY, "silenced", FOE, "action:test.unknown")
    (rolled,) = _payloads(_use(engine, "Silence-Breaking Note", ALLY), "CHECK_ROLLED")
    assert rolled["dc"] == 15  # "If no opposing DC exists, use DC 15"
    assert bool(_held(engine.state.actors[ALLY], "condition:typed.silenced")) is not rolled["success"]


def test_silence_breaking_note_adds_proficiency_bonus_twice_from_level_15():
    mods = {}
    for cl in (10, 15):
        engine = _engine(_bundle("tianxia.talent.music.silence_breaking_note", cl=cl), allies=(_ally_bundle(),))
        _put(engine, ALLY, "silenced", FOE, "action:test.unknown")
        _use(engine, "Silence-Breaking Note", ALLY)
        mods[cl] = next(e for e in engine.events if e.event_type == "CHECK_ROLLED").payload["actor"]["modifier"]
    assert mods[15] - mods[10] == 8  # PB 4, twice


def test_wound_memory_suturing_has_a_choice_per_kind_of_effect_and_ends_it_on_a_success():
    bundle = _bundle("tianxia.talent.life.wound_memory_suturing", dc=-40)
    assert [n for n in _rows(bundle) if n.startswith("Wound Memory")] == [
        "Wound Memory Suturing: Healing prevented or halved", "Wound Memory Suturing: No Temporary HP", "Wound Memory Suturing: Bleeding"]
    engine = _engine(bundle, allies=(_ally_bundle(),))
    assert not {n for n in _legal(engine) if n.startswith("Wound Memory")}  # nothing to close
    _put(engine, ALLY, "bleeding", FOE, "action:test.foe_bite")
    _put_modifier(engine, ALLY, "healing_reduction", "half", FOE, "action:test.foe_curse")
    assert {n for n in _legal(engine) if n.startswith("Wound Memory")} == {
        "Wound Memory Suturing: Bleeding", "Wound Memory Suturing: Healing prevented or halved"}
    ally = engine.state.actors[ALLY]
    assert typed_executor._reduced_healing(engine, ally, 10) == 5
    events = _use(engine, "Wound Memory Suturing: Healing prevented or halved", ALLY)
    assert _payloads(events, "CHECK_ROLLED")[0]["skill"] == "Cultivation Check"
    assert typed_executor._reduced_healing(engine, ally, 10) == 10
    assert _held(ally, "condition:typed.bleeding")  # the other effect is untouched: "choose one"


def test_wound_memory_suturing_suppresses_on_a_failure_until_the_end_of_the_targets_next_turn():
    engine = _engine(_bundle("tianxia.talent.life.wound_memory_suturing", dc=50), allies=(_ally_bundle(),))
    ally = engine.state.actors[ALLY]
    _put(engine, ALLY, "no_temp_hp", FOE, _own_action(engine, "Wound Memory Suturing: No Temporary HP"))  # DC 50: the check fails
    events = _use(engine, "Wound Memory Suturing: No Temporary HP", ALLY)
    assert _payloads(events, "CHECK_ROLLED")[0]["success"] is False
    assert not _held(ally, "condition:typed.no_temp_hp") and _held(ally, "condition:typed.suppressed.no_temp_hp")
    engine._grant_temp_hp(ally, 5, "test", ME)
    assert ally.temporary_hp == 5  # "suppressed": temporary hit points can be gained again
    ext.run("turn_end", engine, ally)
    assert not _held(ally, "condition:typed.no_temp_hp")  # its next turn has not come yet
    ally.turns_started += 1
    ext.run("turn_end", engine, ally)
    assert _held(ally, "condition:typed.no_temp_hp") and not ally.turn_flags["typed_round_suppressed"]


def test_a_suppressed_effect_that_runs_out_meanwhile_does_not_come_back():
    engine = _engine(_bundle("tianxia.talent.life.wound_memory_suturing", dc=50), allies=(_ally_bundle(),))
    ally = engine.state.actors[ALLY]
    _put_modifier(engine, ALLY, "healing_reduction", "none", FOE, _own_action(engine, "Wound Memory Suturing: Healing prevented or halved"))
    _use(engine, "Wound Memory Suturing: Healing prevented or halved", ALLY)
    assert typed_executor._reduced_healing(engine, ally, 10) == 10
    ally.modifiers.clear()  # the curse's own clock ran out
    ally.turns_started += 1
    ext.run("turn_end", engine, ally)
    assert not ally.modifiers and typed_executor._reduced_healing(engine, ally, 10) == 10


# ------------------------------------------------------------------------------------------- Last Chance Grapple


def _grapple_save(engine, foe_save):
    """The foe's Strength and Dexterity saves are forced: 50 holds against the Grapple, -40 fails it."""
    foe = engine.state.actors[AN]
    foe.saving_throws["STR"] = foe.saving_throws["DEX"] = foe_save
    return foe


def test_last_chance_grapple_retries_the_grapple_after_a_save_held_against_it():
    """"When one creature succeeds on its saving throw against your Unarmed Strike Grapple option, expend Martial Focus. Use a
    Bonus Action before the end of your turn to attempt to Grapple the same creature again": it was an inert Bonus Action."""
    engine = _engine(_bundle("TAL_WRESTLING_LAST_CHANCE_GRAPPLE"))
    me = engine.state.actors[ME]
    foe = _grapple_save(engine, 50)
    assert "Last Chance Grapple" not in _legal(engine)  # nothing has held yet
    _use(engine, "Grapple", AN)
    assert not _held(foe, "condition:typed.grappled")  # it held
    assert "Last Chance Grapple" in _legal(engine)
    _grapple_save(engine, -40)
    events = _use(engine, "Last Chance Grapple", AN)
    assert _held(foe, "condition:typed.grappled"), [e.event_type for e in events]
    assert me.resources["resource:core.martial_focus"] == 0 and not me.bonus_action_available
    (rolled,) = _payloads(events, "SAVE_ROLLED")  # one save: the Grapple attempt alone, no further Attacks
    assert rolled["dc"] == 8 + 4 + 2  # the Grapple option's own DC: 8 + PB + Strength


def test_last_chance_grapple_is_used_up_by_one_retry_and_ends_with_the_turn():
    engine = _engine(_bundle("TAL_WRESTLING_LAST_CHANCE_GRAPPLE"))
    me = engine.state.actors[ME]
    foe = _grapple_save(engine, 50)
    _use(engine, "Grapple", AN)
    _use(engine, "Last Chance Grapple", AN)  # held again
    assert not _held(foe, "condition:typed.grappled")
    _ready(engine)
    engine._gain_resource(me, "resource:core.martial_focus", 1, "test")
    assert "Last Chance Grapple" not in _legal(engine)  # one retry per held save (the held retry is not the Unarmed Strike option)
    engine._system_start_turn()  # the next turn of mine
    _ready(engine)
    assert "Last Chance Grapple" not in _legal(engine)  # "before the end of your turn": the note did not carry over


def test_last_chance_grapple_needs_martial_focus_and_a_held_grapple_not_a_failed_one():
    engine = _engine(_bundle("TAL_WRESTLING_LAST_CHANCE_GRAPPLE"))
    me = engine.state.actors[ME]
    _grapple_save(engine, -40)
    _use(engine, "Grapple", AN)  # it failed: the foe is Grappled, so there is nothing to retry
    assert "Last Chance Grapple" not in _legal(engine)
    engine = _engine(_bundle("TAL_WRESTLING_LAST_CHANCE_GRAPPLE"))
    _grapple_save(engine, 50)
    _use(engine, "Grapple", AN)
    engine._spend_resource(engine.state.actors[ME], "resource:core.martial_focus", 1, "test")
    _ready(engine)
    assert "Last Chance Grapple" not in _legal(engine)  # no Martial Focus to expend
