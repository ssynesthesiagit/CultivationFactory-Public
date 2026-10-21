"""Regression tests for the Sol review findings on the Heaven-Thunder Storm Soul branch.

Each test targets one fixed branch; the report records which of them were run against the pre-fix code and failed.
"""
from types import SimpleNamespace

import pytest

from combat.ext import mgr_reserve_heaven_thunder_storm_soul_tribulation_scarred_meridians as storm
from combat.ext import passive_rows, ability_source

QI = 'resource:core.qi'
STAMINA = 'resource:core.stamina'


def cond(condition_id, **data):
    return SimpleNamespace(condition_id=condition_id, data=data, source_actor_id='X', source_definition_id='X')


def actor(eid='T', resources=None, conditions=(), **extra):
    return SimpleNamespace(entity_id=eid, display_name=eid, resources=dict(resources or {}),
        conditions={i: c for i, c in enumerate(conditions)}, active=True, position=(0, 0), **extra)


# P1: a named Sentence suppression blocks only the Path pools the chosen systems spend.
def test_named_suppression_blocks_only_spent_pools(monkeypatch):
    target = actor(resources={QI: 5, STAMINA: 3})
    engine = SimpleNamespace(action_catalog={
        'SRC_QI': SimpleNamespace(costs=((QI, 2),)),
        'SRC_OTHER': SimpleNamespace(costs=((STAMINA, 1),)),
    })
    ctx = SimpleNamespace(engine=engine)
    assert storm.named_pools(ctx, target, {'SRC_QI'}) == {QI}
    assert STAMINA not in storm.named_pools(ctx, target, {'SRC_QI'})


# P2: Living Heavenly Tribulation exposes a three-Seal creature to the owner's Cultivation Check.
def fake_living_world(monkeypatch, seals, foe_cl, check_result):
    monkeypatch.setattr(storm, 'owned_row', lambda e, a: True)
    monkeypatch.setattr(storm, 'living', lambda e, a: object())
    monkeypatch.setattr(storm, 'seal_count', lambda e, o, t: seals)
    monkeypatch.setattr(storm, 'numbers', lambda e, a: {'cl': 10, 'save_dc': 14})
    monkeypatch.setattr(passive_rows, 'known_level', lambda e, c: foe_cl)
    monkeypatch.setattr(ability_source, 'cultivation_check', lambda *a, **k: check_result)


def test_living_three_seals_expose_unless_concealment_succeeds(monkeypatch):
    viewer, target = actor('V'), actor('F')
    fake_living_world(monkeypatch, seals=3, foe_cl=14, check_result=False)
    assert storm.living_exposes(SimpleNamespace(), viewer, target) is True
    fake_living_world(monkeypatch, seals=3, foe_cl=14, check_result=True)
    assert storm.living_exposes(SimpleNamespace(), viewer, target) is False


def test_living_two_seals_do_not_expose(monkeypatch):
    fake_living_world(monkeypatch, seals=2, foe_cl=14, check_result=False)
    assert storm.living_exposes(SimpleNamespace(), actor('V'), actor('F')) is False


# P1b: Sentence removes Seals only once its saving throw has actually resolved.
def sentence_world(monkeypatch, save_result):
    spent, suppressed = [], []
    monkeypatch.setattr(storm, 'replace', lambda obj, **kw: SimpleNamespace(**{**vars(obj), **kw}))
    monkeypatch.setattr(storm, 'seal_count', lambda e, o, t: 5)
    monkeypatch.setattr(storm, 'source_gap', lambda ctx, t: 0)
    monkeypatch.setattr(storm, 'choose', lambda ctx, key, labels, prompt, **k: ['3'])
    monkeypatch.setattr(storm, 'saving_throw', lambda ctx, t, ability, **k: save_result)
    monkeypatch.setattr(storm, 'suppress_named', lambda ctx, t, duration, **k: suppressed.append(duration))
    import combat.ext.stacking_marks as marks
    monkeypatch.setattr(marks, 'spend', lambda e, o, t, name, source, number=1: spent.append(number) or True)
    ctx = SimpleNamespace(engine=None, actor=actor('ME'), target=actor('F'), source='SRC', typed={}, action=None)
    storm.sentence(ctx)
    return spent, suppressed


