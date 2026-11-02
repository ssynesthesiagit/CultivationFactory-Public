"""Printed tradition effects through service choice transport and persisted intents."""
import pytest

from combat.gate5_service import CombatService, _ReactionRequired
from combat.gate2_runtime_models import ActionIntent, ReactionDecision, CandidateKind
from combat import flight, posture, typed_executor as te
from combat.ext import life_state, thrum_of_the_grave as grave
from test_riders_c8 import ROOT, ME, ALLY, MIND_SPIKE, SD_ALL, TG_ALL, YC, bundle, STAFF

ENEMY = 'actor:factory.a2gtra5_enemy'
FOE2 = 'actor:factory.a2gtra5_foe2'
SV = 'tianxia.tradition.spirit.sovereign_will.feature.'
YOKAI_IDS = [MIND_SPIKE] + [YC + name for name in ('yokai_mask', 'unmasking', 'true_yokai_form', 'yokai_lord')]


def prepared(ids, actor_id=ME, **kwargs):
    doc = bundle(ids, actor_id=actor_id, **kwargs)
    doc['actor_template']['maximum_hp'] = 600
    for name, effects in {
        'Test fall prone': [{'type': 'condition', 'condition': 'prone', 'applies_to': 'self', 'duration': {'kind': 'until_removed'}}],
        'Test lose consciousness': [{'type': 'condition', 'condition': 'unconscious', 'applies_to': 'self', 'duration': {'kind': 'until_removed'}}],
        'Test save aid': [{'type': 'save_bonus', 'amount': 100, 'abilities': ['DEX'], 'applies_to': 'self', 'duration': {'kind': 'until_removed'}}],
        'Test suppress flight': [{'type': 'condition', 'condition': 'test_flight_suppressed', 'applies_to': 'self', 'condition_data': {'flight_disabled': True}, 'duration': {'kind': 'until_removed'}}],
        'Test Dexterity save': [{'type': 'save', 'ability': 'dex', 'applies_to': 'self', 'on_fail': [], 'on_success': []}],
        'Test psychic object': [{'type': 'object_damage', 'flat': 30, 'damage_types': ['psychic']}],
        'Test enable flight': [{'type': 'condition', 'condition': 'test_flight', 'applies_to': 'self', 'condition_data': {'fly_speed_ft': 40, 'flight_hover': True}, 'duration': {'kind': 'until_removed'}}],
        'Test mortal wound': [{'type': 'damage', 'flat': 605, 'damage_types': ['force'], 'applies_to': 'self'}],
    }.items():
        key = 'test:a2gtra5.' + actor_id.rsplit('.', 1)[-1] + '.' + name.replace(' ', '_')
        doc['action_catalog'].append({'source_definition_id': key, 'display_name': name, 'owner_id': actor_id,
            'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'OBJECT' if name == 'Test psychic object' else 'SELF', 'range_ft': 60 if name == 'Test psychic object' else None,
            'parameters': {'typed': {'effects': effects, 'numbers': {'cl': 18, 'pb': kwargs.get('pb', 6), 'save_dc': kwargs.get('dc', 40), 'key_mod': 4},
                          'duration': {'kind': 'instant'}, 'riders': []}}})
        doc['actor_template']['action_ids'].append(key)
    return doc


