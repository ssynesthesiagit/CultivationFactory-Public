"""Printed Insights through service transactions, cold reload, and journal replay."""
import pytest
from combat.ext import insights_defenses as ins
from tests.auto_worker1_support import LEFT, RIGHT, act, fight as service_fight, reload, resolve, turn


def fight(tmp_path, talents, **kwargs):
    def fields(doc, aid):
        f = doc['spheres_and_talents']
        ids = f.get('learned_talent_record_ids', [])
        # The fixture's sheet helper omits central Insights; add them in their
        # real sheet field rather than pretending they are sphere talents.
        f['cultivation_insight_record_ids'] = [mid for mid in (talents if aid == LEFT else kwargs.get('right_talents', [])) if mid.startswith('insight.')]
        f['learned_talent_record_ids'] = [mid for mid in ids if not mid.startswith('insight.')]
    return service_fight(tmp_path, talents, sheet_edit=fields, **kwargs)


def damage(kind='thunder', amount=20):
    return {'type': 'damage', 'flat': amount, 'damage_types': [kind]}


@pytest.mark.parametrize('owned,resistant', [(True, False), (True, True), (False, False)])
def test_bell_bone_once_per_round_after_resistance(tmp_path, owned, resistant):
    resistance = [{'type': 'resistance', 'damage_types': ['thunder'], 'applies_to': 'self', 'duration': {'kind': 'until_removed'}}] if resistant else []
    combat, table, mid = fight(tmp_path, [ins.BELL] if owned else [], prepare=resistance,
                               prepare_target='SELF', cause=[damage()])
    if resistant:
        resolve(lambda a: act(table, mid, 'Prepare', a))
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].current_hp == 1000 - ((10 if resistant else 20) - (4 if owned else 0))
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].current_hp == 1000 - 2 * (10 if resistant else 20) + (4 if owned else 0)


@pytest.mark.parametrize('owned,amount', [(True, 1), (True, 100), (False, 1)])
def test_bell_skin_only_real_guard_zero_damage(tmp_path, owned, amount):
    combat, table, mid = fight(tmp_path, [ins.GUARD] + ([ins.SKIN] if owned else []),
                               left_resource='Stamina', cause=[damage('fire', amount)])
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    reward = owned and amount == 1
    assert bool([c for c in actor.conditions.values() if c.condition_id == ins.AC]) == reward
    spent = sum(e.payload.get('amount', 0) for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.actor_id == LEFT)
    assert actor.resources[ins.STAMINA] == 100 - spent + int(reward)
    if reward:
        assert ins.skin_ac(engine, actor) == 1
        turn(table, mid, LEFT)
        assert ins.skin_ac(reload(combat, mid), reload(combat, mid).state.actors[LEFT]) is None


@pytest.mark.parametrize('name,dc', [('grappled', 1), ('grappled', 100), ('restrained', 1)])
def test_body_like_water_bonus_action_escape(tmp_path, name, dc):
    condition = {'type': 'condition', 'condition': name, 'applies_to': 'target', 'until_escape': True}
    option = {'type': 'escape_option', 'guards': [name], 'kind': 'check', 'abilities': ['STR'], 'name': 'Test hold'}
    combat, table, mid = fight(tmp_path, [ins.WATER], cause=[condition, option], cause_save_dc=dc,
        prepare=[{'type': 'healing', 'flat': 1, 'applies_to': 'self'}], prepare_target='SELF',
        prepare_costs=[(ins.FOCUS, 1)])
    resolve(lambda a: act(table, mid, 'Prepare', a))
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'Body Like Water: escape', a))
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert bool(ins.holds(actor)) == (dc == 100)
    assert actor.resources[ins.FOCUS] == (0 if dc == 100 else 1)
    assert not actor.bonus_action_available and actor.action_available
    assert any(e.event_type == 'CHECK_ROLLED' and e.source_definition_id.endswith('body_like_water') for e in engine.events)


def test_body_like_water_uses_source_restraint_check_and_names_it(tmp_path):
    """The Bonus Action preserves the selected restraint's printed ability and DC through commit/reload/replay."""
    combat, table, mid = fight(tmp_path, [ins.WATER],
        cause=[{'type': 'action_restraint', 'ability': 'DEX', 'applies_to': 'target'}],
        cause_save_dc=100)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    turn(table, mid, LEFT)

    result, prompts = resolve(lambda a: act(table, mid, 'Body Like Water: escape', a))
    assert prompts
    choice = prompts[0].get('choice') or {}
    assert 'Keeper' in prompts[0].get('moment', '')
    labels = [str(option.get('label', '')) for option in choice.get('options', [])]
    assert any('Cause' in label and 'Visitor' in label and 'Dexterity ability check against DC 100' in label for label in labels), labels

    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert ins.holds(actor)
    escape = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.source_definition_id.endswith('body_like_water')]
    assert escape and escape[-1].payload['dc'] == 100 and escape[-1].payload['ability'] == 'DEX'
    assert engine.events[-1].event_type in {'CHECK_ROLLED', 'INTENT_COMMITTED'}


