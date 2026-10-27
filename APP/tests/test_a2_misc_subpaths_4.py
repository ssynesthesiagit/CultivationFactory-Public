"""CombatService preview/commit and cold-reload coverage for the Misc 4 pass."""
import copy
import pytest

from combat.gate5_service import CombatService
from combat import typed_executor as te
from test_riders_c8 import ROOT, ME, MIND_SPIKE, DW, EM, ED, bundle, held
from tests.thrum_grave_support import TG  # moved here by 18faa4ab (no longer exported by test_riders_c8)
from test_riders_c8_review import service_commit

ENEMY = 'actor:factory.misc4_enemy'
ALLY = 'actor:factory.misc4_ally'
DE = 'tianxia.tradition.spirit.dream_eater.feature.'


def setup_action(b, effects, name='Set up test', *, target='SELF', economy='NONE'):
    action = copy.deepcopy(next(a for a in b['action_catalog'] if a['display_name'] == 'Mind Spike'))
    action.update(source_definition_id='test:misc4.' + name.replace(' ', '_'), display_name=name,
                  economy=economy, target_kind=target, range_ft=60, costs=[])
    action['parameters']['typed'].update(effects=effects, riders=[])
    action['parameters']['expected_damage'] = 0
    if economy == 'NONE':
        action['parameters']['free_primary'] = True  # declared free activation; NONE alone is not a primary intent (ad49b65f)
    b['action_catalog'].append(action)
    b['actor_template']['action_ids'].append(action['source_definition_id'])
    return action


def match(tmp_path, mine, other=None, friend=None, *, seed='MISC4', enemy_at=(7, 6), ally_at=(6, 7)):
    mine['actor_template']['maximum_hp'] = 500
    mine['actor_template']['initiative_bonus'] = 50
    other = other or bundle([MIND_SPIKE], actor_id=ENEMY)
    other['actor_template']['maximum_hp'] = 500
    other['actor_template']['initiative_bonus'] = 100
    actors = [ME, ENEMY]
    teams = {ME: 'team:a', ENEMY: 'team:b'}
    positions = {ME: {'x': 6, 'y': 6}, ENEMY: {'x': enemy_at[0], 'y': enemy_at[1]}}
    bundles = [mine, other]
    if friend:
        friend['actor_template']['maximum_hp'] = 500
        actors.append(ALLY)
        teams[ALLY] = 'team:a'
        positions[ALLY] = {'x': ally_at[0], 'y': ally_at[1]}
        bundles.append(friend)
    svc = CombatService(ROOT, tmp_path)
    session = svc.persistence.create_match(match_seed=seed, maximum_rounds=20, typed_bundles=tuple(bundles),
                roster_setup={'primary_actor_ids': actors, 'team_by_actor': teams, 'starting_positions': positions})
    return Table(svc, session)


class Table:
    def __init__(self, svc, session):
        self.svc, self.session = svc, session
        self.metadata = {'participant_control_modes': {a: 'MANUAL' for a in session.engine.state.actors}}
        self.choice = lambda context: context.extension_choice.option_ids[:context.extension_choice.minimum_selections] if (
            context.extension_choice and not context.extension_choice.allow_decline) else ()

    @property
    def engine(self):
        return self.session.engine

    def act(self, name, target=None):
        return service_commit(self.svc, self.session, self.metadata, name, target, choose=self.choice)

    def advance(self, who):
        for _ in range(12):
            if self.engine.state.current_actor_id == who:
                return
            self.act('End turn')
        pytest.fail('Actor never received a turn')

    def reload(self):
        before = self.engine.state.model_dump(mode='json')
        self.session = self.svc.persistence.load_match(self.session.match_id)
        assert self.engine.state.model_dump(mode='json') == before
        assert self.session.verify()['status'] == 'PASS'


def condition(name, rule=None):
    return {'type': 'condition', 'condition': name, 'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED',
            'condition_data': {'rule': rule or {}}}