class Table:
    def __init__(self, tmp_path, ids, *, enemy_ids=(MIND_SPIKE,), pb=6, dc=40, choose=None, second_foe=None, second_foe_at=(8, 6)):
        self.service = CombatService(ROOT, tmp_path)
        bundles = [prepared(ids, pb=pb, dc=dc), prepared(enemy_ids, ENEMY, dc=5, items=(STAFF,)), prepared([MIND_SPIKE], ALLY)]
        teams = {ME: 'team:a', ALLY: 'team:a', ENEMY: 'team:b'}
        seats = {ME: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, ENEMY: {'x': 6, 'y': 6}}
        roster = [ME, ENEMY, ALLY]
        if second_foe is not None:
            # A second hostile seat: Choreography Strings are only ever placed on
            # creatures that failed a Spirit Awakening save, and Threaded Step
            # refuses same-team subjects, so a hostile is the legal second bearer.
            bundles.append(prepared([MIND_SPIKE], second_foe, dc=5))
            teams[second_foe] = 'team:b'
            seats[second_foe] = {'x': second_foe_at[0], 'y': second_foe_at[1]}
            roster.append(second_foe)
        self.session = self.service.persistence.create_match(match_seed='A2GTRA5', maximum_rounds=30,
            typed_bundles=tuple(bundles),
            roster_setup={'rules': {'zero_hp': 'dying_2024'}, 'primary_actor_ids': roster, 'team_by_actor': teams,
                'starting_positions': seats})
        self.metadata = {'participant_control_modes': {who: 'MANUAL' for who in roster}}
        self.choose = choose
        self.choice_prompts = []
        self.advance(ME)

    @property
    def engine(self):
        return self.session.engine

    def actor(self, who=ME):
        return self.engine.state.actors[who]

    def reload(self):
        before = self.engine.state.model_dump(mode='json')
        self.session = self.service.persistence.load_match(self.session.match_id)
        assert self.engine.state.model_dump(mode='json') == before
        assert self.session.verify()['status'] == 'PASS'

    def advance(self, who):
        for _ in range(20):
            if self.engine.state.current_actor_id == who:
                return
            self.act('End turn')
        pytest.fail('turn did not advance')

    def act(self, name=None, target=None, *, predicate=None):
        candidates = self.engine.legal_candidates()
        matches = [c for c in candidates if (name is None or (name == 'End turn' and c.kind == CandidateKind.END_TURN) or c.display_name == name or c.display_name.startswith(name + ' at ') or c.display_name.startswith(name + ' to '))
                         and (target is None or target in c.target_ids) and (predicate is None or predicate(c))]
        assert matches, (name, [(c.display_name, c.target_ids) for c in candidates],
                         [(a.display_name, a.target_kind) for a in self.engine.action_catalog.values() if name and name in a.display_name])
        candidate = matches[0]
        intent = ActionIntent(intent_id=f'a2gtra5-{candidate.state_version}', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version,
            actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination)
        decisions = []
        for _ in range(40):
            try:
                preview = self.service._run_preview(self.session, self.metadata, intent, tuple(decisions))
                break
            except _ReactionRequired as pause:
                context = pause.context
                spec = context.extension_choice
                if spec is not None:
                    trigger = context.choice_trigger or {}
                    self.choice_prompts.append((trigger.get('name', ''), trigger.get('prompt', '')))
                chosen = self.choose(context) if self.choose else None
                if chosen is None:
                    chosen = () if spec is None or spec.allow_decline else spec.option_ids[:spec.minimum_selections]
                decisions.append(ReactionDecision(checkpoint=context.checkpoint, reactor_id=context.reactor_id,
                    reaction_source_id=context.reaction_source_id, selection='USE' if chosen else 'DECLINE', option_ids=chosen))
        else:
            pytest.fail('too many choices')
        before = len(self.engine.events)
        self.session.mechanical.execute_intent(ActionIntent.model_validate(preview['intent']))
        events = self.engine.events[before:]
        assert [e.model_dump(mode='json') for e in events] == preview['events']
        return events

    def move(self, x, y, z=0):
        return self.act(predicate=lambda c: c.kind == CandidateKind.MOVE and c.destination is not None
            and (c.destination.x, c.destination.y, c.destination.z) == (x, y, z))

    def stand(self):
        return self.act(predicate=lambda c: c.display_name.startswith('Stand up'))


def select_strings(context):
    key = context.reaction_source_id
    if key.endswith('soulstring.place'):
        return ('place',)
    if key.endswith('soulstring.command'):
        return ('drop',)
    if key.endswith('soulstring.rhythm'):
        return ('heavy_rise', 'still')
    return None


@pytest.mark.parametrize('command', ['Drop', 'Kneel'])
def test_commanding_voice_next_turn_drop_and_kneel(tmp_path, command):
    table = Table(tmp_path, [MIND_SPIKE, SV + 'commanding_voice'])
    table.act('Commanding Voice: ' + command, ENEMY)
    table.reload()
    table.act('End turn')
    table.advance(ENEMY)
    table.reload()
    if command == 'Drop':
        assert any('Commanding Voice' in prompt and 'Commanding Voice: Drop' in prompt and 'no extra cost' in prompt
                   for _name, prompt in table.choice_prompts)
        rows = [c for c in table.actor(ENEMY).conditions.values() if c.condition_id == 'condition:typed.dropped_item']
        assert len(rows) == 1 and rows[0].data['dropped_at'] == table.actor(ENEMY).position.model_dump(mode='json')
        assert not any(c.source_definition_id == rows[0].data.get('disables_action') for c in table.engine.legal_candidates())
    else:
        assert any(c.condition_id.endswith('.prone') for c in table.actor(ENEMY).conditions.values())
        assert not any(c.display_name.startswith('Stand up') for c in table.engine.legal_candidates())
        table.act('End turn')
        table.advance(ENEMY)
        table.reload()
        assert not any(c.condition_id == 'condition:typed.obeying_command' for c in table.actor(ENEMY).conditions.values())
        assert posture.standing_cost(table.engine, table.actor(ENEMY)) is not None or not posture.prone_conditions(table.actor(ENEMY))


