"""Real service regressions for the four placement-menu review findings."""
import json
from types import SimpleNamespace

import pytest

from combat import placement_menu
from combat.ext import free_uses, needle, placed
from combat.gate5_service import AI_RESPONSE_SCHEMA
from tests.test_menuspeed3_review import offline_menu_embeddings, payload
from tests.test_menuspeed3_placement import setup, root_for
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn


def named_row(combat, mid, name):
    return next(c for c in combat._legal_candidates(combat._load_session(mid))
                if c.display_name.startswith(name))


def test_native_vessel_local_auto_raise_and_reposition_reload(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, ['PUPPETRY_BASE_RAISE_THE_VESSEL', 'PUPPETRY_BASE_PUPPET_STRIKE'])
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    with placement_menu.query():
        context = combat.ai_decision_context(combat._load_session(mid))
    root = next(c for c in context.legal_candidates if c.source_definition_id.endswith('vessel.raise'))
    assert root.metadata.get('placement_evaluation'), 'native Vessel AI gate must evaluate concrete squares'
    result = combat.auto_step(mid)
    assert result['status'] == 'COMMITTED', result
    engine = reload(tmp_path, mid)
    raised = placed.of(engine, 'vessel', owner_id=OWNER)
    assert raised
    before = raised[0].center
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    turn(table, mid, FOE)
    session = combat._load_session(mid)
    move = max((c for c in session.engine.legal_candidates() if c.kind == 'MOVE'),
               key=lambda c: c.destination.x)
    settle(table, mid, move.candidate_id)
    turn(table, mid, OWNER)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    context = combat.ai_decision_context(combat._load_session(mid))
    root = next(c for c in context.legal_candidates if c.source_definition_id.endswith('vessel.move'))
    assert root.metadata.get('placement_evaluation')
    from tests.test_menuspeed3_review import drive_auto
    drive_auto(combat, mid, root, monkeypatch, 'LOCAL_AUTO')
    assert placed.of(reload(tmp_path, mid), 'vessel', owner_id=OWNER)[0].center != before


def test_table_square_warning_names_unavoidable_ally(tmp_path):
    # A sealed area probe exercises the native safety projection, not a fake
    # picker row. The unavoidable recipient is present in the real table.
    from combat.canonical import canonical_sha256
    def area_probe(bundles):
        b = bundles[0]
        sid = 'action:test.placement_warning'
        b['actor_template']['action_ids'].append(sid)
        b['action_catalog'].append({'source_definition_id': sid, 'owner_id': OWNER,
            'display_name': 'Force burst', 'economy': 'ACTION', 'resolution_kind': 'TYPED',
            'target_kind': 'CELL', 'range_ft': 60, 'parameters': {'typed': {
                'area': {'shape': 'sphere', 'size_ft': 10},
                'effects': [{'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'creatures_in_area'}],
                'numbers': {}, 'duration': {'kind': 'instant'}, 'riders': []}}})
        b.pop('bundle_sha256', None)
        b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [], named=True, bundle_transform=area_probe)
    root = named_row(combat, mid, 'Force burst')
    rows = list(placement_menu.cells(combat._load_session(mid).engine, root))
    hit = next(c for c in rows if 'Hits allies too: Tobin' in c.display_name)
    prompts = settle(table, mid, root.candidate_id,
                     picks={placement_menu.CHOICE: needle.cell_id(hit.destination, include_altitude=True)})
    picker = next(p for p in prompts if p['context']['reaction_source_id'] == placement_menu.CHOICE)
    option = next(o for o in picker['choice']['options'] if o['id'] == needle.cell_id(hit.destination, include_altitude=True))
    assert 'Hits allies too: Tobin' in option['label'], 'square presentation must retain native ally warning'
    assert option['cell'] in picker['choice']['map_pick']['cells']
    reload(tmp_path, mid)


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('fund', ['court_of_charged_paths', 'lightning_sovereign_incarnation', 'automatic'])
def test_funding_choice_persists_and_preserves_lash(tmp_path, monkeypatch, reverse, fund):
    talents = ['TAL_LIGHTNING_LIGHTNING_SOVEREIGN_INCARNATION', 'TAL_LIGHTNING_COURT_OF_CHARGED_PATHS',
               'TAL_LIGHTNING_GATHER_CHARGE', 'TAL_LIGHTNING_LIGHTNING_LASH']
    if reverse:
        talents.reverse()
    combat, table, mid = fixture(tmp_path, talents)
    settle(table, mid, named_row(combat, mid, 'Court of Charged Paths').candidate_id)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, named_row(combat, mid, 'Lightning Sovereign Incarnation').candidate_id)
    engine = combat._load_session(mid).engine
    free = next(c for c in combat._legal_candidates(combat._load_session(mid))
                if 'Gather Charge' in c.display_name and '(free)' in c.display_name)
    grants = engine.action_catalog[free.source_definition_id].parameters['free_use']['grants']
    grant = next(g for g in grants if g['state'] == ('court_of_charged_paths' if fund == 'automatic' else fund))
    if fund == 'automatic':
        from tests.test_menuspeed3_review import drive_auto
        drive_auto(combat, mid, free, monkeypatch, 'LOCAL_AUTO')
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    else:
        prompts = settle(table, mid, free.candidate_id, picks={free_uses.CHOICE: grant['key']})
        assert any(p['context']['reaction_source_id'] == free_uses.CHOICE for p in prompts), 'funding grant must be selectable'
    saved = reload(tmp_path, mid)
    assert saved.state.actors[OWNER].turn_flags[free_uses._flag(saved, grant)]
    lash = [c for c in saved.legal_candidates() if 'Lightning Lash' in c.display_name and '(free)' in c.display_name]
    assert bool(lash) == (fund != 'lightning_sovereign_incarnation')
    if lash:
        settle(table, mid, lash[0].candidate_id)
        reload(tmp_path, mid)


