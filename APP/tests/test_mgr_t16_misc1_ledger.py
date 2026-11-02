"""Ledger choice/scope/transfer regressions via native service transactions."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext.fate_riders import LEDGER, LEDGER_ABILITY, LEDGER_TRACKING
from combat.typed_executor import check_mode
from tests.worker2_support import (OWNER, ALLY, FOE, candidate, fixture, reload,
                                  sealed_native_attack, settle, turn)


def probe(bundle, ability, skill=None, hazards=()):
    """A sealed check source exercises the public context seam, never a live model."""
    source = f'action:test.ledger.{bundle["actor_id"]}.{ability}.{skill}.{"-".join(hazards)}'
    row = {'source_definition_id': source, 'display_name': 'Probe '+ability+str(skill)+str(hazards),
           'owner_id': bundle['actor_id'], 'economy': 'ACTION', 'resolution_kind': 'TYPED',
           'target_kind': 'ANY_CREATURE', 'range_ft': 60, 'parameters': {'typed': {
               'source': source, 'numbers': {}, 'effects': [{'type': 'contest_against',
                 'actor_check': {'kind': 'check', 'ability': ability, 'skill': skill, 'hazards': list(hazards)},
                 'target_check': {'kind': 'dc', 'dc': 15}, 'on_success': [], 'on_fail': []}]}}, 'costs': []}
    bundle['action_catalog'].append(row)
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    return row['display_name']


def checks(engine, actor):
    return [e.payload['actor'] for e in engine.events if e.event_type == 'CHECK_ROLLED'
            and e.actor_id == actor and str(e.source_definition_id).startswith('action:test.ledger.')]


def auto_candidate(combat, table, mid, cid):
    """A fake primary selector, with real LOCAL_AUTO reaction/choice handling."""
    from combat.gate4_adapters import ManualControllerAdapter
    real=combat.controller
    class Pick:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context:(cid,())).choose_primary_action(context)
        def __getattr__(self,name):
            return getattr(real,name)
    combat.controller=Pick()
    return settle(table,mid,cid,auto=True)


@pytest.mark.parametrize('ask,ability', [(True,a) for a in ['STR','DEX','CON','INT','WIS','CHA']] + [(False,'STR')])
def test_all_six_ability_choices_penalize_only_the_chosen_checks(tmp_path, ask, ability):
    labels = []
    def seal(bundles):
        labels.append(probe(bundles[2], ability))
    combat, table, mid = fixture(tmp_path, [LEDGER], owner_dc=100,
        seed='T16-LEDGER-'+ability, ask=True, bundle_transform=seal,
        modes={OWNER:'MANUAL' if ask else 'LOCAL_AUTO', ALLY:'MANUAL', FOE:'MANUAL'})
    cid=candidate(combat,mid,'Marked by the Ledger: Disadvantage on Checks',target=FOE).candidate_id
    prompts=(settle(table,mid,cid,picks={'choice:needle.fate_ledger_ability':[ability]})
             if ask else auto_candidate(combat,table,mid,cid))
    engine = reload(tmp_path, mid)
    conditions = [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == LEDGER_ABILITY]
    assert conditions
    selected = conditions[-1].data['ability']
    if ask:
        assert selected == ability
        prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.fate_ledger_ability')
        assert {o['id'] for o in prompt['choice']['options']} == {'STR','DEX','CON','INT','WIS','CHA'}
    assert check_mode(engine.state.actors[FOE], selected, engine=engine) == 'DISADVANTAGE'
    other = next(a for a in ['STR','DEX','CON','INT','WIS','CHA'] if a != selected)
    assert check_mode(engine.state.actors[FOE], other, engine=engine) == 'NORMAL'
    if ask or selected == ability:
        if not ask:
            combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='MANUAL')
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, labels[0], target=OWNER).candidate_id)
        assert checks(reload(tmp_path, mid), FOE)[-1]['mode'] == 'DISADVANTAGE'


@pytest.mark.parametrize('skill,purpose,target,expected', [
    ('Perception', 'find', FOE, 'ADVANTAGE'),
    ('Survival', 'track', FOE, 'ADVANTAGE'),
    ('Perception', 'study', FOE, 'NORMAL'),
    ('Survival', 'track', ALLY, 'NORMAL'),
])
def test_tracking_scope_requires_marked_subject_and_find_or_track(tmp_path, skill, purpose, target, expected):
    labels=[]
    def seal(bundles):
        labels.append(probe(bundles[0], 'WIS', skill, (purpose,)))
    combat, table, mid = fixture(tmp_path, [LEDGER], owner_dc=100,
        seed='T16-TRACK-'+skill+purpose+target, bundle_transform=seal)
    settle(table, mid, candidate(combat, mid, 'Marked by the Ledger: Tracking Advantage', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == LEDGER_TRACKING for c in engine.state.actors[OWNER].conditions.values())
    assert check_mode(engine.state.actors[OWNER], 'WIS', skill, engine=engine) == 'NORMAL'
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, labels[0], target=target).candidate_id)
    assert checks(reload(tmp_path, mid), OWNER)[-1]['mode'] == expected


@pytest.mark.parametrize('branch', ['Tracking Advantage', 'Disadvantage on Checks'])
def test_moving_ledger_mark_moves_its_check_binding_and_preserves_expiry(tmp_path, branch):
    def seal(bundles):
        sealed_native_attack(bundles[1], 'Finisher', count=1, sides=2, modifier=100, attack_bonus=100)
    combat, table, mid = fixture(tmp_path, [LEDGER], owner_dc=100, extra_foes=1,
        seed='T16-TRANSFER-'+branch, bundle_transform=seal)
    settle(table, mid, candidate(combat, mid, 'Marked by the Ledger: '+branch, target=FOE).candidate_id,
           picks={'choice:needle.fate_ledger_ability': ['WIS']})
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Finisher', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    turn(table, mid, OWNER)
    new = FOE+'1'
    before = next(c for a in engine.state.actors.values() for c in a.conditions.values()
                  if c.condition_id in {LEDGER_TRACKING, LEDGER_ABILITY})
    settle(table, mid, candidate(combat, mid, 'Move the Ledger Mark', target=new).candidate_id)
    engine = reload(tmp_path, mid)
    after = next(c for a in engine.state.actors.values() for c in a.conditions.values()
                 if c.condition_id in {LEDGER_TRACKING, LEDGER_ABILITY})
    assert after.expires_on == before.expires_on
    if branch == 'Tracking Advantage':
        assert after.data['target_id'] == new
    else:
        assert after.target_id == new
        assert not any(c.condition_id == LEDGER_ABILITY for c in engine.state.actors[FOE].conditions.values())
