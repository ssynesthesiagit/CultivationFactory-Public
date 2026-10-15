"""Chains fifth-pass mechanics through real table commits and cold replay."""
import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.auto_worker1_support import (LEFT, RIGHT, ALLY, act, fight, turn,
    cell_send, resolve, action_sender)

CLONE = 'tianxia.talent.chains.chain_clone'
LASH = 'TAL_CHAINS_CHAIN_LASH_BASE'
WEIGHT = 'tianxia.talent.chains.weighted_links'


def cold(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def clone_fight(tmp_path, **kwargs):
    combat, table, mid = fight(tmp_path, [CLONE], positions={
        LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 5, 'y': 6}, ALLY: {'x': 4, 'y': 5}},
        ally=[], left_attack_bonus=100, **kwargs)
    resolve(cell_send(table, mid, 'Chain Clone', (4, 6)))
    engine = cold(tmp_path, mid)
    clone, = [a for a in engine.state.actors.values() if (a.summon or {}).get('source') == CLONE]
    assert clone.active and clone.position.x == 4 and clone.position.y == 6
    assert clone.armor_class == 18 and clone.maximum_hp == 90 and clone.speed_ft == 30
    assert clone.summon['owner'] == LEFT
    order = engine.state.initiative_order
    assert order[order.index(LEFT) + 1] == clone.entity_id
    return combat, table, mid, clone.entity_id


def command(table, mid):
    assert act(table, mid, 'Command Chain Clone')['status'] == 'COMMITTED'


def test_clone_attack_command_slow_and_owner_expiry_with_both_sides(tmp_path):
    combat, table, mid, cid = clone_fight(tmp_path)
    before = cold(tmp_path, mid)
    enemy_hp, ally_hp = before.state.actors[RIGHT].current_hp, before.state.actors[ALLY].current_hp
    command(table, mid)
    turn(table, mid, cid)
    # AI's real adapter chooses the legal strike while ally and enemy are adjacent.
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    resolve(lambda answers: table.auto_step(mid, table.state(mid)['last_sequence'], answers))
    engine = cold(tmp_path, mid)
    assert engine.state.actors[RIGHT].current_hp < enemy_hp
    assert engine.state.actors[ALLY].current_hp == ally_hp
    mods = [m for m in engine.state.actors[RIGHT].modifiers.values() if m.target_field == 'speed_ft']
    assert len(mods) == 1 and mods[0].value == -5
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 25
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    turn(table, mid, LEFT)
    assert not [m for m in cold(tmp_path, mid).state.actors[RIGHT].modifiers.values() if m.target_field == 'speed_ft']


@pytest.mark.parametrize('dc,held', [(100, True), (1, False)])
def test_clone_tether_inherits_owner_dc_and_expires_on_owner_turn(tmp_path, dc, held):
    combat, table, mid, cid = clone_fight(tmp_path, left_save_dc=dc)
    command(table, mid)
    turn(table, mid, cid)
    before_qi = cold(tmp_path, mid).state.actors[LEFT].resources['resource:core.qi']
    from tests.auto_worker1_support import settle
    def refuse(prompt):
        return [option['id'] for option in prompt['choice']['options'] if 'Refuse' in option['label']]
    result, _ = settle(lambda answers: act(table, mid, 'Set the Tether', answers, target_id=RIGHT), choose=refuse)
    assert result['status'] == 'COMMITTED'
    engine = cold(tmp_path, mid)
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == before_qi - 1
    bonds = [c for c in engine.state.actors[RIGHT].conditions.values() if c.condition_id.endswith('.bound')]
    assert bool(bonds) == held
    if held:
        assert bonds[0].source_actor_id == cid and bonds[0].data['tether_ft'] == 30
    else:
        assert engine._effective_speed(engine.state.actors[RIGHT]) == 25
    turn(table, mid, LEFT)
    engine = cold(tmp_path, mid)
    assert not any(c.condition_id.endswith('.bound') for c in engine.state.actors[RIGHT].conditions.values())
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30


