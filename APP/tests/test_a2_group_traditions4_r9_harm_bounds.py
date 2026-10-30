"""A2GTRA4r9 fix round: the shared harm reader bounds an unresolved amount instead of guessing its sign.

Review finding 1 (r8): ``effect_harm`` substituted PB/CL = 1 and called that sign-preserving. It is not.
``half_pb`` floors to zero at the invented value while execution reduces the attack, ``pb`` with
``flat: -2`` reads as a penalty there while execution grants an attack bonus at PB 3, an ability
modifier has no rule-fixed sign at all, and ``key_ability_modifier`` was checked against ``key``
while execution consumes ``key_mod``.

The two cases are witnessed where each one actually reaches the player, because the shared contract
is read with and without a row's own numbers depending on the seam:

* the penalties -- ``typed_reactions._answers_a_hostile_effect``, the hunt-74 gate that closes a
  reaction written to answer a hostile effect when a *heal* arrives instead. It reads a row through
  the contract with no formula context at all, so a bystander row whose penalty is written in the
  engine's own amount vocabulary must be classified from that row alone.
* the benefit -- the Welcoming Ground ``row_allowed`` seam, which does pass the row's numbers and so
  must resolve ``key_mod`` under the name execution reads.

Every row is declared in the bundle's own ``typed_reactions``, so gate2_engine rebuilds it on every
load and each case survives a cold reload.
"""
import copy

import pytest

from combat.gate5_service import CombatService
from test_riders_c8 import ROOT, ME, MK_ALL, SPIRITUAL_SENSE, MIND_SPIKE, bundle
from test_a2_group_traditions4 import ENEMY, ALLY, SECOND, act, advance, reload
from test_a2_group_traditions4_fix import held, prepare, welcome_the_spirit

WELCOMED = 'condition:typed.welcoming_ground'


def prepare_ally(tmp_path, *, reactions=()):
    """``prepare``'s table with the bystander row on ALLY and a healing technique ME can aim at it.

    ALLY is on ME's own team (team:a) and the healing row carries no harm, so
    ``_incoming_is_adverse`` reads the incoming ability as a benefit -- the printed hunt-74 case. The
    hostile arm uses the spirit's own Mind Spike instead, which is adverse by team, so the same row
    is offered there and the heal arm measures the gate rather than a row that never fires.
    """
    service = CombatService(ROOT, tmp_path)
    me = bundle([*MK_ALL, SPIRITUAL_SENSE], dc=40, resonance=100)
    enemy = bundle([MIND_SPIKE], actor_id=ENEMY, cl=5, dc=40)
    ally = bundle([MIND_SPIKE], actor_id=ALLY)
    partner = bundle([MIND_SPIKE], actor_id=SECOND, cl=5)
    for doc in (me, enemy, ally, partner):
        doc['actor_template']['maximum_hp'] = 1000
    mending = copy.deepcopy(next(a for a in me['action_catalog'] if a['display_name'] == 'Mind Spike'))
    mending.update(source_definition_id=mending['source_definition_id'] + '.r9_mending',
                   display_name='Test mending', target_kind='ALLY_OR_SELF', range_ft=60, costs=[])
    mending['parameters']['typed']['effects'] = [{'type': 'healing', 'flat': 5, 'applies_to': 'target'}]
    me['action_catalog'].append(mending)
    me['actor_template']['action_ids'].append(mending['source_definition_id'])
    if reactions:
        ally['typed_reactions'] = list(reactions)
    session = service.persistence.create_match(
        match_seed='A2GTRA4R9', maximum_rounds=30, typed_bundles=(me, enemy, ally, partner),
        roster_setup={'primary_actor_ids': [ME, ENEMY, ALLY, SECOND],
                      'team_by_actor': {ME: 'team:a', ALLY: 'team:a', ENEMY: 'team:b', SECOND: 'team:b'},
                      'starting_positions': {ME: {'x': 6, 'y': 6}, ALLY: {'x': 7, 'y': 8},
                                             ENEMY: {'x': 11, 'y': 6}, SECOND: {'x': 9, 'y': 7}}})
    metadata = {'participant_control_modes': {ME: 'MANUAL', ENEMY: 'MANUAL', ALLY: 'MANUAL', SECOND: 'MANUAL'}}
    return service, session, metadata


def _target_row(feature_id, effect, numbers=None, ability_mods=None):
    """A ``technique_targets`` row: the reactor's answer to an ability aimed at it."""
    return {'feature_id': feature_id, 'block': 'generic', 'kind': 'technique_targets', 'costs': [],
            'range_ft': 60, 'melee': False, 'ranged': True, 'effects': [effect],
            **({'numbers': numbers} if numbers else {}), **({'ability_mods': ability_mods} if ability_mods else {})}


