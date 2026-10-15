"""Review regressions for C9: exact attack lifetime and printed Air rules."""
import pytest

from test_riders_c9 import (air_fight, answers, rig, turn, use, bow, weapon_attack,
                           cast_at, ME, AN, ALLY, FOE2, ROOT, sheet, authority)
from combat.gate2_runtime_models import ActionIntent, Position
from combat.ext.air_currents import ARROW_PENDING


@pytest.mark.parametrize("blocked", ["invisible", "blinded", "no_reactions", "wall"])
def test_arrow_guard_requires_sight_and_reaction_permission_after_turn_start(blocked):
    engine = air_fight(["TAL_AIR_ARROW_TURNING_BREATH"], ally=True)
    guard, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    ally.armor_class = -50
    if blocked == "no_reactions":
        engine._apply_condition(guard, "condition:typed.denied", "test", AN, expires_on="UNTIL_REMOVED",
                                data={"rule": {"no_reactions": True}})
    elif blocked == "wall":
        engine.grid.blocked.add((4, 6))
        engine.__dict__.pop("_wall_base", None)
    else:
        holder = ally if blocked == "invisible" else guard
        engine._apply_condition(holder, "condition:typed." + blocked, "test", AN, expires_on="UNTIL_REMOVED")
    turn(engine, ME)
    assert guard.reaction_available
    asked = answers(engine, {})
    turn(engine, AN)
    rig(engine, 1)
    use(engine, bow(engine), target=ALLY)
    assert not any(a.endswith("arrow_turning") for a in asked)


def test_sovereign_free_arrow_prompt_and_unavailable_reaction():
    engine = air_fight(["TAL_AIR_ARROW_TURNING_BREATH", "TAL_AIR_SKY_SOVEREIGN_INCARNATION"], cl=17, ally=True)
    use(engine, "Sky-Sovereign Incarnation")
    engine.state.actors[ME].reaction_available = False
    engine.state.actors[ALLY].armor_class = -50
    seen = []
    from combat.gate2_runtime_models import ReactionDecision
    def provider(request):
        seen.append(request)
        return ReactionDecision(**{k: request[k] for k in ("checkpoint", "reactor_id", "reaction_source_id")},
                                selection="USE", option_ids=("use",)), None
    engine.set_reaction_provider(provider)
    turn(engine, AN)
    rig(engine, 1)
    use(engine, bow(engine), target=ALLY)
    request = next(r for r in seen if r["reaction_source_id"].endswith("arrow_turning"))
    assert "No Reaction" in str(request) and "Use your Reaction" not in str(request)
    assert not engine.state.actors[ME].reaction_available


def test_empty_lung_records_are_caster_scoped():
    engine = air_fight(["TAL_AIR_EMPTY_LUNG_EDICT"], cl=15, foe_ids=["TAL_AIR_EMPTY_LUNG_EDICT"], second_foe=True)
    engine.state.actors[AN].team_id = engine.state.actors[ME].team_id
    use(engine, "Empty-Lung Edict", target=FOE2)
    engine.state.actors[ME].action_available = True
    assert not any(c.display_name == "Empty-Lung Edict" and FOE2 in c.target_ids for c in engine.legal_candidates())
    turn(engine, AN)
    use(engine, "Empty-Lung Edict", target=FOE2)
    from combat.typed_executor import mark_condition_id
    held = {c.condition_id for c in engine.state.actors[FOE2].conditions.values()}
    assert {mark_condition_id("Empty-Lung Edict", owner) for owner in (ME, AN)} <= held
    engine.state.actors[AN].action_available = True
    assert not any(c.display_name == "Empty-Lung Edict" and FOE2 in c.target_ids for c in engine.legal_candidates())


@pytest.mark.parametrize("ac,natural,steps", [(17, 15, True), (200, 15, False), (17, 1, False), (-50, 15, False)])
def test_cloud_step_requires_penalty_caused_miss(ac, natural, steps):
    engine = air_fight(["TAL_AIR_CLOUD_SLEEVE_GUARD"], foe_at=(4, 6))
    cast_at(engine, "Gather Current: Lift", (8, 8))
    me = engine.state.actors[ME]
    me.armor_class = ac
    original = engine.roller.d20
    def d20(**kwargs):
        record = original(**kwargs)
        if kwargs["reason"].startswith("ATTACK:"):
            return record.model_copy(update={"dice": (natural,), "natural_result": natural,
                                             "total": natural + kwargs["modifier"], "discarded": ()})
        return record
    engine.roller.d20 = d20
    turn(engine, AN)
    start = me.position
    events = use(engine, weapon_attack(engine, AN), target=ME)
    assert (me.position != start) is steps


