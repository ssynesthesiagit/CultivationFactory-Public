"""Table regressions for the R13 review, using real saved transactions."""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.gate2_runtime_content import AN
from tests.test_riders_lane13 import ROOT, ME, THORN, bundle
from combat.canonical import canonical_sha256


def saved_table(tmp_path, compiled, foes=(AN,), seed="R13-REVIEW"):
    for row in compiled:
        row.pop("bundle_sha256", None)
        row["bundle_sha256"] = canonical_sha256(row)
    service = CombatService(ROOT, tmp_path)
    actors = [ME, *foes]
    session = service.persistence.create_match(match_seed=seed, typed_bundles=tuple(compiled),
        roster_setup={"primary_actor_ids": actors,
            "team_by_actor": {a: "team:a" if a == ME else "team:b" for a in actors},
            "starting_positions": {a: {"x": 3 if a == ME else 4 + i // 2, "y": 6 + i // 2}
                                   for i, a in enumerate(actors)}})
    mid = session.match_id
    for actor in actors:
        service.set_controller_mode(mid, actor_id=actor, controller_mode="MANUAL")
    return service, TabletopService(service, tmp_path), mid


def act(table, mid, group_name=None, replies=()):
    state = table.state(mid)
    menu = state["menu"]
    candidate = menu["end_turn"] if group_name is None else next(
        g for g in menu["actions"] if g["label"] == group_name)["options"][0]["candidate_id"]
    return table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], list(replies))


def turn(table, mid, actor):
    for _ in range(4):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        act(table, mid)
    raise AssertionError("actor did not get a turn")


