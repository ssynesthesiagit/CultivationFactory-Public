"""Fix-round regressions for the Sol review of the Orbiting Shield Warden lane.

F1: a real bound Shield that is floating when a fight ends must keep its own
identity, HP and item profile through a journey continuation, and stay
selectable by Bound Shield after cold reload.

F2: Shield-Step Escort must be offered after a qualifying Interposition move
and after a Close the Bulwark move.
"""
from types import SimpleNamespace as NS

import pytest

from combat.ext import orbiting_shield_warden as w
from combat.ext.scoundrel_riders import object_id
from combat.gate5_service import CombatService
from combat.relations import ALLY, ENEMY, relation as _relation
from combat.tabletop_service import TabletopService
from tests import r1i_service_support as s
from tests.h1_support import ROOT
from tests.test_mgr_t14_orbiting_shield_warden_floor58 import RAISE, choose_and_commit
from tests.test_mgr_t14_warden_review_f9 import advance, bound_fight, commit, fresh, options

DEFLECT = w.DEFLECT


def _select(prompt, ids):
    if any(i.startswith('cell:') for i in ids):
        return ['cell:4,5,0'] if 'cell:4,5,0' in ids else []
    if s.OWNER in ids:
        return [s.OWNER]
    return None


def _finish(table, combat, mid):
    for _ in range(80):
        if fresh(combat, mid).state.terminal_result is not None:
            return
        commit(table, mid, table.state(mid)['menu']['end_turn'], _select)
    pytest.fail('Round-capped fight did not finish')


def test_f1_floating_real_shield_survives_continuation_with_identity(tmp_path):
    combat, table, mid, state, item = bound_fight(tmp_path)
    commit(table, mid, s.candidate(table, mid, 'Release bound Shield'), _select)
    real_id = object_id(s.OWNER, item['key'])
    assert real_id in fresh(combat, mid).state.objects
    _finish(table, combat, mid)
    jid = state['journey_id']
    combat = CombatService(ROOT, tmp_path)
    resumed = combat.journey_resume(jid, combat.journey_state(jid)['revision'])
    mid2 = combat.journey_start_combat(jid, resumed['revision'], {s.OWNER: 'team:a', s.FOE: 'team:b'})['match_id']
    table2 = TabletopService(combat, tmp_path)
    advance(table2, mid2, s.OWNER)
    engine = fresh(combat, mid2)
    # No projected replacement may take the place of the actual item.
    assert not [o for o in engine.state.objects.values() if o.object_id.startswith('object:warden.journey.')]
    real = engine.state.objects[real_id]
    assert real.object_kind == 'BOUND_SHIELD'
    assert not real.component[w.TAG]['projected']
    assert real.maximum_hp == state['actors'][s.OWNER]['source_states'][w.BOND]['profile']['hp']
    assert options(table2, mid2, 'Call bound Shield')
    assert combat.journey_replay(jid)['status'] == 'PASS'


