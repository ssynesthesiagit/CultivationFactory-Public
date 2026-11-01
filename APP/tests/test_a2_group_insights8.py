"""Real table/session executions with sealed fixtures and cold replay."""
import pytest
from combat.ext import insights8 as si
from tests.auto_worker1_support import fight as service_fight
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, reload, resolve, turn


def fight(tmp_path, talents=(), **kwargs):
    right = kwargs.get('right_talents', ())
    def selected(doc, aid):
        owned = talents if aid == LEFT else right if aid == RIGHT else ()
        doc['spheres_and_talents']['cultivation_insight_record_ids'] = [x for x in owned if x.startswith('insight.')]
    return service_fight(tmp_path, talents, sheet_edit=selected, **kwargs)


GRAPPLE = {'type': 'save', 'ability': 'STR', 'dc': 'technique_save_dc', 'on_fail': [
    {'type': 'condition', 'condition': 'grappled', 'applies_to': 'target', 'until_escape': True}], 'on_success': []}
HIT = {'type': 'attack', 'attack_kind': 'unarmed', 'count': 1, 'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['bludgeoning']}]}


def damage(engine, source):
    return [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and (e.source_definition_id == source or e.payload.get('display_source_id') == source)]


def name_source(bundle):
    for a in bundle['action_catalog']:
        if a['display_name'] == 'Prepare':
            a['parameters']['typed']['source'] = 'TAL_WRESTLING_OPENING_STRIKE'
            a['parameters']['typed']['sphere'] = 'tianxia.sphere.wrestling'


def test_grip_failed_check_once_per_turn_and_next_turn_refresh(tmp_path):
    combat, table, mid = fight(tmp_path, [si.GRIP], prepare=[GRAPPLE], cause=[{'type': 'escape_grapple', 'bonus': -100}], cause_target='SELF')
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    turn(table, mid, RIGHT)
    for _ in range(2):
        resolve(lambda a: act(table, mid, 'Cause', a))
    engine = reload(combat, mid)
    assert len(damage(engine, si.GRIP)) == 1
    assert engine.state.actors[RIGHT].current_hp == 996
    checks = [e for e in engine.events if e.event_type == 'CHECK_ROLLED']
    assert len(checks) == 2 and all(e.payload['actor']['mode'] == 'DISADVANTAGE' for e in checks)
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a))
    assert len(damage(reload(combat, mid), si.GRIP)) == 2


def test_grip_successful_escape_no_damage(tmp_path):
    combat, table, mid = fight(tmp_path, [si.GRIP], prepare=[GRAPPLE], cause=[{'type': 'escape_grapple', 'bonus': 100}], cause_target='SELF')
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a))
    assert not damage(reload(combat, mid), si.GRIP)


def test_wrestling_grapple_after_resolves_limit_and_hostile_side(tmp_path):
    combat, table, mid = fight(tmp_path, [si.WRESTLING], prepare=[GRAPPLE], bundle_edit=name_source)
    for _ in range(2):
        resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    engine = reload(combat, mid)
    packets = damage(engine, si.WRESTLING)
    assert len(packets) == 1 and packets[0].target_ids == (RIGHT,)
    assert engine.state.actors[RIGHT].current_hp == 996
    events = engine.events
    assert next(i for i,e in enumerate(events) if e.event_type == 'CONDITION_APPLIED' and e.payload.get('condition_id') == 'condition:typed.grappled') < events.index(packets[0])


