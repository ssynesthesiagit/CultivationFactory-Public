"""C11 review regressions; no browsers or live stores are used."""
from types import SimpleNamespace

import pytest

from combat.gate2_runtime_models import ActionIntent
from combat.ext import life_state
from tests import test_riders_c11 as L


def test_candle_shelters_third_failure_from_nonmassive_damage(monkeypatch):
    engine, owner, target = L._candle_squad([L.CANDLE], monkeypatch)
    engine._commit_damage(target, 10, "FORCE", "test:blow", L.AN, None, reaction_depth=0)
    assert target.life_state == "DYING"
    target.turn_flags[life_state.RECORD] = {"ok": 0, "bad": 2}
    before = owner.resources["resource:core.stamina"]
    engine._commit_damage(target, 1, "FORCE", "test:blow", L.AN, None, reaction_depth=0)
    assert target.active and target.life_state == "STABLE"
    assert owner.resources["resource:core.stamina"] == before - 5
    assert not owner.reaction_available


def test_candle_does_not_shelter_rolled_death_failures_after_earlier_damage(monkeypatch):
    engine, owner, target = L._candle_squad([L.CANDLE], monkeypatch)
    engine._commit_damage(target, 10, "FORCE", "test:blow", L.AN, None, reaction_depth=0)
    before = owner.resources["resource:core.stamina"]
    life_state.die(engine, target, "three failed death saving throws", "system:death_save")
    assert not target.active and owner.reaction_available
    assert owner.resources["resource:core.stamina"] == before


def test_rapid_unweave_preserves_hidden_eye_domain_and_its_modifiers():
    from combat.ext import qiweaving_unweave

    court = "TAL_THE_HIDDEN_EYE_COURT_OF_THE_HIDDEN_EYE"
    foe_bundle = L.compile_character(L._sheet("tianxia.sphere.the_hidden_eye", [court]), actor_id=L.t.FOE)
    engine, owner, foe = L._duel(L._bundle(L.QI, []), foe_bundle)
    L._act(engine, foe.entity_id, "Court of the Hidden Eye")
    action = next(a for a in engine.action_catalog.values() if a.owner_id == foe.entity_id and a.display_name == "Court of the Hidden Eye")
    engine._add_modifier(foe, action.source_definition_id, "armor_class", "ADD", 2, "self", expires_on="UNTIL_REMOVED")
    engine.state.current_actor_id = L.ME
    assert any(c.condition_id == "condition:typed.eye_court" for c in foe.conditions.values())
    assert qiweaving_unweave.patterns(engine, foe) == []
    assert L.RAPID not in L._names(engine)


def _fixture_rules(monkeypatch, text):
    """Point the plug-in's printed-text reader at a fixture record instead of the owner's file.  That reader is the
    shared combat.ext.qiweaving_common.rules_text, which combat.ext.qiweaving_unweave imports by name."""
    from combat.ext import qiweaving_unweave as unweave

    rules = {"fixture": text}
    monkeypatch.setattr(unweave, "rules_text", lambda: rules)
    return rules


@pytest.mark.parametrize("classification", ["Martial Domain", "Secret Inheritance", "Formation project", "artifact-level effect", "campaign-scale working"])
def test_unweave_protected_categories_are_bounded(monkeypatch, classification):
    from combat.ext import qiweaving_unweave as unweave

    action = SimpleNamespace(source_definition_id="action:typed.fixture.ordinary+variant",
                             parameters={"typed": {"source": "fixture"}})
    ordinary = "#### Ordinary pattern\nPrerequisite: Core Formation Realm, Domain talent.\nCan affect a Formation project or artifact."
    rules = _fixture_rules(monkeypatch, ordinary)
    assert unweave._supported_source(action)
    for text in (f"#### Protected power - {classification}\nDuration: 1 minute",
                 f"#### Protected power\nSource Category: {classification}\nDuration: 1 minute"):
        rules["fixture"] = text
        assert not unweave._supported_source(action)
    rules["fixture"] = ordinary
    action.parameters["typed"]["source_category"] = classification
    assert not unweave._supported_source(action)
    action.parameters["typed"].pop("source_category")
    rules["fixture"] = ""
    assert not unweave._supported_source(action)


