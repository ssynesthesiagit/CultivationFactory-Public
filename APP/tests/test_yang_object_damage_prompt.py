"""Yang Current's object damage choice through a sealed table action and replay."""
from combat.canonical import canonical_sha256
from combat.ext import effect
from combat.gate2_runtime_models import Position, RuntimeObjectState
from tests.test_a2_qi_subpaths_6 import FLOW, choose_current
from tests.worker2_support import OWNER, candidate, fixture, reload, settle

OBJECT = 'object:test.yang_object'
NAME = 'Carved stone urn'


@effect('test_yang_object_setup', harmful=False)
def setup_object(ctx, row):
    ctx.engine._update_object(RuntimeObjectState(
        object_id=OBJECT, object_kind='custom', position=Position(x=4, y=6),
        current_hp=500, maximum_hp=500, ac=1, unattended=True, flammable=False,
        component={'blocks': False, 'material': 'stone', 'name': NAME}), ctx.source)


def test_yang_current_names_object_and_bonus_survives_reload(tmp_path, monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority

    def prepare(bundles):
        owner = bundles[0]
        sid = 'action:test.yang_object_setup'
        owner['action_catalog'].append({
            'source_definition_id': sid, 'display_name': 'Place urn', 'owner_id': OWNER,
            'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
            'parameters': {'free_primary': True, 'typed': {
                'source': sid, 'effects': [{'type': 'test_yang_object_setup'}],
                'numbers': {}, 'riders': [], 'duration': {'kind': 'instant'}}}})
        owner['actor_template']['action_ids'].append(sid)
        for action in owner['action_catalog']:
            typed = action.get('parameters', {}).get('typed', {})
            if typed.get('source') == 'TAL_DEATH_ROTTING_GRASP':
                typed['numbers']['attack_bonus'] = 100
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)

    combat, table, mid = fixture(tmp_path, ['TAL_DEATH_ROTTING_GRASP', FLOW],
        cl=5, named=True, bundle_transform=prepare, seed='YANG-OBJECT-PROMPT')
    choose_current(table, mid, 'yang')
    settle(table, mid, candidate(combat, mid, 'Place urn').candidate_id)
    before = reload(tmp_path, mid)
    owner_name = before.state.actors[OWNER].display_name
    assert before.state.actors[OWNER].turn_flags.get('_round_balanced_yang') is None
    original_die = DeterministicRollAuthority._die

    def hit_die(roller, sides):
        if sides == 20:
            index = roller.counter
            roller.counter += 1
            return 10, index
        return original_die(roller, sides)

    monkeypatch.setattr(DeterministicRollAuthority, '_die', hit_die)
    prompts = settle(table, mid, candidate(combat, mid, 'Rotting Grasp', target=OBJECT).candidate_id,
        choices={'choice:needle.balanced_yang': ['increase']})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.balanced_yang')
    assert 'Rotting Grasp' in prompt['moment']
    assert 'affecting ' + NAME in prompt['moment']
    assert 'affecting ' + owner_name not in prompt['moment']
    engine = reload(tmp_path, mid)
    roll = next(r for r in reversed(engine.rolls) if r.reason.startswith('DAMAGE:') and r.actor_id == OWNER)
    assert roll.modifier == engine.state.actors[OWNER].proficiency_bonus
    assert 500 - engine.state.objects[OBJECT].current_hp == roll.total
    assert engine.state.actors[OWNER].turn_flags['_round_balanced_yang'] == f'{engine.state.round_number}:{OWNER}'