@pytest.mark.parametrize('choice', ['damage', 'slow', 'reactions', 'step'])
def test_sword_bone_one_choice_per_hit_turn_and_recipient_expiry(tmp_path, choice):
    combat, table, mid = fight(tmp_path, [si.BONE], prepare=[HIT], prepare_attack_bonus=100)
    before = reload(combat, mid)
    position = before.state.actors[LEFT].position
    _, prompts = resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT), {
        'choice:needle.insights8_bone': [choice], 'choice:needle.insights8_step': ['cell:2,6']})
    if choice == 'step':
        step_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.insights8_step')
        prompt_text = str(step_prompt)
        assert 'Your Prepare hit' in prompt_text
        assert 'Visitor' in prompt_text
        assert 'so you can move' in prompt_text
        assert 'legal destination up to 5 feet away' in prompt_text
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].turn_flags['_round_insights8:' + si.BONE] == si.turn(engine)
    if choice == 'damage':
        assert len(damage(engine, si.BONE)) == 1
        assert damage(engine, si.BONE)[0].payload['damage_type'].upper() == 'SLASHING'
    elif choice == 'slow':
        assert engine._effective_speed(engine.state.actors[RIGHT]) == before._effective_speed(before.state.actors[RIGHT]) - 5
    elif choice == 'reactions':
        from combat.typed_executor import condition_rules
        assert any(r.get('no_reactions') for r in condition_rules(engine.state.actors[RIGHT]))
    else:
        assert engine.grid.distance_ft(position, engine.state.actors[LEFT].position) == 5
        assert engine.state.actors[LEFT].movement_remaining_ft == before.state.actors[LEFT].movement_remaining_ft
    # A second free attack in the same turn cannot offer a second benefit.
    _, prompts = resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.insights8_bone' for p in prompts)
    if choice in ('slow', 'reactions'):
        turn(table, mid, RIGHT)
        engine = reload(combat, mid)
        assert not [c for c in engine.state.actors[RIGHT].conditions.values() if c.source_definition_id == si.BONE]
        assert not [m for m in engine.state.actors[RIGHT].modifiers.values() if m.source_definition_id == si.BONE]


def test_wine_miss_free_step_decline_preserves_use_and_round_limit(tmp_path):
    def miss(bundle):
        for a in bundle['action_catalog']:
            if a['display_name'] == 'Cause':
                a['parameters']['typed']['numbers']['attack_bonus'] = -100
    combat, table, mid = fight(tmp_path, [si.WINE], cause=[HIT], cause_target='HOSTILE_ENTITY', cause_save_dc=100,
                              right_score=1, bundle_edit=miss)
    # Seal a guaranteed miss stimulus, not an injected Insight effect.
    turn(table, mid, RIGHT)
    before = reload(combat, mid)
    _, prompts = resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT), {'choice:needle.insights8_step': []})
    wine_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.insights8_step')
    prompt_text = str(wine_prompt)
    assert 'missed you with Cause, so you can move' in prompt_text
    assert 'once per round' in prompt_text and 'no action or resource' in prompt_text
    engine = reload(combat, mid)
    assert '_round_insights8:' + si.WINE not in engine.state.actors[LEFT].turn_flags
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT), {'choice:needle.insights8_step': ['cell:2,6']})
    engine = reload(combat, mid)
    assert engine.grid.distance_ft(before.state.actors[LEFT].position, engine.state.actors[LEFT].position) == 5
    assert engine.state.actors[LEFT].movement_remaining_ft == before.state.actors[LEFT].movement_remaining_ft
    assert engine.state.actors[LEFT].turn_flags['_round_insights8:' + si.WINE] == str(engine.state.round_number)


def test_tempered_reflexes_failed_dex_reroll_once_and_stomping_boost(tmp_path):
    stomp = 'tianxia.path.body_refining.feature.stomping_step'
    save = {'type': 'save', 'ability': 'DEX', 'dc': 'technique_save_dc', 'on_fail': [], 'on_success': []}
    combat, table, mid = fight(tmp_path, [si.REFLEXES, stomp], cause=[save], left_score=1)
    resolve(lambda a: act(table, mid, 'Stomping Step', a), {'choice:needle.dash_or_disengage': ['disengage']})
    turn(table, mid, RIGHT)
    _, prompts = resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    engine = reload(combat, mid)
    dex = [r for r in engine.rolls if r.actor_id == LEFT and r.reason.startswith('SAVE:')]
    assert any(r.mode == 'ADVANTAGE' for r in dex)
    assert any('Reflexive Reversal' in str(p) for p in prompts)
    _, prompts2 = resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    assert not any('Reflexive Reversal' in str(p) for p in prompts2)
    reload(combat, mid)


