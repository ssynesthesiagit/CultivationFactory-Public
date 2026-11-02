"""Ancestral Bloodline Awakening: table transactions, cold reload, journal replay.

Every gift is driven through the TabletopService (execute_intent), then the fight
is cold-reloaded and its journal replayed, so the recorded gift choice and every
spent resource survive a save/load cycle.
"""
import pytest
from combat.ext import ancestral_bloodline as lineage
from combat.flight import profile as flight_profile
from tests.cw2_service_support import add_action, seal
from tests.test_r9i_karma_persistence import act
from tests.worker2_support import FOE, OWNER, ALLY, fixture, candidate, settle, turn, reload

INSIGHT = 'insight.ancestral-bloodline-awakening'
GIFT = 'condition:typed.lineage_gift'
FLIGHT = 'condition:typed.dragon_flight'
PHOENIX_USED = 'condition:typed.phoenix_gift_used'
QI = 'resource:core.qi'
HP = 60


def setup(tmp_path, *, bundle_transform=None, owner_ac=14, owner_dc=16, **layout):
    def prepare(bundles):
        for bundle in bundles:
            add_action(bundle, 'Cause', [{'type': 'damage', 'applies_to': 'target',
                                               'flat': 5, 'damage_types': ['force']}])
            seal(bundle)
        if bundle_transform:
            bundle_transform(bundles)
    return fixture(tmp_path, [], owner_insights=[INSIGHT],
                   bundle_transform=prepare, owner_ac=owner_ac, owner_dc=owner_dc,
                   positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 5, 'y': 7},
                              FOE: {'x': 4, 'y': 6}},
                   **layout)


def pick(combat, table, mid, title):
    return settle(table, mid, candidate(combat, mid, title).candidate_id)


def by_name(engine, title):
    return [c for c in engine.legal_candidates()
            if engine.action_catalog.get(c.source_definition_id)
            and engine.action_catalog[c.source_definition_id].display_name == title]


def lances(bundles):
    add_action(bundles[2], 'Fire Lance', [{'type': 'damage', 'applies_to': 'target',
                                                'flat': 20, 'damage_types': ['fire']}],
                target='HOSTILE_ENTITY')
    add_action(bundles[2], 'Frost Lance', [{'type': 'damage', 'applies_to': 'target',
                                                 'flat': 20, 'damage_types': ['cold']}],
                target='HOSTILE_ENTITY')


def push(bundles):
    add_action(bundles[2], 'Forceful Push', [{'type': 'forced_movement', 'applies_to': 'target',
                                                   'distance_ft': 10, 'direction': 'away'}],
                target='HOSTILE_ENTITY')


def strikes(bundles):
    add_action(bundles[2], 'Drain', [{'type': 'damage', 'applies_to': 'target',
                                           'flat': 55, 'damage_types': ['necrotic']}],
                target='HOSTILE_ENTITY')
    add_action(bundles[2], 'Strike', [{'type': 'damage', 'applies_to': 'target',
                                            'flat': 20, 'damage_types': ['bludgeoning']}],
                target='HOSTILE_ENTITY')
    add_action(bundles[2], 'Massive Strike', [{'type': 'damage', 'applies_to': 'target',
                                                    'flat': 65, 'damage_types': ['bludgeoning']}],
                target='HOSTILE_ENTITY')


def qi_bolt(bundles):
    def bolt(name, economy, source):
        add_action(bundles[0], name, [{'type': 'save', 'ability': 'con',
                                                'evidence': f'{name}: Constitution saving throw',
                                                'on_fail': [{'type': 'damage', 'applies_to': 'target',
                                                               'flat': 5, 'damage_types': ['force']}]}],
                    target='HOSTILE_ENTITY')
        made = bundles[0]['action_catalog'][-1]
        made['economy'] = economy
        made['parameters']['typed']['source'] = source
        made['parameters']['typed']['numbers']['save_dc'] = 100
    bolt('Qi Bolt', 'ACTION', 'tianxia.subpath.qi.test.qi_bolt')
    bolt('Qi Flourish', 'BONUS_ACTION', 'tianxia.subpath.qi.test.qi_flourish')
    seal(bundles[0])