@pytest.mark.parametrize("success", [False, True])
def test_legacy_restraint_escape_table_commit_reload(tmp_path, success):
    compiled = bundle([THORN + "impaling_garden"], dc=1 if success else 50)
    garden = next(a for a in compiled["action_catalog"] if a["display_name"] == "Impaling Garden")
    # Isolate the printed source-bound restraint from damage/save randomness.
    # Its actual escape action/check and the table transaction are unmodified.
    garden["parameters"]["typed"]["effects"] = [
        {"type": "action_restraint", "ability": "str", "applies_to": "target"}]
    garden["target_kind"] = "HOSTILE_ENTITY"
    garden["range_ft"] = 15
    garden["radius_ft"] = None
    garden["costs"] = []
    service, table, mid = saved_table(tmp_path, [compiled])
    turn(table, mid, ME)
    assert act(table, mid, "Impaling Garden")["status"] == "COMMITTED"
    turn(table, mid, AN)
    before = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert AN not in before.typed_actor_ids
    assert any(c.data.get("action_escape") for c in before.state.actors[AN].conditions.values())
    result = act(table, mid, "Escape source restraint")
    if result["status"] == "REACTION_REQUIRED":
        reaction = result["reaction"]
        reply = {**reaction["context"], "selection": "USE",
                 "option_ids": [reaction["choice"]["options"][0]["id"]]}
        result = act(table, mid, "Escape source restraint", [reply])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    foe = loaded.engine.state.actors[AN]
    check = next(e.payload for e in reversed(loaded.engine.events) if e.event_type == "CHECK_ROLLED")
    assert check["success"] is success and check["ability"] == "STR"
    assert check["actor"]["modifier"] == -1
    assert not foe.action_available
    assert bool([c for c in foe.conditions.values() if c.data.get("action_escape")]) is not success
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("success", [False, True])
def test_living_painting_own_strength_escape_table_commit_reload(tmp_path, success):
    owner = bundle(["tianxia.subpath.qi.painting_cultivator.feature.living_painting"],
                   ability_mods={"STR": 4})
    tiger = next(s for s in owner["summons"] if s["summon"]["group"] == "living_painting_tiger")
    summon_id = tiger["actor_id"]
    # Begin with the form already manifested; isolate the escape/command table flow.
    tiger["summon"]["arrives"] = "start"
    enemy = bundle([THORN + "impaling_garden"], actor_id=AN, dc=1 if success else 50)
    garden = next(a for a in enemy["action_catalog"] if a["display_name"] == "Impaling Garden")
    garden["parameters"]["typed"]["effects"] = [
        {"type": "action_restraint", "ability": "str", "applies_to": "target"}]
    garden.update(target_kind="HOSTILE_ENTITY", range_ft=30, radius_ft=None, costs=[])
    service, table, mid = saved_table(tmp_path, [owner, enemy], seed="R13-SUMMON-ESCAPE")
    turn(table, mid, AN)
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"] == "Impaling Garden")
    candidate = next(c for c in group["options"] if summon_id in c["target_ids"])
    result = table.act(mid, candidate["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    turn(table, mid, ME)
    assert act(table, mid, "Command Living Painting")["status"] == "COMMITTED"
    turn(table, mid, summon_id)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    form = loaded.engine.state.actors[summon_id]
    assert form.saving_throws["STR"] == 4
    assert form.summon["ability_mods"]["STR"] == 0
    assert all(type(v) is int for v in form.summon["ability_mods"].values())
    assert form.summon["commanded"] and form.action_available
    assert any(c.data.get("action_escape") for c in form.conditions.values())
    result = act(table, mid, "Escape source restraint")
    if result["status"] == "REACTION_REQUIRED":
        reaction = result["reaction"]
        reply = {**reaction["context"], "selection": "USE",
                 "option_ids": [reaction["choice"]["options"][0]["id"]]}
        result = act(table, mid, "Escape source restraint", [reply])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    form = loaded.engine.state.actors[summon_id]
    check = next(e.payload for e in reversed(loaded.engine.events) if e.event_type == "CHECK_ROLLED")
    assert check["actor"]["modifier"] == 0
    assert check["ability"] == "STR" and check["success"] is success
    assert form.saving_throws["STR"] == 4 and form.summon["ability_mods"]["STR"] == 0
    assert not form.action_available
    assert bool([c for c in form.conditions.values() if c.data.get("action_escape")]) is not success
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_check_modifier_preserves_old_compiled_numbers_and_roster_fallback():
    from types import SimpleNamespace
    from combat.ability_checks import ability_modifier

    actor = SimpleNamespace(summon=None, saving_throws={"STR": -1, "DEX": 4})
    assert ability_modifier(actor, "STR", numbers={"ability_mods": {"STR": 3}}) == 3
    assert ability_modifier(actor, "STR") == -1
    assert ability_modifier(actor, "DEX", fallback=2) == 2
    actor.summon = {"ability_mods": {"STR": 0, "DEX": -2}}
    assert ability_modifier(actor, "STR", numbers={"ability_mods": {"STR": 4}}) == 0
    assert ability_modifier(actor, "DEX", fallback=2) == -2


@pytest.mark.parametrize("initial", [0, 4])
@pytest.mark.parametrize("old_bundle", [False, True, "gm_miss_charge"])
def test_unbroken_bolt_real_legacy_misses_remain_gm_only_across_rounds_and_reload(tmp_path, initial, old_bundle):
    """Native misses work with current and both historical passive kinds.

    Round 21 Lock4 (f80502a8) enabled native miss notifications; Round 22's
    C7 merge (de0c0817) compiles melee_miss_charge instead of gm_miss_charge.
    Construct legacy kinds from that current generator row, retaining the
    historical node id for the lead's integration selection.
    """
    from tests.test_riders_lane13 import PREFIX
    owner = bundle([PREFIX + "body_of_the_unbroken_bolt"])
    owner["actor_template"]["armor_class"] = 1000
    pool = "resource:named.thunder_charge"
    resource = next(r for r in owner["actor_template"]["resources"] if r["resource_id"] == pool)
    resource["initial"] = initial
    generator = next(r for r in owner["typed_passives"]
                     if r.get("feature_id") == PREFIX + "body_of_the_unbroken_bolt"
                     and r.get("kind") == "melee_miss_charge")
    expected_kind = ("miss_charge" if old_bundle is True else
                     "gm_miss_charge" if old_bundle else "melee_miss_charge")
    generator["kind"] = expected_kind
    service, table, mid = saved_table(tmp_path, [owner], seed="R13-LEGACY-MISS")
    for round_index in range(2):
        turn(table, mid, AN)
        assert act(table, mid, "Paired Bi Shou Assault")["status"] == "COMMITTED"
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        stored_generators = [r for r in loaded.engine.typed_passive_rows[ME]
                             if r.get("feature_id") == generator["feature_id"]
                             and r.get("resource_id") == pool]
        assert len(stored_generators) == 1
        assert stored_generators[0]["kind"] == expected_kind
        attacks = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == AN]
        assert attacks and all(not e.payload["provisional_hit"] for e in attacks)
        assert loaded.engine.state.actors[ME].resources[pool] == min(initial + round_index + 1, 4)
        gains = [e for e in loaded.engine.events if e.event_type == "RESOURCE_GAINED"
                 and e.actor_id == ME and e.payload.get("resource_id") == pool]
        assert len(gains) == (round_index + 1 if initial == 0 else 0)
        assert all(e.payload["gained"] == 1 and
                   e.source_definition_id == PREFIX + "body_of_the_unbroken_bolt" for e in gains)
        assert not any(c.condition_id.startswith("condition:typed.path_rider_round")
                       for c in loaded.engine.state.actors[ME].conditions.values())
        act(table, mid)
        turn(table, mid, ME)
        act(table, mid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.round_number >= 2
    assert not any(e.event_type == "GM_RIDER" and "Miss-to-Charge is not automated" in e.payload["rider"]
                   for e in loaded.engine.events)
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ally", [False, True])
@pytest.mark.parametrize("reduction", [0, 10])
@pytest.mark.parametrize("ai_turn", [False, True])
def test_sweeping_table_reposition_offers_defenses_and_honors_reduction(tmp_path, ally, reduction, ai_turn):
    from tests.test_riders_lane13 import BOJUTSU, STAFF
    from combat.gate2_runtime_content import LEE
    from combat.gate4_adapters import ManualControllerAdapter

    owner = bundle([BOJUTSU + "sweeping_strike"], items=[STAFF])
    victim = bundle([], actor_id=AN)
    victim["actor_template"]["armor_class"] = 0
    reactor = bundle([], actor_id=LEE) if ally else victim
    reactor["typed_reactions"].append({"block": "generic", "feature_id": "test:forced_brace",
        "name": "Forced movement brace", "kind": "ally_forced_moved" if ally else "forced_moved",
        "ask": True, "range_ft": 30, "costs": [], "numbers": {"pb": 4},
        "effects": [{"type": "temp_hp", "flat": 3, "applies_to": "self"},
                    {"type": "forced_movement", "distance_ft": reduction}]})
    foes = (AN, LEE) if ally else (AN,)
    service, table, mid = saved_table(tmp_path, [owner, victim, *([reactor] if ally else [])], foes)
    turn(table, mid, ME)
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["source_definition_id"].endswith(".weapon.gun"))
    candidate = next(c for c in group["options"] if AN in c["target_ids"])["candidate_id"]
    if ai_turn:
        service.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
        real = service.controller
        class StaffAttacker:
            def choose_primary_action(self, context):
                chosen = next(c for c in context.legal_candidates
                              if c.source_definition_id.endswith(".weapon.gun") and AN in c.target_ids)
                return ManualControllerAdapter(lambda _context: (chosen.candidate_id, ())).choose_primary_action(context)
            def choose_reaction(self, context):
                from combat.gate2_runtime_models import ReactionDecision
                if context.reactor_id != ME:
                    return real.choose_reaction(context)
                source = context.reaction_source_id
                option = ("Reposition within reach" if source.endswith("bojutsu_result") else
                          "cell:4,7" if source.endswith("bojutsu_reposition") else "Use Sweeping Strike")
                decision = ReactionDecision(checkpoint=context.checkpoint, reactor_id=ME,
                    reaction_source_id=source, selection="USE", option_ids=(option,))
                return ManualControllerAdapter(lambda _context: ("", ()),
                    reaction_chooser=lambda _context: decision).choose_reaction(context)
            def __getattr__(self, name):
                return getattr(real, name)
        service.controller = StaffAttacker()
    replies = []
    def submit():
        if ai_turn:
            return table.auto_step(mid, state["last_sequence"], replies)
        return table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], replies)
    before = CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json")
    seen_defense = False
    result = submit()
    while result["status"] == "REACTION_REQUIRED":
        reaction = result["reaction"]
        context = reaction["context"]
        source = context["reaction_source_id"]
        if source.endswith("bojutsu_result"):
            options = ["Reposition within reach"]
        elif source.endswith("bojutsu_reposition"):
            assert all(o["label"] == "Move to " + o["id"].removeprefix("cell:")
                       for o in reaction["choice"]["options"])
            options = ["cell:4,7"]
        elif source == "reaction:typed.test:forced_brace":
            seen_defense = True
            assert context["reactor_id"] == (LEE if ally else AN)
            assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
            options = []
        else:
            options = [reaction["choice"]["options"][0]["id"]]
        replies.append({**context, "selection": "USE", "option_ids": options})
        result = submit()
    assert seen_defense and result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    defender = loaded.engine.state.actors[LEE if ally else AN]
    assert not defender.reaction_available and defender.temporary_hp == 3
    position = loaded.engine.state.actors[AN].position
    assert (position.x, position.y) == ((4, 6) if reduction else (4, 7))
    event = next(e for e in loaded.engine.events if e.event_type == "REACTION_RESOLVED"
                 and e.payload.get("checkpoint") == "FORCED_MOVEMENT")
    assert event.payload["distance_before"] == 5
    assert event.payload["distance_after"] == (0 if reduction else 5)
    assert loaded.mechanical.replay()["status"] == "PASS"