def test_two_moons_retains_only_dual_wielding_focus_once_and_decline_preserves(tmp_path):
    def dual(bundle):
        for a in bundle['action_catalog']:
            if a['display_name'] == 'Prepare':
                a['parameters']['typed']['sphere'] = 'tianxia.sphere.dual_wielding'
    cost = {'type': 'spend_resource', 'resource_id': 'resource:core.martial_focus', 'flat': 1, 'applies_to': 'self'}
    combat, table, mid = fight(tmp_path, [si.MOONS], prepare=[cost], prepare_target='SELF', bundle_edit=dual)
    _, prompts = resolve(lambda a: act(table, mid, 'Prepare', a))
    engine = reload(combat, mid)
    assert any('Two-Moons Focus' in str(p) for p in prompts)
    assert engine.state.actors[LEFT].resources['resource:core.martial_focus'] == 1
    resolve(lambda a: act(table, mid, 'Prepare', a))
    assert reload(combat, mid).state.actors[LEFT].resources['resource:core.martial_focus'] == 0


def test_wrestling_does_not_damage_an_allied_grapple_recipient(tmp_path):
    combat, table, mid = fight(tmp_path, [si.WRESTLING], prepare=[GRAPPLE], prepare_target='ANY_CREATURE',
                              bundle_edit=name_source, ally=[])
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=ALLY))
    engine = reload(combat, mid)
    assert any(c.condition_id == 'condition:typed.grappled' for c in engine.state.actors[ALLY].conditions.values())
    assert not damage(engine, si.WRESTLING)
    assert engine.state.actors[ALLY].current_hp == engine.state.actors[ALLY].maximum_hp


def test_wrestling_failed_maneuver_is_inert(tmp_path):
    fail = {**GRAPPLE, 'dc': 1}
    combat, table, mid = fight(tmp_path, [si.WRESTLING], prepare=[fail], bundle_edit=name_source, left_save_dc=1)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert not damage(engine, si.WRESTLING)
    assert not any(c.condition_id == 'condition:typed.grappled' for c in engine.state.actors[RIGHT].conditions.values())


def test_bone_decline_does_not_spend_allowance(tmp_path):
    combat, table, mid = fight(tmp_path, [si.BONE], prepare=[HIT], prepare_attack_bonus=100)
    _, prompts = resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT), {'choice:needle.insights8_bone': []})
    assert any('Sword-Bone Insight' in str(p) for p in prompts)
    engine = reload(combat, mid)
    assert '_round_insights8:' + si.BONE not in engine.state.actors[LEFT].turn_flags
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT), {'choice:needle.insights8_bone': ['damage']})
    assert len(damage(reload(combat, mid), si.BONE)) == 1


def test_iron_fist_slashing_choice_and_declared_attack_replay(tmp_path):
    iron = 'tianxia.path.body_refining.feature.iron_fist'
    combat, table, mid = fight(tmp_path, [si.BONE, iron], spheres=['tianxia.sphere.iron_fist'])
    engine = reload(combat, mid)
    actions = [a for a in engine.action_catalog.values() if a.owner_id == LEFT and (a.parameters.get('typed') or {}).get('source') in {'tianxia.sphere.iron_fist', 'tianxia.path.body_refining.feature.iron_fist'}]
    assert actions
    assert all('SLASHING' in a.parameters['typed']['weapon']['damage_types'] for a in actions)
    # Real declared attack transports the damage-type choice as well as the hit rider.
    _, prompts = resolve(lambda a: act(table, mid, actions[0].display_name, a, target_id=RIGHT),
        {'choice:needle.insights8_bone': [], 'choice:needle.iron_fist_damage_type': ['SLASHING']})
    engine = reload(combat, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.iron_fist_damage_type' for p in prompts)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED']
    assert packets and packets[-1].payload['damage_type'].upper() == 'SLASHING'


