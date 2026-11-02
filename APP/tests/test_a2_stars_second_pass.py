"""Stars second pass through service commits, transactional choices and cold reload."""
import pytest

from combat.ext import stars
from tests.test_a2_stars_insights import fight, bonus_rolls
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, reload, resolve, action_sender, cell_send

MANTLE = 'tianxia.talent.stars.cold_star_mantle'
HIT = {'type': 'attack', 'attack_kind': 'melee', 'on_hit': []}


def weapon(bundle):
    for action in bundle['action_catalog']:
        if action['display_name'] == 'Prepare':
            action['parameters']['typed']['weapon'] = {
                'damage': {'count': 1, 'sides': 8, 'modifier': 3}, 'damage_type': 'COLD'}


def native_weapon(bundle):
    for action in bundle['action_catalog']:
        if action['display_name'] == 'Prepare':
            action.update(resolution_kind='ATTACK', parameters={'attack_kind': 'weapon'},
                attack_bonus=100, damage={'count': 1, 'sides': 8, 'modifier': 3}, damage_type='COLD')


@pytest.mark.parametrize('auto,decline', [(False, False), (False, True), (True, False)])
@pytest.mark.parametrize('native', [False, True])
def test_mantle_weapon_bonus_confirmed_choice_and_shared_allowance(tmp_path, auto, decline, native):
    combat, table, mid = fight(tmp_path, [MANTLE], prepare=[HIT],
        bundle_edit=native_weapon if native else weapon, prepare_attack_bonus=100)
    resolve(lambda a: act(table, mid, 'Cold Star Mantle', a))
    picks = {'choice:needle.stars_cold_mantle': []} if decline else None
    _, prompts = resolve(action_sender(combat, table, mid, 'Prepare', ai=auto, target_id=RIGHT), picks)
    engine = reload(combat, mid)
    assert bonus_rolls(engine)[-1].modifier == (3 if decline else 7)
    assert (stars.MANTLE_TURN in engine.state.actors[LEFT].turn_flags) == (not decline)
    assert bool([p for p in prompts if p['context']['reaction_source_id'] ==
                 'choice:needle.stars_cold_mantle']) == (not auto)
    if auto:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    assert bonus_rolls(reload(combat, mid))[-1].modifier == (7 if decline else 3)
    assert not any(e.event_type == 'GM_RIDER' and 'weapon bonus' in str(e.payload)
                   for e in engine.events)
    assert not any(e.event_type == 'GM_RIDER' and e.source_definition_id.endswith('cold_star_mantle')
                   for e in engine.events)


def test_mantle_weapon_and_standalone_damage_share_clock_and_reset(tmp_path):
    damage = {'type': 'damage', 'dice': {'count': 1, 'sides': 6}, 'damage_types': ['force']}
    combat, table, mid = fight(tmp_path, [MANTLE], prepare=[HIT], bundle_edit=weapon,
        prepare_attack_bonus=100, extra_actions=[('Starlight', {'target_kind': 'HOSTILE_ENTITY',
                                                               'effects': [damage]})])
    resolve(lambda a: act(table, mid, 'Cold Star Mantle', a))
    resolve(lambda a: act(table, mid, 'Starlight', a, target_id=RIGHT))
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    assert [r.modifier for r in bonus_rolls(reload(combat, mid))] == [4, 3]
    from tests.auto_worker1_support import turn
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    assert bonus_rolls(reload(combat, mid))[-1].modifier == 7


def test_mantle_pure_physical_weapon_does_not_qualify(tmp_path):
    def physical(bundle):
        weapon(bundle)
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Prepare':
                action['parameters']['typed']['weapon']['damage_type'] = 'SLASHING'
    combat, table, mid = fight(tmp_path, [MANTLE], prepare=[HIT], bundle_edit=physical,
                              prepare_attack_bonus=100)
    resolve(lambda a: act(table, mid, 'Cold Star Mantle', a))
    _, prompts = resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert bonus_rolls(engine)[-1].modifier == 3
    assert stars.MANTLE_TURN not in engine.state.actors[LEFT].turn_flags
    assert not prompts


