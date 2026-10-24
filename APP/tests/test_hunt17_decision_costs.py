"""Printed immediate prices agree with actual table payment and fresh reloads."""
import pytest
from combat import ext
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.r1i_service_support import OWNER, FOE, fixture, candidate, force_ai_candidate
from tests.test_formations import _sheet
from tests.r10_fixup_support import cast_sender, commit as commit_send

BLOOD = 'tianxia.path.body_refining.feature.blood_pump'


@pytest.mark.parametrize('auto', [False, True])
def test_blood_pump_prompt_names_actual_price_before_commit(tmp_path, monkeypatch, auto):
    def lethal(ctx, effect):
        target = ctx.engine.state.actors[OWNER]
        ctx.engine._commit_damage(target, target.current_hp + 1, 'FORCE', ctx.source, FOE,
                                 ctx.intent, reaction_depth=0)
    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, 'test_lethal_blow', lethal)
    def prepare(bundles):
        doc = sheet([BLOOD], cl=17, primary='Stamina')
        doc['identity']['path'] = 'Body Refining'
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 60
        bundles[0] = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
        foe = bundles[1]
        action = ActionDefinition(source_definition_id='action:test.lethal_blow', display_name='Lethal blow',
            owner_id=FOE, economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='HOSTILE_ENTITY',
            range_ft=5, parameters={'typed': {'effects': [{'type': 'test_lethal_blow'}], 'numbers': {}, 'riders': []}})
        foe['action_catalog'].append(action.model_dump(mode='json'))
        foe['actor_template']['action_ids'] = [*foe['actor_template']['action_ids'], action.source_definition_id]
        foe.pop('bundle_sha256', None)
        foe['bundle_sha256'] = canonical_sha256(foe)
    combat, table, mid, send, commit = fixture(tmp_path, [BLOOD], bundle_transform=prepare)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    action = candidate(table, mid, 'Lethal blow', OWNER)
    if auto:
        force_ai_candidate(combat, mid, FOE, action)
    before = dict(combat._load_session(mid).engine.state.actors[OWNER].resources)
    result = send(action, auto=auto)
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['reaction'] == 'Blood Pump'
    assert '6 Stamina' in prompt['cost'] and 'Reaction' not in prompt['cost']
    assert '1 Hit Point' in prompt['rules'] and 'Once per scene' in prompt['rules']
    assert send(action, [{**prompt['context'], 'selection': 'USE', 'option_ids': ['use']}], auto=auto)['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = fresh.engine.state.actors[OWNER]
    assert actor.current_hp == 1
    assert actor.resources['resource:core.stamina'] == before['resource:core.stamina'] - 6
    assert actor.reaction_available
    assert fresh.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('auto', [False, True])
def test_devours_prompt_shows_reaction_and_paying_pool(tmp_path, auto):
    talent = 'tianxia.talent.formations.formation_devours_technique'
    def prepare(bundles):
        doc = _sheet([talent], 17, 60)
        doc['ability_scores_and_statistics']['primary_resource']['name'] = 'Stamina'
        bundles[0] = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid, send, commit = fixture(tmp_path, [talent],
        foe_talents=['TAL_METAL_THOUSAND_EDGE_RAIN'], bundle_transform=prepare,
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 8, 'y': 6},
                   'actor:factory.r1i-second': {'x': 3, 'y': 7}})
    commit_send(cast_sender(combat, table, mid, 'Combat Array: Locking Gate', at=(4, 6)))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    before = dict(combat._load_session(mid).engine.state.actors[OWNER].resources)
    engine = combat._load_session(mid).engine
    options = [c for c in engine.legal_candidates() if 'Thousand-Edge Rain' in c.display_name and c.destination]
    assert options
    action = min(options, key=lambda c: abs(c.destination.x - 3) + abs(c.destination.y - 6))
    caster = cast_sender(combat, table, mid, 'Thousand-Edge Rain', at=(action.destination.x, action.destination.y))
    if auto:
        force_ai_candidate(combat, mid, FOE, action.candidate_id)
        caster = lambda answers=(): table.auto_step(mid, 0, list(answers))
    result = caster()
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert '3 Stamina' in prompt['cost'] and 'Reaction' in prompt['cost']
    assert 'not charge' not in prompt['table_note']
    answers = [{**prompt['context'], 'selection': 'USE', 'option_ids': ['prevent']}]
    result = caster(answers)
    if result['status'] == 'REACTION_REQUIRED':
        # AUTO45 asks the manual caster which creatures in the area to affect.
        # Answer that recipient choice to reach the table's payment commit.
        # Select no recipients; do not silently accept another paid reaction.
        recipients = result['reaction']
        assert recipients['context']['reaction_source_id'] == 'choice:needle.area_recipients'
        assert recipients['choice']['minimum'] == 0
        answers.append({**recipients['context'], 'selection': 'USE', 'option_ids': []})
        result = caster(answers)
    assert result['status'] == 'COMMITTED', result.get('reaction')
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = fresh.engine.state.actors[OWNER]
    assert actor.resources['resource:core.stamina'] == before['resource:core.stamina'] - 3
    assert not actor.reaction_available
    assert fresh.mechanical.replay()['status'] == 'PASS'
