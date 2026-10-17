"""Iron Marrow's optional survival save covers native no-intent damage at the table."""
import copy
import json
import zipfile

import pytest

from combat.ext import karma_riders, riders_metal
from combat import ext
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install
from tests.test_zones import ROOT, SHEET
from tests.r1i_service_support import force_ai_candidate
from tests.r10_fixup_support import cast_sender

FEATURE = "tianxia.talent.metal.indestructible_iron_marrow_sutra"
OWNER = FACTORY_ACTOR_PREFIX + "aaaaaaaa"
FOE = FACTORY_ACTOR_PREFIX + "bbbbbbbb"


def add_event_probe(monkeypatch, callback):
    """Inject native damage without removing the production life-state hooks."""
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', ()), callback])


def fight(monkeypatch, tmp_path, *, cl=10, succeeds=True, lethal=True, enemy_attack=False, foe_hp=80):
    for project in ("aaaaaaaa", "bbbbbbbb"):
        sheet = copy.deepcopy(SHEET)
        owner = project == "aaaaaaaa"
        sheet["identity"].update(display_name="Iron Monk" if owner else "Practice Rival",
                                 cultivation_level=cl)
        sheet["spheres_and_talents"] = {"sphere_record_ids": ["tianxia.sphere.metal"] if owner else [],
            "learned_talent_record_ids": [FEATURE] if owner else []}
        sheet["ability_scores_and_statistics"].update(hit_points={"maximum": 80 if owner else foe_hp},
            technique_save_dc=10, primary_resource={"name": "Qi", "maximum": 100})
        sheet["equipment"] = [] if owner else [{"starting_kit": {
            "items": [{"item_id": "tianxia.mortal.weapon.jian"}]}}]
        path = tmp_path / "portable_characters" / project / "current.zip"
        path.parent.mkdir(parents=True)
        with zipfile.ZipFile(path, "w") as zipped:
            zipped.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    install(monkeypatch, "d20_result", lambda *args: {
        "source_id": "test:save", "operation": "replace", "natural_result": 20 if succeeds else 1})

    def prepare(engine, kind, kwargs):
        if kind == "HOLD_POSITION_COMMITTED" and kwargs["actor_id"] == OWNER:
            owner = engine.state.actors[OWNER]
            if enemy_attack:
                engine._commit_damage(owner, owner.current_hp + owner.temporary_hp - 2, "FORCE",
                                      "test:already-wounded", FOE, None, reaction_depth=0)
                return
            # A real, evented Fate Deferred obligation arrives through its native
            # turn_end consumer, which calls _commit_damage with intent=None.
            engine._apply_condition(owner, karma_riders.DEFERRED, karma_riders.DEFERRED_ID, FOE,
                expires_on="UNTIL_REMOVED", data={"amount": owner.current_hp + owner.temporary_hp + 5
                    if lethal else 1, "type": "FORCE", "due": owner.turns_started})
    add_event_probe(monkeypatch, prepare)
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "Marrow yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    mid = service.create_factory_match(project_ids=["aaaaaaaa"], opponent_actor_ids=[FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, arena_id="battlefield:map.marrow-yard",
        match_seed="C17-MARROW-FLOOR")["match_id"]
    table = TabletopService(service, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert cast_sender(service, table, mid, "Indestructible Iron Marrow Sutra")()["status"] == "COMMITTED"
    assert act(table, mid, "system:combat.hold_position")["status"] == "COMMITTED"
    return service, table, mid


@pytest.mark.parametrize("case", ["use", "decline", "failed", "auto", "nonlethal"])
def test_native_no_intent_payment_pause_commit_reload(monkeypatch, tmp_path, case):
    service, table, mid = fight(monkeypatch, tmp_path, succeeds=case != "failed", lethal=case != "nonlethal")
    before = service._load_session(mid).engine.state.model_dump(mode="json")
    menu = table.state(mid)["menu"]
    args = (mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)
    if case == "auto":
        force_ai_candidate(service, mid, OWNER, menu["end_turn"])
        result = table.auto_step(mid, 0)
    else:
        result = table.act(*args)
        if case != "nonlethal":
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            text = json.dumps(prompt)
            assert all(word in text for word in ("Indestructible Iron Marrow Sutra", "Iron Monk", "Fate Deferred",
                                                "Constitution", "1 HP", "no action or resource"))
            assert service._load_session(mid).engine.state.model_dump(mode="json") == before
            service = CombatService(ROOT, tmp_path)
            table = TabletopService(service, tmp_path)
            answer = {**prompt["context"], "selection": "DECLINE" if case == "decline" else "USE",
                      "option_ids": [] if case == "decline" else ["save"]}
            result = table.act(*args, [answer])
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    owner = engine.state.actors[OWNER]
    survives = case in ("use", "auto")
    assert owner.current_hp == (1 if survives else 80 if case == "nonlethal" else 0)
    # New table fights retain an unconscious, dying actor until death saves
    # settle it; declining or failing the Sutra does not remove that actor.
    assert owner.active
    if case in ('decline', 'failed'):
        assert owner.life_state == "DYING"
    states = [c for c in owner.conditions.values() if c.condition_id == riders_metal.MARROW]
    assert bool(states) == (not survives)
    if states:
        assert states[0].data["attempt_round"] == (before["round_number"] if case == "failed" else 0)
    events = [e for e in engine.events if e.sequence > before["event_sequence"]]
    assert len([e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id.endswith(FEATURE)]) == int(case in ("use", "failed", "auto"))
    assert len([e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == karma_riders.DEFERRED_ID]) == 1
    assert not any(c.condition_id == karma_riders.DEFERRED for c in owner.conditions.values())
    assert owner.resources == before["actors"][OWNER]["resources"]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("selection", ["hit", "spare", "auto", "terminal"])
def test_nascent_thorns_choose_hostiles_after_success(monkeypatch, tmp_path, selection):
    service, table, mid = fight(monkeypatch, tmp_path, cl=15, foe_hp=1 if selection == "terminal" else 80)
    before = service._load_session(mid).engine.state.model_copy(deep=True)
    menu = table.state(mid)["menu"]
    args = (mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)
    if selection == "auto":
        force_ai_candidate(service, mid, OWNER, menu["end_turn"])
        result = table.auto_step(mid, 0)
    else:
        result = table.act(*args)
        assert result["status"] == "REACTION_REQUIRED"
        answer = {**result["reaction"]["context"], "selection": "USE", "option_ids": ["save"]}
        result = table.act(*args, [answer])
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert {o["id"] for o in prompt["choice"]["options"]} == {FOE}
        assert all(text in json.dumps(prompt) for text in ("Iron Monk", "Practice Rival", "10 feet", "Piercing"))
        assert service._load_session(mid).engine.state == before
        thorn_answer = {**prompt["context"], "selection": "DECLINE" if selection == "spare" else "USE",
                        "option_ids": [] if selection == "spare" else [FOE]}
        table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        result = table.act(*args, [answer, thorn_answer])
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert engine.state.actors[OWNER].current_hp == 1
    assert not any(c.condition_id == riders_metal.MARROW for c in engine.state.actors[OWNER].conditions.values())
    events = [e for e in engine.events if e.sequence > before.event_sequence]
    assert len([e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id.endswith(FEATURE)]) == 1
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert len(damage) == int(selection != "spare")
    if damage:
        assert damage[0].payload["damage_type"] == "PIERCING"
        assert engine.state.actors[FOE].current_hp == max(0, before.actors[FOE].current_hp - damage[0].payload["hp_damage"])
    if selection == "terminal":
        # Nested no-intent thorns kill outright when the excess reaches max HP;
        # the global natural-20 fixture must never resurrect this dead target.
        assert damage[0].payload['hp_damage'] - before.actors[FOE].current_hp >= before.actors[FOE].maximum_hp
        assert not engine.state.actors[FOE].active
    assert (engine.state.terminal_result is not None) == (selection == "terminal")
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("packet", ["no_intent", "final_reduction", "temporary", "unowned"])
def test_floor_is_after_defenses_and_inert_without_lethal_owned_state(monkeypatch, packet):
    from tests.test_riders_lane4 import _metal, _cast
    from combat.gate2_runtime_content import AN
    engine, owner, _ = _metal(FEATURE, cl=10)
    if packet != "unowned":
        _cast(engine, "Indestructible Iron Marrow Sutra", exact=True)
    owner.current_hp = 2
    owner.temporary_hp = 10 if packet == "temporary" else 0
    owner.saving_throws["CON"] = 500
    if packet == "final_reduction":
        install(monkeypatch, "final_damage", lambda *args: {"amount": 1})
    before = len(engine.rolls)
    engine._commit_damage(owner, 3, "FORCE", "test:packet", AN, None, reaction_depth=0)
    assert len(engine.rolls) - before == int(packet == "no_intent")
    assert owner.current_hp == (0 if packet == "unowned" else 2 if packet == "temporary" else 1)


def test_native_massive_damage_keeps_production_lifecycle_after_reload(monkeypatch, tmp_path):
    """A damage probe must retain the production massive-damage listeners."""
    service, table, mid = fight(monkeypatch, tmp_path, lethal=False, foe_hp=1)
    before = service._load_session(mid).engine.state.event_sequence

    def native_packet(engine, kind, kwargs):
        if kind == 'TURN_ENDED' and kwargs['actor_id'] == OWNER:
            engine._commit_damage(engine.state.actors[FOE], 2, 'FORCE',
                                  'test:native_massive', OWNER, None, reaction_depth=0)

    add_event_probe(monkeypatch, native_packet)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    foe = loaded.engine.state.actors[FOE]
    assert foe.current_hp == 0 and not foe.active
    events = [e for e in loaded.engine.events if e.sequence > before]
    assert any(e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == 'test:native_massive'
               and e.payload['hp_damage'] == 2 for e in events)
    assert not any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in events)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize("owner_roll, source_roll, expected_distance", [(20, 1, 0), (10, 10, 0), (1, 20, 10)])
