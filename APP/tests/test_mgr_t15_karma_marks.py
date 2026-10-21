"""MGR-T15 Karma marks: whole-record service regressions for the five named-record talents.

Every case compiles real portable characters, drives the real table (candidate -> consent -> roll -> commit), cold-reloads the
saved fight (mechanical replay PASS) and asserts on the reloaded engine.  Public-capable: only synthetic sheets, the public
compiler and public service helpers (tests.h1_support, tests.worker2_support, tests.cw2_service_support).

Records (APP/authority/typed_mechanics/rules_text.json):
  TAL_KARMA_RECORD_THE_DEED, tianxia.talent.karma.clean_hands, tianxia.talent.karma.karmic_mirror,
  tianxia.talent.karma.ledger_seal_scripture, tianxia.talent.karma.no_lie_before_the_ledger.
"""
import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.ext.karma_imprints import RECORD, held
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import mark_condition_id
from tests.cw2_service_support import add_action, seal
from tests.h1_support import ROOT, sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn

MIRROR = 'tianxia.talent.karma.karmic_mirror'
NO_LIE = 'tianxia.talent.karma.no_lie_before_the_ledger'
CLEAN = 'tianxia.talent.karma.clean_hands'
MIRROR_ROW = 'reaction:typed.' + MIRROR
RECORD_ROW = 'reaction:typed.' + RECORD
CLEAN_PROMPT = 'choice:needle.karma_clean_hands'
CP = 'resource:core.qi'


def _imprint(kind, owner):
    return mark_condition_id(kind + ' Imprint', owner).removeprefix('condition:typed.')


def _prepare_mirror(bundles, *, seed='debt', incoming='damage', damage=5):
    """Seal a setup action that places the owner's Imprint, and one hostile single-target typed effect for the foe."""
    for bundle in bundles:
        bundle['actor_template']['maximum_hp'] = 100
    owner, _ally, foe = bundles
    if seed == 'debt':
        add_action(owner, 'Seed Debt', [{'type': 'condition', 'condition': _imprint('Debt', OWNER),
                                         'applies_to': 'target', 'duration': 'until_removed',
                                         'condition_data': {'cause': 'Prepared deed'}}], target='HOSTILE_ENTITY')
    elif seed == 'grace':
        add_action(owner, 'Seed Grace', [{'type': 'condition', 'condition': _imprint('Grace', OWNER),
                                          'applies_to': 'self', 'duration': 'until_removed',
                                          'condition_data': {'cause': 'Prepared deed'}}], target='SELF')
    if incoming == 'save':
        add_action(foe, 'Foe command', [{'type': 'save', 'ability': 'wis', 'dc': 'technique_save_dc', 'applies_to': 'target',
                                         'on_fail': [{'type': 'damage', 'applies_to': 'target', 'flat': damage,
                                                      'formula': 'none', 'damage_types': ['PSYCHIC']}]}],
                   target='HOSTILE_ENTITY')
    else:
        add_action(foe, 'Foe curse', [{'type': 'damage', 'applies_to': 'target', 'flat': damage,
                                       'formula': 'none', 'damage_types': ['PSYCHIC']}], target='HOSTILE_ENTITY')
    for bundle in bundles:
        seal(bundle)


def _strike_owner(combat, table, mid, name, *, picks):
    turn(table, mid, FOE)
    return settle(table, mid, candidate(combat, mid, name, target=OWNER).candidate_id, picks)


def test_karmic_mirror_is_not_offered_without_a_matching_imprint(tmp_path):
    """Wrong-owner/no-trigger negative: no Debt on the attacker and no Grace on the defender -> no Reaction, no CP spent."""
    combat, table, mid = fixture(tmp_path, [MIRROR], bundle_transform=lambda b: _prepare_mirror(b, seed='none'))
    prompts = _strike_owner(combat, table, mid, 'Foe curse', picks={})
    assert not [p for p in prompts if p['context']['reaction_source_id'] == MIRROR_ROW]
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[CP] == 100
    assert engine.state.actors[FOE].current_hp == 100
    assert engine.state.actors[OWNER].current_hp == 95  # the hostile effect still landed