def test_borrowed_limbs_drops_exact_held_object_after_reload(tmp_path):
    table = Table(tmp_path, SD_ALL, choose=select_strings)
    for _ in range(2):
        table.act('Mind Spike', ENEMY)
        table.act('End turn')
        table.advance(ME)
    table.act('Dance of Borrowed Limbs', ENEMY)
    table.reload()
    table.act('End turn')
    table.advance(ENEMY)
    table.reload()
    assert any('Dance of Borrowed Limbs' in prompt and 'Dance of Borrowed Limbs: Drop' in prompt and 'no extra cost' in prompt
               for _name, prompt in table.choice_prompts)
    drops = [c for c in table.actor(ENEMY).conditions.values() if c.condition_id == 'condition:typed.dropped_item']
    assert len(drops) == 1 and drops[0].source_definition_id.endswith('dance_of_borrowed_limbs')


def test_stolen_rhythm_prices_standing_and_elevation_after_reload(tmp_path):
    table = Table(tmp_path, SD_ALL, enemy_ids=YOKAI_IDS, choose=select_strings)
    table.act('End turn')
    table.advance(ENEMY)
    table.act('Yokai Lineage: Kitsune')
    table.act('True Yokai Form')
    table.act('End turn')
    table.advance(ME)
    table.act('Mind Spike', ENEMY)
    table.act('Stolen Rhythm', ENEMY)
    table.reload()
    table.act('End turn')
    table.advance(ENEMY)
    table.act('Test fall prone')
    table.reload()
    before = table.actor(ENEMY).movement_remaining_ft
    events = table.stand()
    assert before - table.actor(ENEMY).movement_remaining_ft == 20
    assert any(e.event_type == 'STOOD_UP' for e in events)
    table.reload()
    before = table.actor(ENEMY).movement_remaining_ft
    table.move(6, 6, 1)
    assert before - table.actor(ENEMY).movement_remaining_ft == 10
    table.reload()


@pytest.mark.parametrize('who,cost', [(ME, 5), (ALLY, 5), (ENEMY, 15)])
def test_theater_standing_benefits_allies_and_not_enemies(tmp_path, who, cost):
    table = Table(tmp_path, SD_ALL)
    table.act('Theater of Strings')
    if who != ME:
        table.act('End turn')
        table.advance(who)
    table.act('Test fall prone')
    table.reload()
    before = table.actor(who).movement_remaining_ft
    table.stand()
    assert before - table.actor(who).movement_remaining_ft == cost
    table.reload()


