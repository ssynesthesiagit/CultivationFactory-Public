"""Astral Projection must not block initiative setup or leave an empty table menu."""
from types import SimpleNamespace
import json
import pytest

from combat import ext
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r1i_service_support import OWNER, FOE, SECOND, fixture
from tests.r1i_service_support import candidate, force_ai_candidate

ASTRAL = "tianxia.path.spirit_awakening.feature.astral_projection"
BELL = "tianxia.talent.music.bell_of_warning"
INVISIBLE = "condition:typed.invisible"


@pytest.mark.parametrize('recover', [False, True])
def test_saved_projection_allows_bell_initiative_setup_and_turn_one(tmp_path, recover):
    ids = [OWNER, FOE, SECOND]
    docs = [sheet([ASTRAL, BELL], cl=17), sheet([BELL], cl=17), sheet([], cl=17)]
    docs[0]["identity"]["path"] = "Spirit Awakening"
    for aid, doc in zip(ids, docs):
        doc["identity"]["display_name"] = aid.split("r1i-")[-1].title()
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
               for aid, doc in zip(ids, docs)]
    projection_action = next(action["source_definition_id"] for action in bundles[0]["action_catalog"]
                             if ((action.get("parameters") or {}).get("typed") or {}).get("source") == ASTRAL)

    def save_existing_projection(engine):
        # H66's actor enters setup with this source-attributed condition already saved.
        actor = engine.state.actors.get(OWNER)
        if actor is not None:
            engine._apply_condition(actor, INVISIBLE, projection_action, actor.entity_id,
                                    expires_on="END_OF_CURRENT_TURN", data={"label": "Invisible"})

    callbacks = ext._HOOKS.setdefault("match_start", [])
    callbacks.append(save_existing_projection)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    try:
        mid = combat._finish_factory_match(
            bundles, ids, {OWNER: "team:a", FOE: "team:b", SECOND: "team:b"},
            {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 6}},
            combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER], [FOE, SECOND],
            control_modes={aid: "MANUAL" for aid in ids}, match_seed="LUNA68-PROJECTION-SETUP",
            display_name="Luna68", maximum_rounds=10,
        )["match_id"]
    finally:
        callbacks.remove(save_existing_projection)

    def send(candidate_id, answers=()):
        menu = table.state(mid)["menu"]
        return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, list(answers))

    saved = combat._load_session(mid)
    actor = saved.engine.state.actors[OWNER]
    from combat.ext.astral_projection import projected_instances

    assert projected_instances(saved.engine, actor)
    assert any(task.actor_id == OWNER and task.source_id == BELL for task in saved.engine.state.setup_tasks)

    menu = table.state(mid)["menu"]
    vetoes = ext._HOOKS.setdefault('candidate_allowed', [])
    if recover:
        vetoes.append(veto_everything)
        combat._derived.clear()
        menu = table.state(mid)['menu']
    setup = next(option["candidate_id"] for group in menu["actions"] if group["label"] == "Finish fight setup"
                 for option in group["options"])
    answers, bell_prompts = [], []
    try:
        before = combat._load_session(mid).engine.state.model_dump(mode='json')
        table.state(mid)
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        for _ in range(12):
            result = send(setup, answers)
            if result["status"] == "COMMITTED":
                break
            assert result["status"] == "REACTION_REQUIRED", result
            prompt = result["reaction"]
            assert prompt["reaction"] == "Bell of Warning"
            # The projected owner cannot ring a physical bell. A nonprojected
            # owner still gets the normal manual Initiative decision.
            assert prompt['context']['reactor_id'] == FOE
            bell_prompts.append(prompt)
            answers.append({**prompt["context"], "selection": "DECLINE"})
        else:
            raise AssertionError("setup did not complete")
        # Reload while the veto remains installed: provenance is a committed
        # event, not a transient menu warning or an in-memory flag.
        fresh = CombatService(ROOT, tmp_path)._load_session(mid)
        records = recovery_records(fresh.engine)
        assert len(records) == int(recover)
        if recover:
            assert_recovery(records[0], 'Finish fight setup')
            assert_recorded_diagnostic(fresh, records[0])
            assert any(row['summary'] == records[0].payload['log'] for row in table.events(mid, 0)['events'])
        assert fresh.mechanical.replay()['status'] == 'PASS'
    finally:
        if recover:
            vetoes.remove(veto_everything)

    fresh = combat._load_session(mid)
    assert bell_prompts
    assert fresh.engine.state.setup_tasks == ()
    assert fresh.engine.state.round_number == 1
    assert any(event.event_type == "TURN_STARTED" and event.payload.get("round") == 1 for event in fresh.engine.events)
    assert projected_instances(fresh.engine, fresh.engine.state.actors[OWNER])


def veto_everything(engine, actor, candidate, action):
    return False


def recovery_records(engine):
    return [event for event in engine.events if event.payload.get('recovery') == 'empty_candidate_menu']