def test_iron_fist_opportunity_attack_reaction_uses_owned_sword_bone_palette(tmp_path):
    combat, table, mid = fight(tmp_path, [si.BONE, 'tianxia.path.body_refining.feature.iron_fist'],
                               spheres=['tianxia.sphere.iron_fist'])
    turn(table, mid, RIGHT)
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination
                     and (c.destination.x, c.destination.y) == (5, 6))
    def leave_reach(answers):
        state = table.state(mid)
        return table.act(mid, candidate.candidate_id, state['menu']['decision_id'], state['menu']['state_version'],
                         state['last_sequence'], answers)
    _, prompts = resolve(leave_reach, {
        'reaction:typed.opportunity_attack': [],
        'choice:needle.iron_fist_damage_type': ['SLASHING'],
        'choice:needle.insights8_bone': [],
    })
    assert any(p['context']['reaction_source_id'] == 'choice:needle.iron_fist_damage_type' for p in prompts)
    replay = reload(combat, mid)
    attacks = [e for e in replay.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == LEFT
               and 'opportunity_attack' in e.source_definition_id]
    assert attacks and any(p.target_ids == (RIGHT,) and p.payload['damage_type'].upper() == 'SLASHING'
                           for p in replay.events if p.event_type == 'DAMAGE_COMMITTED')


def test_wine_step_runs_for_native_incoming_attack_miss(tmp_path, monkeypatch):
    from combat import ext
    def native_miss(ctx, effect):
        ctx.engine._resolve_attack_spec(ctx.actor, ctx.target, {
            'attack_bonus': -100, 'damage': None, 'fixed_damage': 1, 'damage_type': 'BLUDGEONING', 'range_ft': None,
            'reach_ft': 5, 'parameters': {'attack_kind': 'weapon'},
        }, ctx.intent, source_definition_id='native:test.incoming_attack', notify=True)
    monkeypatch.setitem(ext._EFFECTS, 'test_insights8_native_attack_miss', native_miss)
    combat, table, mid = fight(tmp_path, [si.WINE], cause=[{'type': 'test_insights8_native_attack_miss'}],
                               cause_target='HOSTILE_ENTITY')
    turn(table, mid, RIGHT)
    before = reload(combat, mid)
    _, prompts = resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT),
                         {'choice:needle.insights8_step': ['cell:2,6']})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.insights8_step' for p in prompts)
    replay = reload(combat, mid)
    assert replay.state.actors[LEFT].position != before.state.actors[LEFT].position
    assert replay.state.actors[LEFT].turn_flags['_round_insights8:' + si.WINE] == str(replay.state.round_number)


def test_two_moons_decline_preserves_use(tmp_path):
    def sources(bundle):
        for a in bundle['action_catalog']:
            if a['display_name'] == 'Prepare':
                a['parameters']['typed']['sphere'] = 'tianxia.sphere.dual_wielding'
    pay = {'type': 'spend_resource', 'resource_id': 'resource:core.martial_focus', 'flat': 1, 'applies_to': 'self'}
    regain = {'type': 'gain_resource', 'resource_id': 'resource:core.martial_focus', 'flat': 1, 'applies_to': 'self'}
    combat, table, mid = fight(tmp_path, [si.MOONS], prepare=[pay], prepare_target='SELF', bundle_edit=sources,
                              extra_actions=[('Recover', {'effects': [regain]})])
    resolve(lambda a: act(table, mid, 'Prepare', a), {'choice:needle.insights8_moons': []})
    assert not reload(combat, mid).state.actors[LEFT].turn_flags.get('_round_insights8_moons_used')
    resolve(lambda a: act(table, mid, 'Recover', a))
    resolve(lambda a: act(table, mid, 'Prepare', a))
    assert reload(combat, mid).state.actors[LEFT].resources['resource:core.martial_focus'] == 1