@pytest.mark.parametrize('control', ['MANUAL', 'LOCAL_AUTO'])
@pytest.mark.parametrize('disadvantage', [False, True])
def test_dream_stitch_substitutes_pb_penalty_before_outcome(tmp_path, control, disadvantage):
    mine = bundle([MIND_SPIKE, DW+'dream_stitch'], pb=6)
    mine['actor_template']['armor_class'] = 60
    other = bundle([MIND_SPIKE], actor_id=ENEMY)
    attack = setup_action(other, [{'type': 'attack', 'attack_kind': 'cultivation_melee', 'count': 1,
                                  'on_hit': [], 'on_miss': []}], 'Test attack', target='HOSTILE_ENTITY', economy='ACTION')
    attack['parameters']['typed']['range_ft'] = 5
    if disadvantage:
        setup_action(other, [condition('test_disadvantage', {'attacks_have': 'DISADVANTAGE'})])
    table = match(tmp_path, mine, other)
    table.advance(ENEMY)
    if disadvantage:
        table.act('Set up test')
    table.reload()
    table.metadata['participant_control_modes'][ME] = control
    def choose(context):
        if context.reaction_source_id.endswith('dreamweaver.dream_stitch'):
            return ('stitch',)
        if context.reaction_source_id.endswith('dreamweaver.stitch_miss'):
            return ('thread',)
        return ()
    table.choice = choose
    events, prompts, _ = table.act('Test attack', ME)
    [roll] = [e.payload for e in events if e.event_type == 'ATTACK_ROLLED']
    assert len(roll['dice']) == 2
    assert roll['modifier'] == attack['parameters']['typed']['numbers']['attack_bonus'] - (6 if disadvantage else 0)
    assert table.engine.state.actors[ME].resources['resource:core.resonance'] == 59
    assert te.bears_mark(table.engine.state.actors[ENEMY], ME, 'Dream Thread')
    assert bool(prompts) is (control == 'MANUAL')
    table.reload()


@pytest.mark.parametrize('impact', [False, True])
@pytest.mark.parametrize('save_fails', [False, True])
def test_impact_recompense_bypasses_only_added_packet(tmp_path, impact, save_fails):
    mine = bundle([MIND_SPIKE, EM+'receive_and_return', EM+'threefold_recompense'], dc=40 if save_fails else -40)
    # Compiled initial pool values are fixture inputs; gameplay spends the real resources.
    for r in mine['actor_template']['resources']:
        if r['resource_id'] == 'resource:named.measure_' + ('impact' if impact else 'intent'):
            r['initial'] = 1
    other = bundle([MIND_SPIKE], actor_id=ENEMY)
    setup_action(other, [{'type': 'temp_hp', 'flat': 500, 'applies_to': 'self'},
                         {'type': 'mark', 'mark': 'Resonance', 'applies_to': 'target', 'duration': {'kind':'until_removed'}}],
                 target='HOSTILE_ENTITY')
    # Mark the enemy using an actual setup action owned by the Recompense user.
    setup_action(mine, [{'type': 'mark', 'mark': 'Resonance', 'applies_to': 'target',
                         'duration': {'kind':'until_removed'}}], 'Mark target', target='HOSTILE_ENTITY')
    table = match(tmp_path, mine, other)
    table.advance(ENEMY)
    table.act('Set up test', ME)
    table.advance(ME)
    table.act('Mark target', ENEMY)
    table.reload()
    def choose(context):
        if context.reaction_source_id.endswith('equal_measure.recompense'):
            return ('impact' if impact else 'intent',)
        if context.reaction_source_id.endswith('equal_measure.recompense_strike'):
            return ('spike',)
        return context.extension_choice.option_ids[:1] if context.extension_choice and not context.extension_choice.allow_decline else ()
    table.choice = choose
    events, _, _ = table.act('Threefold Recompense', ENEMY)
    packets = [e.payload for e in events if e.event_type == 'DAMAGE_COMMITTED' and ENEMY in e.target_ids]
    assert len(packets) == 2
    normal, bonus = packets
    assert normal['temporary_hp_absorbed'] == normal['reduced_to'] and normal['hp_damage'] == 0
    assert bonus['temporary_hp_absorbed'] == (0 if impact else bonus['reduced_to'])
    assert bonus['hp_damage'] == (bonus['reduced_to'] if impact else 0)
    assert table.engine.state.actors[ENEMY].temporary_hp == 500-normal['reduced_to']-(0 if impact else bonus['reduced_to'])
    assert table.engine.state.actors[ENEMY].current_hp == 500-(bonus['reduced_to'] if impact else 0)
    table.reload()