def also_veto_system(engine, actor, candidate, action):
    # Attribution must come from the menu state, even if the hook ceases to veto
    # once an intent has been accepted. Re-querying in the event loses this name.
    if candidate.kind.value == 'END_TURN' and getattr(engine, '_active_intent', None) is None:
        return False


def broken_system_query(engine, actor, candidate, action):
    if candidate.kind.value == 'END_TURN':
        raise RuntimeError('synthetic query failure')


def assert_recovery(event, label, names=('veto_everything',)):
    assert event.event_type == 'PASSIVE_TRIGGERED'
    assert event.payload['vetoing_plugins'] == sorted(f'{__name__}.{name}' for name in names)
    assert event.payload['log'].startswith(label + ' was restored')
    assert 'system:' not in event.payload['log']


def assert_recorded_diagnostic(session, event):
    journal = [json.loads(line) for line in
               (session.store.match_dir / 'ControllerJournal.ndjson').read_text().splitlines()]
    diagnostics = [diagnostic for row in journal
                   for diagnostic in (row.get('primary_decision_record') or {}).get('diagnostics', [])]
    assert event.payload in diagnostics


@pytest.mark.parametrize('auto', [False, True])
def test_all_candidate_vetoes_commit_and_reload_a_system_end_turn_choice(tmp_path, auto):
    combat, table, mid, _send, _commit = fixture(tmp_path, [], seed="LUNA68-ALL-VETOED")
    if auto:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    callbacks = ext._HOOKS.setdefault("candidate_allowed", [])

    callbacks.append(veto_everything)
    callbacks.append(also_veto_system)
    callbacks.append(broken_system_query)
    combat._derived.clear()
    try:
        before = combat._load_session(mid).engine.state.model_dump(mode='json')
        menu = table.state(mid)["menu"]
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        if not auto:
            assert menu['end_turn']
        assert all(c.kind.value == 'END_TURN' for c in combat._legal_candidates(combat._load_session(mid)))
        result = table.auto_step(mid, 0) if auto else _commit(menu['end_turn'])
        assert result['status'] == 'COMMITTED'
        fresh = CombatService(ROOT, tmp_path)._load_session(mid)
        assert fresh.engine.state.current_actor_id != OWNER
        records = recovery_records(fresh.engine)
        assert len(records) == 1
        assert_recovery(records[0], 'End Turn', ('veto_everything', 'also_veto_system'))
        assert_recorded_diagnostic(fresh, records[0])
        assert not any('synthetic query failure' in str(e.payload) for e in fresh.engine.events)
        assert any(row['summary'] == records[0].payload['log'] for row in table.events(mid, 0)['events'])
        assert fresh.mechanical.replay()['status'] == 'PASS'
    finally:
        callbacks.remove(veto_everything)
        callbacks.remove(also_veto_system)
        callbacks.remove(broken_system_query)


def test_projection_keeps_non_hostile_reactions_and_blocks_reaction_attacks():
    from combat.ext.astral_projection import allowed, physical_reaction_rows

    actor = SimpleNamespace(entity_id="projected", conditions={"projection": SimpleNamespace(
        condition_id=INVISIBLE, source_definition_id=ASTRAL, source_actor_id="projected")})
    engine = SimpleNamespace(action_catalog={})
    candidate = SimpleNamespace(kind="REACTION", source_definition_id="reaction:test")
    defense = SimpleNamespace(target_kind="SELF", parameters={"typed": {"effects": [{"type": "ac_bonus"}]}})
    attack = SimpleNamespace(target_kind="HOSTILE_ENTITY", parameters={"typed": {"effects": [{"type": "attack"}]}})
    assert allowed(engine, actor, candidate, defense) is None
    assert allowed(engine, actor, candidate, attack) is False
    assert physical_reaction_rows(engine, actor, {"kind": "hit", "effects": [{"type": "ac_bonus"}]}) is None
    assert physical_reaction_rows(engine, actor, {"kind": "attack_reaction", "effects": []}) is False
    assert physical_reaction_rows(engine, actor, {'kind': 'hit', 'effects': [
        {'type': 'ac_bonus', 'on_success': [{'type': 'teleport'}]}]}) is False
    assert physical_reaction_rows(engine, actor, {'kind': 'hit', 'effects': [{'type': 'future_effect'}]}) is False
    assert physical_reaction_rows(engine, actor, {'kind': 'hit', 'effects': [
        {'type': 'ac_bonus', 'future_branch': {'nested': [[{'type': 'healing'}]]}}]}) is False
    assert physical_reaction_rows(engine, actor, {'kind': 'hit', 'target_kind': 'HOSTILE_ENTITY',
                                                 'effects': [{'type': 'ac_bonus'}]}) is False