def test_active_marrow_opposes_forced_movement(monkeypatch, owner_roll, source_roll, expected_distance):
    from combat import typed_reactions
    from tests.test_riders_lane4 import _cast, _metal

    engine, owner, foe = _metal(FEATURE, cl=10)
    _cast(engine, "Indestructible Iron Marrow Sutra", exact=True)
    natural = {owner.entity_id: owner_roll, foe.entity_id: source_roll}
    install(monkeypatch, "d20_result", lambda _engine, roll, _intent: {
        "source_id": "test:forced_movement_contest", "operation": "replace",
        "natural_result": natural[roll.actor_id]})

    assert typed_reactions.on_forced_movement(engine, owner, foe, 10) == expected_distance
    rolls = [r for r in engine.rolls if r.reason.endswith(("Metal Check", "forced movement"))]
    assert len(rolls) == 2
    assert rolls[0].actor_id == owner.entity_id and rolls[1].actor_id == foe.entity_id
    assert (rolls[0].total >= rolls[1].total) == (expected_distance == 0)
    if expected_distance == 0:
        rider = next(e for e in engine.events if e.event_type == "GM_RIDER"
                     and "Indestructible Iron Marrow Sutra" in e.payload.get("rider", ""))
        assert all(part in rider.payload["rider"] for part in
                   ("3 CP", "1 minute", owner.display_name, foe.display_name,
                    "forced movement", "Metal Check"))