def test_karmic_mirror_debt_imprint_forces_a_charisma_save_and_punishes_a_success(tmp_path):
    """Debt branch, successful save: the Imprint and 4 CP are spent, and the attacker takes PB + key modifier Psychic damage."""
    combat, table, mid = fixture(tmp_path, [MIRROR], bundle_transform=lambda b: _prepare_mirror(b, seed='debt'))
    settle(table, mid, candidate(combat, mid, 'Seed Debt', target=FOE).candidate_id)
    assert len(held(reload(tmp_path, mid).state.actors[FOE], OWNER, 'debt')) == 1
    prompts = _strike_owner(combat, table, mid, 'Foe curse', picks={MIRROR_ROW: 'use'})
    assert [p for p in prompts if p['context']['reaction_source_id'] == MIRROR_ROW]
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[CP] == 96
    assert held(engine.state.actors[FOE], OWNER, 'debt') == []
    roll = next(r for r in reversed(engine.events) if r.event_type == 'SAVE_ROLLED'
                and r.actor_id == FOE and r.payload.get('reason', '').endswith(':CHA'))
    assert roll.payload['dc'] == 16 and roll.payload['success'] is True
    assert engine.state.actors[FOE].current_hp == 100 - 6  # Proficiency Bonus 4 + key modifier 2
    assert engine.state.actors[OWNER].current_hp == 95