@pytest.mark.parametrize('decline', [False, True])
def test_mantle_physical_packet_and_later_cold_riders_keep_separate_choices(tmp_path, decline):
    def physical(bundle):
        weapon(bundle)
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Prepare':
                action['parameters']['typed']['weapon']['damage_type'] = 'SLASHING'
    # The first row delivers the weapon packet; both later rows really roll
    # Cold damage. They must not retroactively qualify the Slashing packet.
    cold = {'type': 'damage', 'dice': {'count': 1, 'sides': 6}, 'damage_types': ['cold']}
    hit = {**HIT, 'on_hit': [
        {'type': 'damage', 'weapon_damage': True, 'damage_types': ['slashing']}, cold, cold]}
    combat, table, mid = fight(tmp_path, [MANTLE], prepare=[hit], bundle_edit=physical,
                              prepare_attack_bonus=100)
    resolve(lambda a: act(table, mid, 'Cold Star Mantle', a))
    before = reload(combat, mid).state.model_dump(mode='json')
    choices = []
    def pick(prompt):
        assert reload(combat, mid).state.model_dump(mode='json') == before
        assert prompt['context']['reactor_id'] == LEFT
        choices.append(prompt)
        # Decline the first Cold roll, then accept the second. Declining does
        # not spend the shared allowance; acceptance spends it exactly once.
        return [] if decline and len(choices) == 1 else ['add_bonus']
    from tests.auto_worker1_support import settle
    settle(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT), choose=pick)
    engine = reload(combat, mid)
    assert [r.modifier for r in bonus_rolls(engine)] == ([3, 0, 4] if decline else [3, 4, 0])
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED']
    assert [e.payload['damage_type'] for e in packets] == ['SLASHING', 'COLD', 'COLD']
    assert len(choices) == (2 if decline else 1)
    assert engine.state.actors[LEFT].turn_flags[stars.MANTLE_TURN] == stars._turn(engine)
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    assert [r.modifier for r in bonus_rolls(reload(combat, mid))][-3:] == [3, 0, 0]