# --------------------------------------------------------------------- Jade Tortoise
def test_jade_tortoise_armor_and_shorter_push(tmp_path):
    plain = tmp_path / 'plain'
    combat, table, mid = setup(plain, bundle_transform=push)
    engine = reload(plain, mid)
    owner = engine.state.actors[OWNER]
    assert lineage.owned(engine, owner) and lineage.gift_of(owner) == ''
    assert lineage.tortoise_armor(engine, owner) == 0
    # no gift recorded: the full 10-foot push lands two squares away
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Forceful Push', target=OWNER).candidate_id)
    engine = reload(plain, mid)
    assert engine.state.actors[OWNER].position.x == 1

    shell = tmp_path / 'shell'
    combat, table, mid = setup(shell, bundle_transform=push)
    pick(combat, table, mid, 'Ancestral Bloodline: Jade Tortoise')
    engine = reload(shell, mid)
    owner = engine.state.actors[OWNER]
    assert lineage.gift_of(owner) == 'tortoise'
    assert lineage.tortoise_armor(engine, owner) == 1
    # the shell is part of the engine's own Armor Class path
    assert engine._ac_modifier(owner) == 1
    assert owner.armor_class + engine._ac_modifier(owner) == 14 + 1
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Forceful Push', target=OWNER).candidate_id)
    engine = reload(shell, mid)
    # the tortoise shell shortens the push to 5 feet: one square, not two
    assert engine.state.actors[OWNER].position.x == 2


