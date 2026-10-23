"""Hollow Field (CL10): the whole printed record on the table.

Ownership is a recorded native acquisition (NS1R evidence + subpath selection,
with its permanent Void Scar) compiled through combat/authority_projection.py.
No test injects the feature id, the field, a mark, or a save result into a
fight; Void Marks are placed by the family's own ``mark_apply`` producer.

The record is exercised where each clause can fail: the real action and its
5 Qi / 60 ft / 20 ft / 1 minute Concentration, a table commit and cold replay,
the field ending with Concentration, both save triggers and once-per-turn, every
printed Hollowing and lesser effect, Deepen the Hollow (2-mark spend,
once-per-turn, the CL+3 repeat save, no repeat for a lower CL, release on
leaving/ending), the continuous inside-field rules through their real pipelines,
hostility from native team facts, and the default-inert guards.
"""
from pathlib import Path

import pytest

from app.core import Database, Settings
from combat import ext, typed_executor, zones
from combat.authority_projection import compile_project_character, project_sheet
from combat.ext import void_touched_hollow_field as hf
from combat.factory_compiler import compile_character
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.void_touched_acquisition_support import build_native_acquisition
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event, install_authority_test_pack
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle

QI = "tianxia.path.qi_cultivation"
PARENT = "tianxia.subpath.qi.void_touched_cultivator"
FEATURE = PARENT + ".feature.hollow_field"
SCAR = "My reflection no longer appears."
VOID = "tianxia.sphere.void"
ARMAMENT = "tianxia.path.qi_cultivation.feature.domain_armament"
TOUCH = "TAL_VOID_HOLLOW_TOUCH"
QUIET_GAP = "TAL_VOID_QUIET_GAP"
EMPTY_STEP = "TAL_VOID_EMPTY_STEP"
NO_PURCHASE = "TAL_VOID_NO_PURCHASE_BODY"
VOICE = "TAL_AIR_BREATH_OF_NO_DISTANCE"


# ------------------------------------------------------------------------------------------------ a real acquisition
def _build_acquisition(root: Path, cl: int = 10):
    """Real NS1R acquisition for the Hollow Field tests."""
    return build_native_acquisition(root, cl, "hollow-field")


@pytest.fixture(scope="module")
def acquired(tmp_path_factory):
    return _build_acquisition(tmp_path_factory.mktemp("hollow-field-acquisition"))


def owner_doc(service, project, cl=10, *, name="Hollow Field user"):
    state = service.get_state(project)
    doc = sheet([], cl=cl, name=name, dc=20)
    doc.setdefault("spheres_and_talents", {})["sphere_record_ids"] = [VOID]
    doc["path_and_subpath"] = {"paths": state["paths"]}
    return doc


def owner_bundle(service, project, actor_id=OWNER, cl=10):
    return compile_project_character(service, project, owner_doc(service, project, cl),
                                     actor_id=actor_id, reaction_plan={"ask": True})


def foe_doc(talents=(), *, cl=10, armament=False, name="Mara"):
    doc = sheet(list(talents), cl=cl, name=name, dc=16)
    if armament:
        doc.setdefault("path_and_subpath", {})["path_feature_record_ids"] = [ARMAMENT]
    return doc


def with_cha(bundles, value):
    for row in bundles:
        if row["actor_id"] != OWNER:
            row["actor_template"]["saving_throws"]["CHA"] = value


def fight(tmp_path, service, project, *, foe_talents=(), cl=10, armament=False, cha=None, seed="HOLLOW-FIELD"):
    places = {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 6, "y": 6}}
    combat, table, mid = fixture(
        tmp_path, [], cl=cl, owner_bundle=owner_bundle(service, project),
        foe_sheet=foe_doc(foe_talents, cl=cl, armament=armament), positions=places,
        bundle_transform=(lambda rows: with_cha(rows, cha)) if cha is not None else None, seed=seed)
    return combat, table, mid


def cast_field(combat, table, mid, at=(6, 6)):
    settle(table, mid, candidate(combat, mid, "Hollow Field", at=at).candidate_id)


def field(engine):
    rows = hf.fields(engine)
    assert len(rows) == 1, [row.zone_id for row in rows]
    return rows[0]


def field_action(engine, owner):
    return next(engine.action_catalog[key] for key in owner.action_ids
                if hf.source_of(engine.action_catalog[key]) == FEATURE)