@pytest.mark.parametrize("source", ["tianxia.talent.ink.painted_law_of_the_scene",
    "TAL_WEATHER_COURT_OF_CHANGING_SKIES", "TAL_SPEAR_SPEAR_PRESSURE"])
@pytest.mark.parametrize("variant", ["", "+variant"])
def test_unweave_preserves_real_protected_sources_and_their_records(source, variant):
    from combat.ext import qiweaving_unweave as unweave

    # These are owner source texts, not invented protected headings. Future
    # creature-held records from these sources must retain Domain protection.
    assert unweave.rules_text()[source]
    action_id = f"action:typed.fixture.{source}{variant}"
    action = SimpleNamespace(source_definition_id=action_id,
                             parameters={"typed": {"source": source}})
    holder = SimpleNamespace(
        conditions={"domain": SimpleNamespace(condition_id="condition:typed.domain_control",
                                               source_definition_id=action_id)},
        modifiers={"bonus": SimpleNamespace(target_field="armor_class", source_definition_id=action_id)})
    engine = SimpleNamespace(action_catalog={action_id: action})
    assert not unweave._supported_source(action)
    assert unweave.patterns(engine, holder) == []


@pytest.mark.parametrize("mention", [
    "Prerequisite: You establish a Weather Domain.",
    "Target: A creature inside a Weather Domain.",
    "When you create a Domain, this pattern grants healing.",
    "You cannot establish a Weather Domain with this pattern.",
    "You establish a moving Qi front centered on your Domain Armament.",
    "You create a Domain Armament.",
])
def test_unweave_domain_mentions_do_not_classify_ordinary_sources(monkeypatch, mention):
    from combat.ext import qiweaving_unweave as unweave

    _fixture_rules(monkeypatch, f"#### Ordinary pattern\n{mention}")
    action = SimpleNamespace(source_definition_id="action:typed.fixture.ordinary",
                             parameters={"typed": {"source": "fixture"}})
    assert unweave._supported_source(action)


def test_folded_reach_is_spent_by_ordinary_melee_attack():
    engine, owner, foe = L._fight(L.SPACE, [L.FOLDED], items=[L.DAO], cl=10)
    L._use(engine, "Folded Reach", target=None)
    L._use(engine, L.DAO_ATTACK)
    assert not any(c.condition_id == "condition:typed.folded_reach" for c in owner.conditions.values())
    foe.position = foe.position.model_copy(update={"x": 7})
    assert L.DAO_ATTACK + " (Folded Reach)" not in L._names(engine)


def test_dense_mist_selects_new_cast_across_event_digit_boundary():
    engine, owner, foe = L._fight(L.WATER, [L.MIST_VEIL], foe_at=(14, 6))
    # Advance with ordinary events, rather than rewriting IDs or counters.
    while engine.state.event_sequence < 75:
        engine._append_event("PASSIVE_TRIGGERED", "test:clock", payload={"trigger": "fixture"})
    L._mist(engine, L.DENSE, at=(8, 6))
    old = next(z for z in engine.state.zones.values() if z.owner_id == L.ME and z.active)
    assert int(old.zone_id.rsplit(":", 1)[1]) < 100
    while engine.state.event_sequence < 120:
        engine._append_event("PASSIVE_TRIGGERED", "test:clock", payload={"trigger": "fixture"})
    # Let the earlier dense mist thin, preserving the basin.
    owner.turns_started += 1
    from combat.ext import water_mist
    water_mist.thin_out(engine, owner)
    L._mist(engine, L.DENSE, at=(10, 6))
    new = next(z for z in engine.state.zones.values() if z.owner_id == L.ME and z.active and z.zone_id != old.zone_id)
    assert old.zone_id > new.zone_id  # the former lexical selection is wrong
    assert old.trigger_profile["obscured"] == "light"
    assert new.trigger_profile["obscured"] == "heavy"


