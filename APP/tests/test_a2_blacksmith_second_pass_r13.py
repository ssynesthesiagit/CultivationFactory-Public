"""Opponent-specific Quench permission through table commits and cold replay."""
import pytest
from combat import ext
from combat.ext.blacksmith_forge import mark_count
from combat.unmaking import NO_REACTIONS_AGAINST
from tests.worker2_support import fixture, reload, turn, OWNER, ALLY, FOE
from tests.test_a2_blacksmith import press, seal
from tests.test_a2_blacksmith_second_pass import setup, declare, die, QUENCH
from tests.test_a2_blacksmith_second_pass_r9 import add_reaction

PROTECTOR = 'actor:factory.worker2-ally3'
LATER = 'actor:factory.worker2-ally4'


@pytest.mark.parametrize('native', [False, True])
@pytest.mark.parametrize('family', ['weapon', 'armor or shield'])
@pytest.mark.parametrize('denial', ['condition', 'provider'])
@pytest.mark.parametrize('blocked', [True, False])
def test_quench_obeys_opponent_permission(tmp_path, monkeypatch, native, family, denial, blocked):
    die(monkeypatch)
    opponent = FOE if blocked else ALLY
    if denial == 'provider':
        def veto(engine, reactor, other):
            if reactor.entity_id == OWNER and other is not None and other.entity_id == opponent:
                return False
        monkeypatch.setitem(ext._HOOKS, 'reaction_allowed', [*ext._HOOKS.get('reaction_allowed', ()), veto])
    def build(bundles):
        setup(3 if family == 'weapon' else 5, native=native)(bundles)
        # Sealed setup action, executed and persisted through the real session.
        seal(bundles[2 if blocked else 1], 'Practice opponent restriction',
             [{'type': 'deny_reactions_against', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}],
             target='ANY_CREATURE')
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=build, named=True)
    if denial == 'condition':
        turn(table, mid, opponent)
        press(combat, table, mid, 'Practice opponent restriction', OWNER)
        turn(table, mid, OWNER)
        e = reload(tmp_path, mid)
        assert any(c.condition_id == NO_REACTIONS_AGAINST and c.data.get('against') == opponent
                   for c in e.state.actors[OWNER].conditions.values())
    declare(combat, table, mid, family)
    target = FOE if family == 'weapon' else OWNER
    if family != 'weapon':
        turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[target].current_hp
    prompts = press(combat, table, mid, 'Sword', target, picks={'choice:needle.blacksmith_quench': ['quench']})
    e = reload(tmp_path, mid)
    offers = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.blacksmith_quench']
    assert bool(offers) == (not blocked)
    assert e.state.actors[OWNER].reaction_available == blocked
    assert mark_count(e.state.actors[OWNER], OWNER) == int(blocked)
    assert sum(x.event_type == 'REACTION_RESOLVED' and x.source_definition_id == QUENCH for x in e.events) == int(not blocked)
    assert (e.state.actors[target].current_hp < before) == (not blocked if family == 'weapon' else blocked)


@pytest.mark.parametrize('natural', [10, 1])
@pytest.mark.parametrize('native', [False, True])
def test_replaced_hit_reaches_ally_only_reduction(tmp_path, monkeypatch, natural, native):
    die(monkeypatch, natural=natural)
    def build(bundles):
        setup(3 if natural == 10 else 12, native=native)(bundles)
        add_reaction(bundles, index=3, kind='ally_hit', feature='test:r13:ally_reduction',
                     effects=[{'type': 'damage_modifier', 'flat': 2, 'applies_to': 'target'}])
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=build, extra_allies=1)
    declare(combat, table, mid, 'weapon')
    before = reload(tmp_path, mid).state.actors[ALLY].current_hp
    prompts = press(combat, table, mid, 'Sword', ALLY,
                    picks={'choice:needle.blacksmith_quench': ['quench'],
                           'reaction:typed.test:r13:ally_reduction': ['USE']})
    e = reload(tmp_path, mid)
    defense, = [x for x in e.events if x.event_type == 'REACTION_RESOLVED'
                and x.source_definition_id == 'test:r13:ally_reduction']
    assert defense.actor_id == PROTECTOR
    assert defense.payload['pending_damage_reduction'] == 2
    assert defense.payload['hit_after_recheck'] is True
    assert any(p['context']['reaction_source_id'] == 'reaction:typed.test:r13:ally_reduction' for p in prompts)
    raw, = [x.payload['total'] for x in e.events if x.event_type == 'DAMAGE_ROLLED' and x.actor_id == OWNER]
    assert before - e.state.actors[ALLY].current_hp == raw - 2
    assert not e.state.actors[OWNER].reaction_available
    assert not e.state.actors[PROTECTOR].reaction_available
    assert e.state.actors[ALLY].reaction_available
    assert mark_count(e.state.actors[OWNER], OWNER) == 0