@pytest.mark.parametrize('auto,decline', [(False, False), (False, True), (True, False)])
def test_mantle_reaction_beneficiary_owns_choice_during_ai_turn(tmp_path, auto, decline):
    from combat.gate4_adapters import ManualControllerAdapter
    from tests.auto_worker1_support import turn

    def cold_weapon(bundle):
        if bundle['actor_id'] == LEFT:
            # Seal a deterministic Cold melee profile, including its compiled
            # Opportunity Attack copy, before creating the service match.
            for action in bundle['action_catalog']:
                typed = action.get('parameters', {}).get('typed', {})
                if typed.get('weapon') and not typed.get('range_ft'):
                    typed['weapon'].update(damage={'count': 1, 'sides': 8, 'modifier': 3},
                                           damage_type='COLD', damage_types=['COLD'])
                    typed.setdefault('numbers', {})['attack_bonus'] = 100
    combat, table, mid = fight(tmp_path, [MANTLE], bundle_edit=cold_weapon)
    resolve(lambda a: act(table, mid, 'Cold Star Mantle', a))
    turn(table, mid, RIGHT)
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='LOCAL_AUTO')
    if auto:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            # A visible adjacent opponent is left behind by this legal move.
            move = next(c for c in context.legal_candidates if c.destination is not None
                        and (c.destination.x, c.destination.y) == (6, 6))
            return ManualControllerAdapter(lambda _: (move.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    before = reload(combat, mid).state.model_dump(mode='json')
    prompts = []
    def pick(prompt):
        assert reload(combat, mid).state.model_dump(mode='json') == before
        assert table.state(mid)['menu']['actor_id'] == RIGHT
        assert prompt['context']['reactor_id'] == LEFT
        prompts.append(prompt)
        if prompt['context']['reaction_source_id'] == 'choice:needle.stars_cold_mantle':
            text = str(prompt)
            assert 'Opportunity Attack' in text and 'Keeper' in text and 'Visitor' in text
            assert 'once-per-turn' in text and 'no action or resource cost' in text
            return [] if decline else ['add_bonus']
        return []  # ordinary reaction prompts have no option selection
    answers = []
    for _ in range(12):
        result = table.auto_step(mid, table.state(mid)['last_sequence'], answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            break
        prompt = result['reaction']
        selected = pick(prompt)
        answers.append({**prompt['context'], 'option_ids': selected,
                        'selection': 'USE' if selected or not prompt.get('choice') else 'DECLINE'})
    else:
        raise AssertionError('too many reaction questions')
    engine = reload(combat, mid)
    assert engine.state.current_actor_id == RIGHT
    assert bonus_rolls(engine)[-1].modifier == (3 if decline else 7)
    assert (stars.MANTLE_TURN in engine.state.actors[LEFT].turn_flags) == (not decline)
    if not decline:
        assert engine.state.actors[LEFT].turn_flags[stars.MANTLE_TURN] == stars._turn(engine)
    assert stars.MANTLE_TURN not in engine.state.actors[RIGHT].turn_flags
    assert not engine.state.actors[LEFT].reaction_available
    assert any(e.event_type == 'REACTION_RESOLVED' and e.actor_id == LEFT
               and e.source_definition_id == 'system:combat.opportunity_attack' for e in engine.events)
    mantle_prompts = [p for p in prompts if p['context']['reaction_source_id'] ==
                     'choice:needle.stars_cold_mantle']
    assert len(mantle_prompts) == (0 if auto else 1)


def test_mantle_mixed_damage_roll_uses_chosen_type(tmp_path):
    damage = {'type': 'damage', 'dice': {'count': 1, 'sides': 6}, 'damage_types': ['cold', 'fire']}
    def immune(bundle):
        if bundle['actor_id'] == RIGHT:
            bundle['typed_passives'].append({'block': 'defense', 'kind': 'immunity',
                'feature_id': 'test:sealed-cold-immunity', 'damage_types': ['COLD']})
    combat, table, mid = fight(tmp_path, [MANTLE], prepare=[damage], bundle_edit=immune)
    resolve(lambda a: act(table, mid, 'Cold Star Mantle', a))
    _, prompts = resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert bonus_rolls(engine)[-1].modifier == 0
    assert stars.MANTLE_TURN not in engine.state.actors[LEFT].turn_flags
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert not prompts


@pytest.mark.parametrize('auto,decline', [(False, False), (False, True), (True, False)])
def test_mantle_independent_reaction_attack_names_actual_reaction(tmp_path, auto, decline):
    from tests.auto_worker1_support import turn, settle
    source = 'reaction:test.counter_sweep'
    def counter(bundle):
        if bundle['actor_id'] == ALLY:
            bundle['actor_template']['display_name'] = 'Second foe'
        if bundle['actor_id'] != LEFT:
            return
        # A normal generic reaction first strikes physically, then its Cleave
        # child uses the Cold weapon. Cleave calls the native resolver outside
        # attack_scope.resolving: this exercises Mantle's no-frame fallback.
        for action in bundle['action_catalog']:
            typed = action.get('parameters', {}).get('typed', {})
            if typed.get('weapon') and not typed.get('range_ft'):
                typed['weapon'].update(damage={'count': 1, 'sides': 8, 'modifier': 3},
                                       damage_type='COLD', damage_types=['COLD'])
                typed.setdefault('numbers', {})['attack_bonus'] = 100
        bundle['typed_reactions'] = [{'feature_id': source, 'name': 'Counter Sweep',
            'block': 'generic', 'kind': 'attacked', 'ask': True, 'requires_sight': True,
            'range_ft': 5, 'costs': [], 'numbers': {'attack_bonus': 100},
            'effects': [{'type': 'attack', 'attack_kind': 'melee weapon', 'strike_with': 'weapon',
                         'on_hit': [{'type': 'damage', 'dice': {'count': 1, 'sides': 4},
                                     'damage_types': ['slashing']}]}, {'type': 'cleave'}]}]
    combat, table, mid = fight(tmp_path, [MANTLE], cause=[HIT], ally=[], ally_team='team:opponents',
                              bundle_edit=counter)
    resolve(lambda a: act(table, mid, 'Cold Star Mantle', a))
    turn(table, mid, RIGHT)
    if auto:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    send = action_sender(combat, table, mid, 'Cause', ai=True, target_id=LEFT)
    before = reload(combat, mid).state.model_dump(mode='json')
    mantle_prompts = []
    def pick(prompt):
        assert reload(combat, mid).state.model_dump(mode='json') == before
        assert prompt['context']['reactor_id'] == LEFT
        if prompt['context']['reaction_source_id'] == 'choice:needle.stars_cold_mantle':
            mantle_prompts.append(prompt)
            assert 'Counter Sweep' in str(prompt) and 'Second foe' in str(prompt)
            assert prompt['action'] == 'Counter Sweep'
            assert prompt['affected'] == 'Second foe'
            assert "Keeper's Counter Sweep damages Second foe" in prompt['moment']
            return [] if decline else ['add_bonus']
        return [o['id'] for o in (prompt.get('choice') or {}).get('options', [])][:1]
    # Generic Reaction consent has no option list, so answer it explicitly
    # before settling the nested optional target and damage choices.
    first = send([])
    answers = []
    if first['status'] == 'REACTION_REQUIRED':
        prompt = first['reaction']
        assert prompt['context']['reaction_source_id'] == 'reaction:typed.' + source
        pick(prompt)
        answers = [{**prompt['context'], 'selection': 'USE', 'option_ids': []}]
        settle(lambda a: send(answers + a), choose=pick)
    else:
        assert auto and first['status'] == 'COMMITTED', first
    engine = reload(combat, mid)
    followup = next(r for r in bonus_rolls(engine) if ':99' in r.reason)
    assert followup.modifier == (3 if decline else 7)
    assert (stars.MANTLE_TURN in engine.state.actors[LEFT].turn_flags) == (not decline)
    assert stars.MANTLE_TURN not in engine.state.actors[RIGHT].turn_flags
    assert not engine.state.actors[LEFT].reaction_available
    assert len(mantle_prompts) == (0 if auto else 1)


@pytest.mark.parametrize('native', [False, True])
def test_mantle_weapon_miss_does_not_spend_or_prompt(tmp_path, native):
    def missed(bundle):
        native_weapon(bundle)
        for action in bundle['action_catalog']:
            if action['display_name'] == 'Prepare':
                action['attack_bonus'] = -1000
    combat, table, mid = fight(tmp_path, [MANTLE], prepare=[HIT],
        bundle_edit=missed if native else weapon, prepare_attack_bonus=-1000)
    resolve(lambda a: act(table, mid, 'Cold Star Mantle', a))
    _, prompts = resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert stars.MANTLE_TURN not in engine.state.actors[LEFT].turn_flags
    assert not bonus_rolls(engine)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.stars_cold_mantle'
                   for p in prompts)


@pytest.mark.parametrize('category,expected', [('magical_misdirection', 'ADVANTAGE'),
                                               ('poison', 'NORMAL')])
def test_mantle_scoped_saving_throw(tmp_path, category, expected):
    save = {'type': 'save', 'ability': 'wis', 'save_categories': [category],
            'applies_to': 'target', 'on_fail': [], 'on_success': []}
    combat, table, mid = fight(tmp_path, [MANTLE], cause=[save])
    resolve(lambda a: act(table, mid, 'Cold Star Mantle', a))
    from tests.auto_worker1_support import turn
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Cause', a, target_id=LEFT))
    saves = [e for e in reload(combat, mid).events if e.event_type == 'SAVE_ROLLED']
    assert saves[-1].payload['mode'] == expected


@pytest.mark.parametrize('mid_id,label', [
    ('STARS_TAL_FALLING_SPARK', 'Falling Spark'),
    ('STARS_TAL_METEOR_SHOWER', 'Meteor Shower'),
    ('STARS_TAL_FALLING_STAR', 'Falling Star'),
    ('STARS_TAL_HEAVEN_FALLING_STAR', 'Heaven-Falling Star')])
@pytest.mark.parametrize('auto', [False, True])
def test_stellar_area_harms_only_enemies_with_both_sides_in_range(tmp_path, mid_id, label, auto):
    combat, table, mid = fight(tmp_path, [mid_id], ally=[], cl=17,
        positions={LEFT: {'x': 3, 'y': 6}, ALLY: {'x': 3, 'y': 5}, RIGHT: {'x': 4, 'y': 6}})
    if auto:
        from combat.gate4_adapters import ManualControllerAdapter
        real = combat.controller
        class Controller:
            def choose_primary_action(self, context):
                candidate = next(c for c in context.legal_candidates
                    if c.destination is not None and (c.destination.x, c.destination.y) == (4, 6)
                    and mid_id in c.source_definition_id)
                return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
        send = lambda answers: table.auto_step(mid, table.state(mid)['last_sequence'], answers)
    else:
        send = cell_send(table, mid, label, (4, 6))
    resolve(send)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].current_hp == 1000
    assert engine.state.actors[ALLY].current_hp == 1000
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert {e.actor_id for e in engine.events if e.event_type == 'SAVE_ROLLED'} == {RIGHT}


def test_mantle_ally_native_attack_uses_caster_pb_and_bearer_clock(tmp_path):
    def armed_ally(bundle):
        if bundle['actor_id'] == ALLY:
            aid = 'action:test.stars.native_ally'
            bundle['actor_template']['action_ids'].append(aid)
            bundle['action_catalog'].append({'source_definition_id': aid, 'display_name': 'Cold Strike',
                'owner_id': ALLY, 'economy': 'NONE', 'resolution_kind': 'ATTACK',
                'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60, 'attack_bonus': 100,
                'damage': {'count': 1, 'sides': 8, 'modifier': 3}, 'damage_type': 'COLD',
                'parameters': {'attack_kind': 'weapon'}})
    combat, table, mid = fight(tmp_path, [MANTLE], ally=[], left_pb=5, right_pb=2,
                              bundle_edit=armed_ally)
    resolve(lambda a: act(table, mid, 'Cold Star Mantle', a, target_id=ALLY))
    from tests.auto_worker1_support import turn
    turn(table, mid, ALLY)
    _, prompts = resolve(lambda a: act(table, mid, 'Cold Strike', a, target_id=RIGHT))
    engine = reload(combat, mid)
    assert bonus_rolls(engine)[-1].modifier == 8
    assert stars.MANTLE_TURN in engine.state.actors[ALLY].turn_flags
    assert stars.MANTLE_TURN not in engine.state.actors[LEFT].turn_flags
    choice = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.stars_cold_mantle')
    assert choice['context']['reactor_id'] == ALLY