def action_of(engine, actor, source):
    return next(engine.action_catalog[key] for key in actor.action_ids
                if hf.source_of(engine.action_catalog[key]) == source)


def mark_context(engine, owner, foe, zone):
    return typed_executor.Context(engine, owner, engine.action_catalog[zone.source_definition_id], None,
                                  {"numbers": dict(zone.trigger_profile.get("numbers") or {}), "effects": [],
                                   "duration": {"kind": "instant"}, "riders": []}, [foe], foe, {})


def put_marks(engine, owner, foe, zone, number=1):
    ctx = mark_context(engine, owner, foe, zone)
    for _ in range(number):
        assert ext.run("mark_apply", ctx, {"mark": "Void Mark"}, foe, None, None)[0] is True


def advance_to(table, mid, actor, *, choices=None):
    """End turns until ``actor`` is up, returning every prompt raised on the way."""
    prompts = []
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return prompts
        prompts.extend(settle(table, mid, table.state(mid)["menu"]["end_turn"], choices=choices))
    raise AssertionError("no turn")


# ------------------------------------------------------------------------------------------------ admission and the action
def test_native_acquisition_compiles_one_hollow_field(acquired):
    service, project = acquired
    projected = project_sheet(service, project, owner_doc(service, project))
    assert projected["path_and_subpath"]["acquisition_choices"][PARENT] == {"void_scar": SCAR}
    bundle = owner_bundle(service, project)
    rows = [row for row in bundle["action_catalog"]
            if (row.get("parameters", {}).get("typed") or {}).get("source") == FEATURE]
    assert len(rows) == 1, [row["display_name"] for row in rows]
    row = rows[0]
    typed = row["parameters"]["typed"]
    assert row["display_name"] == "Hollow Field"
    assert row["target_kind"] == "CELL" and row["range_ft"] == 60 and row["radius_ft"] == 20
    assert row["economy"] == "ACTION" and list(row["costs"]) == [["resource:core.qi", 5]]
    assert typed["duration"] == {"kind": "minutes", "amount": 1, "concentration": True}
    assert typed["min_cl"] == 10 and typed["void_scar"] == SCAR
    spec = typed["zone_spec"]
    assert spec["shape"] == "sphere" and spec["size_ft"] == 20 and spec["centered_on_self"] is False
    assert spec["obscured"] == "light" and spec["visual"]["darkness"] is False
    assert spec["visual"]["light"] is None and spec["profile"][hf.ZONE_TAG] == 1
    assert not typed.get("options"), "save-time choices are not separate cast actions"
    assert typed["riders"] == [], "automated combat clauses must not remain GM instructions"
    trigger = spec["triggers"][0]
    assert trigger["on"] == ["enter", "start"] and trigger["who"] == "hostile"
    assert trigger["effects"][0]["ability"] == "CHA"
    assert spec["inside"][0]["muffles"] is True