def test_focus_retention_does_not_refresh_at_the_next_owner_turn(tmp_path):
    def dual(bundle):
        for a in bundle['action_catalog']:
            if a['display_name'] == 'Prepare':
                a['parameters']['typed']['sphere'] = 'tianxia.sphere.dual_wielding'
    pay = {'type': 'spend_resource', 'resource_id': 'resource:core.martial_focus', 'flat': 1, 'applies_to': 'self'}
    combat, table, mid = fight(tmp_path, [si.MOONS], prepare=[pay], prepare_target='SELF', bundle_edit=dual)
    resolve(lambda a: act(table, mid, 'Prepare', a))
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    _, prompts = resolve(lambda a: act(table, mid, 'Prepare', a))
    assert not any('Two-Moons Focus' in str(p) for p in prompts)
    assert reload(combat, mid).state.actors[LEFT].resources['resource:core.martial_focus'] == 0


def test_grip_failed_repeat_save_is_disadvantaged_and_deals_one_packet(tmp_path):
    hold = {**GRAPPLE, 'on_fail': [{**GRAPPLE['on_fail'][0], 'condition_data': {'escape_save': 'STR'}}]}
    def fail(bundle):
        if bundle['actor_id'] == RIGHT:
            bundle['actor_template']['saving_throws']['STR'] = -100
    combat, table, mid = fight(tmp_path, [si.GRIP], prepare=[hold],
        cause=[{'type': 'escape_grapple'}], cause_target='SELF', bundle_edit=fail)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a))
    engine = reload(combat, mid)
    assert len(damage(engine, si.GRIP)) == 1
    assert [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1].payload['mode'] == 'DISADVANTAGE'


def test_tempered_reflexes_boost_and_reroll_on_native_dex_save(monkeypatch, tmp_path):
    from combat import ext
    def native_save(ctx, effect):
        ctx.engine._roll_save(ctx.target, 'DEX', 100, ctx.source)
    # Sealed incoming-save stimulus; the owned Insight's rules are unmodified.
    monkeypatch.setitem(ext._EFFECTS, 'test_insights8_native_save', native_save)
    stomp = 'tianxia.path.body_refining.feature.stomping_step'
    combat, table, mid = fight(tmp_path, [si.REFLEXES, stomp],
        cause=[{'type': 'test_insights8_native_save'}], left_score=1)
    resolve(lambda a: act(table, mid, 'Stomping Step', a), {'choice:needle.dash_or_disengage': ['disengage']})
    turn(table, mid, RIGHT)
    _, first_prompts = resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT),
                               {'choice:needle.insights8_reflexes': ['yes']})
    assert any('Reflexive Reversal' in str(p) for p in first_prompts)
    engine = reload(combat, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED']
    assert saves[-1].payload['mode'] == 'ADVANTAGE'
    assert not any(c.source_definition_id == si.REFLEXES for c in engine.state.actors[LEFT].conditions.values())
    assert any('reroll' in str(e.payload).lower() for e in engine.events if e.event_type == 'D20_REWRITTEN')
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    _, again = resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    assert not any('Reflexive Reversal' in str(p) for p in again)
    reload(combat, mid)


def test_wrestling_bonus_waits_for_the_whole_successful_maneuver(tmp_path):
    maneuver = {**GRAPPLE, 'on_fail': [*GRAPPLE['on_fail'],
        {'type': 'damage', 'flat': 2, 'damage_types': ['bludgeoning']}]}
    combat, table, mid = fight(tmp_path, [si.WRESTLING], prepare=[maneuver], bundle_edit=name_source)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    engine = reload(combat, mid)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED']
    assert len(packets) == 2
    assert packets[-1].payload.get('display_source_id') == si.WRESTLING


def test_unowned_grapple_and_failed_escape_are_inert(tmp_path):
    combat, table, mid = fight(tmp_path, [], prepare=[GRAPPLE], bundle_edit=name_source,
        cause=[{'type': 'escape_grapple', 'bonus': -100}], cause_target='SELF')
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a))
    engine = reload(combat, mid)
    assert not damage(engine, si.WRESTLING) and not damage(engine, si.GRIP)


def test_two_moons_does_not_retain_unrelated_focus_spending(tmp_path):
    pay = {'type': 'spend_resource', 'resource_id': 'resource:core.martial_focus', 'flat': 1, 'applies_to': 'self'}
    combat, table, mid = fight(tmp_path, [si.MOONS], prepare=[pay], prepare_target='SELF')
    _, prompts = resolve(lambda a: act(table, mid, 'Prepare', a))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources['resource:core.martial_focus'] == 0
    assert not any('Two-Moons Focus' in str(p) for p in prompts)


