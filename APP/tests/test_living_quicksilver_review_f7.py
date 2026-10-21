"""Refused Exchange Substance attempts are free, through table commit/reload."""
import pytest
from types import SimpleNamespace
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.typed_executor import condition_rules
from combat.ext.mgr_reserve_living_quicksilver_immortal_embryo_living_mercury_body import data
from tests.test_living_quicksilver_review_f6 import (
    add_hook, synthetic_actions, living_bodies, BLADE,
)
from tests.test_living_quicksilver_native import (
    setup, combat, engine, use, A, B, MASS, FEATURES, candidate, settle, turn,
)

SEAL = 'action:test.review.spatial_seal'


def spatial_seal(monkeypatch):
    def actions(info):
        if info['actor_id'] != A:
            return None
        return [ActionDefinition(
            source_definition_id=SEAL, display_name='Test spatial seal',
            owner_id=A, economy='NONE', resolution_kind='TYPED', target_kind='SELF',
            parameters={'free_primary': True, 'typed': {'source': SEAL,
                'effects': [{'type': 'condition', 'condition': 'restrained',
                    'applies_to': 'self', 'duration': {'kind': 'rounds', 'amount': 10},
                    'condition_data': {'rule': {'no_teleport': 1}}}]}})]
    add_hook(monkeypatch, 'compile_actions', actions)


@pytest.mark.parametrize('recipient', ['owner', 'body'])
@pytest.mark.parametrize('barrier', ['condition', 'gate'])
def test_refused_exchange_preserves_mass_reaction_and_round_limit(
        tmp_path, monkeypatch, recipient, barrier):
    # Even a critical must leave the Body alive: its destruction legitimately
    # earns Mass and would obscure the refused exchange's payment invariant.
    synthetic_actions(monkeypatch, damage_sides=2, flat_rider=1)
    spatial_seal(monkeypatch)
    gates = []
    if barrier == 'gate':
        def refuse(ctx, start, destination):
            if ctx.actor.entity_id == A:
                gates.append((start, destination))
                return False
        add_hook(monkeypatch, 'teleport_gate', refuse)
    cold, jid, act, world = setup(tmp_path, monkeypatch, 6,
        positions={A: {'x': 3, 'y': 3}, B: {'x': 4, 'y': 3}})
    table, mid = combat(cold, jid, tmp_path)
    body = living_bodies(use(cold, table, mid, 'Create Quicksilver Body: 2 Qi'))[0]
    if barrier == 'condition':
        use(cold, table, mid, 'Test spatial seal')
        assert any(r.get('no_teleport') for r in condition_rules(engine(cold, mid).state.actors[A]))
    turn(table, mid, B)
    key = 'choice:needle.quicksilver.' + ('exchange_substance' if recipient == 'owner' else 'body_exchange')
    selected = body.object_id if recipient == 'owner' else 'exchange'
    for _ in range(4):
        before = engine(cold, mid)
        owner_before = before.state.actors[A].model_copy(deep=True)
        assert owner_before.reaction_available and owner_before.resources[MASS] > 0
        if recipient == 'owner':
            c = candidate(cold(), mid, 'Review Qi blade', target=A)
        else:
            c = next(c for c in before.legal_candidates()
                if c.target_ids == (body.object_id,)
                and c.source_definition_id == 'action:test.review.object_attack.' + B)
        prompts = settle(table, mid, c.candidate_id, picks={key: selected})
        after = engine(cold, mid)  # cold load and mechanical replay after table commit
        if any(p['context']['reaction_source_id'] == key for p in prompts):
            break
        turn(table, mid, A)
        turn(table, mid, B)
    else:
        pytest.fail('The real hostile attack never offered Exchange Substance.')
    owner_after = after.state.actors[A]
    assert owner_after.position == owner_before.position
    assert after.state.objects[body.object_id].position == body.position
    assert owner_after.resources[MASS] == owner_before.resources[MASS]
    assert owner_after.reaction_available == owner_before.reaction_available
    assert data(owner_after).get('exchange_round') == data(owner_before).get('exchange_round')
    assert after.state.objects[body.object_id].component.get('reaction_round') == body.component.get('reaction_round')
    events = after.events[len(before.events):]
    assert not any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == FEATURES[1] for e in events)
    # Refusing the swap must not cancel the original hit.
    if recipient == 'owner':
        assert owner_after.current_hp < owner_before.current_hp
    else:
        assert after.state.objects[body.object_id].current_hp < before.state.objects[body.object_id].current_hp
    if barrier == 'gate':
        assert gates


def test_copied_quicksilver_actions_retain_typed_economies():
    from combat.ext.mgr_reserve_living_quicksilver_immortal_embryo_living_mercury_body import (
        remove_partial_actions, distributed_options,
    )
    action = ActionDefinition(source_definition_id='action:test.bonus',
        display_name='Test bonus feature', owner_id=A, economy='BONUS_ACTION',
        resolution_kind='TYPED', target_kind='SELF',
        parameters={'typed': {'source': FEATURES[1], 'effects': []}})
    info = {'owned_ids': FEATURES, 'actions': [action]}
    hidden = remove_partial_actions(action, info)
    sibling, = distributed_options(info)
    assert hidden.economy is EconomyKind.NONE and hidden.economy.value == 'NONE'
    assert sibling.economy is EconomyKind.NONE and sibling.economy.value == 'NONE'
    assert action.economy is EconomyKind.BONUS_ACTION
    assert sibling.source_definition_id != action.source_definition_id


def test_granted_query_retains_typed_economy_and_original_action():
    from combat.granted_actions import candidates

    class QueryEngine:
        # A synthetic candidate provider, not a patched runtime engine.
        def __init__(self, action):
            self.action_catalog = {action.source_definition_id: action}
            self.state = SimpleNamespace(actors={A: SimpleNamespace(control_mode='MANUAL')})

        def action_candidates_for_sources(self, sources):
            action = self.action_catalog[sources[0]]
            assert action.economy is EconomyKind.NONE
            assert action.economy.value == 'NONE'
            from combat.primary_intents import allows_primary
            assert allows_primary(action), 'A granted paid action must retain native activation permission.'
            return [SimpleNamespace(metadata={})]

    action = ActionDefinition(source_definition_id='action:test.grant',
        display_name='Test granted feature', owner_id=A, economy='ACTION',
        resolution_kind='TYPED', target_kind='SELF')
    actor = SimpleNamespace(entity_id=A, action_ids=[action.source_definition_id], control_mode='MANUAL')
    e = QueryEngine(action)
    assert len(candidates(e, actor, action)) == 1
    assert e.action_catalog[action.source_definition_id] is action
    assert action.economy is EconomyKind.ACTION
