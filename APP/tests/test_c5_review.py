"""Focused C5 review regressions. No browsers or live data are used."""

import pytest
import copy
import json

from tests import test_riders_c5 as C


@pytest.fixture
def table_rules():
    # Round20 restored this loader: validate and use the real presentation path.
    import combat.tabletop_service as tabletop
    texts = json.loads((C.ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    assert tabletop._rules_texts() == texts


def _table(tmp_path, talents, *, spheres=(C.UNMAKING,), items=(C.DAO,), dc=100, mode="MANUAL", intermediary=False,
           cp=None, hp=2000):
    from combat.canonical import canonical_sha256
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    mine = C.compile_character(C._sheet(talents, items=items, spheres=spheres, dc=dc), actor_id=C.ME,
                               reaction_plan={"ask": True})
    foe = C.compile_character(C.t._sheet(None, [], {}, dc=dc), actor_id=C.AN)
    for bundle in (mine, foe):
        bundle["actor_template"].update(armor_class=0, maximum_hp=hp if bundle is mine else 2000,
                                        initiative_bonus=1000 if bundle is mine else -1000)
        if bundle is mine and cp is not None:
            for resource in bundle["actor_template"]["resources"]:
                if resource["resource_id"] == "resource:core.stamina":
                    resource["initial"] = cp
        for action in bundle["action_catalog"]:
            typed = action.get("parameters", {}).get("typed", {})
            if typed.get("numbers"):
                typed["numbers"]["attack_bonus"] = 100
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    bundles, actors = [mine, foe], [C.ME, C.AN]
    teams, positions = {C.ME: "team:a", C.AN: "team:b"}, {C.ME: {"x": 3, "y": 6}, C.AN: {"x": 4, "y": 6}}
    if intermediary:
        middle = C.compile_character(C.t._sheet(None, [], {}), actor_id="actor:factory.middle")
        middle["actor_template"].update(initiative_bonus=0, maximum_hp=2000, speed_ft=0)
        middle.pop("bundle_sha256", None)
        middle["bundle_sha256"] = canonical_sha256(middle)
        bundles.append(middle)
        actors.append(middle["actor_id"])
        teams[middle["actor_id"]], positions[middle["actor_id"]] = "team:a", {"x": 2, "y": 8}
    combat = CombatService(C.ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="C5-REVIEW", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": actors, "team_by_actor": teams, "starting_positions": positions})
    combat._read_metadata(session.match_id, session)
    metadata = combat._metadata_path(session.match_id)
    data = json.loads(metadata.read_text())
    data["participant_control_modes"][C.ME] = mode
    metadata.write_text(json.dumps(data))
    return combat, TabletopService(combat, tmp_path), session.match_id


def _act(combat, table, match_id, name, *, choices=None, target=None):
    menu = table.state(match_id)["menu"]
    candidate = next(c for c in combat.decision(match_id)["context"]["legal_candidates"]
                     if c["display_name"].lower() == name.lower()
                     and (target is None or target in c["target_ids"]))
    before = combat._load_session(match_id).engine.state.model_dump(mode="json")
    answers, prompts = [], []
    for _ in range(12):
        result = table.act(match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            from combat.gate5_service import CombatService
            loaded = CombatService(C.ROOT, combat.userdata_root)._load_session(match_id).engine
            assert loaded.state.model_dump(mode="json") == combat._load_session(match_id).engine.state.model_dump(mode="json")
            return loaded, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        prompts.append(prompt)
        source = prompt["context"]["reaction_source_id"]
        options = [o["id"] for o in prompt.get("choice", {}).get("options", [])]
        choose = (choices or {}).get(source.split(".")[-1])
        chosen = choose(options) if choose else options[:1]
        answers.append({**prompt["context"], "selection": "USE" if chosen else "DECLINE", "option_ids": chosen})
    raise AssertionError("table did not finish its choices")


def test_channel_crack_table_direct_and_delivered_attack_share_weapon(tmp_path, table_rules):
    combat, table, mid = _table(tmp_path, ["TAL_AXES_HEWING_STRIKE"], spheres=(C.UNMAKING, "tianxia.sphere.axes"),
                               items=({"item_id": "tianxia.mortal.weapon.fu", "name": "Fu", "quantity": 1},))
    for name in ("Fu (Short Axe) attack", "Fu (Short Axe) attack: Hewing Strike: Bite"):
        _act(combat, table, mid, "Ruin Channel")
        engine, prompts = _act(combat, table, mid, name, choices={"unmaking_cost": lambda options: C._kind(options, "crack")})
        assert any(p["context"]["reaction_source_id"].endswith("unmaking_cost") for p in prompts), (name, prompts, [(e.event_type, e.payload) for e in engine.events[-8:]])
        cracks = C.unmaking_channels.cracked_channels(engine.state.actors[C.ME])
        assert len(cracks) == 1
        weapon = next(iter(cracks))
        assert engine.action_catalog[weapon].display_name == "Fu (Short Axe) attack"
        _act(combat, table, mid, "End turn")
        _act(combat, table, mid, "End turn")
    assert cracks[weapon] == 2
    _act(combat, table, mid, "Ruin Channel")
    engine, _ = _act(combat, table, mid, "Fu (Short Axe) attack: Hewing Strike: Bite",
                     choices={"unmaking_cost": lambda o: C._kind(o, "crack")})
    assert any(c.data.get("disables_action") == weapon for c in engine.state.actors[C.ME].conditions.values())
    _act(combat, table, mid, "End turn")
    engine, _ = _act(combat, table, mid, "End turn")
    assert not any("Fu (Short Axe)" in c["display_name"] and "attack" in c["display_name"]
                   for c in combat.decision(mid)["context"]["legal_candidates"])
    from combat import ext
    assert ext.any_false("opportunity_allowed", engine, engine.state.actors[C.ME], engine.state.actors[C.AN])


def test_channel_opportunity_copy_and_unarmed_classification():
    from combat.typed_executor import Context, run_effects

    engine, me, foe = C._fight([], items=[C.DAO])
    base = next(a for a in engine.action_catalog.values() if a.display_name == "Dao (Saber / Broadsword) attack")
    delivery = base.model_copy(deep=True, update={"source_definition_id": "test:delivery"})
    delivery.parameters["typed"]["delivered_by"] = base.source_definition_id
    engine.action_catalog[delivery.source_definition_id] = delivery
    opportunity = delivery.model_copy(deep=True, update={"source_definition_id": "test:opportunity"})
    opportunity.parameters["typed"].pop("delivered_by")
    opportunity.parameters["typed"]["opportunity_of"] = delivery.source_definition_id
    C._use(engine, "Ruin Channel", None)
    C.unmaking.charged_hit(Context(engine, me, opportunity, None, opportunity.parameters["typed"], [foe], foe), foe)
    assert C.unmaking_channels.cracks(me, base.source_definition_id) == 1
    assert not C.unmaking_channels.cracks(me, delivery.source_definition_id)
    unarmed = next(a for a in engine.action_catalog.values() if a.display_name == "Shove: Prone")
    ctx = Context(engine, me, unarmed, None, unarmed.parameters["typed"], [foe], foe)
    assert C.unmaking_channels.channel_weapon_identity(ctx) is None
    me.resources[C.STRAIN] = 0
    C._use(engine, "Ruin Channel", None)
    C.unmaking.charged_hit(ctx, foe)
    assert me.resources[C.STRAIN] == 1


def test_devouring_dregs_recovers_crack_from_delivering_weapon():
    from combat.typed_executor import Context

    engine, me, foe = C._fight(["TAL_UNMAKING_DEVOURING_DREGS"], items=[C.DAO])
    base = next(a for a in engine.action_catalog.values() if a.display_name == "Dao (Saber / Broadsword) attack")
    delivery = base.model_copy(deep=True, update={"source_definition_id": "test:delivery"})
    delivery.parameters["typed"]["delivered_by"] = base.source_definition_id
    C.unmaking_channels.crack(engine, me, base.source_definition_id, 1, "test")
    me.resources[C.STRAIN] = 0
    engine._commit_damage(foe, 10000, "FORCE", "test", me.entity_id, None, reaction_depth=0)
    C.unmaking._devouring_dregs(Context(engine, me, delivery, None, delivery.parameters["typed"], [foe], foe), foe,
                               {"devouring_dregs"})
    assert C.unmaking_channels.cracks(me, base.source_definition_id) == 0


@pytest.fixture
def attack_die(monkeypatch):
    """Script only dice at the real attack seam, including deterministic table preview retries."""
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.h1_support import script
    die = [19]
    original = Gate4ControllerEngine._resolve_attack_spec
    def resolve(engine, *args, **kwargs):
        script(engine, [die[0], die[0], *([1] * 50)])
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", resolve)
    return die


def test_circle_cleaving_table_second_all_miss_never_offers_old_victim(tmp_path, table_rules, attack_die):
    combat, table, mid = _table(tmp_path, [C.SAB + "circle_cleaving_saber"], spheres=("tianxia.sphere.sabers",))
    engine, prompts = _act(combat, table, mid, "Circle-Cleaving Saber")
    assert C._gp(engine, engine.state.actors[C.AN])
    assert any(p["context"]["reaction_source_id"].endswith("choose_hit_target") for p in prompts)
    _act(combat, table, mid, "End turn")
    engine, _ = _act(combat, table, mid, "End turn")
    assert not C._gp(engine, engine.state.actors[C.AN])
    attack_die[0] = 1
    engine, prompts = _act(combat, table, mid, "Circle-Cleaving Saber")
    assert not C._gp(engine, engine.state.actors[C.AN])
    assert not any(p["context"]["reaction_source_id"].endswith("choose_hit_target") for p in prompts)


def test_circle_cleaving_only_current_hits_including_zero_damage_are_eligible():
    from combat.ext.sabers_riders import remember_choice_hits, choose_hit_target
    from combat.typed_executor import Context
    engine, me, foes = C._crowd([C.SAB + "circle_cleaving_saber"], foes=2)
    action = next(a for a in engine.action_catalog.values() if a.display_name == "Circle-Cleaving Saber")
    effect = next(row for row in action.parameters["typed"]["effects"] if row["type"] == "choose_hit_target")
    first = Context(engine, me, action, None, action.parameters["typed"], foes)
    remember_choice_hits(first, foes[0], True, False)
    choose_hit_target(first, effect)
    assert C._gp(engine, foes[0])
    second = Context(engine, me, action, None, action.parameters["typed"], foes)
    remember_choice_hits(second, foes[0], False, False)
    remember_choice_hits(second, foes[1], True, False)
    choose_hit_target(second, effect)
    assert second.damage_cache["_choose_hit_targets"] == [foes[1].entity_id]
    assert C._gp(engine, foes[1])


def _table_move(combat, table, mid, x, y):
    candidate = next(c for c in combat.decision(mid)["context"]["legal_candidates"] if c["kind"] == "MOVE"
                     and c.get("destination") == {"x": x, "y": y})
    return _act(combat, table, mid, candidate["display_name"])


def _blood_thread(engine, target=C.AN):
    from combat.typed_executor import mark_condition_id
    marks = [c for c in engine.state.actors[target].conditions.values()
             if c.condition_id == mark_condition_id("Blood Thread", C.ME)]
    assert len(marks) == 1
    return marks[0]


@pytest.mark.parametrize("followup", ["decline", "successful_save"])
def test_crimson_mark_table_later_thread_does_not_shorten_extension(tmp_path, table_rules, attack_die, followup):
    combat, table, mid = _table(tmp_path, [C.BL + "crimson_mark"], spheres=("tianxia.sphere.blood",))
    engine, prompts = _act(combat, table, mid, "Blood Thread", target=C.AN)
    assert any(p["context"]["reaction_source_id"].endswith("crimson_mark") for p in prompts)
    original = _blood_thread(engine).model_dump(mode="json")
    from combat.ext.effect_durations import round_token
    assert original["expires_on"] == round_token(engine, 600)  # Printed one hour, counted from this application.
    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "End turn")
    with pytest.MonkeyPatch.context() as dice:
        if followup == "successful_save":
            from combat.gate2_rolls import DeterministicRollAuthority
            original_d20 = DeterministicRollAuthority.d20
            def succeed(roller, *, modifier, actor_id, reason, mode="NORMAL"):
                # Script only save dice; preserve real save adjudication and retained roll events.
                return original_d20(roller, modifier=modifier + (1000 if reason.startswith("SAVE:") else 0),
                                    actor_id=actor_id, reason=reason, mode=mode)
            dice.setattr(DeterministicRollAuthority, "d20", succeed)
        # The foe the Thread lands on is asked whether it will bear the paid hour and refuses, so the printed
        # Constitution saving throw is what decides the new hour; a passed save defeats only that new hour and
        # leaves the one already bought standing.
        engine, prompts = _act(combat, table, mid, "Blood Thread", target=C.AN,
            choices={"crimson_mark": lambda options: ["skip"]} if followup != "successful_save"
                    else {"crimson_mark_willing": lambda options: ["refuse"]})
    assert _blood_thread(engine).model_dump(mode="json") == original
    _act(combat, table, mid, "End turn")
    engine, _ = _act(combat, table, mid, "End turn")
    assert _blood_thread(engine).model_dump(mode="json") == original


def test_ordinary_blood_thread_table_still_expires_without_crimson_mark(tmp_path, table_rules, attack_die):
    from combat.ext.blood_riders import bears_thread
    combat, table, mid = _table(tmp_path, [], spheres=("tianxia.sphere.blood",))
    engine, prompts = _act(combat, table, mid, "Blood Thread", target=C.AN)
    assert not prompts
    assert _blood_thread(engine).expires_on == "START_OF_MARKER_NEXT_TURN"
    _act(combat, table, mid, "End turn")
    engine, _ = _act(combat, table, mid, "End turn")
    assert not bears_thread(engine, engine.state.actors[C.ME], engine.state.actors[C.AN])


def test_crimson_mark_willing_table_extends_without_save_and_later_decline_preserves_it(tmp_path, table_rules):
    combat, table, mid = _table(tmp_path, [C.BL + "crimson_mark"], spheres=("tianxia.sphere.blood",), intermediary=True)
    target = "actor:factory.middle"
    engine, prompts = _act(combat, table, mid, "Blood Thread: willing creature", target=target)
    # The owner is offered the hour, then the creature it would land on is asked whether it will bear it: the
    # printed save is for an unwilling creature, so willingness is that creature's own answer (this harness
    # takes the first option, which is the acceptance). The hour still needs no save.
    assert [p["context"]["reaction_source_id"].split(".")[-1] for p in prompts] == ["crimson_mark", "crimson_mark_willing"]
    assert prompts[-1]["context"]["reactor_id"] == target
    original = _blood_thread(engine, target).model_dump(mode="json")
    from combat.ext.effect_durations import round_token
    assert original["expires_on"] == round_token(engine, 600)
    assert not any(e.event_type == "SAVE_ROLLED" for e in engine.events)
    for _ in range(3):
        _act(combat, table, mid, "End turn")
    engine, prompts = _act(combat, table, mid, "Blood Thread: willing creature", target=target,
                           choices={"crimson_mark": lambda options: ["skip"]})
    assert _blood_thread(engine, target).model_dump(mode="json") == original


def test_crimson_mark_ai_table_extends_automatically_and_zero_cp_refresh_preserves_it(tmp_path, table_rules, attack_die, monkeypatch):
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate5_service import CombatService
    from tests.test_tabletop_hunt6 import on_hold
    combat, table, mid = _table(tmp_path, [C.BL + "crimson_mark"], spheres=("tianxia.sphere.blood",), mode="LOCAL_AUTO")
    # Select the triggering action only; real AI reaction/choice resolution remains intact.
    def choose(context):
        candidate = next(c for c in context.legal_candidates if c.display_name == "Blood Thread" and C.AN in c.target_ids)
        return ManualControllerAdapter(lambda context: (candidate.candidate_id, ())).choose_primary_action(context)
    monkeypatch.setattr(combat.controller, "choose_primary_action", choose)
    assert table.auto_step(mid, 0, [])["status"] == "COMMITTED"
    engine = CombatService(C.ROOT, tmp_path)._load_session(mid).engine
    original = _blood_thread(engine).model_dump(mode="json")
    from combat.ext.effect_durations import round_token
    assert original["expires_on"] == round_token(engine, 600)
    metadata = combat._metadata_path(mid)
    data = json.loads(metadata.read_text())
    data["participant_control_modes"][C.ME] = "MANUAL"
    metadata.write_text(json.dumps(data))
    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "End turn")
    def empty_cp(engine):
        for pool in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance"):
            if pool in engine.state.actors[C.ME].resources:
                actor = engine.state.actors[C.ME]
                engine._spend_resource(actor, pool, actor.resources[pool], "test:empty_cp")
    with monkeypatch.context() as setup:
        on_hold(setup, empty_cp)
        _act(combat, table, mid, "Hold position")
    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "End turn")
    data["participant_control_modes"][C.ME] = "LOCAL_AUTO"
    metadata.write_text(json.dumps(data))
    assert table.auto_step(mid, 0, [])["status"] == "COMMITTED"
    engine = CombatService(C.ROOT, tmp_path)._load_session(mid).engine
    assert _blood_thread(engine).model_dump(mode="json") == original


@pytest.mark.parametrize("ordinary_move", [False, True])
def test_black_vein_step_table_endpoint_and_ordinary_movement_close_window(tmp_path, table_rules, attack_die, ordinary_move):
    combat, table, mid = _table(tmp_path, ["TAL_UNMAKING_BLACK_VEIN_STEP"])
    _act(combat, table, mid, "Overdraw: ready")
    engine, _ = _act(combat, table, mid, "Black Trace: Sting", target=C.AN)
    assert "black_vein_step" in engine.state.actors[C.ME].turn_flags, [(e.event_type, e.target_ids, str(e.payload)[:160]) for e in engine.events if e.event_type in ("ATTACK_ROLLED", "DAMAGE_COMMITTED")]
    engine, _ = _table_move(combat, table, mid, 3, 5)
    engine, _ = _table_move(combat, table, mid, 3, 6)
    before = engine.state.actors[C.ME].resources[C.STRAIN]
    name = "Black-Vein Step: unarmed strike"
    assert any(c["display_name"] == name for c in combat.decision(mid)["context"]["legal_candidates"]), (engine.state.actors[C.ME].turn_flags, engine.state.actors[C.ME].movement_remaining_ft)
    if ordinary_move:
        engine, _ = _table_move(combat, table, mid, 3, 7)
        assert not any(c["display_name"] == name for c in combat.decision(mid)["context"]["legal_candidates"])
        assert engine.state.actors[C.ME].turn_flags["black_vein_step_closed"]
    else:
        engine, _ = _act(combat, table, mid, name)
        assert engine.state.actors[C.ME].resources[C.STRAIN] == before + 1
        assert not any(c["display_name"] == name for c in combat.decision(mid)["context"]["legal_candidates"])


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_armed_channel_black_trace_never_triggers_shock(tmp_path, table_rules, attack_die, monkeypatch, mode):
    combat, table, mid = _table(tmp_path, ["TAL_UNMAKING_MERIDIAN_RUIN_SHOCK"])
    engine, _ = _act(combat, table, mid, "Ruin Channel")
    before = dict(engine.state.actors[C.ME].resources)
    engine, prompts = _channel_test_hit(combat, table, mid, "Black Trace: Sting", mode, monkeypatch)
    assert not any("Meridian Ruin Shock" in p["moment"] for p in prompts)
    assert engine.state.actors[C.ME].resources == before
    assert any(c.condition_id == C.unmaking.CHANNEL for c in engine.state.actors[C.ME].conditions.values())
    assert C._damage(engine.events, ".ruin_channel", C.AN) == 0
    assert not {"condition:typed.no_cp_regain", "condition:typed.reaction_denied",
                "condition:typed.concentration_mode"}.intersection(c.condition_id for c in engine.state.actors[C.AN].conditions.values())


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("charged_hit", [False, True])
def test_shred_requires_actual_channel_on_other_sphere_hit(tmp_path, table_rules, attack_die, monkeypatch, mode, charged_hit):
    from tests.test_tabletop_hunt6 import on_hold
    combat, table, mid = _table(tmp_path, ["TAL_UNMAKING_SHRED_THE_TEMPORARY_SHAPE"],
                               spheres=(C.UNMAKING, "tianxia.sphere.blood", C.IRON_FIST))
    with monkeypatch.context() as setup:
        on_hold(setup, lambda engine: C._summoned(engine.state.actors[C.AN]))
        _act(combat, table, mid, "Hold position")
    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "End turn")
    engine, _ = _act(combat, table, mid, "Ruin Channel")
    before = dict(engine.state.actors[C.ME].resources)
    engine, prompts = _channel_test_hit(combat, table, mid, "Unarmed Strike (Iron Fist)" if charged_hit else "Blood Thread", mode, monkeypatch)
    assert (C._damage(engine.events, ".shred_the_temporary_shape", C.AN) > 0) == charged_hit
    assert (C._damage(engine.events, ".ruin_channel", C.AN) > 0) == charged_hit
    assert any(c.condition_id == C.unmaking.CHANNEL for c in engine.state.actors[C.ME].conditions.values()) != charged_hit
    if mode == "MANUAL":
        assert any("Shred the Temporary Shape" in p["moment"] for p in prompts) == charged_hit
    if not charged_hit:
        assert engine.state.actors[C.ME].resources == before