@pytest.mark.parametrize('damage_type', ['psychic', 'force', 'slashing', 'necrotic'])
def test_three_step_keeps_selected_type_for_all_targets(tmp_path, damage_type):
    mine = bundle([MIND_SPIKE, ED+'afterimage_edge', ED+'three_step_soul_execution'])
    # Three persisted Echo Positions are produced by the ordinary condition effect.
    from combat.ext.echo_step_disciple import ECHO
    setup_action(mine, [{'type':'condition','condition':ECHO.removeprefix('condition:typed.'),'applies_to':'self','expires_on':'UNTIL_REMOVED',
                         'condition_data':{'cell':c,'label':'Echo Position'}} for c in ([6,6],[6,7],[8,7])])
    table = match(tmp_path, mine)
    table.advance(ME)
    table.act('Set up test')
    table.reload()
    def choose(context):
        spec = context.extension_choice
        if context.reaction_source_id.endswith('echo_step.three_step_damage'):
            return (damage_type,)
        if context.reaction_source_id.endswith('echo_step.three_step_move'):
            return ()
        return spec.option_ids[:1] if spec else ()
    table.choice = choose
    events, prompts, _ = table.act('Three-Step Soul Execution')
    rolls = [e for e in events if e.event_type == 'ATTACK_ROLLED']
    assert len(rolls) == 3
    packets = [e.payload for e in events if e.event_type == 'DAMAGE_COMMITTED']
    assert packets and {p['damage_type'].lower() for p in packets} == {damage_type}
    [selection] = [p for p in prompts if p.reaction_source_id.endswith('echo_step.three_step_damage')]
    assert 'every strike' in selection.choice_trigger['prompt']
    table.reload()


@pytest.mark.parametrize('curse', [False, True])
@pytest.mark.parametrize('save_fails', [False, True])
def test_ally_sleep_intervention_checks_side_and_reloads(tmp_path, curse, save_fails):
    mine = bundle([MIND_SPIKE])
    other = bundle([MIND_SPIKE, DE+'sleeping_curse'], actor_id=ENEMY, dc=40 if save_fails else -40)
    friend = bundle([MIND_SPIKE], actor_id=ALLY)
    kind = 'dream_cursed_sleep' if curse else 'dreamweaver_refuge_sleep'
    setup_action(other, [{'type':kind,'applies_to':'target'}], 'Test sleep', target='HOSTILE_ENTITY', economy='ACTION')
    table = match(tmp_path, mine, other, friend)
    table.advance(ENEMY)
    table.act('Test sleep', ALLY)
    table.reload()
    table.advance(ME)
    name = 'Wake Cursed Sleeper: invoke their name or bond' if curse else 'Wake Dream-Sleeping Ally'
    candidates = [c for c in table.engine.legal_candidates() if c.display_name == name]
    assert candidates and {t for c in candidates for t in c.target_ids} == {ALLY}
    events, _, _ = table.act(name, ALLY)
    asleep = any(c.condition_id == 'condition:typed.unconscious' for c in table.engine.state.actors[ALLY].conditions.values())
    assert asleep is (curse and save_fails)
    if curse:
        [save] = [e.payload for e in events if e.event_type == 'SAVE_ROLLED']
        assert save['success'] is not save_fails
    table.reload()


@pytest.mark.parametrize('ending', ['dismiss', 'unconscious', 'paralyzed'])
def test_gravebeat_rhythm_ends_with_real_action(tmp_path, ending):
    mine = bundle([MIND_SPIKE, TG+'gravebeat'])
    setup_action(mine, [condition('paralyzed' if ending == 'paralyzed' else 'unconscious')], 'Test unconscious')
    table = match(tmp_path, mine)
    table.advance(ME)
    table.act('Gravebeat')
    table.reload()
    assert held(table.engine.state.actors[ME], 'condition:typed.gravebeat_rhythm')
    table.act('Dismiss Gravebeat' if ending == 'dismiss' else 'Test unconscious')
    assert bool(held(table.engine.state.actors[ME], 'condition:typed.gravebeat_rhythm')) is (ending == 'paralyzed')
    table.reload()


