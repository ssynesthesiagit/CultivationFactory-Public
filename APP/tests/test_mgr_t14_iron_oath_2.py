"""Native table regressions; upstream duty/suppression remain explicitly open."""
import pytest

from combat.ext import foundation_combat as f
from tests.test_a2_foundations_two import table_fixture, use
from tests.worker2_support import OWNER, ALLY, FOE, reload, turn, settle, sealed_native_attack


def encounter(tmp_path, *, stage='Refined', expression='Iron Interposition', diagonal=False):
    def two_blows(bundles):
        action = next(a for a in bundles[2]['action_catalog'] if a['display_name'] == 'Hostile blow')
        action['economy'] = 'BONUS_ACTION'
        sealed_native_attack(bundles[2], 'Second hostile blow', damage_type='POISON',
                             count=1, sides=4, modifier=40, attack_bonus=50, range_ft=5)
    combat, table, mid = table_fixture(tmp_path, 'oath', current=0, stage=stage, transform=two_blows)
    use(combat, table, mid, 'Declare Protected Subject', choices={f.CHOICE + 'foundation_subject': [ALLY]})
    if diagonal:
        turn(table, mid, ALLY)
        movement = next(c for c in combat._load_session(mid).engine.legal_candidates()
                        if c.source_definition_id == 'system:combat.movement' and c.destination
                        and (c.destination.x, c.destination.y) == (4, 5))
        settle(table, mid, movement.candidate_id)
        turn(table, mid, OWNER)
    if expression:
        use(combat, table, mid, 'Foundation expression: ' + expression)
    # The native hostile damage event, not supplied condition/resource metadata,
    # produces the token. The first event cannot itself be guarded.
    turn(table, mid, FOE)
    use(combat, table, mid, 'Hostile blow', OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == 1
    assert not any(e.event_type == 'REACTION_RESOLVED'
                   and e.source_definition_id == f.feature('oath', 'iron_oath_guard') for e in engine.events)
    return combat, table, mid


@pytest.mark.parametrize('stage,expression,target,cut', [
    ('Refined', 'Iron Interposition', ALLY, 10),
    ('Refined', 'Iron Interposition', OWNER, 6),
    ('Refined', 'Oath-Skin Mantle', ALLY, 6),
    ('Awakened', None, ALLY, 6),
])
def test_guard_selected_expression_ownership_payment_and_reload(tmp_path, stage, expression, target, cut):
    combat, table, mid = encounter(tmp_path, stage=stage, expression=expression)
    prompts = use(combat, table, mid, 'Second hostile blow', target)
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and target in e.target_ids][-1]
    pending = [e for e in engine.events if e.event_type == 'REACTION_WINDOW_OPENED'
               and e.payload.get('checkpoint') == 'DAMAGE_APPLICATION'][-1]
    assert damage.payload['hp_damage'] == pending.payload['pending_damage'] - cut
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.source_definition_id == f.feature('oath', 'iron_oath_guard')]
    assert len(spent) == 1 and spent[0].payload['amount'] == 1
    assert not engine.state.actors[OWNER].reaction_available
    if target == ALLY:
        assert engine.state.actors[OWNER].resources[f.pool('oath')] == 0
    assert any('Iron Oath Guard' in str(prompt) for prompt in prompts)
    if expression:
        assert f.held(engine.state.actors[OWNER], 'expression').data['feature'] == f.feature(
            'oath', 'iron_interposition' if expression == 'Iron Interposition' else 'oath_skin_mantle')


def test_declining_guard_does_not_spend_or_move(tmp_path):
    combat, table, mid = encounter(tmp_path)
    use(combat, table, mid, 'Second hostile blow', ALLY,
        choices={f.CHOICE + 'foundation_combat': None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == 1
    assert engine.state.actors[OWNER].reaction_available
    assert not any(e.event_type == 'RESOURCE_SPENT'
                   and e.source_definition_id == f.feature('oath', 'iron_oath_guard') for e in engine.events)


def test_optional_native_step_precedes_reduction_and_survives_reload(tmp_path):
    combat, table, mid = encounter(tmp_path, diagonal=True)
    before = reload(tmp_path, mid).state.actors[OWNER].movement_remaining_ft
    prompts = use(combat, table, mid, 'Second hostile blow', ALLY,
                  choices={f.CHOICE + 'iron_interposition': 'first'})
    engine = reload(tmp_path, mid)
    movements = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER]
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and ALLY in e.target_ids][-1]
    paid = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
            and e.source_definition_id == f.feature('oath', 'iron_oath_guard')][-1]
    assert movements and paid.sequence < movements[-1].sequence < damage.sequence
    assert engine.state.actors[OWNER].movement_remaining_ft == before
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (4, 6)
    assert any(p['context'].get('reaction_source_id') == f.CHOICE + 'iron_interposition' for p in prompts)


def test_iron_interposition_requires_current_ally_relation_not_roster_team(tmp_path):
    """The printed clause protects an adjacent ally, so a GM relation override must win over the team id."""
    combat, table, mid = encounter(tmp_path)
    engine = combat._load_session(mid).engine
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER, 'other': ALLY,
                                         'relation': 'ENEMY'},
                            expected_state_version=engine.state.state_version)
    use(combat, table, mid, 'Second hostile blow', ALLY)
    engine = reload(tmp_path, mid)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and ALLY in e.target_ids][-1]
    window = [e for e in engine.events if e.event_type == 'REACTION_WINDOW_OPENED'
              and e.payload.get('checkpoint') == 'DAMAGE_APPLICATION'][-1]
    pb, cultivation = f.values(engine, engine.state.actors[OWNER])
    assert engine.state.actors[OWNER].resources[f.pool('oath')] == 0, 'the ordinary Iron Oath Guard still paid'
    assert (window.payload['pending_damage'] - damage.payload['hp_damage']
            - damage.payload.get('temporary_hp_absorbed', 0)) == pb * 2 + cultivation