def _channel_test_hit(combat, table, mid, name, mode, monkeypatch):
    if mode == "MANUAL":
        return _act(combat, table, mid, name, target=C.AN,
                    choices={"unmaking_cost": lambda o: C._kind(o, "strain"), "unmaking_option": lambda o: ["use"]})
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate5_service import CombatService
    metadata = combat._metadata_path(mid)
    data = json.loads(metadata.read_text())
    data["participant_control_modes"][C.ME] = "LOCAL_AUTO"
    metadata.write_text(json.dumps(data))
    # Select only the attack under test; retain real AI rider eligibility and decisions.
    def choose(context):
        candidate = next(c for c in context.legal_candidates if c.display_name == name and C.AN in c.target_ids)
        return ManualControllerAdapter(lambda context: (candidate.candidate_id, ())).choose_primary_action(context)
    with monkeypatch.context() as selection:
        selection.setattr(combat.controller, "choose_primary_action", choose)
        assert table.auto_step(mid, 0, [])["status"] == "COMMITTED"
    loaded = CombatService(C.ROOT, combat.userdata_root)._load_session(mid).engine
    assert loaded.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
    return loaded, []


def test_meridian_ruin_shock_table_asks_and_persists_chosen_rider(tmp_path, table_rules, attack_die):
    combat, table, mid = _table(tmp_path, ["TAL_UNMAKING_MERIDIAN_RUIN_SHOCK"], spheres=(C.UNMAKING, C.IRON_FIST))
    _act(combat, table, mid, "Ruin Channel")
    engine, prompts = _act(combat, table, mid, "Unarmed Strike (Iron Fist)",
                          choices={"unmaking_cost": lambda o: C._kind(o, "strain"), "unmaking_option": lambda o: ["use"]})
    assert any("Meridian Ruin Shock" in p["moment"] for p in prompts)
    foe = engine.state.actors[C.AN]
    assert {"condition:typed.no_cp_regain", "condition:typed.reaction_denied", "condition:typed.concentration_mode"} <= {c.condition_id for c in foe.conditions.values()}
    assert engine.state.actors[C.ME].resources[C.STRAIN] == 2