def test_active_marrow_blocks_unattributed_forced_movement():
    from combat import typed_reactions
    from tests.test_riders_lane4 import _cast, _metal

    engine, owner, _foe = _metal(FEATURE, cl=10)
    _cast(engine, "Indestructible Iron Marrow Sutra", exact=True)
    before = len(engine.rolls)
    assert typed_reactions.on_forced_movement(engine, owner, None, 10) == 0
    assert len(engine.rolls) == before


@pytest.mark.parametrize("attacker_mode", ["MANUAL", "AI"])
@pytest.mark.parametrize("owner_wins", [False, True])
@pytest.mark.parametrize("check_effects", [False, True])
def test_forced_push_opposed_check_commits_and_replays_at_table(
        monkeypatch, tmp_path, attacker_mode, owner_wins, check_effects):
    """A typed Wind Lash push must resolve Iron Marrow through table persistence."""
    from tests.test_riders_c9 import _portable

    wind = FACTORY_ACTOR_PREFIX + "wind"
    owner = FACTORY_ACTOR_PREFIX + "owner"
    _portable(tmp_path, "wind", ["TAL_AIR_GALE_PUSH"], dc=60, sphere="tianxia.sphere.air")
    _portable(tmp_path, "owner", [FEATURE], dc=10, sphere="tianxia.sphere.metal")
    if check_effects:
        def source_check_effects(engine, event_type, kwargs):
            if event_type == "INTENT_ACCEPTED" and kwargs.get("actor_id") == wind:
                subject = engine.state.actors[wind]
                engine._apply_condition(subject, "condition:typed.needle_shadow_strike", "test:shadow-strike",
                                        owner, expires_on="END_OF_HOLDER_NEXT_TURN")
                engine._apply_condition(subject, "condition:typed.check_mode", "test:all-check-disadvantage",
                    owner, expires_on="END_OF_HOLDER_NEXT_TURN",
                    data={"rule": {"check_mode": {"ALL": "DISADVANTAGE"}}})
        install(monkeypatch, "event", source_check_effects)
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "Marrow contest", "width_squares": 16,
        "height_squares": 10, "walls": [], "starts": {"team1": [[3, 5]], "team2": [[8, 5]]}})
    mid = service.create_factory_match(project_ids=["wind"], opponent_actor_ids=[owner],
        control_modes={wind: "MANUAL" if attacker_mode == "MANUAL" else "LOCAL_AUTO", owner: "MANUAL"},
        arena_id="battlefield:map.marrow-contest",
        match_seed=f"C17-MARROW-{attacker_mode}-{owner_wins}")["match_id"]
    table = TabletopService(service, tmp_path)

    def act(candidate_id):
        state = table.state(mid)
        return table.act(mid, candidate_id, state["menu"]["decision_id"],
                         state["menu"]["state_version"], state["last_sequence"])

    # The Sutra is activated on its owner's turn and remains active for the push.
    for _ in range(8):
        state = table.state(mid)
        if state["menu"]["actor_id"] == owner:
            break
        assert act(state["menu"]["end_turn"])["status"] == "COMMITTED"
    assert state["menu"]["actor_id"] == owner
    assert cast_sender(service, table, mid, "Indestructible Iron Marrow Sutra")()["status"] == "COMMITTED"

    # Advance to Wind Lash's turn; force only the two opposed-check d20s. The
    # separate attack/save rolls are deterministic hits and failed resistance.
    for _ in range(8):
        state = table.state(mid)
        if state["menu"]["actor_id"] == wind:
            break
        assert act(state["menu"]["end_turn"])["status"] == "COMMITTED"
    assert state["menu"]["actor_id"] == wind
    check_naturals = {owner: 20 if owner_wins else 1, wind: 1 if owner_wins else 20}
    def d20_result(_engine, roll, _intent):
        reason = str(roll.reason)
        if "Metal Check" in reason:
            return {"source_id": "test:marrow_table_contest", "operation": "replace",
                    "natural_result": check_naturals[owner]}
        if "forced movement" in reason:
            return {"source_id": "test:marrow_table_contest", "operation": "replace",
                    "natural_result": check_naturals[wind]}
        if roll.actor_id == wind:
            return {"source_id": "test:marrow_table_attack", "operation": "replace", "natural_result": 20}
        return {"source_id": "test:marrow_table_save", "operation": "replace", "natural_result": 1}
    install(monkeypatch, "d20_result", d20_result)

    if attacker_mode == "MANUAL":
        group = next(g for g in state["menu"]["actions"] if g["label"] == "Wind Lash: Push")
        candidate_id = next(o["candidate_id"] for o in group["options"] if owner in o["target_ids"])
    else:
        candidates = CombatService(ROOT, tmp_path)._load_session(mid).engine.legal_candidates()
        candidate_id = next(c.candidate_id for c in candidates if c.display_name == "Wind Lash: Push"
                            and owner in c.target_ids)
    before = service._load_session(mid).engine.events[-1].sequence
    if attacker_mode == "AI":
        force_ai_candidate(service, mid, wind, candidate_id)
        assert table.auto_step(mid, 0)["status"] == "COMMITTED"
    else:
        assert act(candidate_id)["status"] == "COMMITTED"

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    moved = loaded.engine.state.actors[owner]
    assert (moved.position.x, moved.position.y) == ((8, 5) if owner_wins else (9, 5))
    later = [e for e in loaded.engine.events if e.sequence > before]
    forced = [e for e in later if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == owner]
    assert len(forced) == int(not owner_wins)
    assert len([r for r in loaded.engine.rolls if "Metal Check" in r.reason]) == 1
    assert len([r for r in loaded.engine.rolls if "forced movement" in r.reason]) == 1
    if check_effects:
        source_roll = next(r for r in loaded.engine.rolls if "forced movement" in r.reason)
        accepted = next(e for e in later if e.event_type == "INTENT_ACCEPTED" and e.actor_id == wind)
        numbers = (loaded.engine.action_catalog[accepted.source_definition_id].parameters.get("typed") or {}).get("numbers") or {}
        assert source_roll.modifier == loaded.engine.state.actors[wind].proficiency_bonus + int(numbers.get("key_mod") or 0) - 2
        assert source_roll.mode == "DISADVANTAGE"
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ai_turn", [False, True])
@pytest.mark.parametrize("selection", ["save", "decline"])
def test_manual_owner_is_asked_on_enemy_manual_and_ai_turns(monkeypatch, tmp_path, ai_turn, selection):
    service, table, mid = fight(monkeypatch, tmp_path, enemy_attack=True)
    assert act(table, mid, "end")["status"] == "COMMITTED"
    menu = table.state(mid)["menu"]
    assert menu["actor_id"] == FOE
    candidate = next(c for c in service._load_session(mid).engine.legal_candidates()
                     if c.display_name == "Jian (Straight Sword) attack" and OWNER in c.target_ids)
    args = (mid, candidate.candidate_id, menu["decision_id"], menu["state_version"], 0)
    before = service._load_session(mid).engine.state.model_dump(mode="json")
    if ai_turn:
        force_ai_candidate(service, mid, FOE, candidate.candidate_id)
        result = table.auto_step(mid, 0)
    else:
        result = table.act(*args)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == OWNER
    assert "Jian (Straight Sword) attack" in json.dumps(prompt)
    assert service._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "DECLINE" if selection == "decline" else "USE",
              "option_ids": [] if selection == "decline" else ["save"]}
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    if ai_turn:
        force_ai_candidate(service, mid, FOE, candidate.candidate_id)
        result = table.auto_step(mid, 0, [answer])
    else:
        result = table.act(*args, [answer])
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[OWNER].current_hp == int(selection == "save")
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