def test_api_provider_discovers_unsampled_square_in_real_exchange(tmp_path, monkeypatch):
    combat, _, mid = setup(tmp_path)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='API_AUTO')
    root = root_for(combat, mid)
    session = combat._load_session(mid)
    from combat.candidate_knowledge import query as observed
    with observed(session.engine):
        legal = list(placement_menu.cells(session.engine, root))
    # Observe ranking probes without changing their answers. The provider will
    # choose a square it discovers only in the second frame, outside that set.
    probed = set()
    native_exact = placement_menu.exact
    def record_probe(engine, candidate, position):
        if candidate.candidate_id == root.candidate_id:
            probed.add(json.dumps(position.model_dump(mode='json'), sort_keys=True))
        return native_exact(engine, candidate, position)
    monkeypatch.setattr(placement_menu, 'exact', record_probe)
    placement_menu.search(session.engine, root, combat.ai_decision_context(session))
    assert probed, 'the real placement sampler must establish the unsampled choice'
    expected = {json.dumps(c.destination.model_dump(mode='json'), sort_keys=True) for c in legal}
    calls, aimed = [], []
    def complete(**kwargs):
        calls.append(kwargs['purpose'])
        frame = json.loads(kwargs['prompt_text'].split('\n\n', 1)[1])
        if kwargs['purpose'] == 'combat_decision':
            assert 'second frame' in frame['response_schema']['action_intent']['placement_destination']
            selected = next(c for c in frame['legal_candidates'] if c['candidate_id'] == root.candidate_id)
            answer = {k: selected[k] for k in ('candidate_id', 'actor_id', 'target_ids', 'destination', 'option_ids')}
            answer.update(decision_id=frame['decision_id'], state_version=frame['state_version'])
            answer['placement_destination'] = None  # explicit null has the same first-stage meaning as omission
        else:
            assert kwargs['purpose'] == 'combat_placement'
            assert frame['decision_context']['active_actor_id'] == OWNER
            assert {json.dumps(p['placement_destination'], sort_keys=True) for p in frame['legal_placements']} == expected
            aimed.append(next(p['placement_destination'] for p in frame['legal_placements']
                              if json.dumps(p['placement_destination'], sort_keys=True) not in probed))
            answer = {**frame['action_intent'], 'placement_destination': aimed[0]}
        return {'value': {'schema': AI_RESPONSE_SCHEMA, 'action_intent': answer}, 'provider_id': 'test:offline', 'model': 'fake'}
    combat.ai_provider = SimpleNamespace(status=lambda: {'ready': True}, complete_json=complete)
    assert combat.auto_step(mid)['status'] == 'COMMITTED'
    assert calls == ['combat_decision', 'combat_placement']
    from combat.gate2_runtime_models import Position
    assert any(z.center == Position.model_validate(aimed[0]) for z in reload(tmp_path, mid).state.zones.values())