def test_shred_table_choice_commits_and_reloads(tmp_path, table_rules, attack_die, monkeypatch):
    from tests.test_tabletop_hunt6 import on_hold
    combat, table, mid = _table(tmp_path, ["TAL_UNMAKING_SHRED_THE_TEMPORARY_SHAPE"])
    with monkeypatch.context() as setup:
        on_hold(setup, lambda engine: C._summoned(engine.state.actors[C.AN]))
        _act(combat, table, mid, "Hold position")
    _act(combat, table, mid, "End turn")
    engine, _ = _act(combat, table, mid, "End turn")
    before = engine.state.actors[C.ME].resources["resource:core.stamina"]
    engine, prompts = _act(combat, table, mid, "Black Trace: Sting", target=C.AN,
                          choices={"unmaking_option": lambda o: ["use"]})
    assert any("Shred the Temporary Shape" in p["moment"] for p in prompts)
    assert C._damage(engine.events, ".shred_the_temporary_shape", C.AN) > 0
    assert engine.state.actors[C.ME].resources["resource:core.stamina"] == before - 1


def test_second_ruin_form_backlash_healing_lock_table_reload(tmp_path, table_rules, monkeypatch):
    from tests.test_tabletop_hunt6 import on_hold
    combat, table, mid = _table(tmp_path, ["TAL_UNMAKING_SECOND_RUIN_FORM_BLACK_PALM_VESSEL"])
    _act(combat, table, mid, "Second Ruin Form: Black Palm Vessel")
    with monkeypatch.context() as setup:
        on_hold(setup, lambda engine: C.unmaking.gain_strain(engine, engine.state.actors[C.ME], 6, "test:backlash"))
        engine, _ = _act(combat, table, mid, "Hold position")
    me = engine.state.actors[C.ME]
    assert any(m.target_field == "healing_reduction" and m.value == "none" for m in me.modifiers.values())
    assert me.resources[C.STRAIN] == 3