def test_karmic_mirror_failed_save_turns_the_hostile_effect_back_on_the_attacker(tmp_path):
    """Debt branch, failed save: the attacker is also affected by the hostile effect (here, its own 5 Psychic damage)."""
    combat, table, mid = fixture(tmp_path, [MIRROR], dc=30,
                                 bundle_transform=lambda b: _prepare_mirror(b, seed='debt'))
    settle(table, mid, candidate(combat, mid, 'Seed Debt', target=FOE).candidate_id)
    _strike_owner(combat, table, mid, 'Foe curse', picks={MIRROR_ROW: 'use'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[CP] == 96
    reflected = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                 and e.actor_id == OWNER and e.target_ids == (FOE,)]
    assert reflected and reflected[-1].payload['hp_damage'] == 5
    assert engine.state.actors[FOE].current_hp == 95


def test_karmic_mirror_grace_imprint_gives_advantage_on_the_effects_save(tmp_path):
    """Grace branch: the defender's Grace Imprint is spent for Advantage on the hostile effect's saving throw."""
    combat, table, mid = fixture(tmp_path, [MIRROR], bundle_transform=lambda b: _prepare_mirror(b, seed='grace', incoming='save'))
    settle(table, mid, candidate(combat, mid, 'Seed Grace', target=OWNER).candidate_id)
    _strike_owner(combat, table, mid, 'Foe command', picks={MIRROR_ROW: 'use'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[CP] == 96
    assert held(engine.state.actors[OWNER], OWNER, 'grace') == []
    save = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED'
                and e.actor_id == OWNER and e.payload.get('dc') == 16)
    assert save.payload['mode'] == 'ADVANTAGE'


@pytest.mark.parametrize('dc,imprint', [(16, False), (30, True)])
def test_no_lie_aura_and_the_judge_declaration_roll_the_printed_save(tmp_path, dc, imprint):
    """The 8 CP Action creates the 60-foot aura; only inside it is the table's free falsehood declaration offered.  Its
    Charisma save deals 4d8 Psychic damage (half and no Imprint on a success) and places one Debt Imprint on a failure."""
    combat, table, mid = fixture(tmp_path, [NO_LIE], dc=dc)
    assert not [c for c in combat._load_session(mid).engine.legal_candidates() if 'no_lie_judge' in c.source_definition_id]
    settle(table, mid, candidate(combat, mid, 'No Lie Before the Ledger').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[CP] == 92
    assert any(zone.active and str(zone.source_definition_id).endswith(NO_LIE) for zone in engine.state.zones.values())
    assert [c for c in engine.legal_candidates()
            if 'no_lie_judge' in c.source_definition_id and c.target_ids == (FOE,)]
    settle(table, mid, candidate(combat, mid, 'Judge a falsehood (No Lie Before the Ledger)', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    save = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE)
    packet = next(e for e in reversed(engine.events) if e.event_type == 'DAMAGE_COMMITTED' and e.target_ids == (FOE,))
    printed = next(r for r in reversed(engine.rolls) if r.actor_id == OWNER and r.reason.startswith('DAMAGE:')
                   and 'no_lie_judge' in r.reason)
    if save.payload['success']:
        assert packet.payload['hp_damage'] == printed.total // 2
        assert held(engine.state.actors[FOE], OWNER, 'debt') == []
    else:
        assert packet.payload['hp_damage'] == printed.total
        assert len(held(engine.state.actors[FOE], OWNER, 'debt')) == 1
    assert (held(engine.state.actors[FOE], OWNER, 'debt') != []) is imprint


def test_no_lie_judge_is_not_offered_outside_the_aura(tmp_path):
    """No-trigger negative: without the active aura the table declaration is not a legal candidate."""
    combat, table, mid = fixture(tmp_path, [NO_LIE])
    engine = combat._load_session(mid).engine
    assert not [c for c in engine.legal_candidates() if 'no_lie_judge' in c.source_definition_id]


def test_record_the_deed_places_a_commanded_minions_debt_on_its_commander(tmp_path):
    """Record the Deed's "commands a minion to perform a harmful act": the Debt lands on the commander, not the visible minion."""
    ids = [OWNER, ALLY, FOE]
    documents = [sheet([RECORD], cl=15, name='Wren'), sheet([], cl=15, name='Tobin'),
                 sheet(['TAL_DEATH_GRAVE_FORMATION'], cl=15, name='Mara')]
    for aid, document in zip(ids, documents):
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 100
        document['ability_scores_and_statistics']['armor_class']['base_value'] = 1
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    bundles = [compile_character(documents[0], actor_id=OWNER, reaction_plan={'ask': True}),
               compile_character(documents[1], actor_id=ALLY, reaction_plan={'ask': True}),
               compile_character(documents[2], actor_id=FOE,
                                 summon_plan={'counts': {'grave_formation': 1, 'lesser_corpse_servant': 0}})]
    assert bundles[2]['summons']
    for bundle in bundles:
        seal(bundle)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: 'team:factory', ALLY: 'team:factory', FOE: 'team:opponents'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 5, 'y': 5}, FOE: {'x': 7, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER, ALLY], [FOE],
        control_modes={aid: 'MANUAL' for aid in ids}, match_seed='KARMA-MINION', display_name='Karma minion',
        maximum_rounds=10)['match_id']
    turn(table, mid, OWNER)
    minion = next(a.entity_id for a in combat._load_session(mid).engine.state.actors.values()
                  if a.summon and a.summon.get('owner') == FOE)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Command Death servants').candidate_id)
    turn(table, mid, minion)
    prompts = settle(table, mid, candidate(combat, mid, 'Grave Assault', target=ALLY).candidate_id,
                     picks={RECORD_ROW: 'use'})
    assert [p for p in prompts if p['context']['reaction_source_id'] == RECORD_ROW]
    engine = reload(tmp_path, mid)
    assert len(held(engine.state.actors[FOE], OWNER, 'debt')) == 1
    assert held(engine.state.actors[minion], OWNER, 'debt') == []


def test_clean_hands_moves_a_coerced_actors_debt_to_the_identified_controller(tmp_path):
    """Clean Hands: a dominated actor's Debt is placed on the controller within 120 feet instead, on the table's choice."""
    def prepare(bundles):
        for bundle in bundles:
            bundle['actor_template']['maximum_hp'] = 100
        foe, minion = bundles[2], bundles[3]
        add_action(foe, 'Dominate', [{'type': 'condition', 'condition': 'dominated', 'applies_to': 'target',
                                      'duration': 'until_removed'}], target='ANY_CREATURE')
        add_action(minion, 'Dominated strike', [{'type': 'damage', 'applies_to': 'target', 'flat': 4,
                                                 'formula': 'none', 'damage_types': ['FORCE']}],
                   target='HOSTILE_ENTITY')
        for bundle in bundles:
            seal(bundle)

    combat, table, mid = fixture(tmp_path, [RECORD, CLEAN], extra_foes=1, bundle_transform=prepare, named=True)
    minion = 'actor:factory.worker2-foe1'
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Dominate', target=minion).candidate_id)
    assert [c.source_actor_id for c in reload(tmp_path, mid).state.actors[minion].conditions.values()
            if c.condition_id.endswith('dominated')] == [FOE]
    turn(table, mid, minion)
    prompts = settle(table, mid, candidate(combat, mid, 'Dominated strike', target=ALLY).candidate_id,
                     picks={CLEAN_PROMPT: 'source', RECORD_ROW: 'use'})
    assert [p for p in prompts if p['context']['reaction_source_id'] == CLEAN_PROMPT]
    engine = reload(tmp_path, mid)
    assert len(held(engine.state.actors[FOE], OWNER, 'debt')) == 1
    assert held(engine.state.actors[minion], OWNER, 'debt') == []


def test_clean_hands_can_decline_and_reports_that_the_visible_actor_was_not_the_debtor(tmp_path):
    """Clean Hands' second half: declining places no Debt anywhere and the ledger says the visible actor was not the true debtor."""
    def prepare(bundles):
        for bundle in bundles:
            bundle['actor_template']['maximum_hp'] = 100
        foe, minion = bundles[2], bundles[3]
        add_action(foe, 'Dominate', [{'type': 'condition', 'condition': 'dominated', 'applies_to': 'target',
                                      'duration': 'until_removed'}], target='ANY_CREATURE')
        add_action(minion, 'Dominated strike', [{'type': 'damage', 'applies_to': 'target', 'flat': 4,
                                                 'formula': 'none', 'damage_types': ['FORCE']}],
                   target='HOSTILE_ENTITY')
        for bundle in bundles:
            seal(bundle)

    combat, table, mid = fixture(tmp_path, [RECORD, CLEAN], extra_foes=1, bundle_transform=prepare, named=True)
    minion = 'actor:factory.worker2-foe1'
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Dominate', target=minion).candidate_id)
    turn(table, mid, minion)
    settle(table, mid, candidate(combat, mid, 'Dominated strike', target=ALLY).candidate_id,
           picks={CLEAN_PROMPT: 'decline'})
    engine = reload(tmp_path, mid)
    assert held(engine.state.actors[FOE], OWNER, 'debt') == []
    assert held(engine.state.actors[minion], OWNER, 'debt') == []
    assert any(e.event_type == 'PASSIVE_TRIGGERED' and CLEAN in e.source_definition_id
               and 'not the true debtor' in str(e.payload.get('log')) for e in engine.events)


def test_record_the_deed_grants_grace_for_removing_a_harmful_condition(tmp_path):
    """Record the Deed's Grace "removes a harmful condition": the creature that cleanses another records Grace on itself."""
    def prepare(bundles):
        for bundle in bundles:
            bundle['actor_template']['maximum_hp'] = 100
        owner, ally = bundles[0], bundles[1]
        add_action(owner, 'Mark Blinded', [{'type': 'condition', 'condition': 'blinded', 'applies_to': 'self',
                                            'duration': 'until_removed'}], target='SELF')
        add_action(ally, 'Cleanse', [{'type': 'remove_condition', 'condition': 'blinded', 'applies_to': 'target'}],
                   target='ANY_CREATURE')
        for bundle in bundles:
            seal(bundle)

    combat, table, mid = fixture(tmp_path, [RECORD], bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Mark Blinded').candidate_id)
    assert any(c.condition_id.endswith('blinded') for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())
    turn(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Cleanse', target=OWNER).candidate_id,
                     picks={RECORD_ROW: 'use'})
    assert [p for p in prompts if p['context']['reaction_source_id'] == RECORD_ROW]
    engine = reload(tmp_path, mid)
    assert len(held(engine.state.actors[ALLY], OWNER, 'grace')) == 1
    assert not any(c.condition_id.endswith('blinded') for c in engine.state.actors[OWNER].conditions.values())
