"""Review F1-F6: real table commits and replay, with no external model clients."""
import ast
from pathlib import Path

import pytest

from combat.ext import ancestral_bloodline as lineage
from tests.cw2_service_support import add_action, seal
from tests.test_a2r_ancestral_bloodline import setup, pick, by_name, answer_fox, QI
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn


@pytest.mark.parametrize('first', ['Ancestral Bloodline: Azure Dragon -- Fire',
                                 'Ancestral Bloodline: Jade Tortoise'])
def test_f1_recorded_gift_cannot_be_replaced_after_reload(tmp_path, first):
    combat, table, mid = setup(tmp_path)
    stale = candidate(combat, mid, 'Ancestral Bloodline: Demon-Blood -- Poison').candidate_id
    pick(combat, table, mid, first)
    engine = reload(tmp_path, mid)
    recorded = lineage.gift_of(engine.state.actors[OWNER])
    assert not any('lineage_gift' in c.source_definition_id for c in engine.legal_candidates())
    # Old candidate ids cannot bypass the engine's new legality check.
    from tests.test_r9i_karma_persistence import act
    from combat.tabletop import TabletopError
    from combat.gate5_service import CombatServiceError
    try:
        result = act(table, mid, stale)
    except (TabletopError, CombatServiceError):
        pass
    else:
        assert result['status'] != 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert lineage.gift_of(engine.state.actors[OWNER]) == recorded
    if recorded == 'dragon':
        assert lineage.chosen_damage(engine.state.actors[OWNER]) == 'FIRE'
    else:
        assert not by_name(engine, 'Draconic Passage: Fly 30 feet')


def test_f2_fresh_automatic_owner_receives_a_fixed_usable_gift(tmp_path):
    combat, table, mid = setup(tmp_path, modes={OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'MANUAL'})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert lineage.gift_of(actor) == 'dragon'
    assert lineage.chosen_damage(actor) == 'ACID'
    assert lineage.dragon_resistance(engine, actor, 'ACID', None, None)
    assert by_name(engine, 'Draconic Passage: Fly 30 feet')
    # The built-in AI context must retain the usable flight option.
    context = combat.ai_decision_context(combat._load_session(mid))
    assert any(c.source_definition_id.endswith('.dragon_flight') for c in context.legal_candidates)
    from tests.test_a2r_bone_general import ai_send
    ai_send(combat, table, mid, by_name(engine, 'Draconic Passage: Fly 30 feet')[0].candidate_id)
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.resources[QI] == 98
    assert any(c.condition_id == lineage.FLIGHT for c in actor.conditions.values())


@pytest.mark.parametrize('gift,title', [
    ('dragon', 'Azure Dragon -- Fire'), ('phoenix', 'Vermilion Phoenix -- Radiant'),
    ('demon', 'Demon-Blood -- Poison'), ('tortoise', 'Jade Tortoise'), ('fox', 'Nine-Tailed Fox')])
def test_f1_f2_recorded_roster_choice_precedes_automatic_default(tmp_path, monkeypatch, gift, title):
    # Freeze an explicit sheet selection in the real roster path before genesis.
    # The worker fixture's non-UUID ids do not refer to actual saved projects.
    from combat import settings_service
    preset = {}
    def prepare(bundles):
        action = next(a for a in bundles[0]['action_catalog']
                      if a['display_name'] == 'Ancestral Bloodline: ' + title)
        preset[OWNER] = [action['source_definition_id']]
    monkeypatch.setattr(settings_service, 'presets_for_roster', lambda service, ids: preset)
    combat, table, mid = setup(tmp_path, bundle_transform=prepare,
                              modes={OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'MANUAL'})
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert lineage.gift_of(actor) == gift
    if gift == 'dragon':
        assert lineage.chosen_damage(actor) == 'FIRE'
    assert not any('lineage_gift' in c.source_definition_id
                   for c in reload(tmp_path, mid).legal_candidates())