@pytest.mark.parametrize('talent,name', [
    ('TAL_WRESTLING_PIN_2', 'Pin'),
    ('TAL_WRESTLING_HARD_WHIP', 'Apply a Slam: Hard Whip'),
])
def test_wrestling_actual_pin_and_throw_bonus_after_maneuver(tmp_path, talent, name):
    # Prepare only establishes a hold; the actual printed talent performs the maneuver.
    combat, table, mid = fight(tmp_path, [si.WRESTLING, talent],
        spheres=['tianxia.sphere.wrestling'], prepare=[GRAPPLE])
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    before = reload(combat, mid)
    assert not damage(before, si.WRESTLING)
    resolve(lambda a: act(table, mid, name, a, target_id=RIGHT),
            {'choice:needle.hard_whip_direction': ['east']})
    engine = reload(combat, mid)
    packets = damage(engine, si.WRESTLING)
    assert len(packets) == 1 and packets[0].target_ids == (RIGHT,)
    if talent == 'TAL_WRESTLING_PIN_2':
        assert any(c.condition_id == 'condition:typed.restrained' for c in engine.state.actors[RIGHT].conditions.values())
    else:
        moved = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == RIGHT and e.payload.get('forced')]
        assert moved and engine.events.index(moved[-1]) < engine.events.index(packets[0])
        assert engine.state.actors[RIGHT].position.x == before.state.actors[RIGHT].position.x + 2


def test_wrestling_effective_size_is_scoped_and_does_not_change_reach_or_space(tmp_path):
    from combat.ext.effective_size import cells
    combat, table, mid = fight(tmp_path, [si.WRESTLING], prepare=[GRAPPLE], bundle_edit=name_source)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    physical = engine._footprint(actor).width_cells
    for purpose in ('grapple', 'carrying', 'wrestling'):
        assert cells(engine, actor, 'act', {purpose}) == physical + 1
    assert cells(engine, actor, 'act', {'comparison'}) == physical
    assert cells(engine, actor, 'resist', {'grapple'}) == physical
    assert engine._footprint(actor).width_cells == physical == 1


def test_sword_bone_declining_the_destination_preserves_its_turn_use(tmp_path):
    combat, table, mid = fight(tmp_path, [si.BONE], prepare=[HIT], prepare_attack_bonus=100)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT), {
        'choice:needle.insights8_bone': ['step'], 'choice:needle.insights8_step': []})
    assert '_round_insights8:' + si.BONE not in reload(combat, mid).state.actors[LEFT].turn_flags
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT), {'choice:needle.insights8_bone': ['damage']})
    assert len(damage(reload(combat, mid), si.BONE)) == 1