def test_clone_dodges_without_command_and_ends_on_concentration_loss(tmp_path):
    combat, table, mid, cid = clone_fight(tmp_path,
        cause=[{'type': 'damage', 'applies_to': 'target', 'flat': 1000, 'damage_type': 'FORCE'}])
    turn(table, mid, RIGHT)
    clone = cold(tmp_path, mid).state.actors[cid]
    assert any(c.condition_id == 'condition:core.dodge' for c in clone.conditions.values())
    assert act(table, mid, 'Cause', target_id=LEFT)['status'] == 'COMMITTED'
    engine = cold(tmp_path, mid)
    assert not engine.state.actors[cid].active


@pytest.mark.parametrize('name,condition', [('Grapple', 'grappled'), ('Shove: Prone', 'prone')])
def test_clone_ordinary_commands_resolve(tmp_path, name, condition):
    combat, table, mid, cid = clone_fight(tmp_path, right_score=1)
    command(table, mid)
    turn(table, mid, cid)
    resolve(lambda answers: act(table, mid, name, answers, target_id=RIGHT))
    assert any(c.condition_id.endswith('.' + condition) for c in cold(tmp_path, mid).state.actors[RIGHT].conditions.values())


def lash_setup(bundle):
    for action in bundle['action_catalog']:
        if (action.get('parameters', {}).get('typed', {}).get('option_of')) == LASH:
            # Two committed hits within one actual turn expose once-per-turn gating.
            action['economy'] = 'NONE'


@pytest.mark.parametrize('weighted,distance', [(False, 5), (True, 10)])
def test_lash_minor_link_once_per_turn_and_weight_does_not_double_key(tmp_path, weighted, distance):
    combat, table, mid = fight(tmp_path, [LASH] + ([WEIGHT] if weighted else []),
        left_attack_bonus=100, bundle_edit=lash_setup,
        positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}})
    start = cold(tmp_path, mid).state.actors[RIGHT].position
    resolve(lambda answers: act(table, mid, 'Chain Lash: Push 5 Feet', answers, target_id=RIGHT))
    engine = cold(tmp_path, mid)
    assert engine.grid.distance_ft(start, engine.state.actors[RIGHT].position) == distance
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == LEFT]
    # The damage roll carries the key modifier once; no optional modifier prompt/packet.
    rolls = [r for r in engine.rolls if str(r.reason).startswith('DAMAGE:')]
    assert rolls[-1].modifier == 2
    first = engine.state.actors[RIGHT].position
    resolve(lambda answers: act(table, mid, 'Chain Lash: Push 5 Feet', answers, target_id=RIGHT))
    assert cold(tmp_path, mid).state.actors[RIGHT].position == first