@pytest.mark.parametrize("cp,hp,after", [(0, 60, (0, 30)), (3, 60, (3, 30)), (0, 1, None), (6, 6, (1, 1))])
def test_sacrifice_table_pays_missing_or_chosen_cp_with_hp_and_survives_commit_reload(tmp_path, table_rules, monkeypatch, cp, hp, after):
    """Crimson Sacrifice ("pay all"): Heart-Seizing Grip costs 6 CP; each replaced CP costs 5 HP, at most 2 x PB, never below 1 HP.
    Rider lane C17: lock round 7's payment_substitution port pays CP the cultivator lacks too (it used to be a GM line)."""
    from tests.test_tabletop_hunt6 import on_hold
    combat, table, mid = _table(tmp_path, [C.BL + "heart_seizing_grip"], spheres=("tianxia.sphere.blood",), cp=cp, hp=hp)
    with monkeypatch.context() as setup:
        on_hold(setup, lambda engine: C._thread(engine, engine.state.actors[C.ME], engine.state.actors[C.AN]))
        _act(combat, table, mid, "Hold position")
    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "End turn")
    engine, _ = _act(combat, table, mid, "Crimson Sacrifice: pay all the CP you may with HP")
    assert not [e for e in engine.events if e.event_type == "GM_RIDER" and "Crimson Sacrifice" in str(e.payload)]
    offered = any(c["display_name"] == "Heart-Seizing Grip" for c in combat.decision(mid)["context"]["legal_candidates"])
    assert offered == (after is not None)
    if after is None:  # 1 HP: nothing can be paid with HP, and 0 CP cannot pay the talent
        return
    engine, prompts = _act(combat, table, mid, "Heart-Seizing Grip", target=C.AN)
    asked = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:alternative_payment"]
    assert len(asked) == 1 and "Crimson Sacrifice" in json.dumps(asked[0]) and "HP" in json.dumps(asked[0])
    assert (engine.state.actors[C.ME].resources["resource:core.stamina"], engine.state.actors[C.ME].current_hp) == after
    assert any(e.event_type == "ALTERNATIVE_PAYMENT_COMMITTED" for e in engine.events)