def test_body_like_water_selected_instance_is_the_only_one_removed(tmp_path):
    combat, table, mid = fight(tmp_path, [ins.WATER], cause=[
        {'type': 'condition', 'condition': 'grappled', 'applies_to': 'target', 'until_escape': True},
        {'type': 'action_restraint', 'ability': 'DEX', 'applies_to': 'target'}], cause_save_dc=1)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    turn(table, mid, LEFT)

    answers, prompts = [], []
    for _ in range(12):
        response = act(table, mid, 'Body Like Water: escape', answers)
        if response['status'] != 'REACTION_REQUIRED':
            assert response['status'] == 'COMMITTED', response
            break
        prompt = response['reaction']
        prompts.append(prompt)
        options = (prompt.get('choice') or {}).get('options', [])
        assert len(options) == 2
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': [options[1]['id']]})
    else:
        raise AssertionError('Body Like Water did not finish its prompted choice')
    assert prompts and 'Keeper' in prompts[0].get('moment', '')
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert any(c.condition_id.endswith('.grappled') for c in actor.conditions.values())
    assert not any(c.condition_id.endswith('.restrained') for c in actor.conditions.values())


def test_body_like_water_breaks_pin_before_underlying_grapple_through_reload(tmp_path):
    combat, table, mid = fight(tmp_path, [ins.WATER], cause=[
        {'type': 'condition', 'condition': 'grappled', 'applies_to': 'target', 'until_escape': True},
        {'type': 'condition', 'condition': 'pinned', 'applies_to': 'target', 'until_escape': True}],
        cause_save_dc=1)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    turn(table, mid, LEFT)

    _result, prompts = resolve(lambda answers: act(table, mid, 'Body Like Water: escape', answers))
    options = (prompts[0].get('choice') or {}).get('options', [])
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert not any(c.condition_id.endswith('.pinned') for c in actor.conditions.values())
    assert any(c.condition_id.endswith('.grappled') for c in actor.conditions.values())
    assert len(options) == 1 and 'pinned' in options[0]['label'].lower(), options
    assert any(e.event_type == 'CHECK_ROLLED' and e.source_definition_id.endswith('body_like_water')
               for e in engine.events)
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    _result, prompts = resolve(lambda answers: act(table, mid, 'Body Like Water: escape', answers))
    options = prompts[0]['choice']['options']
    assert not ins.holds(reload(combat, mid).state.actors[LEFT])
    assert len(options) == 1 and 'grappled' in options[0]['label'].lower(), options


def test_body_like_water_recorded_hold_label_uses_bonus_action_cost(tmp_path):
    combat, table, mid = fight(tmp_path, [ins.WATER], cause=[
        {'type': 'condition', 'condition': 'grappled', 'applies_to': 'target', 'until_escape': True},
        {'type': 'escape_option', 'guards': ['grappled'], 'kind': 'check', 'abilities': ['STR'],
         'name': 'Recorded hold', 'help': True, 'end_of_turn': True}], cause_save_dc=100)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    turn(table, mid, LEFT)
    _result, prompts = resolve(lambda answers: act(table, mid, 'Body Like Water: escape', answers))
    engine = reload(combat, mid)
    assert ins.holds(engine.state.actors[LEFT])  # DC 100 keeps it held; the intent committed through the service.
    labels = [o.get('label', '') for o in prompts[0]['choice']['options']]
    assert any('use a Bonus Action' in label and 'use an Action' not in label
               and 'free try' not in label and 'ally' not in label for label in labels), labels


def test_body_like_water_repeats_a_hold_save_and_records_save_provenance(monkeypatch, tmp_path):
    from combat import ext
    def save_advantage(engine, escaper, grips):
        return 'ADVANTAGE' if grips else None
    monkeypatch.setitem(ext._HOOKS, 'escape_save_mode',
                        [*ext._HOOKS.get('escape_save_mode', []), save_advantage])
    combat, table, mid = fight(tmp_path, [ins.WATER],
        cause=[{'type': 'condition', 'condition': 'grappled', 'escape_save': 'STR',
                'applies_to': 'target', 'until_escape': True}], cause_save_dc=1)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'Body Like Water: escape', a))
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert not ins.holds(actor)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.source_definition_id.endswith('body_like_water')]
    assert saves and saves[-1].payload['reason'].endswith(':STR') and saves[-1].payload['success']
    roll = next(r for r in reversed(engine.rolls) if str(r.reason).startswith('SAVE:') and r.actor_id == LEFT)
    assert roll.mode == 'ADVANTAGE'
    assert any(e.event_type == 'CONDITION_REMOVED' and e.payload.get('instance_id') for e in engine.events)