def test_f2_interposition_offers_shield_step_escort_after_qualifying_move(tmp_path, monkeypatch):
    calls = []
    original = w.escort_step

    def record(engine, owner, obj, key):
        calls.append(key)
        return original(engine, owner, obj, key)

    monkeypatch.setattr(w, 'escort_step', record)
    combat, table, mid, send, commit_ = s.fixture(tmp_path, [RAISE, DEFLECT], owner_cl=6, owner_ac=2,
        foe_score=10, seed='WARDEN-ESCORT-INTERPOSE', wide=True)

    def source_answers(prompt, options_):
        ids = [o['id'] for o in options_]
        for desired in ('cell:3,5,0', s.OWNER, 'absorb', 'turn'):
            if desired in ids:
                return [desired]
        return None

    choose_and_commit(table, mid, send, s.candidate(table, mid, 'Manifest Ward'), source_answers)
    choose_and_commit(table, mid, send, table.state(mid)['menu']['end_turn'], source_answers)
    for _ in range(6):
        if table.state(mid)['menu']['actor_id'] == s.FOE:
            break
        choose_and_commit(table, mid, send, table.state(mid)['menu']['end_turn'], source_answers)
    assert table.state(mid)['menu']['actor_id'] == s.FOE
    cid = s.candidate(table, mid, 'Unarmed Strike', s.OWNER)
    answers = []
    seen = False
    for _ in range(48):
        result = send(cid, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        answer = {**p['context'], 'selection': 'DECLINE'}
        if p.get('choice'):
            opts = p['choice']['options']
            ids = [o['id'] for o in opts]
            if 'absorb' in ids or 'turn' in ids:
                seen = True
            selected = source_answers(p, opts)
            answer.update(selection='USE', option_ids=selected if selected is not None else ids[:1])
        answers.append(answer)
    else:
        raise AssertionError('Too many native attack decisions')
    assert seen, 'Interposition must be offered for this scenario.'
    assert any(k.startswith('interpose.escort.') for k in calls), calls


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_copy(self, update=None):
        clone = _Obj(**self.__dict__)
        clone.__dict__.update(update or {})
        return clone


def test_f2_close_the_bulwark_movement_offers_shield_step_escort(monkeypatch):
    import combat.relations as relations
    import combat.typed_reactions as reactions
    owner = _Obj(entity_id='owner', active=True, turn_flags={}, resources={w.QI: 10},
                 proficiency_bonus=2, display_name='Owner', position=(0, 0))
    ally = _Obj(entity_id='ally', active=True, turn_flags={}, resources={}, proficiency_bonus=2,
                display_name='Ally', position=(0, 0))
    foe = _Obj(entity_id='foe', active=True, turn_flags={}, resources={}, proficiency_bonus=2,
               display_name='Foe', position=(40, 0))
    ward = _Obj(object_id='shield-1', position=(0, 0), component={})
    actors = {'owner': owner, 'ally': ally, 'foe': foe}
    state = NS(actors=actors, round_number=1)
    updated, calls = [], []
    engine = NS(state=state,
                grid=NS(distance_ft=lambda a, b: 5 * max(abs(a[0] - b[0]), abs(a[1] - b[1]))),
                _apply_condition=lambda *a, **k: None,
                _update_object=lambda obj, source, owner_id: updated.append(obj))

    def rel(eng, a, b):
        if a is owner and b is foe:
            return ENEMY
        if a is owner and b is ally:
            return ALLY
        return None

    class _Paid:
        def __init__(self):
            self.damage_cache = {}

    from contextlib import contextmanager

    @contextmanager
    def paid(*a, **k):
        yield _Paid()

    def record(eng, actor, obj, key):
        calls.append(key)

    monkeypatch.setattr(w, 'shields', lambda eng, actor, inactive=False: [ward] if actor is owner else [])
    monkeypatch.setattr(w, 'profile', lambda eng, actor, feature=None: actor is owner)
    monkeypatch.setattr(w, 'active_formation', lambda eng, actor: False)
    monkeypatch.setattr(w, 'locations', lambda eng, actor, pos, feet, near=None: [pos])
    monkeypatch.setattr(w, 'choose', lambda eng, actor, key, options_, **kw: list(options_)[:kw.get('maximum', 1)])
    monkeypatch.setattr(w, 'point_choice', lambda eng, actor, key, cells, optional=False: (1, 0))
    monkeypatch.setattr(w, 'paid_response', paid)
    monkeypatch.setattr(w, 'escort_step', record)
    monkeypatch.setattr(w, 'activation_key', lambda eng, source: 'act-1', raising=False)
    monkeypatch.setattr(relations, 'relation', rel)
    monkeypatch.setattr(reactions, 'can_react', lambda eng, actor: True)
    ctx = NS(engine=engine, typed={'area': 1}, targets=[foe], target=ally, actor=foe,
             source='source.blast', damage_cache={})
    w.close_bulwark(ctx, {'type': 'attack'})
    assert any(o.position == (1, 0) for o in updated), 'The Ward must move under Close the Bulwark.'
    assert calls == ['bulwark.escort.shield-1'], calls