@pytest.mark.parametrize('trigger,altitude,should_trigger', [
    ('prone', 1, True), ('prone', 7, False), ('stand', 1, True), ('stand', 7, False),
])
def test_theater_choreography_triggers_use_zone_volume_after_reload(tmp_path, trigger, altitude, should_trigger):
    """Only a creature actually inside the 30-foot field is moved 5 feet, once per round.

    Every position change below is a committed intent played through CombatService
    and reloaded from disk, so the journal -- not the live engine object -- is what
    puts the bearer at its altitude. Position units are 5-foot cells, so altitude 1
    sits 5 feet up (inside the field) and altitude 7 sits 35 feet up (outside it).
    """
    from combat import zones
    from combat.spatial_areas import zone_contains

    steps = []

    def choose(context):
        # Theater of Strings moves another bearer once per round. Decline that move
        # on the fall so the round is still open when the named trigger follows.
        if context.reaction_source_id.endswith('soulstring.theater_move'):
            steps.append(context)
            return () if len(steps) == 1 else None
        return select_strings(context)

    table = Table(tmp_path, SD_ALL, choose=choose, second_foe=FOE2)
    # Both bearers must be hostiles that failed a save: Threaded Step never places a
    # String on the dancer's own team, so an ally could not supply the second bearer.
    table.act('Mind Spike', ENEMY)
    table.reload()
    table.act('End turn')
    table.advance(ENEMY)
    table.act('Test enable flight')
    table.move(7, 6, altitude)
    table.reload()
    table.act('End turn')
    table.advance(FOE2)
    table.reload()
    table.act('End turn')
    table.advance(ME)
    table.act('Mind Spike', FOE2)
    table.reload()
    table.act('End turn')
    table.advance(ENEMY)
    table.act('End turn')
    table.advance(FOE2)
    table.reload()
    table.act('End turn')
    table.advance(ME)
    table.act('Theater of Strings')
    table.reload()
    field = next(z for z in zones.typed_zones(table.engine) if z.owner_id == ME)
    assert zone_contains(table.engine, table.actor(ENEMY), field) is should_trigger
    table.act('End turn')
    table.advance(ENEMY)
    # The bearer acts once, and each case measures only its own trigger: the standing
    # case falls Prone and stands in this one turn, because a turn start stands a
    # Prone creature by itself. The prompt list is marked between the two.
    mark = len(table.choice_prompts)
    table.act('Test fall prone')
    if trigger == 'stand':
        mark = len(table.choice_prompts)
        table.stand()
    table.reload()
    prompted = any('Theater of Strings' in prompt and 'move another String bearer' in prompt
                   for _name, prompt in table.choice_prompts[mark:])
    assert prompted is should_trigger


@pytest.mark.parametrize('lineage,speed,hover', [('Kitsune', 40, True), ('Tengu', 50, False)])
def test_true_form_native_flight_survives_cold_reload(tmp_path, lineage, speed, hover):
    table = Table(tmp_path, YOKAI_IDS)
    table.act('Yokai Lineage: ' + lineage)
    table.act('True Yokai Form')
    table.reload()
    profile = flight.profile(table.engine, table.actor())
    assert (profile.speed_ft, profile.hover) == (speed, hover)
    table.move(3, 6, 1)
    table.reload()
    assert table.actor().position.z == 1


def test_tengu_mask_reduces_native_fall_without_changing_landing(tmp_path):
    table = Table(tmp_path, YOKAI_IDS, pb=2)
    table.act('Yokai Lineage: Tengu')
    table.act('True Yokai Form')
    table.move(3, 6, 6)
    table.reload()
    events = table.act('Test suppress flight')
    falls = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and ME in e.target_ids]
    assert falls and table.actor().position.z == 0
    assert any(e.payload.get('fall_distance_ft') == 30 for e in events)
    assert sum((e.payload or {}).get('hp_damage', 0) for e in falls) <= 6
    table.reload()


def test_grand_silk_offers_action_repeat_save_and_removes_only_its_hold(tmp_path):
    table = Table(tmp_path, YOKAI_IDS)
    table.act('Yokai Lineage: Jorogumo')
    table.act('True Yokai Form')
    table.act('End turn')
    table.advance(ME)
    table.act('Grand Silk', predicate=lambda c: c.destination is not None and c.destination.x == 6 and c.destination.y == 6)
    table.reload()
    table.act('End turn')
    table.advance(ENEMY)
    table.reload()
    assert any(c.condition_id == 'condition:typed.escape_option' and c.data.get('name') == 'Grand Silk'
               for c in table.actor(ENEMY).conditions.values())
    table.act('Test save aid')
    events = table.act('Test Dexterity save')
    roll = next(e.payload for e in events if e.event_type == 'SAVE_ROLLED')
    assert roll['modifier'] == table.actor(ENEMY).saving_throws['DEX']  # typed bonus changes DC, never double-applies natively
    table.act('Break free')
    table.reload()
    assert not any(c.condition_id.endswith('.restrained') for c in table.actor(ENEMY).conditions.values())