# --------------------------------------------------------------------- Azure Dragon
def test_azure_dragon_resists_only_chosen_type(tmp_path):
    combat, table, mid = setup(tmp_path, bundle_transform=lances, owner_dc=100)
    pick(combat, table, mid, 'Ancestral Bloodline: Azure Dragon -- Fire')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert lineage.gift_of(owner) == 'dragon'
    assert lineage.chosen_damage(owner) == 'FIRE'
    assert lineage.dragon_resistance(engine, owner, 'FIRE', None, None) == \
        [{'kind': 'resistance', 'damage_types': ['FIRE']}]
    assert lineage.dragon_resistance(engine, owner, 'COLD', None, None) is None
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Fire Lance', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == HP - 10
    settle(table, mid, candidate(combat, mid, 'Frost Lance', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == HP - 30


def test_azure_dragon_passage_is_a_gated_bonus_action(tmp_path):
    combat, table, mid = setup(tmp_path)
    engine = reload(tmp_path, mid)
    assert not by_name(engine, 'Draconic Passage: Fly 30 feet')
    pick(combat, table, mid, 'Ancestral Bloodline: Azure Dragon -- Fire')
    engine = reload(tmp_path, mid)
    offered = by_name(engine, 'Draconic Passage: Fly 30 feet')
    assert offered
    settle(table, mid, offered[0].candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[QI] == 100 - 2
    assert any(c.condition_id == FLIGHT for c in owner.conditions.values())
    assert flight_profile(engine, owner).speed_ft == 30
    # the wings last until the end of the turn that granted them
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == FLIGHT for c in engine.state.actors[OWNER].conditions.values())
    assert flight_profile(engine, engine.state.actors[OWNER]).speed_ft == 0


# --------------------------------------------------------------------- Vermilion Phoenix
def test_vermilion_phoenix_continuity_bursts_and_is_once_per_scene(tmp_path):
    combat, table, mid = setup(tmp_path, bundle_transform=strikes, owner_dc=100)
    pick(combat, table, mid, 'Ancestral Bloodline: Vermilion Phoenix -- Fire')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Drain', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == 5
    # a 20-point hit would reduce the owner to 0 without killing it outright
    settle(table, mid, candidate(combat, mid, 'Strike', target=OWNER).candidate_id,
              picks={'choice:needle.phoenix_continuity': 'remain'})
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert owner.current_hp == 1
    assert owner.resources[QI] == 100 - 4
    assert any(c.condition_id == PHOENIX_USED for c in owner.conditions.values())
    # the foe within 5 feet fails its Dexterity save (DC 100) and takes 2d8 Fire
    assert HP - 16 <= foe.current_hp <= HP - 2
    burst = [ev for ev in engine.events if ev.event_type == 'DAMAGE_COMMITTED'
             and ev.source_definition_id == INSIGHT]
    assert burst and burst[-1].payload['damage_type'] == 'FIRE'
    assert 1 <= int(burst[-1].payload['hp_damage']) <= 16
    # once per scene: a second drop to 0 is not rescued and bursts no more
    settle(table, mid, candidate(combat, mid, 'Drain', target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == 0
    assert engine.state.actors[FOE].current_hp == foe.current_hp


def test_vermilion_phoenix_burst_halves_on_a_success(tmp_path):
    combat, table, mid = setup(tmp_path, bundle_transform=strikes, owner_dc=1)
    pick(combat, table, mid, 'Ancestral Bloodline: Vermilion Phoenix -- Radiant')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Drain', target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Strike', target=OWNER).candidate_id,
              picks={'choice:needle.phoenix_continuity': 'remain'})
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    # the foe's Dexterity save succeeds (DC 1): the 2d8 Radiant burst is halved
    assert HP - 8 <= foe.current_hp <= HP - 1
    burst = [ev for ev in engine.events if ev.event_type == 'DAMAGE_COMMITTED'
             and ev.source_definition_id == INSIGHT]
    assert burst and burst[-1].payload['damage_type'] == 'RADIANT'


def test_vermilion_phoenix_refuses_a_killing_blow(tmp_path):
    combat, table, mid = setup(tmp_path, bundle_transform=strikes, owner_dc=100)
    pick(combat, table, mid, 'Ancestral Bloodline: Vermilion Phoenix -- Fire')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Drain', target=OWNER).candidate_id)
    # 65 damage at 5 Hit Points exceeds the creature's maximum: killed outright
    settle(table, mid, candidate(combat, mid, 'Massive Strike', target=OWNER).candidate_id,
              picks={'choice:needle.phoenix_continuity': 'remain'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == 0
    assert not any(c.condition_id == PHOENIX_USED for c in engine.state.actors[OWNER].conditions.values())


def test_vermilion_phoenix_declines_when_not_asked(tmp_path):
    combat, table, mid = setup(tmp_path, bundle_transform=strikes, owner_dc=100)
    pick(combat, table, mid, 'Ancestral Bloodline: Vermilion Phoenix -- Fire')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Drain', target=OWNER).candidate_id)
    # the owner declines the rescue and falls
    settle(table, mid, candidate(combat, mid, 'Strike', target=OWNER).candidate_id,
              picks={'choice:needle.phoenix_continuity': None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == 0
    assert engine.state.actors[OWNER].resources[QI] == 100


# --------------------------------------------------------------------- Demon-Blood
def test_demon_blood_rider_adds_1d6_once_per_turn(tmp_path):
    combat, table, mid = setup(tmp_path, bundle_transform=qi_bolt)
    pick(combat, table, mid, 'Ancestral Bloodline: Demon-Blood -- Necrotic')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert lineage.gift_of(owner) == 'demon'
    assert lineage.chosen_damage(owner) == 'NECROTIC'
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Qi Bolt', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    rider = [ev for ev in engine.events if ev.event_type == 'DAMAGE_COMMITTED'
             and ev.source_definition_id == INSIGHT]
    assert rider and rider[-1].payload['damage_type'] == 'NECROTIC'
    assert 1 <= int(rider[-1].payload['hp_damage']) <= 6
    # the Qi Bolt's 5 force damage, plus one 1d6 Necrotic rider packet
    assert foe.current_hp == HP - 5 - int(rider[-1].payload['hp_damage'])
    # once per turn: the bonus-action Qi feature rides no more
    settle(table, mid, candidate(combat, mid, 'Qi Flourish', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert len([ev for ev in engine.events if ev.event_type == 'DAMAGE_COMMITTED'
                and ev.source_definition_id == INSIGHT]) == 1
    # both Qi features' force damage, plus the single 1d6 rider
    assert foe.current_hp == HP - 10 - int(rider[-1].payload['hp_damage'])


def test_demon_blood_ignores_features_that_are_not_qi_powered(tmp_path):
    combat, table, mid = setup(tmp_path, bundle_transform=qi_bolt)
    pick(combat, table, mid, 'Ancestral Bloodline: Demon-Blood -- Necrotic')
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    # the Cause action spends no Qi and is no Qi-powered feature: no rider
    settle(table, mid, candidate(combat, mid, 'Cause', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert not [ev for ev in engine.events if ev.event_type == 'DAMAGE_COMMITTED'
                and ev.source_definition_id == INSIGHT]


# --------------------------------------------------------------------- Nine-Tailed Fox
def answer_fox(table, mid, cid):
    answers = []
    for _ in range(20):
        result = act(table, mid, cid, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            return
        prompt = result['reaction']
        use_it = str(prompt['context'].get('checkpoint') or '').startswith('TYPED:' + lineage.FOX_CHECKPOINT)
        answers.append({**prompt['context'], 'selection': 'USE' if use_it else 'DECLINE'})


def test_nine_tailed_fox_reaction_imposes_disadvantage(tmp_path):
    combat, table, mid = setup(tmp_path)
    pick(combat, table, mid, 'Ancestral Bloodline: Nine-Tailed Fox')
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert lineage.gift_of(owner) == 'fox'
    assert lineage._fox_guard(engine, lineage._fox_holders(engine)[0], None)
    cid = candidate(combat, mid, 'Unarmed Strike', target=OWNER).candidate_id
    answer_fox(table, mid, cid)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[QI] == 100 - 1
    assert not owner.reaction_available
    rewritten = [ev for ev in engine.events if ev.event_type == 'D20_REWRITTEN'
                 and ev.source_definition_id == INSIGHT]
    assert rewritten
    # the rewrite replaces the observed d20, and the attack resolves on the replaced roll
    assert rewritten[-1].payload['operation'] == 'replace'
    attack = next(ev for ev in engine.events if ev.event_type == 'ATTACK_ROLLED')
    assert attack.payload['natural_result'] == rewritten[-1].payload['result']['natural_result']


def test_nine_tailed_fox_requires_an_available_reaction(tmp_path):
    combat, table, mid = setup(tmp_path, extra_foes=1)
    pick(combat, table, mid, 'Ancestral Bloodline: Nine-Tailed Fox')
    turn(table, mid, FOE)
    answer_fox(table, mid, candidate(combat, mid, 'Unarmed Strike', target=OWNER).candidate_id)
    # Without a turn refresh, a second attack cannot spend the same Reaction.
    second = 'actor:factory.worker2-foe1'
    turn(table, mid, second)
    answer_fox(table, mid, candidate(combat, mid, 'Unarmed Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    rewritten = [ev for ev in engine.events if ev.event_type == 'D20_REWRITTEN'
                 and ev.source_definition_id == INSIGHT]
    assert len(rewritten) == 1


def test_gift_choice_persists_through_a_cold_reload(tmp_path):
    combat, table, mid = setup(tmp_path)
    pick(combat, table, mid, 'Ancestral Bloodline: Jade Tortoise')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    recorded = next(c for c in owner.conditions.values() if c.condition_id == GIFT)
    assert recorded.data['gift'] == 'tortoise'
    assert engine._ac_modifier(owner) == 1