@pytest.mark.parametrize("command,speed", [("push", 20), ("push", 40), ("pull", 30)])
def test_puppet_table_manual_ask_at_ai_creatures_turn_start_commit_reload(tmp_path, table_rules, monkeypatch, command, speed):
    from tests.test_tabletop_hunt6 import on_hold
    combat, table, mid = _table(tmp_path, [C.BL + "blood_puppet"], spheres=("tianxia.sphere.blood",))
    def prepare(engine):
        me, foe = engine.state.actors[C.ME], engine.state.actors[C.AN]
        engine._commit_damage(foe, 1000, "FORCE", "test:setup", C.ME, None, reaction_depth=0)
        C._thread(engine, me, foe)
        engine._add_modifier(foe, "test:speed", "speed_ft", "ADD", speed - foe.speed_ft, "ALL_MOVEMENT", expires_on="UNTIL_REMOVED")
        foe.position = type(foe.position)(x=8, y=5)  # Avoid the map hazard in this distance test.
        engine._append_event("MOVEMENT_COMMITTED", "test:setup", actor_id=foe.entity_id,
                             payload={"destination": {"x": 8, "y": 5}, "path": [], "cost_ft": 0, "forced": True})
    with monkeypatch.context() as setup:
        on_hold(setup, prepare)
        _act(combat, table, mid, "Hold position")
    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "Blood Puppet")
    metadata = combat._metadata_path(mid)
    data = json.loads(metadata.read_text())
    data["participant_control_modes"][C.AN] = "LOCAL_AUTO"
    metadata.write_text(json.dumps(data))
    engine, prompts = _act(combat, table, mid, "End turn", choices={"blood_puppet": lambda o: [command]})
    assert engine.state.current_actor_id == C.AN
    puppet = next(p for p in prompts if p["context"]["reaction_source_id"].endswith("blood_puppet"))
    assert "Blood Puppet" in puppet["moment"] and engine.state.actors[C.AN].display_name in puppet["moment"]
    assert abs(engine.state.actors[C.AN].position.x - 8) == (speed // 2) // 5


@pytest.mark.parametrize("owner_mode", ["MANUAL", "LOCAL_AUTO"])
def test_puppet_choice_on_ai_step_pauses_for_manual_owner_and_auto_owner_decides(tmp_path, table_rules, monkeypatch, owner_mode):
    from tests.test_tabletop_hunt6 import on_hold
    combat, table, mid = _table(tmp_path, [C.BL + "blood_puppet"], spheres=("tianxia.sphere.blood",), intermediary=True)
    def prepare(engine):
        engine._commit_damage(engine.state.actors[C.AN], 1000, "FORCE", "test:setup", C.ME, None, reaction_depth=0)
        C._thread(engine, engine.state.actors[C.ME], engine.state.actors[C.AN])
    with monkeypatch.context() as setup:
        on_hold(setup, prepare)
        _act(combat, table, mid, "Hold position")
    for _ in range(3):
        _act(combat, table, mid, "End turn")
    _act(combat, table, mid, "Blood Puppet")
    _act(combat, table, mid, "End turn")  # intermediary's AI turn will advance into the puppet's turn
    metadata = combat._metadata_path(mid)
    data = json.loads(metadata.read_text())
    data["participant_control_modes"].update({C.ME: owner_mode, C.AN: "LOCAL_AUTO", "actor:factory.middle": "LOCAL_AUTO"})
    metadata.write_text(json.dumps(data))
    seen = []
    for _ in range(8):
        before = combat._load_session(mid).engine.state.model_dump(mode="json")
        result = table.auto_step(mid, 0, [])
        if result["status"] == "REACTION_REQUIRED":
            assert owner_mode == "MANUAL"
            assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
            prompt = result["reaction"]
            assert prompt["context"]["reaction_source_id"] == "choice:needle.blood_puppet"
            seen.append(prompt)
            result = table.auto_step(mid, 0, [{**prompt["context"], "selection": "USE", "option_ids": ["no_reactions"]}])
        assert result["status"] == "COMMITTED", result
        engine = combat._load_session(mid).engine
        if engine.state.current_actor_id == C.AN:
            break
    assert engine.state.current_actor_id == C.AN
    assert bool(seen) == (owner_mode == "MANUAL")
    expected = "condition:typed.reaction_denied" if seen else "condition:typed.prone"
    assert any(c.condition_id == expected for c in engine.state.actors[C.AN].conditions.values())
    from combat.gate5_service import CombatService
    assert CombatService(C.ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == engine.state.model_dump(mode="json")


@pytest.mark.parametrize("cp,hp,after", [(0, 60, (0, 30)), (3, 60, (3, 30)), (0, 1, None)])
def test_sacrifice_covers_cp_the_cultivator_lacks_when_its_hp_allows(cp, hp, after):
    L1, engine, me, ally, foe = C._bleeder(["heart_seizing_grip"], qi=cp)
    me.current_hp = hp
    C._thread(engine, me, foe)
    events = C._cast_as(L1, engine, "Crimson Sacrifice: pay all the CP you may with HP", None)
    assert not any(e.event_type == "GM_RIDER" and "Crimson Sacrifice" in str(e.payload) for e in events)
    assert bool(C._offered(L1, engine, "Heart-Seizing Grip", foe.entity_id)) == (after is not None)
    if after is not None:
        C._cast_paying(L1, engine, "Heart-Seizing Grip", C.AN)
        assert (me.resources[C.QI], me.current_hp) == after
    else:
        assert (me.resources[C.QI], me.current_hp) == (cp, hp)


def test_sacrifice_respects_the_one_hp_floor():
    L1, engine, me, ally, foe = C._bleeder(["heart_seizing_grip"], qi=6)
    me.current_hp = 6
    C._thread(engine, me, foe)
    C._cast_as(L1, engine, "Crimson Sacrifice: pay all the CP you may with HP", None)
    C._cast_paying(L1, engine, "Heart-Seizing Grip", C.AN)
    assert (me.resources[C.QI], me.current_hp) == (1, 1)


@pytest.mark.parametrize("command", ["push", "pull"])
def test_puppet_movement_uses_each_creatures_current_speed_without_mutating_commands(command):
    from combat.ext import blood_riders

    original = copy.deepcopy(blood_riders.PUPPET_COMMANDS)
    for speed in (20, 40, 30):
        L1, engine, me, ally, foe = C._bleeder(["blood_puppet"], dc=50)
        C._thread(engine, me, foe)
        foe.current_hp = 200
        C._cast_as(L1, engine, "Blood Puppet", foe.entity_id)
        C._answers(engine, {"blood_puppet": lambda options: [command]})
        for current_speed in (speed, speed + 10):
            foe.speed_ft = current_speed
            me.position = type(me.position)(x=2, y=6)
            foe.position = type(foe.position)(x=8, y=6)
            start = foe.position.x
            C._turn_of(engine, foe.entity_id)
            distance = (current_speed // 2) // 5
            assert abs(foe.position.x - start) == distance
            assert blood_riders.PUPPET_COMMANDS == original