@pytest.mark.parametrize('who,expected', [(ALLY, 'ADVANTAGE'), (ENEMY, 'NORMAL')])
def test_grave_keeper_death_saves_use_live_ally_membership(tmp_path, who, expected):
    def choose(context):
        return ('keeper',) if context.reaction_source_id.endswith('thrum.memory') else None
    table = Table(tmp_path, TG_ALL, choose=choose)
    table.act('Call the Unquiet', predicate=lambda c: c.destination is not None and c.destination.x == 5 and c.destination.y == 7)
    table.reload()
    modes = life_state._modes(table.actor(who), table.engine)
    assert bool(modes) is (who == ALLY)
    table.act('End turn')
    table.advance(who)
    table.act('Test mortal wound')
    table.reload()
    assert table.actor(who).life_state == 'DYING'
    # Native boundaries roll a dying creature's save and pass its turn.
    # Advance real committed turns until that save, without forcing a turn slot.
    for _ in range(8):
        table.act('End turn')
        checks = [e for e in table.engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == who
                  and (e.payload or {}).get('skill') == 'Death Saving Throw']
        if checks:
            break
    table.reload()
    assert checks and checks[-1].payload['actor']['mode'] == expected


def test_gravebeat_ends_when_owner_becomes_unconscious(tmp_path):
    table = Table(tmp_path, TG_ALL)
    table.act('Gravebeat')
    table.reload()
    assert any(c.condition_id == grave.THRUMMING for c in table.actor().conditions.values())
    table.act('Test lose consciousness')
    table.reload()
    assert not any(c.condition_id == grave.THRUMMING for c in table.actor().conditions.values())


def test_knife_between_thoughts_blocks_reactions_only_against_its_owner(tmp_path):
    from combat.typed_reactions import reaction_permitted_against
    prefix = 'tianxia.tradition.spirit.unwritten_footprint.feature.'
    def choose(context):
        return ('strike',) if context.reaction_source_id.endswith('unwritten.between_thought') else None
    table = Table(tmp_path, [MIND_SPIKE, prefix + 'step_no_record_keeps', prefix + 'knife_between_thoughts'], choose=choose)
    table.act('Step No Record Keeps', ENEMY)
    table.act('Mind Spike', ENEMY)
    table.reload()
    assert any(c.condition_id == 'condition:typed.cannot_punish_the_unwritten' for c in table.actor(ENEMY).conditions.values())
    assert not reaction_permitted_against(table.engine, table.actor(ENEMY), table.actor(ME))
    assert reaction_permitted_against(table.engine, table.actor(ENEMY), table.actor(ALLY))


def test_ripple_before_space_and_translation_preserve_height_after_reload(tmp_path):
    ripple = 'tianxia.tradition.spirit.well_of_hours.feature.ripple_of_before'
    def choose(context):
        return ('record',) if context.reaction_source_id.endswith('well.before_space') else None
    table = Table(tmp_path, [*YOKAI_IDS, ripple], choose=choose)
    table.act('Yokai Lineage: Kitsune')
    table.act('True Yokai Form')
    table.move(3, 6, 4)
    table.act('End turn')
    table.advance(ME)
    table.move(5, 6, 4)
    table.reload()
    assert table.actor().turn_flags['c8_before_space'] == [3, 6, 4]
    before = dict(table.actor().resources)
    table.act('Echo of the Chosen Step')
    table.reload()
    assert (table.actor().position.x, table.actor().position.y, table.actor().position.z) == (3, 6, 4)
    assert table.actor().resources['resource:core.resonance'] == before['resource:core.resonance'] - 1
    assert table.actor().resources['resource:named.time_debt'] == before['resource:named.time_debt'] + 1


def test_unquiet_echo_resists_psychic_damage_through_object_service_action(tmp_path):
    table = Table(tmp_path, TG_ALL)
    table.act('Call the Unquiet', predicate=lambda c: c.destination is not None and c.destination.x == 5 and c.destination.y == 7)
    table.reload()
    echo = grave.echo_of(table.engine, table.actor())
    before, key = echo.current_hp, echo.object_id
    table.act('Test psychic object', key)
    table.reload()
    assert table.engine.state.objects[key].current_hp == before - 15


def test_grave_keeper_uses_three_dimensional_echo_distance(tmp_path):
    def choose(context):
        return ('keeper',) if context.reaction_source_id.endswith('thrum.memory') else None
    table = Table(tmp_path, TG_ALL, choose=choose)
    table.act('Call the Unquiet', predicate=lambda c: c.destination is not None and c.destination.x == 5 and c.destination.y == 7)
    table.reload()
    assert life_state._modes(table.actor(ALLY), table.engine)
    table.act('End turn')
    table.advance(ALLY)
    table.act('Test enable flight')
    table.move(4, 7, 5)
    table.reload()
    assert not life_state._modes(table.actor(ALLY), table.engine)