@pytest.mark.parametrize('anatomy', ['throne_wings', 'burning_name'])
def test_seraphic_throne_wings_grant_real_hovering_flight(tmp_path, anatomy):
    from combat.flight import profile
    SM = 'tianxia.tradition.spirit.seraphic_molter.feature.'
    mine = bundle([MIND_SPIKE, SM+'first_molt', SM+'molt_the_mortal_name'])
    table = match(tmp_path, mine)
    table.advance(ME)
    def choose(context):
        if context.reaction_source_id.endswith('seraphic.anatomies'):
            return (anatomy, 'crown_of_unselfing')
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    table.choice = choose
    table.act('Molt the Mortal Name')
    table.reload()
    capability = profile(table.engine, table.engine.state.actors[ME])
    assert capability.speed_ft == (60 if anatomy == 'throne_wings' else 0)
    assert capability.hover is (anatomy == 'throne_wings')
    assert table.engine.state.actors[ME].resources['resource:named.molt_debt'] == 1
    flying = [c for c in table.engine.legal_candidates() if c.destination is not None and c.destination.z > 0]
    if anatomy == 'throne_wings':
        assert flying
        candidate = flying[0]
        table.act(candidate.display_name)
        assert table.engine.state.actors[ME].position.z > 0
        table.reload()
    else:
        assert not flying


@pytest.mark.parametrize('declared', [False, True])
def test_perfect_witness_requires_action_and_matching_destination(tmp_path, declared):
    choir = 'tianxia.tradition.spirit.choir_of_the_unopened_eye.feature.'
    mine = bundle([MIND_SPIKE, choir+'edict_of_perfect_witness'])
    setup_action(mine, [{'type':'choir_edict','applies_to':'target'}], 'Test edict', target='HOSTILE_ENTITY')
    other = bundle([MIND_SPIKE], actor_id=ENEMY)
    setup_action(other, [{'type':'teleport','applies_to':'self','distance_ft':30}], 'Test teleport', economy='BONUS_ACTION')
    table = match(tmp_path, mine, other)
    table.advance(ME)
    table.act('Test edict', ENEMY)
    table.advance(ENEMY)
    start = table.engine.state.actors[ENEMY].position
    table.reload()
    def choose(context):
        if context.reaction_source_id.endswith('choir.departure_method'):
            return ('technique',)
        if context.reaction_source_id.endswith('choir.departure'):
            return ('cell:9,6',)
        if context.reaction_source_id.endswith('teleport_destination'):
            return ('cell:9,6',)
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    table.choice = choose
    if declared:
        table.act('Declare Departure to the Witness')
        assert not table.engine.state.actors[ENEMY].action_available
        assert table.engine.state.actors[ENEMY].turn_flags['choir_declared_departure']['method'] == 'technique'
        table.reload()
    candidate = next(c for c in table.engine.legal_candidates() if c.display_name.startswith('Test teleport')
                     and c.destination is not None and (c.destination.x,c.destination.y) == (9,6))
    table.act(candidate.display_name)
    position = table.engine.state.actors[ENEMY].position
    assert (position.x, position.y) == ((9,6) if declared else (start.x,start.y))
    table.reload()


def test_perfect_witness_does_not_block_forced_subject_teleport(tmp_path):
    choir = 'tianxia.tradition.spirit.choir_of_the_unopened_eye.feature.'
    mine = bundle([MIND_SPIKE], actor_id=ME)
    other = bundle([MIND_SPIKE, choir+'edict_of_perfect_witness'], actor_id=ENEMY)
    setup_action(other, [{'type':'choir_edict','applies_to':'target'}], 'Test edict', target='HOSTILE_ENTITY')
    forced = setup_action(other, [{'type':'teleport','applies_to':'target','distance_ft':30,
                                   'choose_subject_destination':True}], 'Test forced teleport', target='HOSTILE_ENTITY')
    table = match(tmp_path, mine, other)
    table.advance(ENEMY)
    table.act('Test edict', ME)
    table.reload()
    table.choice = lambda context: ('cell:5,6',) if context.reaction_source_id.endswith('subject_destination') else (
        context.extension_choice.option_ids[:1] if context.extension_choice and not context.extension_choice.allow_decline else ())
    before = table.engine.state.actors[ME].position
    table.act('Test forced teleport', ME)
    after = table.engine.state.actors[ME].position
    assert (after.x, after.y) == (5, 6)
    assert (after.x, after.y) != (before.x, before.y)
    table.reload()


