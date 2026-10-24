"""Shared harm semantics reach real table consent, commit, reload and replay."""
import pytest

from combat import ext, factory_compiler
from combat.area_recipients import scoped_area
from combat.effect_harm import classify_effect
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.typed_reactions import _incoming_is_adverse
from tests.test_area_shapes import _Actor
from tests.test_lock_choices import install
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, PROJECTS, table_fight
from tests.h1_support import ROOT

COUNTER = 'test:area-counter'
FIELD = 'TAL_DEATH_WITHERING_FIELD'
BLAST = 'test:area-blast'


def counter_bundle(monkeypatch, reactors):
    original = factory_compiler.compile_character
    def compile_with_counter(*args, **kwargs):
        bundle = original(*args, **kwargs)
        if kwargs['actor_id'] in reactors:
            bundle['typed_reactions'].append({
                'feature_id': COUNTER, 'name': 'Counter the incoming technique',
                'block': 'generic', 'kind': 'technique_targets', 'range_ft': 60, 'ask': True,
                'costs': [['resource:core.qi', 1]],
                'effects': [{'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'attacker'}]})
        return bundle
    monkeypatch.setattr(factory_compiler, 'compile_character', compile_with_counter)


@pytest.mark.parametrize('manual', [True, False], ids=['manual-ask-me', 'automatic-actor'])
@pytest.mark.parametrize('payload', ['withering-field', 'blast', 'bare-attack'])
def test_enemy_harmful_area_counter_survives_table_commit_reload_replay(tmp_path, monkeypatch, manual, payload):
    counter_bundle(monkeypatch, {RIGHT})
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(PROJECTS['right'], {'mode': 'ask'}, {COUNTER})
    source = FIELD if payload == 'withering-field' else BLAST
    if payload != 'withering-field':
        def compile_area(info):
            if info['actor_id'] != LEFT:
                return []
            attack = {'type': 'attack', 'attack_kind': 'cultivation_ranged', 'count': 1,
                      'on_hit': [{'type': 'destructive_blast_damage'}] if payload == 'blast' else [],
                      'on_miss': []}
            return [ActionDefinition(source_definition_id=source, display_name='Practice destructive burst',
                owner_id=LEFT, economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='SELF', radius_ft=15,
                parameters={'typed': {'numbers': {**info['numbers'], 'attack_bonus': 99},
                    'area': {'shape': 'sphere', 'size_ft': 15, 'centered_on_self': True}, 'effects': [attack]}})]
        install(monkeypatch, 'compile_actions', compile_area)
    combat, table, mid = table_fight(tmp_path, [FIELD] if payload == 'withering-field' else [], ally_talents=[],
        control_modes={LEFT: 'MANUAL', ALLY: 'MANUAL', RIGHT: 'MANUAL' if manual else 'LOCAL_AUTO'})
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    state = table.state(mid)
    group = next(g for g in state['menu']['actions'] if source in g['source_definition_id'])
    from tests.test_friendly_fire_area_table import _commit_area_action
    result, option = _commit_area_action(table, mid, group['label'],
                                         {'x': 4, 'y': 4} if payload == 'withering-field' else None)
    if manual:
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert prompt['context']['reactor_id'] == RIGHT
        assert COUNTER in prompt['context']['reaction_source_id']
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        # Reopen the table before answering the player's actual pending decision.
        from combat.tabletop_service import TabletopService
        table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        state = table.state(mid)
        result = table.act(mid, option['candidate_id'], state['menu']['decision_id'], state['menu']['state_version'],
            state['last_sequence'], [{**prompt['context'], 'selection': 'USE'}])
    assert result['status'] == 'COMMITTED', result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    counters = [e for e in loaded.engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == COUNTER]
    assert [e.actor_id for e in counters] == [RIGHT]
    defender = loaded.engine.state.actors[RIGHT]
    assert not defender.reaction_available
    assert defender.resources['resource:core.qi'] == before['actors'][RIGHT]['resources']['resource:core.qi'] - 1
    if payload == 'withering-field':
        from combat.zones import typed_zones
        fields = list(typed_zones(loaded.engine))
        assert len(fields) == 1 and fields[0].trigger_profile['triggers']
    else:
        attacks = [e for e in loaded.engine.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == source]
        assert len(attacks) == 1 and set(attacks[0].target_ids) == {RIGHT}
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_registered_semantics_zone_scopes_and_unknown_enemy_fallback(monkeypatch):
    ext.effects()
    for kind, harmful in [('practice_harm', True), ('practice_benefit', False)]:
        monkeypatch.setitem(ext.effects(), kind, None)
        monkeypatch.setitem(ext._EFFECT_HARM, kind, None)
        ext.effect(kind, harmful=harmful)(lambda ctx, row: None)
        assert ext.effect_harm(kind) is harmful
    # Registry metadata is general: these names do not occur in the classifier.
    for kind in ('practice_harm', 'destructive_blast_damage', 'figment_premise'):
        assert classify_effect({'type': kind}) is True
        area = scoped_area({'shape': 'sphere', 'size_ft': 15}, [{'type': kind}])
        assert area['recipients'] == 'hostile' and area['exclude_self']
    user, ally, enemy = _Actor('user', 'a', 3, 4), _Actor('ally', 'a', 3, 5), _Actor('enemy', 'b', 4, 4)
    harm = {'type': 'zone', 'applies_to': 'enemies_in_area', 'triggers': [
        {'effects': [{'type': 'save', 'applies_to': 'creatures_in_area', 'on_fail': [{'type': 'practice_harm'}]}]}]}
    typed = {'area': {'shape': 'sphere', 'size_ft': 15}, 'effects': [harm, {'type': 'practice_benefit'}]}
    assert scoped_area(typed['area'], typed['effects'])['recipients'] == 'all'
    assert _incoming_is_adverse(user, enemy, typed)
    assert not _incoming_is_adverse(user, ally, typed)
    assert not _incoming_is_adverse(user, user, typed)
    # Zone trigger membership also bounds a child's broader printed scope.
    harm.pop('applies_to')
    harm['triggers'][0]['who'] = 'hostile'
    assert _incoming_is_adverse(user, enemy, typed)
    assert not _incoming_is_adverse(user, ally, typed)
    # Unknown enemy payloads retain the old conservative adverse fallback,
    # while explicitly helpful leaves and usage marks never open a counter.
    for unknown in ({'type': 'unclassified_future_effect'}, {'type': 'zone'}):
        typed['effects'] = [unknown]
        assert _incoming_is_adverse(user, enemy, typed)
        assert not _incoming_is_adverse(user, ally, typed)
    opaque_save = {'type': 'save', 'on_fail': [{'type': 'zone'}]}
    assert classify_effect(opaque_save) is True
    policy = scoped_area({'shape': 'sphere', 'size_ft': 15}, [opaque_save])
    assert policy['recipients'] == 'hostile' and policy['exclude_self']
    for benefit in ({'type': 'practice_benefit'}, {'type': 'mark', 'once_per_creature': True},
                    {'type': 'practice_harm', 'stance': 'helpful'}):
        typed['effects'] = [benefit]
        assert not _incoming_is_adverse(user, enemy, typed)
    # An attack's own roll is adverse even if its rider is a known benefit.
    typed['effects'] = [{'type': 'attack', 'on_hit': [{'type': 'practice_benefit'}]}]
    assert _incoming_is_adverse(user, enemy, typed)
    assert not _incoming_is_adverse(user, ally, typed)


def test_area_harm_reader_keeps_unresolved_pb_penalties_and_pb_benefits_distinct():
    from combat.area_recipients import _harmful

    penalty = {'type': 'attack_modifier', 'applies_to': 'attacker', 'flat': 0, 'formula': 'pb'}
    benefit = {'type': 'ac_bonus', 'applies_to': 'target', 'flat': 0, 'formula': 'pb'}
    assert _harmful(penalty), 'an unresolved executable attack penalty was admitted as harmless'
    assert not _harmful(benefit), 'a positive Proficiency Bonus to AC was classified as harm'


def test_area_harm_reader_bounds_an_unresolved_amount_instead_of_reading_one_value():
    """A shared consumer with no formula context must bound the amount, not invent its sign.

    ``half_pb`` floors to zero at the invented PB = 1 while execution reduces an attack at PB 2,
    and ``pb`` with a -2 offset reads as a penalty there while execution grants an attack bonus at
    PB 3. An ability modifier has no rule-fixed sign at all, and ``key_ability_modifier`` resolves
    ``key_mod`` -- so a benefit with that context in hand must not be classified as harm.
    """
    from combat.area_recipients import _harmful

    for effect in ({'type': 'attack_modifier', 'applies_to': 'attacker', 'flat': 0, 'formula': 'half_pb'},
                   {'type': 'attack_modifier', 'applies_to': 'attacker', 'flat': -2, 'formula': 'pb'},
                   {'type': 'attack_modifier', 'applies_to': 'attacker', 'flat': 0, 'formula': 'con'},
                   {'type': 'save_modifier', 'applies_to': 'target', 'flat': 0, 'formula': 'attack_ability_modifier'}):
        assert _harmful(effect), f'an unresolved amount was read as harmless: {effect}'
    # The positive benefit controls: a bound that no level can push below zero, and a key modifier
    # supplied under the name execution actually reads.
    assert not _harmful({'type': 'ac_bonus', 'applies_to': 'target', 'flat': 0, 'formula': 'pb'}), \
        'a positive Proficiency Bonus to AC was classified as harm'
    assert not _harmful({'type': 'ac_bonus', 'applies_to': 'target', 'flat': 0, 'formula': 'pb+2'}), \
        'a PB plus a positive offset can never be an AC penalty'
    assert _harmful({'type': 'ac_bonus', 'applies_to': 'target', 'flat': 0, 'formula': 'pb-2'}), \
        'a PB minus a larger offset can be an AC penalty'
    supplied = {'type': 'save_modifier', 'applies_to': 'target', 'flat': 0, 'formula': 'key_ability_modifier'}
    from combat.effect_harm import classify_effect
    assert classify_effect(supplied, numbers={'key_mod': 3}) is False, \
        'a positive key ability modifier to a save was classified as harm'
    assert classify_effect(supplied) is True, \
        'an unresolved key ability modifier was classified as a benefit'


def test_white_sun_benefit_recipients_never_offer_the_counter(tmp_path, monkeypatch):
    from combat.ext import cai_clan as cai
    from tests.test_cai_clan_subpath import _fight, _use
    counter_bundle(monkeypatch, {LEFT, ALLY, RIGHT})
    for name in ('left', 'ally', 'right'):
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(PROJECTS[name], {'mode': 'ask'}, {COUNTER})
    combat, table, mid = _fight(tmp_path)
    _use(table, mid, 'Empyreal Layer', [LEFT, ALLY])
    from tests.test_friendly_fire_area_table import _commit_area_action
    result, option = _commit_area_action(table, mid, 'White Sun Judgment', {'x': 4, 'y': 4})
    prompts, answers = [], []
    for _ in range(8):
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        prompts.append(prompt)
        answers.append({**prompt['context'], 'selection': 'USE'})
        state = table.state(mid)
        result = table.act(mid, option['candidate_id'], state['menu']['decision_id'],
                           state['menu']['state_version'], state['last_sequence'], answers)
    assert result['status'] == 'COMMITTED', result
    assert [p['context']['reactor_id'] for p in prompts] == [RIGHT]
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    counters = [e.actor_id for e in loaded.engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == COUNTER]
    assert counters == [RIGHT]
    protection = [e for e in loaded.engine.events if e.event_type == 'DAMAGE_ROLLED'
                  and e.payload.get('reason') == 'White Sun Judgment protects invested allies']
    assert len(protection) == 1 and set(protection[0].target_ids) == {LEFT, ALLY}
    for who in (LEFT, ALLY):
        actor = loaded.engine.state.actors[who]
        assert actor.reaction_available and actor.temporary_hp >= protection[0].payload['total']
        assert not any(e.event_type == 'DAMAGE_COMMITTED' and cai.FLARE in (e.source_definition_id or '')
                       and who in e.target_ids for e in loaded.engine.events)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('who,recipients,expected', [
    ('hostile', 'hostile', {'enemy'}), ('ally', 'allies', {'ally'}),
    ('any', 'all', {'user', 'ally', 'enemy'}),
])
@pytest.mark.parametrize('payload_key', ['triggers', 'inside'])
def test_zone_trigger_scope_is_shared_by_membership_and_reactions(who, recipients, expected, payload_key):
    user, ally, enemy = _Actor('user', 'a', 3, 4), _Actor('ally', 'a', 3, 5), _Actor('enemy', 'b', 4, 4)
    payload = {'who': who, 'effects': [{'type': 'damage', 'flat': 4, 'applies_to': 'target'}]} \
        if payload_key == 'triggers' else {'who': who, 'harmful': True, 'name': 'Practice hazardous surroundings'}
    effects = [{'type': 'zone', payload_key: [payload]}]
    if who == 'any':
        effects[0]['recipient_text'] = 'Each creature in the area is affected.'
    area = scoped_area({'shape': 'sphere', 'size_ft': 15}, effects)
    assert area['recipients'] == recipients
    assert area['exclude_self'] == (who != 'any')
    typed = {'area': area, 'effects': effects}
    assert {a.entity_id for a in (user, ally, enemy) if _incoming_is_adverse(user, a, typed)} == expected