def saved_projection_fixture(tmp_path, owned, *, active=True, **kwargs):
    """Start with the same source-owned, persisted projection as the live bug."""
    def project(engine):
        if not active or OWNER not in engine.state.actors:
            return
        actor = engine.state.actors[OWNER]
        source = next(action.source_definition_id for action in engine.action_catalog.values()
                      if action.owner_id == OWNER and
                      (action.parameters.get('typed') or {}).get('source') == ASTRAL)
        engine._apply_condition(actor, INVISIBLE, source, OWNER, expires_on='UNTIL_REMOVED')

    callbacks = ext._HOOKS.setdefault('match_start', [])
    callbacks.append(project)
    try:
        result = fixture(tmp_path, [ASTRAL, *owned], **kwargs)
        from combat.ext.astral_projection import projected_instances
        engine = result[0]._load_session(result[2]).engine
        assert bool(projected_instances(engine, engine.state.actors[OWNER])) == active
        return result
    finally:
        callbacks.remove(project)


def test_projected_creature_cannot_make_a_real_opportunity_attack(tmp_path):
    from tests.test_carry import KIT
    combat, table, mid, send, commit = saved_projection_fixture(
        tmp_path, [], seed='PROJECTION-OPPORTUNITY', owner_kit={'starting_kit': KIT})
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    engine = combat._load_session(mid).engine
    start = engine.state.event_sequence
    move = next(c for c in combat._legal_candidates(combat._load_session(mid))
                if c.kind.value == 'MOVE' and
                engine.grid.distance_ft(c.destination, engine.state.actors[OWNER].position) > 5)
    result = send(move.candidate_id)
    assert result['status'] == 'COMMITTED', result
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not any(e.actor_id == OWNER and e.event_type == 'REACTION_WINDOW_OPENED'
                   for e in fresh.engine.events if e.sequence > start)
    assert fresh.engine.state.actors[OWNER].reaction_available
    assert fresh.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('active', [False, True])
@pytest.mark.parametrize('auto', [False, True])
def test_projection_refuses_real_life_line_stitch_on_another_creature(tmp_path, active, auto):
    stitch = 'tianxia.talent.thread.life_line_stitch'

    def fragile_ally(bundles):
        from combat.canonical import canonical_sha256
        bundles[2]['actor_template']['maximum_hp'] = 1
        bundles[2].pop('bundle_sha256')
        bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])

    combat, table, mid, send, commit = saved_projection_fixture(
        tmp_path, [stitch], active=active, seed='PROJECTION-STITCH',
        foe_talents=['TAL_VOID_VOID_NEEDLE'], allies=[SECOND], bundle_transform=fragile_ally)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    action = candidate(table, mid, 'Void Needle', SECOND)
    if auto:
        force_ai_candidate(combat, mid, FOE, action)
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    answers, prompted = [], False
    for _ in range(16):
        result = send(action, answers, auto=auto)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        use = 'Life-Line Stitch' in prompt['reaction']
        prompted |= use
        answers.append({**prompt['context'], 'selection': 'USE' if use else 'DECLINE'})
    else:
        pytest.fail('too many reaction prompts')
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    resolved = [e for e in fresh.engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == stitch]
    assert bool(resolved) is not active
    if not auto:
        assert prompted is not active
    else:
        assert not prompted
    assert fresh.engine.state.actors[SECOND].current_hp == (0 if active else 1)
    assert fresh.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('auto', [False, True])
def test_projected_creature_uses_real_stamina_guard_at_the_table(tmp_path, auto):
    guard = 'tianxia.path.body_refining.feature.stamina_guard'
    def body_resources(bundles):
        doc = sheet([ASTRAL, guard], cl=17, primary='Stamina')
        doc['identity']['path'] = 'Body Refining'
        bundles[0] = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid, send, commit = saved_projection_fixture(
        tmp_path, [guard], seed='PROJECTION-SELF-DEFENSE', foe_talents=['TAL_VOID_VOID_NEEDLE'],
        bundle_transform=body_resources)
    before = combat._load_session(mid).engine.state.actors[OWNER].resources['resource:core.stamina']
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    action = candidate(table, mid, 'Void Needle', OWNER)
    if auto:
        force_ai_candidate(combat, mid, FOE, action)
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    answers, prompted = [], False
    for _ in range(16):
        result = send(action, answers, auto=auto)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        use = prompt['reaction'] == 'Stamina Guard'
        prompted |= use
        answer = {**prompt['context'], 'selection': 'USE' if use else 'DECLINE'}
        if use and prompt['context']['reaction_source_id'] == 'reaction:core.stamina_guard':
            answer['spend'] = 1
        if use and prompt.get('choice'):
            answer['option_ids'] = (prompt['choice'].get('preferred') or [prompt['choice']['options'][0]['id']])[:1]
        answers.append(answer)
    else:
        pytest.fail('too many reaction prompts')
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == 'REACTION_RESOLVED' and 'stamina_guard' in e.source_definition_id
               for e in fresh.engine.events)
    assert fresh.engine.state.actors[OWNER].resources['resource:core.stamina'] < before
    if not auto:
        assert prompted
    else:
        assert not prompted
    assert fresh.mechanical.replay()['status'] == 'PASS'