def test_sentence_without_resolved_save_spends_no_seals(monkeypatch):
    spent, suppressed = sentence_world(monkeypatch, save_result=None)
    assert spent == []
    assert suppressed == []


def test_sentence_with_resolved_save_spends_then_suppresses(monkeypatch):
    spent, suppressed = sentence_world(monkeypatch, save_result=False)
    assert spent == [3]
    assert suppressed == ['until_start_of_next_turn']


# P3: Sentence's shorter cap does not apply once defenses are specifically broken.
def test_broken_defenses_detected_from_engine_states():
    assert storm.defenses_broken(actor(conditions=[cond('condition:typed.shield_broken')])) is True
    assert storm.defenses_broken(actor(conditions=[cond('condition:typed.guard_broken')])) is True
    assert storm.defenses_broken(actor()) is False


# P4: hostility declarations carry a round expiry from their real remaining clock time.
def test_meaningful_declaration_expires_with_its_clock(monkeypatch):
    monkeypatch.setattr(storm, 'owned_row', lambda e, a: True)
    applied = []

    class Engine:
        state = SimpleNamespace(round_number=1, actors={})
        typed_bundle_documents = [{'actor_id': 'T', 'journey_setup': {'heaven_thunder': {
            'sparks': 0, 'living_used': 0, 'declarations': [{
                'value': {'source_actor_id': 'F', 'source_id': 'SRC'}, 'receipt_id': 'r1',
                'expires_at': 100, 'remaining_seconds': 12}]}}}]

        def _apply_condition(self, owner, condition_id, source, owner_id, *, expires_on, data):
            applied.append(cond(condition_id, **data))

    engine = Engine()
    owner = actor('T', resources={}, conditions=())
    owner.resource_maximums = {storm.SPARK: 3}
    owner.turn_flags = {}
    engine.state.actors = {'T': owner}
    storm.encounter_setup(engine)
    owner.conditions = {i: c for i, c in enumerate(applied)}
    source = SimpleNamespace(entity_id='F')
    assert storm.meaningful_source(engine, owner, source, 'SRC') is True
    engine.state.round_number = 3
    assert storm.meaningful_source(engine, owner, source, 'SRC') is True
    engine.state.round_number = 4
    assert storm.meaningful_source(engine, owner, source, 'SRC') is False


# P5: Ninefold Flash keeps every creature in reach selectable for an AI seat.
def test_flash_target_menu_is_not_narrowed_for_ai(monkeypatch):
    calls = []
    monkeypatch.setattr(storm, 'hostile', lambda e, a, t: False)
    monkeypatch.setattr(storm, 'pick_cell', lambda ctx, feet, key, **k: (1, 1))
    import combat.ext.rider_support as rs
    import combat.senses as senses
    monkeypatch.setattr(rs, 'teleport', lambda ctx, a, cell: True)
    monkeypatch.setattr(senses, 'perceives', lambda e, a, t: t.entity_id != 'HIDDEN')

    def fake_choose(ctx, key, options, prompt, **kwargs):
        if key == 'flash_cost':
            return ['1']
        calls.append((list(options), kwargs.get('automatic_options')))
        return []

    monkeypatch.setattr(storm, 'choose', fake_choose)
    me = actor('ME', resources={storm.SPARK: 1})
    hidden = actor('HIDDEN')
    engine = SimpleNamespace(state=SimpleNamespace(actors={'ME': me, 'HIDDEN': hidden}),
        grid=SimpleNamespace(distance_ft=lambda a, b: 5),
        _spend_resource=lambda *a, **k: None)
    storm.flash(SimpleNamespace(engine=engine, actor=me, source='SRC', numbers={}))
    options, automatic = calls[0]
    # The full reach menu stays offered; an automatic AI seat may pick only creatures it perceives.
    assert sorted(options) == ['HIDDEN', 'ME']
    assert automatic == ['ME']