def clone_ai_sender(combat, table, mid, label, target_id):
    """Force the named legal ability through the real adapter; owner controls its summon."""
    from combat.gate4_adapters import ManualControllerAdapter
    menu = table.state(mid)['menu']
    cid = next(o['candidate_id'] for g in menu['actions'] if g['label'] == label
               for o in g['options'] if target_id in o.get('target_ids', []))
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            candidate = next((row for row in context.legal_candidates if row.candidate_id == cid), None)
            return ManualControllerAdapter(lambda _: (cid, tuple(candidate.option_ids) if candidate else ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    return lambda answers: table.auto_step(mid, table.state(mid)['last_sequence'], answers)


def test_clone_help_ai_selects_only_allies_and_consumes_on_next_attack(tmp_path):
    combat, table, mid, cid = clone_fight(tmp_path)
    command(table, mid)
    turn(table, mid, cid)
    resolve(clone_ai_sender(combat, table, mid, 'Help: Distract', RIGHT))
    engine = cold(tmp_path, mid)
    beneficiaries = [a for a in engine.state.actors.values() if any(
        m.target_field == 'attack_mode_vs' and m.value == 'ADVANTAGE:' + RIGHT
        for m in a.modifiers.values())]
    assert len(beneficiaries) == 1 and beneficiaries[0].entity_id in (LEFT, ALLY)
    assert beneficiaries[0].team_id == engine.state.actors[cid].team_id
    assert not engine.state.actors[RIGHT].modifiers
    receiver = beneficiaries[0].entity_id
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    turn(table, mid, receiver)
    engine = cold(tmp_path, mid)
    group = next(g for g in table.state(mid)['menu']['actions'] if any(
        RIGHT in o.get('target_ids', []) for o in g['options']) and
        g['label'] not in ('Grapple', 'Shove: Push 5 ft', 'Shove: Prone'))
    resolve(lambda answers: act(table, mid, group['label'], answers, target_id=RIGHT))
    engine = cold(tmp_path, mid)
    assert not any(m.target_field == 'attack_mode_vs' and m.value == 'ADVANTAGE:' + RIGHT
                   for m in engine.state.actors[receiver].modifiers.values())


def test_lash_grapple_benefit_is_specific_to_target_and_next_actual_grapple_check(tmp_path):
    contest = {'type': 'contest_against',
        'actor_check': {'kind': 'check', 'ability': 'STR', 'skill': 'Athletics'},
        'target_check': {'kind': 'dc'},
        'on_success': [{'type': 'condition', 'condition': 'grappled', 'applies_to': 'target', 'until_escape': True}]}
    combat, table, mid = fight(tmp_path, [LASH], left_attack_bonus=100,
        bundle_edit=lash_setup, extra_witness=True, prepare=[contest])
    resolve(lambda answers: act(table, mid, 'Chain Lash: Grapple Advantage', answers, target_id=RIGHT))
    engine = cold(tmp_path, mid)
    grant, = [c for c in engine.state.actors[LEFT].conditions.values()
               if c.condition_id == 'condition:typed.chains_lash_grapple']
    assert grant.data['target_id'] == RIGHT
    witness = 'actor:factory.auto111-witness'
    resolve(lambda answers: act(table, mid, 'Prepare', answers, target_id=witness))
    engine = cold(tmp_path, mid)
    assert any(c.condition_id == grant.condition_id for c in engine.state.actors[LEFT].conditions.values())
    prior = len(engine.rolls)
    resolve(lambda answers: act(table, mid, 'Prepare', answers, target_id=RIGHT))
    engine = cold(tmp_path, mid)
    checks = [r for r in engine.rolls[prior:] if r.actor_id == LEFT and r.reason.startswith('CHECK:')]
    assert checks and len(checks[0].dice) == 2
    assert not any(c.condition_id == grant.condition_id for c in engine.state.actors[LEFT].conditions.values())


@pytest.mark.parametrize('owned', [False, True])
@pytest.mark.parametrize('talent,ac,hp', [
    ('tianxia.talent.chains.shackling_chain', 17, 75),
    ('tianxia.talent.chains.chain_prison', 17, 120)])
def test_warden_prison_statistics_are_owned_and_persist(tmp_path, owned, talent, ac, hp):
    combat, table, mid = fight(tmp_path, [talent] + (['insight.prison-warden'] if owned else []))
    name = 'Shackling Chain' if talent.endswith('shackling_chain') else 'Chain Prison'
    assert act(table, mid, name, target_id=RIGHT)['status'] == 'COMMITTED'
    objects = list(cold(tmp_path, mid).state.objects.values())
    prison, = [o for o in objects if o.object_kind == 'BOUND_CHAIN']
    assert prison.ac == ac + (2 if owned else 0)
    assert prison.maximum_hp == hp + (20 if owned else 0)
    assert prison.current_hp == prison.maximum_hp


def test_warden_escape_blocks_paid_teleport_until_escapees_next_turn(tmp_path):
    def teleport_action(bundle):
        if bundle['actor_id'] != RIGHT:
            return
        aid = 'action:test.chains.escaped_teleport'
        bundle['actor_template']['action_ids'].append(aid)
        bundle['action_catalog'].append({'source_definition_id': aid, 'display_name': 'Escape teleport',
            'owner_id': RIGHT, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
            'range_ft': 30, 'costs': [['resource:core.qi', 1]], 'parameters': {'typed': {
                'effects': [{'type': 'teleport', 'applies_to': 'self', 'distance_ft': 15}],
                'numbers': {'cl': 15, 'pb': 4, 'key_mod': 2, 'save_dc': 12},
                'duration': {'kind': 'instant'}, 'riders': []}}})
    combat, table, mid = fight(tmp_path, ['tianxia.talent.chains.chain_prison', 'insight.prison-warden'],
        cause=[{'type': 'object_damage', 'flat': 1000, 'damage_types': ['force']}],
        cause_target='OBJECT', bundle_edit=teleport_action)
    assert act(table, mid, 'Chain Prison', target_id=RIGHT)['status'] == 'COMMITTED'
    prison, = [o for o in cold(tmp_path, mid).state.objects.values() if o.object_kind == 'BOUND_CHAIN']
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause', target_id=prison.object_id)['status'] == 'COMMITTED'
    engine = cold(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.chains_warden_escape'
               for c in engine.state.actors[RIGHT].conditions.values())
    before = engine.state.actors[RIGHT].position
    qi = engine.state.actors[RIGHT].resources['resource:core.qi']
    resolve(lambda answers: act(table, mid, 'Escape teleport', answers))
    engine = cold(tmp_path, mid)
    assert engine.state.actors[RIGHT].position == before
    assert engine.state.actors[RIGHT].resources['resource:core.qi'] == qi - 1
    turn(table, mid, LEFT)
    turn(table, mid, RIGHT)
    assert not any(c.condition_id == 'condition:typed.chains_warden_escape'
                   for c in cold(tmp_path, mid).state.actors[RIGHT].conditions.values())
    from tests.auto_worker1_support import settle
    settle(lambda answers: act(table, mid, 'Escape teleport', answers),
           choose=lambda prompt: [prompt['choice']['options'][-1]['id']])
    assert cold(tmp_path, mid).state.actors[RIGHT].position != before


def test_clone_tether_not_offered_when_owner_cannot_pay(tmp_path):
    def six_points(doc, aid):
        if aid == LEFT:
            doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 6
    combat, table, mid, cid = clone_fight(tmp_path, sheet_edit=six_points)
    command(table, mid)
    turn(table, mid, cid)
    result, _ = resolve(lambda answers: act(table, mid, 'Set the Tether', answers, target_id=RIGHT))
    assert result['status'] == 'COMMITTED'
    assert cold(tmp_path, mid).state.actors[LEFT].resources['resource:core.qi'] == 0
    turn(table, mid, LEFT)
    command(table, mid)
    turn(table, mid, cid)
    assert not any(g['label'] == 'Set the Tether' for g in table.state(mid)['menu']['actions'])


def test_clone_tether_willing_ally_needs_no_save(tmp_path):
    combat, table, mid, cid = clone_fight(tmp_path, left_save_dc=1)
    command(table, mid)
    turn(table, mid, cid)
    before = cold(tmp_path, mid)
    saves = len([e for e in before.events if e.event_type == 'SAVE_ROLLED'])
    result, prompts = resolve(lambda answers: act(table, mid, 'Set the Tether', answers, target_id=ALLY))
    assert result['status'] == 'COMMITTED'
    assert len(prompts) == 1
    import json
    shown = json.dumps(prompts[0])
    assert 'accept' in shown.lower() and 'Tether' in shown
    owner_name = cold(tmp_path, mid).state.actors[LEFT].display_name
    assert 'Speed is 10 feet lower' in shown and 'cannot Dash' in shown
    assert 'Disadvantage' in shown and 'more than 30 feet' in shown
    assert f"start of {owner_name}'s next turn" in shown
    assert '1 cultivation point' in shown and 'you spend nothing' in shown
    assert 'answering costs you no action' in shown
    engine = cold(tmp_path, mid)
    assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED']) == saves
    bound, = [c for c in engine.state.actors[ALLY].conditions.values()
              if c.condition_id.endswith('.bound')]
    assert bound.source_actor_id == cid and bound.data['tether_ft'] == 30
    turn(table, mid, LEFT)
    assert not any(c.condition_id.endswith('.bound')
                   for c in cold(tmp_path, mid).state.actors[ALLY].conditions.values())


def test_clone_tether_player_can_refuse_during_table_action(tmp_path):
    combat, table, mid, cid = clone_fight(tmp_path, left_save_dc=1)
    command(table, mid)
    turn(table, mid, cid)
    engine_before = cold(tmp_path, mid)
    before_speed = engine_before._effective_speed(engine_before.state.actors[ALLY])
    def refuse(prompt):
        choice = prompt.get('choice') or {}
        return [option['id'] for option in choice.get('options', [])
                if 'Refuse' in str(option.get('label', ''))]
    from tests.auto_worker1_support import settle
    result, prompts = settle(lambda answers: act(table, mid, 'Set the Tether', answers, target_id=ALLY), choose=refuse)
    assert result['status'] == 'COMMITTED' and len(prompts) == 1
    import json
    assert 'Visitor' in json.dumps(prompts[0])
    engine = cold(tmp_path, mid)
    assert not any(c.condition_id.endswith('.bound') for c in engine.state.actors[ALLY].conditions.values())
    assert engine._effective_speed(engine.state.actors[ALLY]) == before_speed - 5


@pytest.mark.parametrize('accept', [True, False])
def test_clone_tether_ai_turn_pauses_for_player_and_cold_reloads(tmp_path, accept):
    combat, table, mid, cid = clone_fight(tmp_path, left_save_dc=1)
    command(table, mid)
    turn(table, mid, cid)
    sender = clone_ai_sender(combat, table, mid, 'Set the Tether', ALLY)
    from tests.auto_worker1_support import settle
    def choose(prompt):
        word = 'Accept' if accept else 'Refuse'
        return [o['id'] for o in prompt['choice']['options'] if word in o['label']]
    result, prompts = settle(sender, choose=choose)
    assert result['status'] == 'COMMITTED' and len(prompts) == 1
    import json
    shown = json.dumps(prompts[0])
    assert 'Speed is 10 feet lower' in shown
    assert 'cannot Dash' in shown and 'Disadvantage' in shown
    owner_name = cold(tmp_path, mid).state.actors[LEFT].display_name
    assert f"start of {owner_name}'s next turn" in shown
    assert '1 cultivation point' in shown and 'you spend nothing' in shown
    engine = cold(tmp_path, mid)
    bonds = [c for c in engine.state.actors[ALLY].conditions.values()
             if c.condition_id.endswith('.bound')]
    if accept:
        assert len(bonds) == 1 and bonds[0].source_actor_id == cid
    else:
        assert not bonds and engine._effective_speed(engine.state.actors[ALLY]) == 25


def test_clone_tether_ai_recipient_answers_automatically_and_cold_reloads(tmp_path):
    combat, table, mid, cid = clone_fight(tmp_path, left_save_dc=100)
    command(table, mid)
    turn(table, mid, cid)
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='LOCAL_AUTO')
    sender = clone_ai_sender(combat, table, mid, 'Set the Tether', RIGHT)
    result = sender([])
    assert result['status'] == 'COMMITTED'
    engine = cold(tmp_path, mid)
    assert any(c.condition_id.endswith('.bound')
               for c in engine.state.actors[RIGHT].conditions.values())
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == RIGHT for e in engine.events)