# The review's examples. Each carries the numbers and ability modifiers execution resolves, so each
# lays a real penalty on the attacker -- and each is one the context-free reader could only settle by
# inventing a value for the input it had not been given.
PENALTIES = [
    pytest.param(_target_row('a2gtra4r9.half_pb', {'type': 'attack_modifier', 'applies_to': 'attacker',
                                                    'flat': 0, 'formula': 'half_pb'}, {'pb': 2}),
                 id='half_pb_floors_at_the_invented_value'),
    pytest.param(_target_row('a2gtra4r9.offset', {'type': 'attack_modifier', 'applies_to': 'attacker',
                                                   'flat': -2, 'formula': 'pb'}, {'pb': 3}),
                 id='pb_with_an_offset_crossing_zero'),
    pytest.param(_target_row('a2gtra4r9.ability', {'type': 'attack_modifier', 'applies_to': 'attacker',
                                                     'flat': 0, 'formula': 'con'},
                             {'pb': 2}, {'con': 4}), id='missing_ability_input'),
]


@pytest.mark.parametrize('row', PENALTIES)
def test_a_penalty_the_harm_reader_cannot_resolve_is_not_offered_to_answer_a_heal(tmp_path, row):
    """A row written as a penalty must keep its meaning when the reader has no formula context.

    The hostile arm proves the row is real: the spirit's Mind Spike on ALLY is adverse by team, so
    the row is offered, resolves, and lays the penalty it declares. The heal arm is the same row
    meeting a benefit, and the reactor's unspent Reaction is what it measures. Without the fix every
    row here read as harmless -- half_pb resolved to zero at the invented PB 1, ``pb`` with a -2
    offset read as -1, and ``con`` resolved to zero because an absent name is not a zero -- so the
    gate read each one as a benefit the reactor may use on a heal.
    """
    service, session, metadata = prepare_ally(tmp_path / 'hostile', reactions=(row,))
    advance(service, session, metadata, ME)
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ENEMY)
    events, _, _ = act(service, session, metadata, 'Mind Spike', ALLY)
    resolved = [e for e in events if e.event_type == 'REACTION_RESOLVED' and e.actor_id == ALLY]
    assert resolved, 'the row never answered a hostile effect, so the heal arm would measure nothing'
    assert int(resolved[0].payload.get('attack_penalty') or 0) > 0, (
        'the hostile row laid no penalty on the attacker, so it is not the penalty this case is about')
    assert not session.engine.state.actors[ALLY].reaction_available, 'the control never spent a Reaction'

    service, session, metadata = prepare_ally(tmp_path / 'heal', reactions=(row,))
    assert session.engine.state.actors[ALLY].reaction_available
    advance(service, session, metadata, ME)
    events, _, _ = act(service, session, metadata, 'Test mending', ALLY)
    assert [e for e in events if e.event_type == 'REACTION_RESOLVED' and e.actor_id == ALLY] == [], (
        'a reaction written as a penalty was offered against a benefit')
    assert session.engine.state.actors[ALLY].reaction_available, (
        'a reaction written as a penalty answered a heal and spent the reactor\'s Reaction')
    session = reload(service, session)
    assert session.engine.state.actors[ALLY].reaction_available, (
        'the closed reaction still spent the reactor\'s Reaction')


KEY_MOD_BENEFIT = {'feature_id': 'a2gtra4r9.key_mod_benefit', 'block': 'generic', 'kind': 'ally_attacked',
                   'costs': [], 'numbers': {'key_mod': 2}, 'range_ft': 30, 'melee': True, 'ranged': True,
                   'effects': [{'type': 'ac_bonus', 'applies_to': 'target', 'duration': 'triggering_attack',
                                'flat': 3, 'formula': 'key_ability_modifier'}]}


def _attacks_the_spirits_ally(service, session, metadata):
    act(service, session, metadata, 'End turn')
    advance(service, session, metadata, ME)
    events, _, _ = act(service, session, metadata, 'Test hostile strike', SECOND)
    assert any(e.event_type == 'ATTACK_ROLLED' for e in events), 'the ally was never attacked'
    return [e for e in events if e.event_type == 'REACTION_RESOLVED' and e.actor_id == ENEMY]


def test_a_benefit_resolving_key_mod_under_the_execution_name_is_not_closed(tmp_path):
    """The other side of the same reading: ``key_ability_modifier`` resolves ``key_mod``.

    Execution reads the key ability modifier out of ``numbers`` under that name, while the old reader
    asked whether a ``key`` had been supplied and so classified this plainly helpful row as hostile.
    The control proves the row is a live reaction before the under-Ground run measures the ban.
    """
    service, session, metadata = prepare(tmp_path / 'control', dc=40, reactions=(KEY_MOD_BENEFIT,))
    assert _attacks_the_spirits_ally(service, session, metadata), (
        'the control never fired the row, so this measures nothing')

    service, session, metadata = prepare(tmp_path / 'grounded', dc=40, reactions=(KEY_MOD_BENEFIT,))
    session = welcome_the_spirit(service, session, metadata)
    assert held(session.engine.state.actors[ENEMY], WELCOMED)
    assert _attacks_the_spirits_ally(service, session, metadata), (
        'the ban closed a beneficial reaction')
    session = reload(service, session)
    assert held(session.engine.state.actors[ENEMY], WELCOMED)