@pytest.mark.parametrize('kind', ['undead', 'haunt', 'possessed', 'humanoid'])
def test_gravebeat_gains_from_hostile_spirit_failed_save(tmp_path, kind):
    mine = bundle([MIND_SPIKE, TG+'gravebeat'], dc=40)
    other = bundle([MIND_SPIKE], actor_id=ENEMY)
    other['actor_template']['creature_types'] = [kind]
    table = match(tmp_path, mine, other)
    table.advance(ME)
    table.act('Mind Spike', ENEMY)
    assert table.engine.state.actors[ME].resources['resource:named.gravebeat'] == int(kind != 'humanoid')
    table.reload()


def test_chronicle_records_and_erases_actual_failed_death_save(tmp_path):
    from combat.ext.life_state import failed_death_saves, RECORD
    from combat.ext.echo_scribe import ENTRY
    ES = 'tianxia.tradition.spirit.echo_scribe.feature.'
    mine = bundle([MIND_SPIKE, ES+'chronicle_of_the_living_soul'])
    setup_action(mine, [{'type':'condition','condition':'death_save_mode','applies_to':'target','expires_on':'UNTIL_REMOVED',
                        'condition_data':{'rule':{'death_save_mode':{'mode':'NORMAL'}}}}], 'Allow dying', target='ALLY_OR_SELF')
    other = bundle([MIND_SPIKE], actor_id=ENEMY)
    setup_action(other, [{'type':'damage','flat':500,'damage_types':['necrotic'],'applies_to':'target'}],
                 'Test drop', target='HOSTILE_ENTITY', economy='ACTION')
    table = match(tmp_path, mine, other, bundle([MIND_SPIKE],actor_id=ALLY), seed='MISC4-DEATH-3')
    table.advance(ME)
    def choose(context):
        if context.reaction_source_id.endswith('echo_scribe.souls'):
            return (ALLY,)
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    table.choice = choose
    table.act('Allow dying', ALLY)
    table.act('Chronicle of the Living Soul')
    table.advance(ENEMY)
    table.act('Test drop', ALLY)
    table.advance(ME)
    table.act('End turn')  # the Recorded Soul rolls its actual failed death save
    table.advance(ME)
    soul = table.engine.state.actors[ALLY]
    assert soul.current_hp == 0 and soul.active
    assert failed_death_saves(soul) == 1
    entries = [c for c in held(table.engine.state.actors[ME], ENTRY) if c.data.get('kind') == 'failed_death_save']
    assert len(entries) == 1 and entries[0].data['soul'] == ALLY
    table.reload()
    events, _, _ = table.act('Rewrite the Margin: erase a failed death save', ALLY)
    [receipt] = [e.payload for e in events if e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('rule') == 'failed_death_save_erased']
    assert (receipt['failures_before'],receipt['failures_after']) == (1,0)
    soul = table.engine.state.actors[ALLY]
    assert soul.current_hp == 0 and soul.life_state == 'DYING' and soul.turn_flags[RECORD] == {'ok':0,'bad':0}
    assert not [c for c in held(table.engine.state.actors[ME], ENTRY) if c.data.get('kind') == 'failed_death_save']
    table.reload()