def test_clone_help_manual_prompt_names_benefit_and_deadline(tmp_path):
    combat, table, mid, cid = clone_fight(tmp_path)
    command(table, mid)
    turn(table, mid, cid)
    result = act(table, mid, 'Help: Distract', target_id=RIGHT)
    assert result['status'] == 'REACTION_REQUIRED'
    import json
    shown = json.dumps(result['reaction'])
    clone = cold(tmp_path, mid).state.actors[cid]
    assert 'Advantage' in shown and f"start of {clone.display_name}'s next turn" in shown
    assert clone.display_name in shown
    assert any('Visitor' in str(option.get('label', ''))
               for option in result['reaction']['choice']['options'])


def test_clone_cannot_create_second_body_while_one_is_present(tmp_path):
    combat, table, mid, cid = clone_fight(tmp_path)
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    before = cold(tmp_path, mid).state.actors[LEFT].resources['resource:core.qi']
    # The shared summon admission rule enforces the printed one-clone limit.
    assert not any(c.display_name.startswith('Chain Clone')
                   for c in cold(tmp_path, mid).legal_candidates())
    engine = cold(tmp_path, mid)
    bodies = [a for a in engine.state.actors.values() if a.active and (a.summon or {}).get('source') == CLONE]
    assert len(bodies) == 1 and bodies[0].entity_id == cid
    assert bodies[0].position.x == 4 and bodies[0].position.y == 6
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == before