def test_field_commit_cold_reload_and_concentration(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert owner.resources["resource:core.qi"] == 25
    assert owner.concentration is not None
    zone = field(engine)
    assert zone.source_definition_id == owner.concentration.source_definition_id
    assert zone.concentration_link is True and zone.duration_rounds == 10
    assert owner.concentration.zone_id == zone.zone_id
    assert zones.actor_inside_zone(engine, foe, zone)
    assert zone.trigger_profile["obscured"] == "light"
    assert zone.trigger_profile["visual"]["light"] is None
    assert zones.muffled(engine, foe) is True
    # Ending Concentration ends the field and its inside effects.
    engine._end_concentration(owner, "TEST")
    assert hf.fields(engine) == []
    assert engine.state.zones[zone.zone_id].active is False
    assert zones.muffled(engine, foe) is False


def test_dim_surroundings_turn_the_field_into_darkness(acquired, tmp_path):
    """Live dim coverage, not a permanent whole-field cast-time sample."""
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    stored = field(engine)
    engine.state.zones["zone:test:lamp"] = stored.model_copy(update={
        "zone_id": "zone:test:lamp", "source_definition_id": "test.dim_lamp",
        "trigger_profile": {"kind": zones.KIND, "shape": "sphere", "size_ft": 20,
                            "visual": {"light": {"level": "dim"}}}})
    foe = engine.state.actors[FOE]
    owner = engine.state.actors[OWNER]
    assert zones.hidden_from(engine, owner, foe)
    engine.state.zones["zone:test:lamp"].trigger_profile["visual"]["light"]["level"] = "bright"
    assert not zones.hidden_from(engine, owner, foe)
    assert stored.trigger_profile["visual"]["darkness"] is False


# ------------------------------------------------------------------------------------------------ the save and its choices
def test_start_of_turn_save_asks_the_owner_and_applies_speed_15(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    cast_field(combat, table, mid)
    prompts = advance_to(table, mid, FOE)
    hollow = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.hollow_field"]
    assert len(hollow) == 1, [p["context"]["reaction_source_id"] for p in prompts]
    prompt = hollow[0]
    assert hollow[0]["reactor"] == "Hollow Field user"
    assert "Hollow Field" in prompt["moment"] and "Charisma" in prompt["moment"]
    assert "Mara" in prompt["moment"] and "Hollow Field user" in prompt["moment"]
    labels = [row["label"] for row in prompt["choice"]["options"]]
    assert "Speed is reduced by 15 feet" in labels
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    speed = [row for row in foe.modifiers.values() if row.target_field == "speed_ft"]
    assert len(speed) == 1 and speed[0].value == -15 and speed[0].operation == "ADD"
    assert speed[0].expires_on.startswith("START_OF_TURN_AT:actor:factory.worker2-foe:")


def test_successful_save_takes_a_lesser_effect(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, cha=60)
    cast_field(combat, table, mid)
    advance_to(table, mid, FOE)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    speed = [row for row in foe.modifiers.values() if row.target_field == "speed_ft"]
    assert len(speed) == 1 and speed[0].value == -5


def test_entering_and_starting_are_once_per_turn(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    cast_field(combat, table, mid)
    advance_to(table, mid, FOE)
    engine = reload(tmp_path, mid)
    zone, foe = field(engine), engine.state.actors[FOE]
    before = len([e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE])
    zones.fire_trigger(engine, zone, foe, "start")
    zones.fire_trigger(engine, zone, foe, "enter")
    after = len([e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE])
    assert after == before
    assert len([row for row in foe.modifiers.values() if row.target_field == "speed_ft"]) == 1


# ------------------------------------------------------------------------------------------------ every printed effect
@pytest.mark.parametrize("key", [item[0] for item in hf.HOLLOWING] + [item[0] for item in hf.LESSER])
def test_each_printed_effect_does_what_it_says(acquired, tmp_path, key):
    service, project = acquired
    talents = (TOUCH, QUIET_GAP, EMPTY_STEP, VOICE)
    combat, table, mid = fight(tmp_path / key, service, project, foe_talents=talents, armament=True)
    cast_field(combat, table, mid)
    if key == "suppress_talent":
        advance_to(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, "Hollow Touch", target=OWNER).candidate_id)
    engine = reload(tmp_path / key, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    zone = field(engine)
    if key == "no_teleport":
        engine._active_action_source_id = action_of(engine, foe, EMPTY_STEP).source_definition_id
    hf.apply_effect(engine, owner, zone, foe, key)
    ids = [c.condition_id for c in foe.conditions.values()]
    if key == "speed15":
        assert [row.value for row in foe.modifiers.values() if row.target_field == "speed_ft"] == [-15]
    elif key == "speed5":
        assert [row.value for row in foe.modifiers.values() if row.target_field == "speed_ft"] == [-5]
    elif key == "suppress_talent":
        from combat.ext import ability_lockout
        locked = ability_lockout.records(foe)
        assert locked and locked[0].data["mode"] == "barred"
        locked_action = next(engine.action_catalog[aid] for aid in foe.action_ids
                             if ability_lockout.key_of(engine.action_catalog[aid]) == locked[0].data["ability"])
        assert ability_lockout.barred(engine, foe, None, locked_action) is False
    elif key == "suppress_armament":
        assert hf.ARMAMENT in ids
        armament = next(engine.action_catalog[aid] for aid in foe.action_ids
                        if hf.source_of(engine.action_catalog[aid]).startswith("armament."))
        assert hf.gate_candidates(engine, foe, None, armament) is False
    elif key == "no_concentration":
        assert hf.NO_CONCENTRATION in ids
        quiet = action_of(engine, foe, QUIET_GAP)
        assert (quiet.parameters["typed"]["duration"] or {}).get("concentration") is True
        assert hf.gate_candidates(engine, foe, None, quiet) is False
    elif key == "no_audible":
        assert "condition:typed.silenced" in ids
        voice = action_of(engine, foe, VOICE)
        assert ext.any_false("candidate_allowed", engine, foe, None, voice) is True
    elif key == "no_healing":
        assert typed_executor.stored_healing_reductions(engine, foe, 12) == 0
    elif key == "no_teleport":
        start = foe.position
        assert hf.hollow_teleport(engine, foe, start, start.model_copy(update={"x": start.x + 2})) is False
    elif key == "reaction_after":
        assert hf.REACTION_AFTER in ids
        # Move it out of the field: the lesser effect is the only thing still holding Reactions.
        foe.position = foe.position.model_copy(update={"x": 40})
        action = action_of(engine, foe, TOUCH)
        ctx = typed_executor.Context(engine, foe, action, None, dict(action.parameters["typed"]), [owner], owner, {})
        foe.reaction_available = True
        hf.reaction_lock_after_powered(ctx)
        assert any(c.condition_id == hf.NO_REACTIONS for c in foe.conditions.values())
        from combat import typed_reactions
        assert typed_reactions._can_react(engine, foe) is False
    elif key == "next_cost":
        # Out of the field, the marker alone adds 1 to the next CP cost.
        foe.position = foe.position.model_copy(update={"x": 40})
        listed = {"resource:core.qi": 5}
        assert hf.hostile_cost(engine, foe, "test", listed, dict(listed)) == {"resource:core.qi": 6}
        engine._spend_resource(foe, "resource:core.qi", 1, "test:spend")
        assert not any(c.condition_id == hf.NEXT_COST for c in foe.conditions.values())


# ------------------------------------------------------------------------------------------------ continuous inside rules
def test_continuous_inside_rules_use_the_real_pipelines(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    # Hostile CP costs +1 through the real cost query.
    listed = {"resource:core.qi": 5}
    assert hf.hostile_cost(engine, foe, "test", listed, dict(listed)) == {"resource:core.qi": 6}
    assert engine.effective_costs(foe, "test:action", [("resource:core.qi", 5)]) == (("resource:core.qi", 6),)
    # Hostile creatures cannot regain CP.
    before = foe.resources["resource:core.qi"]
    engine._gain_resource(foe, "resource:core.qi", 3, "test:gain")
    assert foe.resources["resource:core.qi"] == before
    # Temporary HP from a hostile cultivation effect is halved.
    amount = 9
    cultivation = field_action(engine, owner).source_definition_id
    assert hf.halve_hostile_temp_hp(engine, foe, amount, foe, cultivation, "temp_hp") == amount - amount // 2
    assert hf.halve_hostile_temp_hp(engine, foe, amount, owner, cultivation, "temp_hp") is None
    assert hf.halve_hostile_temp_hp(engine, foe, amount, foe, "test:item", "hp") is None
    # The field's own sound clause.
    assert zones.muffled(engine, foe) is True
    # The owner's own costs and gains are untouched.
    assert hf.hostile_cost(engine, owner, "test", listed, dict(listed)) is None
    assert hf.no_hostile_regain(engine, owner, "resource:core.qi", 3, "test") is None


def test_powered_technique_locks_reactions_until_its_next_turn(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, foe_talents=(TOUCH,))
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    action = action_of(engine, foe, TOUCH)
    ctx = typed_executor.Context(engine, foe, action, None, dict(action.parameters["typed"]), [owner], owner, {})
    foe.reaction_available = True
    hf.reaction_lock_after_powered(ctx)
    assert any(c.condition_id == hf.NO_REACTIONS for c in foe.conditions.values())
    from combat import typed_reactions
    assert typed_reactions._can_react(engine, foe) is False


# ------------------------------------------------------------------------------------------------ Deepen the Hollow
def test_deepen_spends_two_marks_once_per_turn_and_repeats(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, foe_talents=(TOUCH, NO_PURCHASE), cl=13)
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    zone = field(engine)
    put_marks(engine, owner, foe, zone, 2)
    assert hf.creature_cl(engine, foe) >= hf._field_cl(zone) + 3
    zones.fire_trigger(engine, zone, foe, "start")
    systems = [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]
    assert len(systems) == 1 and systems[0].data["kind"] == "sphere"
    assert systems[0].data["zone"] == zone.zone_id
    assert [row["feature_id"] for row in systems[0].data["rows"]["passive"]] == [NO_PURCHASE]
    assert not [row for row in engine.typed_passive_rows[FOE] if row.get("feature_id") == NO_PURCHASE]
    assert hf._deepen_records(zone) and hf._deepen_records(zone)[0]["target"] == FOE
    from combat.ext import void_touched_cultivator as void
    assert void.mark_count(foe, OWNER) == 0
    # Once per turn: refreshed marks cannot buy a second suppression in the same turn.
    put_marks(engine, owner, foe, zone, 3)
    zones.fire_trigger(engine, zone, foe, "start")
    assert len([c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]) == 1
    assert len(hf._deepen_records(zone)) == 1
    assert void.mark_count(foe, OWNER) == 3
    # CL+3 target repeats the Charisma save at the end of its turn and ends it on a success.
    foe.saving_throws["CHA"] = 60
    hf.deepen_repeat_save(engine, foe)
    assert not [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]
    assert [row for row in engine.typed_passive_rows[FOE] if row.get("feature_id") == NO_PURCHASE]


def test_lower_cl_target_gets_no_automatic_repeat(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, foe_talents=(TOUCH,), cl=12)
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    zone = field(engine)
    put_marks(engine, owner, foe, zone, 2)
    zones.fire_trigger(engine, zone, foe, "start")
    assert [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]
    foe.saving_throws["CHA"] = 60
    hf.deepen_repeat_save(engine, foe)
    assert [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM], "a lower-CL target never auto-repeats"


def test_deepen_ends_when_the_field_ends(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, foe_talents=(TOUCH,))
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    zone = field(engine)
    put_marks(engine, owner, foe, zone, 2)
    zones.fire_trigger(engine, zone, foe, "start")
    assert [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]
    engine._end_concentration(owner, "TEST")
    assert not [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]


def test_deepen_ends_when_the_creature_leaves(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, foe_talents=(TOUCH,))
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    zone = field(engine)
    put_marks(engine, owner, foe, zone, 2)
    zones.fire_trigger(engine, zone, foe, "start")
    assert [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]
    foe.position = foe.position.model_copy(update={"x": 40})
    hf._reconcile_systems(engine)
    assert not [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]


def test_entering_the_field_makes_the_save(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    zone, foe = field(engine), engine.state.actors[FOE]
    assert not [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    zones.fire_trigger(engine, zone, foe, "enter")
    rolls = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert len(rolls) == 1
    assert [row.value for row in foe.modifiers.values() if row.target_field == "speed_ft"] == [-15]


def test_lower_source_cl_teleport_and_the_secret_authority_exception(acquired, tmp_path):
    service, project = acquired

    def second_void_cultivator(rows):
        for index, row in enumerate(rows):
            if row["actor_id"] == ALLY:
                rows[index] = compile_project_character(
                    service, project, owner_doc(service, project, name="Second Void"),
                    actor_id=ALLY, reaction_plan={"ask": True})

    places = {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}}
    combat, table, mid = fixture(tmp_path, [], cl=8, owner_bundle=owner_bundle(service, project),
                                 foe_sheet=foe_doc((EMPTY_STEP,), cl=8), positions=places,
                                 bundle_transform=second_void_cultivator, seed="HOLLOW-TELEPORT")
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, ally, foe = (engine.state.actors[key] for key in (OWNER, ALLY, FOE))
    zone = field(engine)
    # A hostile creature inside with a lower Source CL is refused unless the owner permits it.
    engine._active_action_source_id = action_of(engine, foe, EMPTY_STEP).source_definition_id
    assert hf.hollow_teleport(engine, foe, foe.position, foe.position.model_copy(update={"x": 8})) is False
    # The field's own owner is always permitted.
    assert hf.hollow_teleport(engine, owner, owner.position, owner.position.model_copy(update={"x": 5})) is None
    # A second Secret-authority cultivator at the field's CL passes the crossing rule...
    engine._active_action_source_id = action_of(engine, ally, PARENT + ".feature.void_step").source_definition_id
    assert hf.hollow_teleport(engine, ally, ally.position, ally.position.model_copy(update={"x": 5})) is None
    # ...and the Hollowing bar, which otherwise refuses any teleport regardless of CL.
    engine._apply_condition(ally, hf.TELEPORT_BAR, "test", owner.entity_id,
                            expires_on=hf._until_target_next_turn(ally),
                            data={"rule": {"hollow_teleport_bar": True}})
    assert hf.hollow_teleport(engine, ally, ally.position, ally.position.model_copy(update={"x": 5})) is None
    engine._active_action_source_id = action_of(engine, foe, EMPTY_STEP).source_definition_id
    assert hf.hollow_teleport(engine, ally, ally.position, ally.position.model_copy(update={"x": 5})) is False


def test_the_field_is_not_a_spirit_awakening_domain(acquired, tmp_path):
    from combat.ext import area_suppression

    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    zone = field(engine)
    assert zone.trigger_profile["name"] == "Hollow Field"
    assert "domain" not in area_suppression.kinds(engine, zone)
    assert (zone.trigger_profile.get("profile") or {}).get("domain") is None


# ------------------------------------------------------------------------------------------------ native hostility
def test_hostility_comes_from_the_native_team_fact(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    # The ally stands on the same team as the field's owner: inside the field,
    # but never a hostile creature the save or the hostile-only clauses touch.
    cast_field(combat, table, mid, at=(3, 8))
    prompts = advance_to(table, mid, ALLY)
    assert not [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.hollow_field"]
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert not [row for row in ally.modifiers.values() if row.target_field == "speed_ft"]
    assert hf._hostile_fields(engine, ally) == []
    # The field's sound/light clauses still apply inside for everyone.
    assert zones.muffled(engine, ally) is True


# ------------------------------------------------------------------------------------------------ default-inert guards
def test_wrong_owner_and_unrecorded_scar_are_inert(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    action = field_action(engine, engine.state.actors[OWNER])
    assert hf.owns(engine, engine.state.actors[OWNER]) is True
    assert hf.owns(engine, ally) is False
    assert hf.gate_candidates(engine, ally, None, action) is None
    # No field anywhere: every continuous hook is inert for ordinary creatures.
    assert hf.fields(engine) == []
    assert hf.hostile_cost(engine, ally, "test", {"resource:core.qi": 2}, {"resource:core.qi": 2}) is None
    assert hf.no_hostile_regain(engine, ally, "resource:core.qi", 2, "test") is None
    assert hf.halve_hostile_temp_hp(engine, ally, 8, engine.state.actors[FOE], "test", "temp_hp") is None
    # A loose feature id with a top-level scar is not an acquisition.
    loose = sheet([], cl=10)
    loose["spheres_and_talents"] = {"sphere_record_ids": [VOID], "learned_talent_record_ids": [FEATURE]}
    loose["path_and_subpath"] = {"void_scar": SCAR}
    bundle = compile_character(loose, actor_id=OWNER)
    row = next(item for item in bundle["action_catalog"]
               if (item.get("parameters", {}).get("typed") or {}).get("source") == FEATURE)
    assert row["parameters"]["typed"]["void_scar"] == ""
    # The inert row omits zone_spec entirely: the core candidate check does
    # `typed["zone_spec"].get(...)`, which would crash on an explicit None.
    assert "zone_spec" not in row["parameters"]["typed"]
    assert row["parameters"].get("inert") is True


# ------------------------------------------------------------------------------------------------ review round 3 regressions
def test_hollowing_teleport_bar_is_chosen_and_survives_table_reload(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, cha=1)
    cast_field(combat, table, mid)
    prompts = advance_to(table, mid, FOE, choices={"choice:needle.hollow_field": "no_teleport"})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.hollow_field"
               and any(row["id"] == "no_teleport" for row in p["choice"]["options"]) for p in prompts)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert any(c.condition_id == hf.TELEPORT_BAR for c in foe.conditions.values())
    # The actual player-facing save/choice was committed by the table; the bar is still
    # effective outside its source field and after Concentration ends.
    foe.position = foe.position.model_copy(update={"x": 40})
    assert hf.hollow_teleport(engine, foe, foe.position, foe.position) is False
    engine._end_concentration(owner, "TEST")
    assert hf.hollow_teleport(engine, foe, foe.position, foe.position) is False


def test_next_cost_penalty_is_chosen_and_survives_table_reload(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, cha=60)
    cast_field(combat, table, mid)
    prompts = advance_to(table, mid, FOE, choices={"choice:needle.hollow_field": "next_cost"})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.hollow_field"
               and any(row["id"] == "next_cost" for row in p["choice"]["options"]) for p in prompts)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert any(c.condition_id == hf.NEXT_COST for c in foe.conditions.values())
    engine._end_concentration(owner, "TEST")
    assert hf.fields(engine) == []
    pool = hf.CP_POOLS[0]
    answer = hf.hostile_cost(engine, foe, "technique", {pool: 1}, {pool: 1})
    assert answer is not None and answer[pool] == 2


def test_deepen_once_per_turn_is_keyed_by_turn_not_by_owner_turns(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, foe_talents=(TOUCH, NO_PURCHASE))
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    zone = field(engine)
    put_marks(engine, owner, foe, zone, 2)
    zones.fire_trigger(engine, zone, foe, "start")
    assert len(hf._deepen_records(zone)) == 1
    # A later turn in the same round (a different slot) is a new turn: a fresh Deepen is allowed.
    engine.state.current_slot_index += 1
    put_marks(engine, owner, foe, zone, 2)
    zones.fire_trigger(engine, zone, foe, "start")
    assert len(hf._deepen_records(zone)) == 2


# ------------------------------------------------------------------------------------------------ one Form, not every Form
GOLDEN_FORM = "tianxia.path.qi_cultivation.feature.golden_core_form"


def _give_forms(engine, creature, *keys):
    """Hold each Form as the real Golden Core Form condition qi_path writes on choice."""
    for key in keys:
        engine._apply_condition(creature, "condition:typed.golden_core_form", GOLDEN_FORM, creature.entity_id,
                                expires_on="UNTIL_REMOVED", data={"form": key, "label": key})


def test_deepen_suspends_only_the_chosen_golden_core_form(acquired, tmp_path):
    from combat.ext import qi_path
    service, project = acquired
    # No talents: the Forms are the only major systems on the target, so the Deepen choice is the Forms alone.
    combat, table, mid = fight(tmp_path, service, project, foe_talents=(), cl=13)
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    zone = field(engine)
    _give_forms(engine, foe, "circulating", "reservoir")
    assert qi_path.forms(foe) == ("circulating", "reservoir")
    put_marks(engine, owner, foe, zone, 2)
    zones.fire_trigger(engine, zone, foe, "start")
    systems = [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]
    assert len(systems) == 1 and systems[0].data["kind"] == "golden_core_form"
    assert systems[0].data["value"] == "circulating"
    # Exactly one Form is suspended; its sibling Form stays on the creature.
    assert qi_path.forms(foe) == ("reservoir",)
    engine._end_concentration(owner, "TEST")
    assert not [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]
    assert sorted(qi_path.forms(foe)) == ["circulating", "reservoir"]


# ------------------------------------------------------------------------------------------------ once per owner turn
def test_deepen_is_once_per_owner_turn_across_creatures(acquired, tmp_path):
    from combat.ext import void_touched_cultivator as void
    service, project = acquired
    combat, table, mid = fixture(
        tmp_path, [], cl=13, owner_bundle=owner_bundle(service, project),
        foe_sheet=foe_doc((TOUCH, NO_PURCHASE), cl=13), extra_foes=1,
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 6, "y": 6}}, seed="HOLLOW-FIELD")
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    second = next(a for a in engine.state.actors.values() if a.entity_id not in (OWNER, ALLY, FOE))
    zone = field(engine)
    second.position = foe.position
    second.saving_throws["CHA"] = foe.saving_throws["CHA"]
    _give_forms(engine, second, "stable")
    put_marks(engine, owner, foe, zone, 2)
    put_marks(engine, owner, second, zone, 2)
    zones.fire_trigger(engine, zone, foe, "start")
    assert len(hf._deepen_records(zone)) == 1
    # Same owner turn, a different creature: the owner's single Deepen was already used.
    zones.fire_trigger(engine, zone, second, "start")
    assert len(hf._deepen_records(zone)) == 1
    assert not [c for c in second.conditions.values() if c.condition_id == hf.SYSTEM]
    assert void.mark_count(second, owner.entity_id) == 2
    # A later owner turn allows the Deepen on the second creature.
    engine.state.current_slot_index += 1
    zones.fire_trigger(engine, zone, second, "start")
    assert len(hf._deepen_records(zone)) == 2
    assert [c for c in second.conditions.values() if c.condition_id == hf.SYSTEM]