@pytest.mark.parametrize("sealant,level,ordinary,doubles", [(False, 1, False, True), (True, 0, False, False),
    (True, 12, False, False), (True, 13, False, True), (True, None, True, False), (True, None, False, True)])
def test_tempered_sealant_qualifies_rampart_fire_per_hit(sealant, level, ordinary, doubles):
    from combat.ext import docket_walls
    from combat.typed_executor import Context

    talents = [L.MOLD, L.RAMPART] + (["TAL_WAX_TEMPERED_SEALANT"] if sealant else [])
    engine, owner, foe = L._fight(L.WAX, talents, foe_at=(12, 6))
    L._mist(engine, L.HALF_RAMPART, at=(8, 6))
    zone = next(z for z in engine.state.zones.values() if z.owner_id == L.ME and z.active)
    # Exercise the actual wall hit/damage path with a deterministic fire weapon.
    action = next(a for a in engine.action_catalog.values() if a.owner_id == L.ME and (a.parameters or {}).get("typed"))
    typed = {**action.parameters["typed"], "wall_weapon": {"fixed_damage": 3, "damage_type": "FIRE"},
             "ordinary_fire": ordinary, "numbers": {"attack_bonus": 100, **({"cl": level} if level is not None else {})}}
    ctx = Context(engine, foe, action, SimpleNamespace(destination=zone.affected_cells[0]), typed, [], None)
    docket_walls.wall_attack(ctx, {"count": 1})
    assert sum(zone.trigger_profile["sections"].values()) == (6 if doubles else 3)
    assert "FIRE" in docket_walls.stats(zone)["vulnerable"]  # no permanent mutation


def test_scripture_deadline_survives_commit_reload_and_expires(tmp_path):
    from combat.gate4_persistence import Gate4Persistence
    from combat.ext import effect_durations, thread_weaving

    persistence = Gate4Persistence(L.ROOT, tmp_path)
    session = persistence.create_match(match_seed="C11-100-ROUNDS", maximum_rounds=120,
        typed_bundles=(L._bundle(L.THREAD, [L.SCRIPTURE]),),
        roster_setup={"primary_actor_ids": [L.ME, L.AN], "team_by_actor": {L.ME: "team:a", L.AN: "team:b"},
                      "starting_positions": {L.ME: {"x": 3, "y": 6}, L.AN: {"x": 8, "y": 6}}})
    def commit(name):
        c = next(c for c in session.engine.legal_candidates() if c.display_name == name)
        session.mechanical.execute_intent(ActionIntent(intent_id=f"c11-exp-{c.state_version}", decision_id=c.decision_id,
            candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids))
    while session.engine.state.current_actor_id != L.ME:
        commit("End turn")
    commit(L.SNARE + " (Qi Thread)")
    loaded = persistence.load_match(session.match_id)
    assert loaded.verify()["status"] == "PASS"
    actor = loaded.engine.state.actors[L.ME]
    condition = next(c for c in actor.conditions.values() if c.condition_id == thread_weaving.QI_THREAD)
    deadline, slot = effect_durations.parse_round(condition.expires_on)
    assert deadline == session.engine.state.round_number + 100
    loaded.engine.state.round_number = deadline - 1
    effect_durations.sweep(loaded.engine, actor, "START_OF_TURN")
    assert any(c.condition_id == thread_weaving.QI_THREAD for c in actor.conditions.values())
    loaded.engine.state.round_number, loaded.engine.state.current_slot_index = deadline, max(0, slot - 1)
    if slot:
        effect_durations.sweep(loaded.engine, actor, "START_OF_TURN")
        assert thread_weaving.offered(loaded.engine, actor, SimpleNamespace(target_ids=(L.AN,)),
            next(a for a in loaded.engine.action_catalog.values() if a.source_definition_id.endswith(thread_weaving.FREE_SUFFIX)))
    loaded.engine.state.current_slot_index = slot
    effect_durations.sweep(loaded.engine, actor, "START_OF_TURN")
    assert not any(c.condition_id == thread_weaving.QI_THREAD for c in actor.conditions.values())
    free = next(a for a in loaded.engine.action_catalog.values() if a.source_definition_id.endswith(thread_weaving.FREE_SUFFIX))
    assert thread_weaving.offered(loaded.engine, actor, SimpleNamespace(target_ids=(L.AN,)), free) is False