def test_wrestling_normal_grapple_button_qualifies(tmp_path):
    def fail(bundle):
        if bundle['actor_id'] == RIGHT:
            bundle['actor_template']['saving_throws']['STR'] = -100
            bundle['actor_template']['saving_throws']['DEX'] = -100
    combat, table, mid = fight(tmp_path, [si.WRESTLING], bundle_edit=fail)
    resolve(lambda a: act(table, mid, 'Grapple', a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert any(c.condition_id == 'condition:typed.grappled' for c in engine.state.actors[RIGHT].conditions.values())
    assert len(damage(engine, si.WRESTLING)) == 1


@pytest.mark.parametrize('own,cost', [(False, 10), (True, 5)])
def test_wrestling_carrying_small_creature_uses_size_categories(tmp_path, own, cost):
    def small(bundle):
        if bundle['actor_id'] == RIGHT:
            bundle['actor_template']['size_category'] = 'Small'
            bundle['actor_template']['saving_throws']['STR'] = -100
            bundle['actor_template']['saving_throws']['DEX'] = -100
    combat, table, mid = fight(tmp_path, [si.WRESTLING] if own else [], bundle_edit=small)
    resolve(lambda a: act(table, mid, 'Grapple', a, target_id=RIGHT))
    before = reload(combat, mid)
    assert before.state.actors[RIGHT].size_category == 'Small'
    # Both actors occupy one square; the printed categories still differ.
    assert before._footprint(before.state.actors[LEFT]).width_cells == before._footprint(before.state.actors[RIGHT]).width_cells == 1
    def walk(answers):
        state = table.state(mid); menu = state['menu']
        path = [{'x': 3, 'y': 6}, {'x': 2, 'y': 6}]
        quote = table.preview_move_path(mid, menu['decision_id'], menu['state_version'], LEFT, path)
        return table.commit_move_path(mid, quote['candidate']['candidate_id'], menu['decision_id'],
            menu['state_version'], LEFT, path, state['last_sequence'], reactions=answers)
    resolve(walk)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].movement_remaining_ft == before.state.actors[LEFT].movement_remaining_ft - cost
    assert engine.state.actors[LEFT].position.x == 2
    assert engine.state.actors[RIGHT].position.x == 3


@pytest.mark.parametrize('own,target_size,eligible', [
    (False, 'Small', True), (False, 'Medium', False),
    (True, 'Medium', True), (True, 'Large', False),
])
def test_wrestling_tiny_grappler_counts_only_one_category_larger(tmp_path, own, target_size, eligible):
    def sizes(bundle):
        if bundle['actor_id'] == LEFT:
            bundle['actor_template']['size_category'] = 'Tiny'
        else:
            bundle['actor_template']['size_category'] = target_size
            bundle['actor_template']['saving_throws']['STR'] = -100
            bundle['actor_template']['saving_throws']['DEX'] = -100
    combat, table, mid = fight(tmp_path, [si.WRESTLING] if own else [], bundle_edit=sizes)
    resolve(lambda a: act(table, mid, 'Grapple', a, target_id=RIGHT))
    engine = reload(combat, mid)
    held = any(c.condition_id == 'condition:typed.grappled' for c in engine.state.actors[RIGHT].conditions.values())
    assert held is eligible
    assert len(damage(engine, si.WRESTLING)) == int(eligible and own)
    assert engine._footprint(engine.state.actors[LEFT]).width_cells == 1


def test_two_moons_retains_focus_for_owned_defensive_whirl_pair_talent(tmp_path):
    """The passive Pair talent's own feature id is its spend source; no catalog action is published for it."""
    from tests.test_auto110_dual import setup, weapon, spent, whirls
    from tests.worker2_support import fixture, settle, reload as cold_reload, OWNER
    from tests.test_auto_martial import DAGGER_PAIR_KIT
    whirl = 'TAL_DUAL_WIELDING_DEFENSIVE_WHIRL'
    combat, table, mid = fixture(tmp_path, [whirl, si.MOONS], owner_kit=DAGGER_PAIR_KIT, foe_kit=DAGGER_PAIR_KIT,
                                 foe_position={'x': 3, 'y': 5}, bundle_transform=lambda b: setup(b, focus=1))
    settle(table, mid, weapon(combat, mid).candidate_id)
    prompts = settle(table, mid, weapon(combat, mid, '#offhand', base=1).candidate_id,
                     {'choice:needle.dual_pair': 'dw_defensive_whirl', 'choice:needle.insights8_moons': 'retain'})
    moons = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.insights8_moons']
    assert moons, 'Two-Moons Focus was never offered for Defensive Whirl'
    rendered = str(moons[0].get('moment', '')) + str(moons[0].get('summary', ''))
    assert 'Defensive Whirl' in rendered and 'Two-Moons Focus' in rendered, rendered
    engine = cold_reload(tmp_path, mid)
    assert sum(v.payload['amount'] for v in spent(engine)) == 0, 'Focus was spent although Two-Moons retained it'
    assert len(whirls(engine)) == 1, 'the Whirl itself still applies after Focus is retained'
    assert engine.state.actors[OWNER].turn_flags.get('_round_insights8_moons_used') == 'fight'