@pytest.mark.parametrize('save_succeeds', [False, True])
def test_motion_recompense_steps_before_damage_and_uses_player_space(tmp_path, save_succeeds):
    mine = bundle([MIND_SPIKE, EM+'receive_and_return', EM+'threefold_recompense'], dc=-40 if save_succeeds else 40)
    for resource in mine['actor_template']['resources']:
        if resource['resource_id'] == 'resource:named.measure_motion':
            resource['initial'] = 1
    setup_action(mine, [{'type':'mark','mark':'Resonance','applies_to':'target','duration':{'kind':'until_removed'}}],
                 'Mark target', target='HOSTILE_ENTITY')
    table = match(tmp_path, mine, enemy_at=(9,6))
    table.advance(ME)
    table.act('Mark target', ENEMY)
    table.reload()
    def choose(context):
        suffix = context.reaction_source_id
        if suffix.endswith('equal_measure.recompense'):
            return ('motion',)
        if suffix.endswith('equal_measure.recompense_strike'):
            return ('spike',)
        if suffix.endswith('equal_measure.recompense_motion'):
            return ('step',)
        if suffix.endswith('recompense_adjacent'):
            return ('cell:8,6',)
        spec = context.extension_choice
        return spec.option_ids[:spec.minimum_selections] if spec and not spec.allow_decline else ()
    table.choice = choose
    events, prompts, _ = table.act('Threefold Recompense', ENEMY)
    if save_succeeds:
        assert (table.engine.state.actors[ME].position.x,table.engine.state.actors[ME].position.y) == (6,6)
        assert not [p for p in prompts if p.reaction_source_id.endswith('equal_measure.recompense_motion')]
        assert not [p for p in prompts if p.reaction_source_id.endswith('recompense_adjacent')]
    else:
        assert (table.engine.state.actors[ME].position.x,table.engine.state.actors[ME].position.y) == (8,6)
    assert (table.engine.state.actors[ENEMY].position.x,table.engine.state.actors[ENEMY].position.y) == (9,6)
    movement = [e.sequence for e in events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ME]
    damage = [e.sequence for e in events if e.event_type == 'DAMAGE_COMMITTED']
    if save_succeeds:
        assert not movement and damage
    else:
        assert movement and damage and max(movement) < min(damage)
        [route_prompt] = [p for p in prompts if p.reaction_source_id.endswith('recompense_adjacent')]
        assert route_prompt.choice_trigger['affected_id'] == ENEMY
    [save] = [e.payload for e in events if e.event_type == 'SAVE_ROLLED']
    assert save['success'] is save_succeeds
    table.reload()


def test_before_save_damage_marker_is_consumed_once_per_area_recipient(tmp_path):
    mine = bundle([MIND_SPIKE], dc=40)
    action = setup_action(mine, [{
        'type': 'save', 'applies_to': 'creatures_in_area', 'ability': 'dex', 'dc': 40,
        'on_fail': [
            {'type': 'damage', 'applies_to': 'target', 'flat': 1,
             'damage_types': ['force'], 'before_save_damage': True},
            {'type': 'damage', 'applies_to': 'target', 'flat': 2,
             'damage_types': ['force']}],
        'on_success': [
            {'type': 'damage', 'applies_to': 'target', 'flat': 3,
             'damage_types': ['force'], 'before_save_damage': True},
            {'type': 'damage', 'applies_to': 'target', 'flat': 4,
             'damage_types': ['force']}] }],
        'Area save marker', target='CELL', economy='ACTION')
    # Printed "each creature" scope is sealed explicitly: unscoped harmful areas default
    # to enemies only (a01c859d), so the recipients need their printed inclusive scope.
    action['parameters']['typed']['area'] = {'shape': 'sphere', 'size_ft': 20,
        'explicit_harmful_recipients': 'every_creature'}
    action['parameters']['any_cell'] = True
    action['range_ft'] = 0
    friend = bundle([MIND_SPIKE], actor_id=ALLY)
    mine['actor_template']['saving_throws']['DEX'] = -1000
    friend['actor_template']['saving_throws']['DEX'] = -1000
    enemy = bundle([MIND_SPIKE], actor_id=ENEMY)
    enemy['actor_template']['saving_throws']['DEX'] = 1000
    table = match(tmp_path, mine, other=enemy, friend=friend, enemy_at=(7, 6), ally_at=(6, 7))
    table.advance(ME)
    candidate = next(c for c in table.engine.legal_candidates()
                     if c.source_definition_id == action['source_definition_id'])
    events, _, _ = table.act(candidate.display_name)
    table.reload()
    hits = [e for e in events if e.event_type == 'DAMAGE_COMMITTED']
    assert len(hits) == 6
    by_target = {actor: [e for e in hits if actor in e.target_ids] for actor in (ME, ENEMY, ALLY)}
    assert all(len(rows) == 2 for rows in by_target.values())
    assert all(rows[0].sequence < rows[1].sequence for rows in by_target.values())
    assert all(rows[0].payload['rolled_or_pending_damage'] == 1 for actor, rows in by_target.items()
               if actor != ENEMY)
    assert all(rows[1].payload['rolled_or_pending_damage'] == 2 for actor, rows in by_target.items()
               if actor != ENEMY)
    assert [e.payload['rolled_or_pending_damage'] for e in by_target[ENEMY]] == [3, 4]