def test_body_like_water_recorded_save_hold_uses_escape_save_modifier(monkeypatch, tmp_path):
    from combat import ext
    def save_advantage(engine, escaper, grips):
        return 'ADVANTAGE' if any(c.condition_id.endswith('.grappled') for c in grips) else None
    monkeypatch.setitem(ext._HOOKS, 'escape_save_mode',
                        [*ext._HOOKS.get('escape_save_mode', []), save_advantage])
    combat, table, mid = fight(tmp_path, [ins.WATER], cause=[
        {'type': 'condition', 'condition': 'grappled', 'applies_to': 'target', 'until_escape': True},
        {'type': 'escape_option', 'guards': ['grappled'], 'kind': 'save',
         'abilities': ['STR'], 'name': 'Recorded save hold', 'end_of_turn': True}],
        cause_save_dc=1)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'Body Like Water: escape', a))
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    assert not ins.holds(actor)
    roll = next(r for r in reversed(engine.rolls)
                if str(r.reason).startswith('SAVE:') and r.actor_id == LEFT)
    assert roll.mode == 'ADVANTAGE'


@pytest.mark.parametrize('feature,condition', [
    ('insight.alchemical-constitution', 'poisoned'),
    ('insight.body-of-thorns-and-spores', 'poisoned'),
    ('insight.bone-tempering-insight', 'prone'),
    ('insight.anchored-soul', 'banishment'),
])
def test_defensive_insight_save_scope(tmp_path, feature, condition):
    cause = [{'type': 'save', 'ability': 'CON', 'save_categories': [condition], 'on_fail': [{'type': 'condition', 'condition': 'poisoned' if condition == 'banishment' else condition}]}]
    combat, table, mid = fight(tmp_path, [feature], cause=cause)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    engine = reload(combat, mid)
    rolls = [r for r in engine.rolls if str(r.reason).startswith('SAVE:') and r.actor_id == LEFT]
    assert rolls and rolls[-1].mode == 'ADVANTAGE'


@pytest.mark.parametrize('feature,category', [
    ('insight.alchemical-constitution', 'alchemical_backlash'),
    ('insight.body-of-thorns-and-spores', 'disease'),
    ('insight.bone-tempering-insight', 'physical_paralysis'),
    ('insight.anchored-soul', 'forced_planar_travel'),
])
def test_explicit_printed_hazard_category_and_unrelated_control(tmp_path, feature, category):
    cause = [{'type': 'save', 'ability': 'CON', 'save_categories': [category],
              'on_fail': [{'type': 'condition', 'condition': 'frightened'}]}]
    combat, table, mid = fight(tmp_path, [feature], cause=cause)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    engine = reload(combat, mid)
    assert [r for r in engine.rolls if str(r.reason).startswith('SAVE:') and r.actor_id == LEFT][-1].mode == 'ADVANTAGE'
    other = tmp_path / 'unrelated'
    combat, table, mid = fight(other, [feature], cause=[{'type': 'save', 'ability': 'CON',
        'on_fail': [{'type': 'condition', 'condition': 'frightened'}]}])
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    engine = reload(combat, mid)
    assert [r for r in engine.rolls if str(r.reason).startswith('SAVE:') and r.actor_id == LEFT][-1].mode == 'NORMAL'


@pytest.mark.parametrize('owned', [True, False])
def test_native_repeat_poison_save_reads_same_sealed_scope(tmp_path, owned):
    cause = [{'type': 'condition', 'condition': 'poisoned', 'duration': {'kind': 'until_removed'},
              'repeat_save': {'ability': 'CON', 'when': 'end'}}]
    combat, table, mid = fight(tmp_path, ['insight.alchemical-constitution'] if owned else [], cause=cause)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'end', a))
    engine = reload(combat, mid)
    rolls = [r for r in engine.rolls if str(r.reason).startswith('SAVE:') and r.actor_id == LEFT]
    assert rolls and rolls[-1].mode == ('ADVANTAGE' if owned else 'NORMAL')


def test_water_action_is_hidden_without_hold_or_ownership(tmp_path):
    for label, ids in [('owned', [ins.WATER]), ('unowned', [])]:
        combat, table, mid = fight(tmp_path / label, ids)
        assert not any('Body Like Water: escape' in c.display_name for c in reload(combat, mid).legal_candidates())
