"""Portable imports, actual misses and cold table/replay for Mirror-Water Reply."""
import hashlib
import json
from pathlib import Path
import zipfile
import pytest
from combat import ext
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
REPLY = 'TAL_WATER_MIRROR_WATER_REPLY'
CURRENT = 'WATER_BASE_SHAPE_CURRENT'
LASH = 'WATER_BASE_WATER_LASH'
OWNER, ALLY, FOE = ('actor:factory.' + pid for pid in ('aaaaaaaa', 'bbbbbbbb', 'ffffffff'))
# Literal dynamic registry/authority dependencies for the public exporter.
AUTHORITY_DEPENDENCIES = (REPLY, CURRENT, LASH, 'WATER_BASE_WATER_INITIATION', 'WATER_BASE_RETURN_THE_FLOW')


def cold(path, mid):
    service = CombatService(ROOT, path)
    session = service._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return service, TabletopService(service, path), session.engine


def native(path, *, owned=True, auto=False, preset=0, walls=None, team1=((3, 4), (3, 5))):
    mechanics = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    bases = [k for k, row in mechanics.items() if row.get('sphere_id') == 'tianxia.sphere.water' and row.get('kind') == 'base_ability']
    for actor, name in ((OWNER, 'Reply owner'), (ALLY, 'Protected ally'), (FOE, 'Missed attacker')):
        doc = {'identity': {'display_name': name, 'proficiency_bonus': 2, 'cultivation_level': 1,
                           'path': 'Qi Cultivation', 'key_ability': 'CON'},
            'ability_scores_and_statistics': {
                'abilities': [{'ability': a, 'score': 14, 'modifier': 2} for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
                'primary_resource': {'name': 'Qi', 'maximum': 30}, 'armor_class': {'base_value': 14},
                'hit_points': {'maximum': 60}, 'speed': {'walking_ft': 30},
                'technique_save_dc': 16, 'technique_attack_bonus': 8},
            'equipment': [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian'}]}}],
            'spheres_and_talents': {'sphere_record_ids': ['tianxia.sphere.water'],
                'learned_talent_record_ids': [REPLY] if actor == OWNER and owned else [],
                'automatic_sphere_component_record_ids': bases}}
        pid = actor.removeprefix('actor:factory.')
        folder = path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(path / 'tabletop_buttons').save_reactions(pid, {'mode': 'auto' if auto and actor == OWNER else 'ask', 'options': {REPLY: preset}}, {REPLY}, {REPLY: 3})
    service = CombatService(ROOT, path)
    saved = service.tabletop_maps.save({'display_name': 'Reply yard', 'width_squares': 10, 'height_squares': 9,
        'walls': [{'shape': 'rect', 'points': [[x, y], [x + 1, y + 1]]} for x, y in ([[5, 5]] if walls is None else walls)], 'starts': {'team1': [list(p) for p in team1], 'team2': [[4, 5]]}})
    mid = service.create_factory_match(project_ids=['aaaaaaaa', 'bbbbbbbb'], opponent_actor_ids=[FOE],
        control_modes={a: ('LOCAL_AUTO' if auto and a == OWNER else 'MANUAL') for a in (OWNER, ALLY, FOE)},
        arena_id='battlefield:map.' + saved['map_id'], match_seed='MGR-T15-REPLY')['match_id']
    return service, TabletopService(service, path), mid


def candidate(service, table, mid, name, target=None, at=None):
    state = table.state(mid)
    choices = [c for c in service._load_session(mid).engine.legal_candidates()
               if name in c.display_name and (target is None or target in c.target_ids)
               and (at is None or c.destination and (c.destination.x, c.destination.y) == at)]
    assert choices, (name, target)
    return min(choices, key=lambda c: (len(c.display_name), c.candidate_id)), state['last_sequence']


def settle(path, mid, selected, choose=lambda p: None, *, reject_invalid=False):
    c, sequence = selected
    answers, prompts = [], []
    for _ in range(24):
        service, table, _ = cold(path, mid)
        result = table.act(mid, c.candidate_id, c.decision_id, c.state_version, sequence, answers)
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        if reject_invalid and prompt['context']['reaction_source_id'] == 'choice:needle.subject_destination':
            from combat.gate5_service import CombatServiceError
            from combat.tabletop import TabletopError
            before = service._load_session(mid).engine.state.model_dump(mode='json')
            bad = {**prompt['context'], 'selection': 'USE', 'option_ids': ['cell:99,99']}
            with pytest.raises((ValueError, CombatServiceError, TabletopError, ext.CheckpointError)) as refused:
                table.act(mid, c.candidate_id, c.decision_id, c.state_version, sequence, [*answers, bad])
            detail = getattr(getattr(refused.value, 'diagnostic', None), 'details', None) or {}
            # gate5 wraps the rejected intent; the underlying destination reason travels in details.reason.
            assert 'completed intent was rejected' in str(refused.value), refused.value
            assert 'destination' in str(detail.get('reason', '')).lower(), detail
            assert cold(path, mid)[2].state.model_dump(mode='json') == before
            reject_invalid = False
        option = choose(prompt)
        answers.append({**prompt['context'], 'selection': 'USE' if option is not None else 'DECLINE',
                        'option_ids': [option] if option else []})
    raise AssertionError('too many prompts')


def turn(path, mid, actor):
    for _ in range(10):
        service, table, engine = cold(path, mid)
        if engine.state.current_actor_id == actor:
            return
        settle(path, mid, candidate(service, table, mid, 'End'))
    raise AssertionError('turn did not arrive')


def dice(monkeypatch, natural=1, save_natural=None):
    def reply_fixed(engine, roll, intent):
        return {'source_id': 'test:reply-dice', 'operation': 'replace', 'natural_result': save_natural if save_natural is not None and 'SAVE' in str(roll.reason).upper() else natural}
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [r for r in ext._HOOKS.get('d20_result', []) if r.__name__ != 'reply_fixed'] + [reply_fixed])


def test_source():
    # Structural, not prose-hashed: the public export scrambles rule prose (#5323).
    assert REPLY in json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    row = json.loads((ROOT / 'authority/typed_mechanics/reviewed_final.d/elements.json').read_text())['mechanics'][REPLY]
    labels = [o['label'] for o in row['options']]
    assert len(labels) == 3 and labels[0].startswith('Move the attacker 10 feet')
    move = row['options'][0]['effects'][0]['on_fail'][0]
    assert move['type'] == 'movement' and move['forced'] and move['choose_subject_destination']


def test_generated_authority_contains_reviewed_reply_mechanics():
    reviewed = json.loads((ROOT / 'authority/typed_mechanics/reviewed_final.d/elements.json').read_text())['mechanics'][REPLY]
    generated = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics'][REPLY]

    # The compiler consumes the generated authority, not reviewed_final.d directly.
    assert generated['options'] == reviewed['options']
    assert generated['riders'] == []
    choices = generated['options']
    attacker_move = choices[0]['effects'][0]['on_fail'][0]
    assert attacker_move['choose_subject_destination'] is True
    assert choices[1]['effects'][0]['type'] == 'water_reply_protected'
    assert choices[2]['effects'][1]['type'] == 'water_reply_opening'
    assert choices[2]['effects'][0]['duration'] == {'kind': 'until_start_of_your_next_turn'}


def test_reply_trigger_is_a_public_runnable_reading():
    # Without this reviewed reading the printed trigger classifies as unsupported on public CI, so the Reply never compiles.
    from combat.reaction_triggers import classify_mechanic_all
    mechanic = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics'][REPLY]
    matches = classify_mechanic_all(mechanic)
    assert [m.kind for m in matches] == ['ally_missed'] and all(m.runnable for m in matches)
    assert matches[0].includes_self is True


@pytest.mark.parametrize('branch,protected', [(0, ALLY), (1, ALLY), (1, OWNER), (2, ALLY)])
def test_native_all_branches_and_separate_identities(tmp_path, monkeypatch, branch, protected):
    service, table, mid = native(tmp_path)
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    dice(monkeypatch)
    service, table, engine = cold(tmp_path, mid)
    before = {a: engine.state.actors[a].position for a in (OWNER, ALLY, FOE)}
    resources = dict(engine.state.actors[OWNER].resources)
    moved = FOE if branch == 0 else protected
    destination = 'cell:4,7' if branch == 0 else ('cell:1,5' if protected == ALLY else 'cell:1,4')
    def choose(prompt):
        source = prompt['context']['reaction_source_id']
        if source == f'reaction:typed.{REPLY}:mode:{branch}':
            assert all(name in str(prompt) for name in ('Mirror-Water Reply', 'Jian'))
            return ''
        if source == 'choice:needle.subject_destination':
            opts = prompt['choice']['options']
            assert destination in {o['id'] for o in opts}, prompt
            assert 'cell:5,5' not in {o['id'] for o in opts}  # wall
            assert 'cell:3,4' not in {o['id'] for o in opts}  # occupied owner
            return destination
        return None
    prompts = settle(tmp_path, mid, candidate(service, table, mid, 'Jian', protected), choose, reject_invalid=branch == 0)
    _, _, engine = cold(tmp_path, mid)
    assert any('Mirror-Water Reply' in str(p) for p in prompts), prompts
    assert not engine.state.actors[OWNER].reaction_available
    assert sum(resources.values()) - sum(engine.state.actors[OWNER].resources.values()) == 1
    if branch in (0, 1):
        x, y = map(int, destination.removeprefix('cell:').split(','))
        assert (engine.state.actors[moved].position.x, engine.state.actors[moved].position.y) == (x, y)
        assert engine.state.actors[moved].movement_remaining_ft == 30
        assert not any(e.event_type == 'ATTACK_ROLLED' and 'opportunity_attack' in e.source_definition_id
                       for e in engine.events)
    else:
        target = engine.state.actors[FOE]
        assert any('soaked' in c.condition_id for c in target.conditions.values())
        incoming = [m for m in target.modifiers.values() if m.source_definition_id == REPLY]
        assert len(incoming) == 1 and incoming[0].target_field == 'incoming_attack_mode'
        assert incoming[0].source_actor_id == OWNER and incoming[0].applies_to == 'NEXT_ATTACK'
        assert not any(m.source_definition_id == REPLY for m in engine.state.actors[OWNER].modifiers.values())
    for actor in (OWNER, ALLY, FOE):
        if branch == 2 or actor != moved:
            assert engine.state.actors[actor].position == before[actor]
    if branch == 2:
        turn(tmp_path, mid, OWNER)
        service, table, engine = cold(tmp_path, mid)
        assert not any(m.source_definition_id == REPLY for m in engine.state.actors[FOE].modifiers.values())
        assert any(c.source_definition_id == REPLY for c in engine.state.actors[FOE].conditions.values())
        settle(tmp_path, mid, candidate(service, table, mid, 'End'))
        _, _, engine = cold(tmp_path, mid)
        assert not any(c.source_definition_id == REPLY for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('case', ['decline', 'dry', 'no_owner'])
def test_native_no_cost_negative_boundaries(tmp_path, monkeypatch, case):
    service, table, mid = native(tmp_path, owned=case != 'no_owner')
    if case != 'dry':
        turn(tmp_path, mid, OWNER)
        service, table, _ = cold(tmp_path, mid)
        settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    dice(monkeypatch)
    service, table, before = cold(tmp_path, mid)
    resources = dict(before.state.actors[OWNER].resources)
    prompts = settle(tmp_path, mid, candidate(service, table, mid, 'Jian', ALLY))
    _, _, after = cold(tmp_path, mid)
    assert after.state.actors[OWNER].resources == resources
    assert after.state.actors[OWNER].reaction_available
    assert not any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == REPLY for e in after.events)
    assert bool([p for p in prompts if REPLY in p['context']['reaction_source_id']]) == (case == 'decline')


@pytest.mark.parametrize('branch', [0, 1, 2])
def test_automatic_owner_can_use_each_preset(tmp_path, monkeypatch, branch):
    # Compile the player's standing option before entering automatic control.
    service, table, mid = native(tmp_path, preset=branch)
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    service, table, before = cold(tmp_path, mid)
    service.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    dice(monkeypatch)
    prompts = settle(tmp_path, mid, candidate(service, table, mid, 'Jian', ALLY))
    _, _, after = cold(tmp_path, mid)
    assert not [p for p in prompts if REPLY in p['context']['reaction_source_id'] or
                p['context']['reaction_source_id'] == 'choice:needle.subject_destination']
    assert not after.state.actors[OWNER].reaction_available
    if branch == 0:
        assert after.state.actors[FOE].position != before.state.actors[FOE].position
    elif branch == 1:
        assert after.state.actors[ALLY].position != before.state.actors[ALLY].position
    else:
        assert any(m.source_definition_id == REPLY for m in after.state.actors[FOE].modifiers.values())


def test_strength_success_spends_cost_but_does_not_move(tmp_path, monkeypatch):
    service, table, mid = native(tmp_path)
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    dice(monkeypatch, save_natural=20)
    service, table, before = cold(tmp_path, mid)
    prompts = settle(tmp_path, mid, candidate(service, table, mid, 'Jian', ALLY),
        lambda p: '' if p['context']['reaction_source_id'] == f'reaction:typed.{REPLY}:mode:0' else None)
    _, _, after = cold(tmp_path, mid)
    assert after.state.actors[FOE].position == before.state.actors[FOE].position
    saves = [e for e in after.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id == REPLY]
    assert saves and saves[-1].actor_id == FOE and saves[-1].payload['success']
    assert not after.state.actors[OWNER].reaction_available
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.subject_destination' for p in prompts)


@pytest.mark.parametrize('case', ['soaked_protected', 'soaked_attacker_only', 'other_basin', 'wrong_basin'])
def test_native_water_qualification_uses_protected_creature(tmp_path, monkeypatch, case):
    service, table, mid = native(tmp_path)
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    if case.startswith('soaked'):
        dice(monkeypatch, natural=20)
        if case == 'soaked_protected':
            turn(tmp_path, mid, FOE)
            service, table, _ = cold(tmp_path, mid)
            settle(tmp_path, mid, candidate(service, table, mid, 'Water Lash', ALLY))
            settle(tmp_path, mid, candidate(*cold(tmp_path, mid)[:2], mid, 'End'))
        else:
            settle(tmp_path, mid, candidate(service, table, mid, 'Water Lash', FOE))
    elif case == 'wrong_basin':
        settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Cleansing Basin', at=(4, 5)))
    else:
        turn(tmp_path, mid, ALLY)
        service, table, _ = cold(tmp_path, mid)
        settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    dice(monkeypatch)
    service, table, _ = cold(tmp_path, mid)
    prompts = settle(tmp_path, mid, candidate(service, table, mid, 'Jian', ALLY))
    reply_prompts = [p for p in prompts if REPLY in p['context']['reaction_source_id']]
    assert bool(reply_prompts) == (case == 'soaked_protected')


def test_native_spent_reaction_cannot_reply(tmp_path, monkeypatch):
    service, table, mid = native(tmp_path)
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    dice(monkeypatch)
    service, table, _ = cold(tmp_path, mid)
    # This ordinary move leaves the owner's Jian reach but stays beside the ally.
    settle(tmp_path, mid, candidate(service, table, mid, 'Move', at=(4, 6)),
           lambda p: '' if 'opportunity_attack' in p['context']['reaction_source_id'] else None)
    service, table, engine = cold(tmp_path, mid)
    assert not engine.state.actors[OWNER].reaction_available
    prompts = settle(tmp_path, mid, candidate(service, table, mid, 'Jian', ALLY))
    assert not any(REPLY in p['context']['reaction_source_id'] for p in prompts)


def test_native_exhausted_cp_cannot_reply(tmp_path, monkeypatch):
    service, table, mid = native(tmp_path, preset=2)
    dice(monkeypatch)
    # Spend the imported pool through legal Basin casts and accepted Replies,
    # completing depletion before the native 20-round draw limit.
    for _ in range(18):
        turn(tmp_path, mid, OWNER)
        service, table, engine = cold(tmp_path, mid)
        if engine.state.actors[OWNER].resources['resource:core.qi'] == 0:
            break
        settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
        turn(tmp_path, mid, FOE)
        service, table, engine = cold(tmp_path, mid)
        if engine.state.actors[OWNER].resources['resource:core.qi'] == 0:
            break
        service.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
        settle(tmp_path, mid, candidate(service, table, mid, 'Jian', ALLY))
        service = cold(tmp_path, mid)[0]
        service.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
        settle(tmp_path, mid, candidate(*cold(tmp_path, mid)[:2], mid, 'End'))
    else:
        raise AssertionError('native CP pool did not exhaust')
    turn(tmp_path, mid, FOE)
    service, table, engine = cold(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 0
    assert engine.state.actors[OWNER].reaction_available
    prompts = settle(tmp_path, mid, candidate(service, table, mid, 'Jian', ALLY))
    assert not any(REPLY in p['context']['reaction_source_id'] for p in prompts)
    assert cold(tmp_path, mid)[2].state.actors[OWNER].reaction_available


def test_legal_destination_need_not_be_visible_to_owner(tmp_path, monkeypatch):
    # The wall at (4,4) blocks the owner's sight of (5,4) but also of (4,5) from the
    # default start (3,4), so no Basin can be made there. Start the owner at (2,4):
    # it sees (4,5) to make the Basin and still cannot see (5,4).
    service, table, mid = native(tmp_path, walls=[[4, 4]], team1=((2, 4), (3, 5)))
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    dice(monkeypatch)
    service, table, engine = cold(tmp_path, mid)
    from combat.gate2_runtime_models import Position
    assert not engine._line_of_sight_actor_to_cell(engine.state.actors[OWNER], Position(x=5, y=4))
    def choose(prompt):
        source = prompt['context']['reaction_source_id']
        if source == f'reaction:typed.{REPLY}:mode:0':
            return ''
        if source == 'choice:needle.subject_destination':
            assert 'cell:5,4' in {o['id'] for o in prompt['choice']['options']}
            return 'cell:5,4'
        return None
    settle(tmp_path, mid, candidate(service, table, mid, 'Jian', ALLY), choose)
    assert cold(tmp_path, mid)[2].state.actors[FOE].position == Position(x=5, y=4)


@pytest.mark.parametrize('cancelled', [False, True])
def test_owner_turn_reply_next_attack_consumes_once(tmp_path, monkeypatch, cancelled):
    service, table, mid = native(tmp_path)
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    # Renew the Action on the owner's next turn, then provoke an actual OA.
    settle(tmp_path, mid, candidate(*cold(tmp_path, mid)[:2], mid, 'End'))
    turn(tmp_path, mid, OWNER)
    dice(monkeypatch)
    service, table, _ = cold(tmp_path, mid)
    def choose(prompt):
        source = prompt['context']['reaction_source_id']
        return '' if 'opportunity_attack' in source or source == f'reaction:typed.{REPLY}:mode:2' else None
    prompts = settle(tmp_path, mid, candidate(service, table, mid, 'Move', at=(2, 4)), choose)
    service, table, engine = cold(tmp_path, mid)
    assert any(REPLY in p['context']['reaction_source_id'] for p in prompts)
    assert any(m.source_definition_id == REPLY for m in engine.state.actors[FOE].modifiers.values())
    if cancelled:
        # Move back adjacent so ranged Water Lash has Disadvantage, which
        # cancels the incoming Advantage but still consumes the one next roll.
        settle(tmp_path, mid, candidate(service, table, mid, 'Move', at=(3, 4)))
        service, table, engine = cold(tmp_path, mid)
    start = engine.state.event_sequence
    settle(tmp_path, mid, candidate(service, table, mid, 'Water Lash', FOE))
    service, table, engine = cold(tmp_path, mid)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.sequence > start and e.actor_id == OWNER]
    assert attacks and attacks[-1].payload['mode'] == ('NORMAL' if cancelled else 'ADVANTAGE')
    assert not any(m.source_definition_id == REPLY for m in engine.state.actors[FOE].modifiers.values())
    assert any(e.event_type == 'MODIFIER_REMOVED' and e.source_definition_id == REPLY and
               e.payload.get('reason') == 'CONSUMED' for e in engine.events if e.sequence > start)


@pytest.mark.parametrize('branch', [0, 1, 2])
def test_player_reply_on_fake_model_turn_cold_resumes(tmp_path, monkeypatch, branch):
    from combat.gate5_service import AI_RESPONSE_SCHEMA
    service, table, mid = native(tmp_path)
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    service, table, before = cold(tmp_path, mid)
    service.set_controller_mode(mid, actor_id=FOE, controller_mode='API_AUTO')
    dice(monkeypatch)
    class Provider:
        calls = 0
        def status(self):
            return {'ready': True}
        def complete_json(self, *, prompt_text, **kwargs):
            self.calls += 1
            frame = json.loads(prompt_text.split('\n\n', 1)[1])
            c = next(c for c in frame['legal_candidates'] if 'Jian' in c['display_name'] and ALLY in c['target_ids'])
            payload = {k: c[k] for k in ('candidate_id', 'actor_id', 'target_ids', 'destination', 'option_ids')}
            payload.update(decision_id=frame['decision_id'], state_version=frame['state_version'])
            return {'value': {'schema': AI_RESPONSE_SCHEMA, 'action_intent': payload, 'rationale': 'Attack the visible ally.'},
                    'provider_id': 'test:offline', 'model': 'fake', 'request_sha256': 'reply-offline-request'}
    provider = Provider()
    service = CombatService(ROOT, tmp_path, ai_provider=provider)
    table = TabletopService(service, tmp_path)
    after = table.state(mid)['last_sequence']
    result = table.auto_step(mid, after)
    answers, seen = [], []
    for _ in range(12):
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        source = prompt['context']['reaction_source_id']
        seen.append(source)
        option = None
        if source == f'reaction:typed.{REPLY}:mode:{branch}':
            assert all(text in str(prompt) for text in ('Mirror-Water Reply', 'Jian', 'Protected ally'))
            option = ''
        if source == 'choice:needle.subject_destination':
            option = prompt['choice']['options'][0]['id']
        answers.append({**prompt['context'], 'selection': 'USE' if option is not None else 'DECLINE',
                        'option_ids': [option] if option else []})
        service, table, paused = cold(tmp_path, mid)
        assert paused.state.actors[OWNER].resources == before.state.actors[OWNER].resources
        assert paused.state.actors[OWNER].reaction_available
        result = table.auto_step(mid, after, answers)
    assert result['status'] == 'COMMITTED' and provider.calls == 1, result
    engine = cold(tmp_path, mid)[2]
    assert not engine.state.actors[OWNER].reaction_available
    assert any(REPLY in source for source in seen)


def test_human_owner_chooses_for_automatic_protected_ally(tmp_path, monkeypatch):
    service, table, mid = native(tmp_path)
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    service, table, _ = cold(tmp_path, mid)
    service.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    dice(monkeypatch)
    def choose(prompt):
        source = prompt['context']['reaction_source_id']
        if source == f'reaction:typed.{REPLY}:mode:1':
            return ''
        if source == 'choice:needle.subject_destination':
            assert prompt['context']['reactor_id'] == OWNER
            return 'cell:2,5'
        return None
    settle(tmp_path, mid, candidate(service, table, mid, 'Jian', ALLY), choose)
    ally = cold(tmp_path, mid)[2].state.actors[ALLY]
    assert (ally.position.x, ally.position.y) == (2, 5)


def test_reply_does_not_invent_a_range_to_the_attacker(tmp_path, monkeypatch):
    service, table, mid = native(tmp_path)
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Move', at=(4, 8)))
    dice(monkeypatch)
    service, table, engine = cold(tmp_path, mid)
    assert engine._distance_actor_to_actor(engine.state.actors[OWNER], engine.state.actors[FOE]) == 20
    start = engine.state.event_sequence
    def choose(prompt):
        source = prompt['context']['reaction_source_id']
        if source == f'reaction:typed.{REPLY}:mode:0':
            return ''
        if source == 'choice:needle.subject_destination':
            return 'cell:4,6'
        return None
    settle(tmp_path, mid, candidate(service, table, mid, 'Water Lash', ALLY), choose)
    engine = cold(tmp_path, mid)[2]
    assert (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y) == (4, 6)
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.sequence > start]
    assert attacks and not attacks[0].payload['provisional_hit']