def _table(tmp_path, kind):
    """Fresh table storage, compiled sheets and Ask-me plans; no live files."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    sphere, talents = {"herd": (L.WARLEADER, [L.HERDSMAN, L.FOCUSING]), "candle": (L.WAX, [L.CANDLE]),
                       "fold": (L.SPACE, [L.FOLDED]), "mist": (L.WATER, [L.MIST_VEIL]),
                       "wax": (L.WAX, [L.MOLD, L.RAMPART, "TAL_WAX_TEMPERED_SEALANT"]),
                       "unweave": (L.QI, []), "ordinary_unweave": (L.QI, [])}[kind]
    ids = [L.ME, L.ALLY1, L.ALLY2, L.t.FOE]
    bundles = []
    for who, display in zip(ids, ["Leader", "Attacker", "Companion", "Enemy"]):
        sheet = L._sheet(sphere if who == L.ME else L.SPACE, talents if who == L.ME else [], items=[L.DAO], cl=15, dc=100)
        if kind == "unweave" and who == L.t.FOE:
            sheet = L._sheet("tianxia.sphere.the_hidden_eye", ["TAL_THE_HIDDEN_EYE_COURT_OF_THE_HIDDEN_EYE"], items=[L.DAO], cl=15)
        if kind == "ordinary_unweave" and who == L.t.FOE:
            sheet = L._sheet("tianxia.sphere.life", ["tianxia.talent.life.revitalizing_thread"], items=[L.DAO], cl=15)
        sheet["identity"]["display_name"] = display
        bundles.append(L.compile_character(sheet, actor_id=who, reaction_plan={"ask": True}))
    combat = CombatService(L.ROOT, tmp_path)
    enemies = [L.t.FOE, L.ALLY2] if kind == "ordinary_unweave" else [L.t.FOE]
    mid = combat._finish_factory_match(bundles, ids,
        {who: "team:b" if who in enemies else "team:a" for who in ids},
        {L.ME: {"x": 3, "y": 6}, L.ALLY1: {"x": 5, "y": 6}, L.ALLY2: {"x": 5, "y": 5},
         L.t.FOE: {"x": 4 if kind == "fold" else 6, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [who for who in ids if who not in enemies], enemies,
        control_modes={who: "MANUAL" for who in ids}, match_seed="C11-TABLE-" + kind,
        display_name="C11 review fixture", maximum_rounds=120)["match_id"]
    table = TabletopService(combat, tmp_path)
    _advance(combat, table, mid, L.ME)
    return combat, table, mid


def _send(table, mid, candidate_id, answers=()):
    state = table.state(mid)
    menu = state["menu"]
    return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))


def _candidate(combat, mid, name):
    return next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.display_name == name)


def _advance(combat, table, mid, actor_id):
    for _ in range(8):
        if combat._load_session(mid).engine.state.current_actor_id == actor_id:
            return
        assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    raise AssertionError("fixture actor never got a turn")


@pytest.mark.parametrize("kind", ["herd", "candle"])
@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("ai_chooser,use", [(False, False), (False, True), (True, True)])
def test_reaction_table_pause_answer_commit_reload(tmp_path, monkeypatch, kind, auto_turn, ai_chooser, use):
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate5_service import CombatService
    from combat.typed_executor import Context, run_effects
    from tests.test_tabletop_hunt6 import on_hold

    monkeypatch.setattr(life_state, "DEATH_SAVES_FOR_ALL", True)
    combat, table, mid = _table(tmp_path, kind)
    if kind == "herd":
        assert _send(table, mid, _candidate(combat, mid, "Deadly Herdsman"))["status"] == "COMMITTED"
    chooser_id = L.ALLY1 if kind == "herd" else L.ME
    target_id = L.t.FOE if kind == "herd" else L.ALLY2
    choice = "choice:needle." + ("deadly_herdsman" if kind == "herd" else "funeral_candle")

    def trigger(engine):
        attacker, target = engine.state.actors[L.ALLY1], engine.state.actors[target_id]
        action = next(a for a in engine.action_catalog.values() if a.owner_id == attacker.entity_id and a.display_name == L.DAO_ATTACK)
        if kind == "herd":
            from combat.ext.warleader_herdsman import herd
            typed = action.parameters["typed"]
            ctx = Context(engine, attacker, action, engine._active_intent, typed, [target], target)
            ctx.attack_effect = next(e for e in typed["effects"] if e.get("type") == "attack")
            engine._commit_damage(target, 1, "SLASHING", action.source_definition_id, attacker.entity_id, None, reaction_depth=0)
            herd(ctx, target, 1)
        else:
            engine._commit_damage(target, target.current_hp, "FORCE", action.source_definition_id, attacker.entity_id, None, reaction_depth=0)
            # Nonmassive damage causes the third failure, not a rolled save.
            for _ in range(3):
                engine._commit_damage(target, 1, "FORCE", action.source_definition_id, attacker.entity_id, None, reaction_depth=0)

    if auto_turn:
        _advance(combat, table, mid, L.ALLY2)
    elif ai_chooser and kind == "candle":
        # The automatic candle owner is off-turn; the player controls the
        # accepted triggering action.
        _advance(combat, table, mid, L.ALLY1)
    on_hold(monkeypatch, trigger)
    cid = _candidate(combat, mid, "Hold position")
    if auto_turn:
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=L.ALLY2, controller_mode="LOCAL_AUTO")
    send = lambda answers: table.auto_step(mid, 0, list(answers)) if auto_turn else _send(table, mid, cid, answers)
    if ai_chooser:
        for who in (L.ME, L.ALLY1, L.ALLY2, L.t.FOE):
            if who != combat._load_session(mid).engine.state.current_actor_id:
                combat.set_controller_mode(mid, actor_id=who, controller_mode="LOCAL_AUTO")
        combat.set_controller_mode(mid, actor_id=chooser_id, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    first = send([])
    if ai_chooser:
        assert first["status"] == "COMMITTED", first
        result, answers = first, []
    else:
        assert first["status"] == "REACTION_REQUIRED", first
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        assert send([])["reaction"] == first["reaction"]
        context = first["reaction"]["context"]
        assert context["reactor_id"] == chooser_id and context["reaction_source_id"] == choice
        prompt = first["reaction"]["moment"]
        assert L.DAO_ATTACK in prompt
        assert ("Enemy" if kind == "herd" else "Companion") in prompt
        answers = [{**context, "selection": "USE" if use else "DECLINE",
                    **({"option_ids": ["prone" if kind == "herd" else "shelter"]} if use else {})}]
        result = send(answers)
    while result["status"] == "REACTION_REQUIRED":
        # The Standard may also offer its optional Momentum Mark. It is not
        # the decision under test and declining it must preserve the shove.
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
        result = send(answers)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(L.ROOT, tmp_path)._load_session(mid)
    target = loaded.engine.state.actors[target_id]
    if kind == "herd":
        from combat.ext.warleader_herdsman import HERD_USED
        assert bool(loaded.engine.state.actors[L.ME].turn_flags.get(HERD_USED)) == use
        assert loaded.engine.state.actors[L.ALLY1].bonus_action_available == (not use)
    else:
        from combat.ext.wax_candle import USED
        assert bool(target.turn_flags.get(USED)) == use
        assert target.active == use
        if use:
            assert target.life_state == "STABLE" and target.current_hp == 0
            assert not loaded.engine.state.actors[L.ME].reaction_available
    assert loaded.mechanical.replay()["status"] == "PASS"
    if use and kind == "herd":
        from combat.ext.warleader_herdsman import herd
        attacker = loaded.engine.state.actors[L.ALLY1]
        attacker.bonus_action_available = True
        action = next(a for a in loaded.engine.action_catalog.values() if a.owner_id == attacker.entity_id and a.display_name == L.DAO_ATTACK)
        ctx = Context(loaded.engine, attacker, action, None, action.parameters["typed"], [target], target)
        ctx.attack_effect = {"type": "attack"}
        before_events = len(loaded.engine.events)
        herd(ctx, target, 1)
        assert attacker.bonus_action_available and len(loaded.engine.events) == before_events
    elif use and kind == "candle":
        from combat.ext.wax_candle import shelter
        owner = loaded.engine.state.actors[L.ME]
        owner.reaction_available = True
        assert shelter(loaded.engine, target, "three failed death saving throws", "system:damage") is False


def test_focusing_tactics_once_flag_commits_reloads_and_prevents_reuse(tmp_path, monkeypatch):
    from combat.gate5_service import CombatService
    from combat.ext.warleader_herdsman import USED, FOCUS
    from tests.test_tabletop_hunt6 import on_hold

    combat, table, mid = _table(tmp_path, "herd")
    assert _send(table, mid, _candidate(combat, mid, "Set the Standard"))["status"] == "COMMITTED"
    def expend(engine):
        engine._spend_resource(engine.state.actors[L.ME], FOCUS, 1, "test:expend")
    on_hold(monkeypatch, expend)
    assert _send(table, mid, _candidate(combat, mid, "Hold position"))["status"] == "COMMITTED"
    _advance(combat, table, mid, L.ALLY1)
    assert _send(table, mid, _candidate(combat, mid, "Restore Martial Focus (Focusing Tactics)"))["status"] == "COMMITTED"
    loaded = CombatService(L.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[L.ME].resources[FOCUS] == 1
    assert loaded.engine.state.actors[L.ALLY1].turn_flags[USED] == L.ME
    assert loaded.mechanical.replay()["status"] == "PASS"
    loaded.engine.state.actors[L.ME].resources[FOCUS] = 0
    loaded.engine.state.actors[L.ALLY1].action_available = True
    assert not any(c.display_name == "Restore Martial Focus (Focusing Tactics)" for c in loaded.engine.legal_candidates())


def test_protected_domain_is_unavailable_after_table_commit_reload(tmp_path):
    from combat.gate5_service import CombatService
    combat, table, mid = _table(tmp_path, "unweave")
    _advance(combat, table, mid, L.t.FOE)
    assert _send(table, mid, _candidate(combat, mid, "Court of the Hidden Eye"))["status"] == "COMMITTED"
    _advance(combat, table, mid, L.ME)
    loaded = CombatService(L.ROOT, tmp_path)._load_session(mid)
    assert any(c.condition_id == "condition:typed.eye_court" for c in loaded.engine.state.actors[L.t.FOE].conditions.values())
    assert not any(c.display_name == L.RAPID for c in loaded.engine.legal_candidates())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_ordinary_realm_scaled_pattern_unweaves_through_table_commit_reload(tmp_path):
    from combat.ext import qiweaving_unweave
    from combat.gate5_service import CombatService

    combat, table, mid = _table(tmp_path, "ordinary_unweave")
    _advance(combat, table, mid, L.t.FOE)
    cast = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                if c.display_name == "Mend the Pulse + Revitalizing Thread" and L.ALLY2 in c.target_ids)
    assert _send(table, mid, cast)["status"] == "COMMITTED"
    _advance(combat, table, mid, L.ME)
    loaded = CombatService(L.ROOT, tmp_path)._load_session(mid)
    foe = loaded.engine.state.actors[L.ALLY2]
    assert any(c.condition_id == "condition:typed.revitalizing_thread" for c in foe.conditions.values())
    assert qiweaving_unweave.patterns(loaded.engine, foe)
    assert loaded.mechanical.replay()["status"] == "PASS"
    cid = next(c.candidate_id for c in loaded.engine.legal_candidates() if c.display_name == L.RAPID and L.ALLY2 in c.target_ids)
    answers = []
    result = _send(table, mid, cid)
    for _ in range(3):
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        options = prompt["choice"]["options"]
        augment = "rapid_unweave_augments" in prompt["context"]["reaction_source_id"]
        answers.append({**prompt["context"], "selection": "DECLINE" if augment else "USE",
                        **({"option_ids": [options[0]["id"]]} if not augment else {})})
        result = _send(table, mid, cid, answers)
    assert result["status"] == "COMMITTED", result
    reloaded = CombatService(L.ROOT, tmp_path)._load_session(mid)
    assert not any(c.condition_id == "condition:typed.revitalizing_thread"
                   for c in reloaded.engine.state.actors[L.ALLY2].conditions.values())
    assert reloaded.mechanical.replay()["status"] == "PASS"


def test_ordinary_attack_consumes_fold_through_table_commit_reload(tmp_path):
    from combat.gate5_service import CombatService
    combat, table, mid = _table(tmp_path, "fold")
    assert _send(table, mid, _candidate(combat, mid, "Folded Reach"))["status"] == "COMMITTED"
    assert _send(table, mid, _candidate(combat, mid, L.DAO_ATTACK))["status"] == "COMMITTED"
    loaded = CombatService(L.ROOT, tmp_path)._load_session(mid)
    assert not any(c.condition_id == "condition:typed.folded_reach" for c in loaded.engine.state.actors[L.ME].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def _zone_candidate(combat, mid, name, at):
    return next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                if c.display_name.startswith(name) and c.destination and (c.destination.x, c.destination.y) == at)


def test_repeated_dense_mist_through_table_commit_reload(tmp_path, monkeypatch):
    from combat.gate5_service import CombatService
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.test_tabletop_hunt6 import on_hold
    combat, table, mid = _table(tmp_path, "mist")
    original = Gate4ControllerEngine._append_event
    def pad_first_cast(engine, event_type, *args, **kwargs):
        event = original(engine, event_type, *args, **kwargs)
        if event_type == "INTENT_DECLARED":
            while engine.state.event_sequence < 90:
                original(engine, "PASSIVE_TRIGGERED", "test:clock", payload={"trigger": "fixture"})
        return event
    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", pad_first_cast)
    assert _send(table, mid, _zone_candidate(combat, mid, L.DENSE, (8, 6)))["status"] == "COMMITTED"
    first = next(z for z in combat._load_session(mid).engine.state.zones.values() if z.owner_id == L.ME and z.active)
    assert int(first.zone_id.rsplit(":", 1)[1]) < 100
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    _advance(combat, table, mid, L.ME)
    def clock(engine):
        while engine.state.event_sequence < 120:
            engine._append_event("PASSIVE_TRIGGERED", "test:clock", payload={"trigger": "fixture"})
    on_hold(monkeypatch, clock)
    assert _send(table, mid, _candidate(combat, mid, "Hold position"))["status"] == "COMMITTED"
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    _advance(combat, table, mid, L.ME)
    assert _send(table, mid, _zone_candidate(combat, mid, L.DENSE, (8, 6)))["status"] == "COMMITTED"
    loaded = CombatService(L.ROOT, tmp_path)._load_session(mid)
    old = loaded.engine.state.zones[first.zone_id]
    new = next(z for z in loaded.engine.state.zones.values() if z.owner_id == L.ME and z.active and z.zone_id != first.zone_id)
    assert old.zone_id > new.zone_id and old.trigger_profile["obscured"] == "light"
    assert new.trigger_profile["obscured"] == "heavy"
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("level,expected", [(15, 3), (16, 6)])
def test_tempered_rampart_fire_damage_commits_reloads(tmp_path, monkeypatch, level, expected):
    from combat.ext import docket_walls
    from combat.gate5_service import CombatService
    from combat.typed_executor import Context
    from tests.test_tabletop_hunt6 import on_hold
    combat, table, mid = _table(tmp_path, "wax")
    assert _send(table, mid, _zone_candidate(combat, mid, L.HALF_RAMPART, (8, 6)))["status"] == "COMMITTED"
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    _advance(combat, table, mid, L.ME)
    def burn(engine):
        zone = next(z for z in engine.state.zones.values() if z.owner_id == L.ME and z.active)
        attacker = engine.state.actors[L.t.FOE]
        action = next(a for a in engine.action_catalog.values() if a.owner_id == attacker.entity_id and a.display_name == L.DAO_ATTACK)
        typed = {**action.parameters["typed"], "numbers": {"cl": level, "attack_bonus": 100},
                 "wall_weapon": {"fixed_damage": 3, "damage_type": "FIRE"}}
        ctx = Context(engine, attacker, action, SimpleNamespace(destination=zone.affected_cells[0]), typed, [], None)
        docket_walls.wall_attack(ctx, {"count": 1})
    on_hold(monkeypatch, burn)
    assert _send(table, mid, _candidate(combat, mid, "Hold position"))["status"] == "COMMITTED"
    loaded = CombatService(L.ROOT, tmp_path)._load_session(mid)
    zone = next(z for z in loaded.engine.state.zones.values() if z.owner_id == L.ME and z.active)
    assert sum(zone.trigger_profile["sections"].values()) == expected
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("reverse", [False, True])
def test_two_wall_defense_subscribers_compose_commit_reload(tmp_path, monkeypatch, reverse):
    from combat import ext
    from combat.ext import docket_walls, wax_rampart
    from combat.gate5_service import CombatService
    from combat.typed_executor import Context
    from tests.test_tabletop_hunt6 import on_hold

    combat, table, mid = _table(tmp_path, "wax")
    assert _send(table, mid, _zone_candidate(combat, mid, L.HALF_RAMPART, (8, 6)))["status"] == "COMMITTED"
    assert _send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    _advance(combat, table, mid, L.ME)

    def resist_fire(ctx, zone, stats):
        # A second independent test subscriber, scoped to this owned wall.
        if zone.owner_id != L.ME:
            return None
        return {**stats, "resist": [*stats.get("resist", []), "FIRE"]}

    subscribers = [wax_rampart.tempered, resist_fire]
    if reverse:
        subscribers.reverse()
    monkeypatch.setitem(ext._HOOKS, "wall_defenses", subscribers)

    def burn(engine):
        zone = next(z for z in engine.state.zones.values() if z.owner_id == L.ME and z.active)
        base = docket_walls.stats(zone)
        attacker = engine.state.actors[L.t.FOE]
        action = next(a for a in engine.action_catalog.values() if a.owner_id == attacker.entity_id and a.display_name == L.DAO_ATTACK)
        typed = {**action.parameters["typed"], "numbers": {"cl": 15, "attack_bonus": 100},
                 "wall_weapon": {"fixed_damage": 8, "damage_type": "FIRE"}}
        ctx = Context(engine, attacker, action, SimpleNamespace(destination=zone.affected_cells[0]), typed, [], None)
        defenses = docket_walls.defense_stats(ctx, zone)
        assert "FIRE" not in defenses["vulnerable"] and "FIRE" in defenses["resist"]
        docket_walls.wall_attack(ctx, {"count": 1})
        assert docket_walls.stats(zone) == base
        # No-subscriber and None-subscriber calls preserve the saved base.
        with monkeypatch.context() as patch:
            patch.setitem(ext._HOOKS, "wall_defenses", [])
            assert docket_walls.defense_stats(ctx, zone) == base
            patch.setitem(ext._HOOKS, "wall_defenses", [lambda *args: None])
            assert docket_walls.defense_stats(ctx, zone) == base

    on_hold(monkeypatch, burn)
    assert _send(table, mid, _candidate(combat, mid, "Hold position"))["status"] == "COMMITTED"
    loaded = CombatService(L.ROOT, tmp_path)._load_session(mid)
    zone = next(z for z in loaded.engine.state.zones.values() if z.owner_id == L.ME and z.active)
    assert sum(zone.trigger_profile["sections"].values()) == 4
    assert "FIRE" in docket_walls.stats(zone)["vulnerable"]
    assert "FIRE" not in docket_walls.stats(zone).get("resist", [])
    assert loaded.mechanical.replay()["status"] == "PASS"