def test_f3_pull_does_not_spend_momentum_before_a_push(tmp_path):
    def prepare(bundles):
        for name, direction in [('Pull', 'toward'), ('Push', 'away')]:
            add_action(bundles[0], name, [{'type': 'forced_movement', 'distance_ft': 10,
                                         'direction': direction, 'applies_to': 'target'}],
                       target='HOSTILE_ENTITY')
        seal(bundles[0])
    combat, table, mid = fixture(tmp_path, [], owner_insights=['insight.brutal-momentum'],
                               foe_position={'x': 6, 'y': 6}, ally_position={'x': 5, 'y': 7},
                               bundle_transform=prepare)
    prompts = settle(table, mid, candidate(combat, mid, 'Pull', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position.x == 4
    assert not engine.state.actors[OWNER].turn_flags.get('brutal_momentum_used')
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.brutal_momentum' for p in prompts)
    prompts = settle(table, mid, candidate(combat, mid, 'Push', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].position.x == 6
    assert engine.state.actors[OWNER].turn_flags.get('brutal_momentum_used')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.brutal_momentum' for p in prompts)


@pytest.mark.parametrize('group,economy', [('painting', 'BONUS_ACTION'), ('death', 'ACTION')])
def test_f4_other_commands_do_not_grant_a_death_step(tmp_path, group, economy):
    from tests.test_a2r_bone_general import setup as bone_setup
    def prepare(bundles):
        # Reuse a real servant, but seal an unrelated command action.
        add_action(bundles[0], 'Other command', [{'type': 'command_summons', 'group': group}])
        bundles[0]['action_catalog'][-1]['economy'] = economy
        if group == 'painting':
            for bundle in bundles[0]['summons']:
                bundle['summon']['group'] = group
                bundle['summon']['command_group'] = group
                seal(bundle)
        seal(bundles[0])
    combat, table, mid = bone_setup(tmp_path, plan={'counts': {'corpse_servant': 1}},
                                  bundle_transform=prepare)
    prompts = settle(table, mid, candidate(combat, mid, 'Other command').candidate_id)
    engine = reload(tmp_path, mid)
    commanded = [a for a in engine.state.actors.values()
                 if a.summon and a.summon.get('owner') == OWNER]
    assert commanded and any(a.summon.get('commanded') for a in commanded)
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.bone_general') for p in prompts)
    assert not any(e.event_type == 'MOVEMENT_COMMITTED' and str(e.source_definition_id).endswith('bone-general')
                   for e in engine.events)


def test_f4_threatened_servant_step_provokes(tmp_path):
    from tests.test_a2r_bone_general import setup as bone_setup, servants
    from tests.test_a2r_brutal_momentum import kit
    combat, table, mid = bone_setup(tmp_path, plan={'counts': {'corpse_servant': 1}},
                                  foe_kit=kit('duan_jian'), foe_position={'x': 3, 'y': 5},
                                  ally_position={'x': 5, 'y': 7})
    servant = servants(reload(tmp_path, mid), 'corpse_servant')[0]
    prompts = settle(table, mid, candidate(combat, mid, 'Command Death servants').candidate_id,
                     picks={'choice:needle.bone_general_move': servant.entity_id,
                            'choice:needle.bone_general_step': 'step:1,4,0'})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reactor_id'] == FOE and not p['context']['reaction_source_id'].startswith('choice:')
               for p in prompts), prompts
    assert engine.state.actors[servant.entity_id].position != servant.position


def test_f4_automatic_servant_does_not_follow_an_unperceived_foe(tmp_path, monkeypatch):
    from combat.ext import bone_general
    from tests.test_a2r_bone_general import setup as bone_setup, servants, use
    combat, table, mid = bone_setup(tmp_path, plan={'counts': {'corpse_servant': 1}})
    servant = servants(reload(tmp_path, mid), 'corpse_servant')[0]
    # A deterministic perception boundary: the summoner still sees its servant,
    # but the servant cannot perceive any destination to pursue an enemy toward.
    monkeypatch.setattr(bone_general, '_perceives', lambda *args: False)
    use(combat, table, mid, 'Command Death servants', auto_ai=True)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[servant.entity_id].summon['commanded']
    assert engine.state.actors[servant.entity_id].position == servant.position
    assert not any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == servant.entity_id for e in engine.events)


def test_f5_foxfire_can_affect_an_ally_attack(tmp_path):
    combat, table, mid = setup(tmp_path)
    pick(combat, table, mid, 'Ancestral Bloodline: Nine-Tailed Fox')
    turn(table, mid, ALLY)
    answer_fox(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[QI] == 99
    assert any(e.event_type == 'D20_REWRITTEN' and e.source_definition_id == lineage.INSIGHT for e in engine.events)


def test_f5_foxfire_cannot_spend_missing_qi(tmp_path):
    def empty_pool(bundles):
        for resource in bundles[0]['actor_template']['resources']:
            if resource['resource_id'] == QI:
                resource['initial'] = 0
        seal(bundles[0])
    combat, table, mid = setup(tmp_path, bundle_transform=empty_pool)
    pick(combat, table, mid, 'Ancestral Bloodline: Nine-Tailed Fox')
    turn(table, mid, FOE)
    answer_fox(table, mid, candidate(combat, mid, 'Unarmed Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[QI] == 0
    assert engine.state.actors[OWNER].reaction_available
    assert not any(e.event_type == 'D20_REWRITTEN' and e.source_definition_id == lineage.INSIGHT for e in engine.events)


def test_f5_reaction_refresh_allows_two_foxfires_in_one_round(tmp_path):
    # Force ally, owner, foe initiative so the refresh stays in one numbered round.
    def initiative(bundles):
        for bundle, bonus in zip(bundles, [0, 100, -100]):
            bundle['actor_template']['initiative_bonus'] = bonus
            seal(bundle)
    combat, table, mid = setup(tmp_path, bundle_transform=initiative)
    pick(combat, table, mid, 'Ancestral Bloodline: Nine-Tailed Fox')
    # Rotate to the actor immediately before owner; its attack spends Foxfire.
    engine = reload(tmp_path, mid)
    order = engine.state.initiative_order
    previous = order[(order.index(OWNER) - 1) % len(order)]
    turn(table, mid, previous)
    target = FOE if previous == ALLY else OWNER
    answer_fox(table, mid, candidate(combat, mid, 'Unarmed Strike', target=target).candidate_id)
    before = reload(tmp_path, mid).state.round_number
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.round_number == before, order
    assert engine.state.actors[OWNER].reaction_available
    answer_fox(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.round_number == before
    assert engine.state.actors[OWNER].resources[QI] == 98
    assert len([e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                and e.source_definition_id == lineage.INSIGHT]) == 2


def test_f6_reaction_compiler_has_one_documented_transform():
    from combat import factory_compiler
    tree = ast.parse(Path(factory_compiler.__file__).read_text())
    hooks = [node.args[0].value for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr in ('run', 'run_strict', 'transform') and node.args
             and isinstance(node.args[0], ast.Constant)]
    assert 'reaction_numbers' not in hooks
    assert hooks.count('compile_reaction') == 1


def test_selector_text_explains_fixed_gift_benefits(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    actions = [a for a in engine.action_catalog.values() if 'lineage_gift' in a.source_definition_id]
    assert actions
    for action in actions:
        text = action.parameters['description']
        gift = action.parameters['typed']['effects'][0]['gift']
        assert 'Choose once' in text and 'cannot be changed in combat' in text
        assert {'dragon': 'Resistance', 'phoenix': '4 Qi', 'demon': '1d6',
                'tortoise': '+1 AC', 'fox': 'Reaction, 1 Qi'}[gift] in text