# P4b: Tribulation Rebirth spends its once-per-scene use only when the lethal hit commits.
def rebirth_world(monkeypatch):
    import combat.typed_executor as te
    import combat.damage_allocation as da
    import combat.ext.retained_updates as ru
    held = SimpleNamespace(data={}, instance_id='I', condition_id='c', source_definition_id='SRC', source_actor_id='FOE')
    discharged, updates = [], []
    monkeypatch.setattr(storm, 'living', lambda e, a: held)
    monkeypatch.setattr(te, 'condition_rules', lambda a: [])
    monkeypatch.setattr(da, 'available_temporary_hp', lambda *a, **k: 0)
    monkeypatch.setattr(ru, 'record_instance_update', lambda e, h, kind, key, item: updates.append(key))
    monkeypatch.setattr(storm, 'discharge', lambda e, t: discharged.append(t.entity_id))
    target = actor('T')
    target.current_hp, target.maximum_hp = 5, 20
    engine = SimpleNamespace(state=SimpleNamespace(actors={'T': target}), events=[])
    return engine, target, held, discharged, updates


def test_rebirth_hook_alone_spends_nothing(monkeypatch):
    engine, target, held, discharged, updates = rebirth_world(monkeypatch)
    floor = storm.tribulation_rebirth(engine, target, 8, 'LIGHTNING', 'SRC', 'FOE', None)
    assert floor == 1
    assert held.data.get('rebirth_used') is None
    assert discharged == [] and updates == []


def test_rebirth_spends_only_on_committed_damage(monkeypatch):
    engine, target, held, discharged, updates = rebirth_world(monkeypatch)
    storm.tribulation_rebirth(engine, target, 8, 'LIGHTNING', 'SRC', 'FOE', None)
    original = SimpleNamespace(source_definition_id='SRC')
    storm.rebirth_discharge(engine, 'DAMAGE_COMMITTED', {'originating_event': original, 'target_ids': ('T',)})
    assert held.data.get('rebirth_used') == 1
    assert discharged == ['T'] and updates == ['I']


def test_rebirth_ignores_commit_from_another_source(monkeypatch):
    engine, target, held, discharged, updates = rebirth_world(monkeypatch)
    storm.tribulation_rebirth(engine, target, 8, 'LIGHTNING', 'SRC', 'FOE', None)
    storm.rebirth_discharge(engine, 'DAMAGE_COMMITTED',
        {'originating_event': SimpleNamespace(source_definition_id='OTHER'), 'target_ids': ('T',)})
    assert held.data.get('rebirth_used') is None
    assert discharged == []


# P6: Heaven-Punishing Reprisal names the action that triggered it.
def test_reprisal_prompt_names_triggering_action(monkeypatch):
    import combat.typed_reactions as tr
    prompts = []
    monkeypatch.setattr(storm, 'owned_row', lambda e, a, feature=None: True)
    monkeypatch.setattr(storm, 'numbers', lambda e, a: {'cl': 10})
    monkeypatch.setattr(storm, 'living', lambda e, o: None)
    monkeypatch.setattr(tr, 'can_react', lambda e, o: True)
    monkeypatch.setattr(tr, 'open_reaction', lambda *a, **k: None, raising=False)
    monkeypatch.setattr(storm, 'context', lambda *a, **k: SimpleNamespace())
    monkeypatch.setattr(storm, 'choose', lambda ctx, key, labels, prompt, **k: prompts.append(prompt) or [])
    engine = SimpleNamespace(grid=SimpleNamespace(distance_ft=lambda a, b: 5),
        state=SimpleNamespace(round_number=1),
        effective_costs=lambda owner, src, costs: costs,
        action_catalog={'SRC': SimpleNamespace(display_name='Fire Ball')})
    owner = actor('OWN', resources={QI: 5}, turn_flags={})
    src = actor('FOE')
    storm.reprisal(engine, owner, src, 'damaged you', action_name=storm.action_label(engine, 'SRC'))
    assert prompts and 'with Fire Ball' in prompts[0]