def test_clone_dismisses_at_one_minute_deadline(tmp_path):
    combat, table, mid, cid = clone_fight(tmp_path, maximum_rounds=30)
    for _ in range(9):
        turn(table, mid, RIGHT)
        turn(table, mid, LEFT)
    assert cold(tmp_path, mid).state.actors[cid].active
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert not cold(tmp_path, mid).state.actors[cid].active


@pytest.mark.parametrize('name', ['Dash', 'Dodge', 'Shove: Push 5 ft'])
def test_clone_remaining_printed_combat_commands(tmp_path, name):
    combat, table, mid, cid = clone_fight(tmp_path, right_score=1)
    command(table, mid)
    turn(table, mid, cid)
    before = cold(tmp_path, mid)
    position = before.state.actors[RIGHT].position
    movement = before.state.actors[cid].movement_remaining_ft
    resolve(lambda answers: act(table, mid, name, answers,
        target_id=RIGHT if name.startswith('Shove') else None))
    engine = cold(tmp_path, mid)
    if name == 'Dash':
        assert engine.state.actors[cid].movement_remaining_ft == movement + 30
    elif name == 'Dodge':
        assert any(c.condition_id == 'condition:core.dodge'
                   for c in engine.state.actors[cid].conditions.values())
    else:
        assert engine.grid.distance_ft(position, engine.state.actors[RIGHT].position) == 5


@pytest.mark.parametrize('name,kind', [('Reduce Speed', 'speed'), ('Visible Link', 'mark')])
def test_lash_other_minor_links_resolve_and_expire(tmp_path, name, kind):
    combat, table, mid = fight(tmp_path, [LASH], left_attack_bonus=100)
    # Read the exact printed option label; no synthetic effect is supplied.
    if kind == 'mark':
        name = next(g['label'].split(': ', 1)[1] for g in table.state(mid)['menu']['actions']
                    if g['label'].startswith('Chain Lash:') and 'Link' in g['label'])
    resolve(lambda answers: act(table, mid, 'Chain Lash: ' + name, answers, target_id=RIGHT))
    engine = cold(tmp_path, mid)
    if kind == 'speed':
        assert engine._effective_speed(engine.state.actors[RIGHT]) == 25
    else:
        from combat.typed_executor import mark_condition_id
        assert any(c.condition_id == mark_condition_id('Link', LEFT)
                   for c in engine.state.actors[RIGHT].conditions.values())
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    engine = cold(tmp_path, mid)
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
    from combat.typed_executor import mark_condition_id
    assert not any(c.condition_id == mark_condition_id('Link', LEFT)
                   for c in engine.state.actors[RIGHT].conditions.values())