@pytest.mark.parametrize("feet,prone", [(10, False), (20, True)])
def test_steady_foot_counts_path_distance_on_difficult_ground(feet, prone):
    engine = air_fight(["TAL_AIR_STORM_WITHOUT_DIRECTION"], cl=15, dc=50, foe_at=(10, 6))
    use(engine, "Storm Without Direction: No Steady Foot")
    # A separate difficult area doubles cost without changing traveled distance.
    from combat import zones
    zone = next(z for z in zones.typed_zones(engine) if z.active)
    zone.trigger_profile["difficult"] = "all"
    turn(engine, AN)
    foe = engine.state.actors[AN]
    foe.movement_remaining_ft = 60
    candidate = next(c for c in engine.legal_candidates() if c.kind.value == "MOVE" and c.destination == Position(x=10 + feet // 5, y=6))
    engine.execute_intent(ActionIntent(intent_id="review-move", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                      state_version=candidate.state_version, actor_id=AN, destination=candidate.destination))
    assert any(c.condition_id == "condition:typed.prone" for c in foe.conditions.values()) is prone


def test_gale_push_successful_save_collision():
    engine = air_fight(["TAL_AIR_GALE_PUSH"], dc=-50, foe_at=(8, 6))
    engine.state.actors[AN].armor_class = -50
    engine.grid.blocked.update({(9, 6), (10, 6)})
    engine.__dict__.pop("_wall_base", None)
    rig(engine)
    name = next(c.display_name for c in engine.legal_candidates() if c.display_name.startswith("Wind Lash: Push + Gale Push"))
    events = use(engine, name, target=AN)
    assert any(e.event_type == "SAVE_ROLLED" and e.payload.get("success") for e in events)
    assert any(c.condition_id == "condition:typed.prone" for c in engine.state.actors[AN].conditions.values())


def test_steady_foot_checks_movement_that_exits_the_area():
    from combat.gate2_grid import SquareGrid
    engine = air_fight(["TAL_AIR_STORM_WITHOUT_DIRECTION"], cl=15, dc=50, foe_at=(26, 6))
    engine.grid = SquareGrid({"width_squares": 40, "height_squares": 10, "square_size_ft": 5,
                             "starting_positions": {}, "terrain_regions": []})
    use(engine, "Storm Without Direction: No Steady Foot")
    turn(engine, AN)
    candidate = next(c for c in engine.legal_candidates() if c.kind.value == "MOVE" and c.destination == Position(x=30, y=6))
    engine.execute_intent(ActionIntent(intent_id="review-exit", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                      state_version=candidate.state_version, actor_id=AN, destination=candidate.destination))
    assert any(c.condition_id == "condition:typed.prone" for c in engine.state.actors[AN].conditions.values())


def test_cloud_step_prompt_names_the_miss_defender_and_free_movement():
    from combat.gate2_runtime_models import ReactionDecision
    engine = air_fight(["TAL_AIR_CLOUD_SLEEVE_GUARD"], foe_at=(4, 6))
    cast_at(engine, "Gather Current: Lift", (8, 8))
    engine.state.actors[ME].armor_class = 17
    rig(engine)
    requests = []
    def provider(request):
        requests.append(request)
        spec = request.get("extension_choice") or {}
        return ReactionDecision(**{k: request[k] for k in ("checkpoint", "reactor_id", "reaction_source_id")},
            selection="USE", option_ids=tuple((spec.get("option_ids") or [])[-1:])), None
    engine.set_reaction_provider(provider)
    turn(engine, AN)
    use(engine, weapon_attack(engine, AN), target=ME)
    request = next(r for r in requests if r["reaction_source_id"].endswith("cloud_sleeve_step"))
    text = str(request)
    assert "Cloud-Sleeve Guard" in text and "attack miss" in text
    assert engine.state.actors[ME].display_name in text
    assert "up to 5 feet" in text and "no additional Reaction or Qi cost" in text
    assert "attack hits" not in text


@pytest.mark.parametrize("trigger_ai,guard_ai", [(False, False), (True, False), (False, True)])
@pytest.mark.parametrize("ac_defense", [False, True])
def test_arrow_table_commit_reload_and_later_attack(monkeypatch, tmp_path, trigger_ai, guard_ai, ac_defense):
    """Real accepted table attacks, off-turn Ask me, reload and mechanical replay.

    Only dice are fixed, through the roller test double; no engine patching.
    A pending benefit is scoped to one roll and consumed or cleared before commit.
    """
    from test_riders_c9 import _portable, BOW
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from combat.tabletop import ButtonStore
    from combat.gate2_rolls import DeterministicRollAuthority
    guard, defender, archer = [FACTORY_ACTOR_PREFIX + s for s in ("22222222", "11111111", "33333333")]
    _portable(tmp_path, "22222222", ["TAL_AIR_ARROW_TURNING_BREATH"], sphere="tianxia.sphere.air", ac=100)
    _portable(tmp_path, "11111111", ["tianxia.path.qi_cultivation.feature.qi_armor"] if ac_defense else [], sphere=None)
    _portable(tmp_path, "33333333", [], sphere=None, items=(BOW,))
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions("11111111", {"mode": "ask"}, set())
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions("22222222", {"mode": "ask"}, set())
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "C9 review yard", "width_squares": 15, "height_squares": 10,
        "walls": [], "starts": {"team1": [[3, 4], [3, 5]], "team2": [[8, 5]]}})
    mid = service.create_factory_match(project_ids=["22222222", "11111111"], opponent_actor_ids=[archer],
        control_modes={a: "MANUAL" for a in (guard, defender, archer)}, arena_id="battlefield:map.c9-review-yard",
        match_seed="C9-ARROW-REVIEW")["match_id"]
    table = TabletopService(service, tmp_path)
    def reload():
        return CombatService(ROOT, tmp_path)._load_session(mid)
    def end():
        state = table.state(mid); menu = state["menu"]
        return table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    while table.state(mid)["menu"]["actor_id"] != archer:
        end()
    if guard_ai:
        service.set_controller_mode(mid, actor_id=guard, controller_mode="LOCAL_AUTO")
    if trigger_ai:
        service.set_controller_mode(mid, actor_id=archer, controller_mode="LOCAL_AUTO")
    original = DeterministicRollAuthority.d20
    def fixed(self, **kwargs):
        record = original(self, **kwargs)
        total = 15 if kwargs["reason"].startswith("ATTACK:") else 16 if kwargs["reason"].startswith("CHECK:TAL_AIR_ARROW_TURNING") else None
        if total is not None:
            return record.model_copy(update={"dice": (15,), "natural_result": 15, "modifier": total - 15, "total": total, "discarded": ()})
        return record
    monkeypatch.setattr(DeterministicRollAuthority, "d20", fixed)
    def attack(reactions):
        state = table.state(mid); menu = state["menu"]
        if trigger_ai:
            return table.auto_step(mid, state["last_sequence"], reactions=reactions)
        option = next(o for g in menu["actions"] if g["label"].startswith("Gong Jian")
                      for o in g["options"] if defender in o.get("target_ids", []))
        return table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], reactions)
    saw_arrow = False
    for _ in range(10):
        before = reload().engine.state.model_dump(mode="json")
        replies = []
        result = attack(replies)
        while result["status"] == "REACTION_REQUIRED":
            prompt = result["reaction"]
            arrow = str(prompt).find("Arrow-Turning Breath") >= 0
            saw_arrow |= arrow
            assert reload().engine.state.model_dump(mode="json") == before
            replies.append({**prompt["context"], "selection": "USE", "option_ids": ["use"] if arrow else []})
            result = attack(replies)
        if any(e.event_type == "ATTACK_ROLLED" for e in reload().engine.events):
            break
    assert result["status"] == "COMMITTED"
    loaded = reload()
    applied = [e for e in loaded.engine.events if e.event_type == "CONDITION_APPLIED" and e.payload.get("condition_id") == ARROW_PENDING]
    assert applied
    assert saw_arrow is (not guard_ai)
    assert not any(c.condition_id == ARROW_PENDING for a in loaded.engine.state.actors.values() for c in a.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"
    hits = [e for e in loaded.engine.events if e.event_type == "DAMAGE_COMMITTED" and defender in e.target_ids]
    assert bool(hits) is (not ac_defense)
    # The cleared benefit cannot affect an unrelated later damage packet after disk reload.
    from combat.ext.air_currents import arrow_turning_reduction
    assert arrow_turning_reduction(loaded.engine, loaded.engine.state.actors[defender], 20, "later-technique", archer) is None
    # Take another actual bow attack after reloading; decline fresh reactions.
    for actor_id in (guard, defender, archer):
        service.set_controller_mode(mid, actor_id=actor_id, controller_mode="MANUAL")
    trigger_ai = False
    end()
    while table.state(mid)["menu"]["actor_id"] != archer:
        end()
    start = len(reload().engine.events)
    replies = []
    result = attack(replies)
    while result["status"] == "REACTION_REQUIRED":
        replies.append({**result["reaction"]["context"], "selection": "DECLINE", "option_ids": []})
        result = attack(replies)
    assert result["status"] == "COMMITTED"
    loaded = reload()
    events = loaded.engine.events[start:]
    rolled = sum(int(e.payload.get("total") or 0) for e in events if e.event_type == "DAMAGE_ROLLED")
    committed = sum(int(e.payload.get("hp_damage") or 0) for e in events if e.event_type == "DAMAGE_COMMITTED" and defender in e.target_ids)
    assert committed == rolled > 0
    assert loaded.mechanical.replay()["status"] == "PASS"
