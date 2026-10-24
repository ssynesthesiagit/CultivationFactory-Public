"""Round23 keeps native strike reach and readied physical delivery together."""
import pytest

from combat.factory_compiler import compile_character
from combat.typed_reactions import triggered_context
from combat.ext.equipment_hands import require_attack_hands
from combat.ext.weapon_hits import weapon_identity
from tests.test_riders_c2 import _sheet, _fight, ME, WS


@pytest.mark.parametrize('extra_staff', [False, True])
def test_triggered_context_combines_selected_weapon_reach_identity_and_hands(extra_staff):
    sheet = _sheet([WS])
    if extra_staff:
        sheet['equipment'][0]['starting_kit']['items'].append({'item_id': 'tianxia.mortal.weapon.gun'})
    engine = _fight(compile_character(sheet, actor_id=ME))
    actor = engine.state.actors[ME]
    source = next(key for key, action in engine.action_catalog.items()
                  if action.owner_id == ME and key.endswith('.weapon.fu'))
    # A generic fixture profile makes lost native reach visible independently
    # of any ability-specific reach provider or opportunity-only extension.
    engine.action_catalog[source] = engine.action_catalog[source].model_copy(update={'reach_ft': 10})
    before = engine.state.model_dump(mode='json')
    attack = {'type': 'attack', 'attack_kind': 'weapon', 'strike_with': 'weapon', 'count': 1}
    context = triggered_context(engine, actor, None,
        {'feature_id': 'test:lock23.counter', 'effects': [attack]})
    assert context.action.reach_ft == 10
    assert context.typed['weapon_source_id'] == weapon_identity(context) == source
    assert context.typed['reaction_attack'] is True
    assert require_attack_hands(context, None, attack) is True
    assert engine.state.model_dump(mode='json') == before


def test_unarmed_packet_does_not_require_its_parent_maneuvers_stowed_weapon():
    from combat.ext.hand_occupancy import GRIP
    sheet = _sheet([WS])
    engine = _fight(compile_character(sheet, actor_id=ME))
    actor = engine.state.actors[ME]
    action = next(action for action in engine.action_catalog.values()
                  if action.owner_id == ME and action.source_definition_id.endswith('.weapon.fu'))
    engine._apply_condition(actor, GRIP, 'test:stowed', ME, expires_on='UNTIL_REMOVED',
        data={'weapon': action.source_definition_id, 'held': 0})
    from combat.typed_executor import Context
    typed = {**action.parameters['typed'], 'unarmed_option': True}
    context = Context(engine, actor, action, None, typed, [], None)
    assert require_attack_hands(context, None, {'type': 'attack', 'attack_kind': 'unarmed'}) is None
    assert require_attack_hands(context, None, {'type': 'attack', 'attack_kind': 'weapon'}) is False