@pytest.mark.parametrize('stage', ['qualified_ac', 'provider', 'hit_ac', 'generic_hit', 'ally_hit'])
@pytest.mark.parametrize('native', [False, True])
def test_post_ac_replacement_continues_to_later_defense(tmp_path, monkeypatch, stage, native):
    """Each AC stage can restore a hit; later providers/ally rows still answer it."""
    die(monkeypatch)
    def build(bundles):
        setup(7, native=native)(bundles)  # 17 hits AC14, misses raised AC18 by one.
        if stage == 'qualified_ac':
            seal(bundles[1], 'Practice weapon guard', [{'type': 'ac_bonus', 'amount': 4,
                 'on': 'ranged' if native else 'melee', 'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'}])
        elif stage == 'hit_ac':
            add_reaction(bundles, index=1, kind='hit_ac', ac=4)
        elif stage in ('generic_hit', 'ally_hit'):
            add_reaction(bundles, index=1 if stage == 'generic_hit' else 3,
                         kind='hit' if stage == 'generic_hit' else 'ally_hit',
                         effects=[{'type': 'ac_bonus', 'amount': 4}])
        # A later ally raises AC once more. The one-attempt guard must not
        # allow the paid Quench to answer this second defense as well.
        if stage not in ('qualified_ac', 'provider'):
            add_reaction(bundles, index=4, kind='ally_hit', feature='test:r13:later',
                         effects=[{'type': 'ac_bonus', 'amount': 2}])
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=build, extra_allies=2)
    if stage in ('provider', 'qualified_ac'):
        from combat.attack_outcomes import unconditional_miss
        def raise_ac(engine, attacker, target, spec, total, natural, effective_ac):
            if target.entity_id == ALLY:
                return {'armor_class': effective_ac + 4, 'hit': False, 'miss_reason': 'armor_class'}
        def later(engine, attacker, target, spec, total, natural, effective_ac):
            if target.entity_id == ALLY:
                engine._append_event('PASSIVE_TRIGGERED', 'test:r13:later', actor_id=target.entity_id,
                                     target_ids=(attacker.entity_id,), payload={'forced_miss': True})
                return unconditional_miss()
        providers = [*ext._HOOKS.get('hit_response', ())]
        monkeypatch.setitem(ext._HOOKS, 'hit_response', [*providers, *([raise_ac] if stage == 'provider' else []), later])
    if stage == 'qualified_ac':
        turn(table, mid, ALLY)
        press(combat, table, mid, 'Practice weapon guard')
        turn(table, mid, OWNER)
    declare(combat, table, mid, 'weapon')
    before = reload(tmp_path, mid).state.actors[ALLY].current_hp
    prompts = press(combat, table, mid, 'Sword', ALLY, picks={
        'reaction:typed.test:r9:defense': ['USE'], 'choice:needle.blacksmith_quench': ['quench'],
        'reaction:typed.test:r13:later': ['USE']})
    e = reload(tmp_path, mid)
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.blacksmith_quench' for p in prompts) == 1
    assert e.state.actors[ALLY].current_hp == before
    assert mark_count(e.state.actors[OWNER], OWNER) == 0
    assert not e.state.actors[OWNER].reaction_available
    assert sum(x.source_definition_id == QUENCH and x.event_type == 'REACTION_RESOLVED' for x in e.events) == 1
    assert any(x.source_definition_id == 'test:r13:later' for x in e.events)
    if stage in ('hit_ac', 'generic_hit', 'ally_hit'):
        defense, = [x for x in e.events if x.source_definition_id == 'test:r9:defense' and x.event_type == 'REACTION_RESOLVED']
        assert defense.payload['hit_after_recheck'] is False
        assert not e.state.actors[ALLY if stage != 'ally_hit' else PROTECTOR].reaction_available
        assert not e.state.actors[LATER].reaction_available


@pytest.mark.parametrize('margin,use', [(1, True), (2, True), (1, False), (3, True)])
def test_native_ling_qi_post_defense_quench(tmp_path, monkeypatch, margin, use):
    from combat.gate2_runtime_content import LING, REACTION_PARAMETERS, ACTORS
    die(monkeypatch)
    armor = REACTION_PARAMETERS['reaction:ling_qi.qi_armor']
    ac = ACTORS[LING].armor_class
    combat, table, initial_mid = fixture(tmp_path, [QUENCH], bundle_transform=setup(ac + armor['ac_bonus'] - margin - 10, native=True))
    bundles = combat._load_session(initial_mid).engine.typed_bundle_documents[:1]
    mid = combat._finish_factory_match(bundles, [OWNER, LING], {OWNER: 'team:smith', LING: 'team:foe'},
        {OWNER: {'x': 3, 'y': 6}, LING: {'x': 6, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER], [LING],
        control_modes={OWNER: 'MANUAL', LING: 'MANUAL'}, match_seed='R13-LING', display_name='R13 Ling',
        maximum_rounds=15)['match_id']
    turn(table, mid, OWNER)
    declare(combat, table, mid, 'weapon')
    before = reload(tmp_path, mid).state.actors[LING]
    prompts = press(combat, table, mid, 'Sword', LING, picks={
        'reaction:ling_qi.qi_armor': ['USE'], 'choice:needle.blacksmith_quench': ['quench'] if use else None})
    e = reload(tmp_path, mid)
    expected = margin <= 2 and use
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.blacksmith_quench' for p in prompts) == int(margin <= 2)
    assert (e.state.actors[LING].current_hp < before.current_hp) == expected
    assert e.state.actors[LING].resources[armor['resource']] == before.resources[armor['resource']] - armor['cost']
    assert not e.state.actors[LING].reaction_available
    assert e.state.actors[OWNER].reaction_available == (not expected)
    assert mark_count(e.state.actors[OWNER], OWNER) == int(not expected)
    defense, = [x for x in e.events if x.source_definition_id == 'reaction:ling_qi.qi_armor' and x.event_type == 'REACTION_RESOLVED']
    assert defense.payload['new_ac'] == ac + armor['ac_bonus']
    assert defense.payload['hit_after_recheck'] is False
