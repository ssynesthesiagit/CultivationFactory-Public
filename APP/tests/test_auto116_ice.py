"""AUTO116: the Ice choices the printed text hands to its owner resolve on the real table.

Every case drives compiled characters through ``TabletopService`` decisions, answers the prompts
the engine actually opened, then reloads the saved fight from disk and replays it. Sealed
synthetic actions only prepare marks and raw damage; no shipped mechanic is replaced.
"""
import json
import zipfile

import pytest

from tests.cw2_service_support import add_action, seal
from tests.test_carry import KIT
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle
from combat.ext.ice_fracture import BITTER, STORED, T, _melee_strikes, lattice_cells, marked

FOE_CELL = {'x': 2, 'y': 5}  # a cell Crystallize Path actually covers in the pillar arena


def setup(bundles):
    """Common sealed setup: initiative, hit points, hopeless saves, a mark and a raw impact."""
    for b, bonus in zip(bundles, [100, -100, 0]):
        b['actor_template']['initiative_bonus'] = bonus
        b['actor_template']['maximum_hp'] = 300
    bundles[2]['actor_template']['armor_class'] = 0
    for ability in ('DEX', 'STR', 'CHA'):
        bundles[2]['actor_template']['saving_throws'][ability] = -100
    add_action(bundles[0], 'Mark foe', [{'type': 'mark', 'mark': 'Fracture Mark', 'applies_to': 'target',
                                         'duration': {'kind': 'until_removed'}}])
    add_action(bundles[0], 'Blind myself', [{'type': 'condition', 'condition': 'blinded', 'applies_to': 'self',
                                             'expires_on': 'UNTIL_REMOVED'}], target='SELF')
    # The ally deals real damage, so the owner's reaction fires on a creature that is not theirs.
    add_action(bundles[1], 'Deal impact', [{'type': 'damage', 'flat': 40, 'damage_types': ['bludgeoning'],
                                            'applies_to': 'target'}])
    for b in bundles:
        seal(b)


FOE2 = "actor:factory.worker2-foe2"


def fixture_two_foes(tmp_path, talents, *, positions, cl=15, seed="WORKER2X"):
    """A four-actor table: owner, ally, and TWO hostiles.

    Crystal Step prints "move that mark to another creature within 10 feet of you", so a case that
    exercises it needs a second hostile that is neither the donor nor the caster's own side.
    """
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet

    ids = [OWNER, ALLY, FOE, FOE2]
    documents = [sheet(talents, cl=cl), sheet([], cl=cl), sheet([], cl=cl), sheet([], cl=cl)]
    for document in documents:
        document['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    for aid, document in zip(ids, documents):
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True})
               for aid, doc in zip(ids, documents)]
    setup(bundles)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids,
        {OWNER: 'team:factory', ALLY: 'team:factory', FOE: 'team:opponents', FOE2: 'team:opponents'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, **positions},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [OWNER, ALLY], [FOE, FOE2],
        control_modes={aid: 'MANUAL' for aid in ids}, match_seed=seed, display_name=seed, maximum_rounds=15)['match_id']
    reach(table, mid, OWNER)
    return combat, table, mid


def asked(prompts, source):
    return [p for p in prompts if p['context']['reaction_source_id'] == source]


def reach(table, mid, actor, picks=None):
    """Answer end turns until ``actor`` is on turn; return every prompt opened on the way."""
    prompts = []
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == actor:
            return prompts
        prompts += settle(table, mid, table.state(mid)['menu']['end_turn'], picks)
    raise AssertionError('no turn')


# --------------------------------------------------------------------------- Winter Stores the Blow
def test_winter_stores_protects_a_visible_hostile_and_owner_picks_the_space(tmp_path):
    """Printed: "A creature you can see takes damage while standing on one of your Lattice Spaces"
    and "One Lattice Space under or adjacent to the creature gains a stored fracture."

    Before this lane the reaction only offered allies and always used the first cell under the
    creature, so a hostile on the lattice was never offered and the adjacent ring was unreachable.
    """
    combat, table, mid = fixture(tmp_path, ['TAL_ICE_WINTER_STORES_THE_BLOW'], foe_position=dict(FOE_CELL),
                                 bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id)
    cells = lattice_cells(combat._load_session(mid).engine, OWNER)
    assert (FOE_CELL['x'], FOE_CELL['y']) in cells, 'the hostile must stand on the lattice'
    reach(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Deal impact', target=FOE).candidate_id,
                     {'choice:needle.winter_stores': 'use', 'choice:needle.winter_stores_space': 'first'})
    assert asked(prompts, 'choice:needle.winter_stores'), 'a visible hostile on the lattice must be offered'
    spaces = asked(prompts, 'choice:needle.winter_stores_space')
    assert spaces and spaces[0]['context']['reactor_id'] == OWNER
    assert len(spaces[0]['choice']['options']) > 1, 'under and adjacent spaces must both be offered'
    engine = reload(tmp_path, mid)
    stored = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == STORED)
    assert (stored.data['x'], stored.data['y']) in cells
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 99
    hits = [v for v in engine.events if v.event_type == 'DAMAGE_COMMITTED' and v.target_ids == (FOE,)]
    assert hits and hits[-1].payload['reduced_to'] < hits[-1].payload['rolled_or_pending_damage'], \
        'the stored fracture must reduce the triggering damage'


def test_winter_stores_declined_leaves_the_damage_alone(tmp_path):
    combat, table, mid = fixture(tmp_path, ['TAL_ICE_WINTER_STORES_THE_BLOW'], foe_position=dict(FOE_CELL),
                                 bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id)
    reach(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Deal impact', target=FOE).candidate_id,
           {'choice:needle.winter_stores': None})
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == STORED for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 100, 'a decline costs nothing'
    assert engine.state.actors[OWNER].reaction_available, 'a declined reaction is not spent'


def test_winter_stores_unseen_creature_is_not_offered(tmp_path):
    """The printed trigger is "a creature you can see", so a blinded owner is never offered."""
    combat, table, mid = fixture(tmp_path, ['TAL_ICE_WINTER_STORES_THE_BLOW'], foe_position=dict(FOE_CELL),
                                 bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Blind myself', target=OWNER).candidate_id)
    reach(table, mid, ALLY)
    prompts = settle(table, mid, candidate(combat, mid, 'Deal impact', target=FOE).candidate_id)
    assert not asked(prompts, 'choice:needle.winter_stores')
    assert not any(c.condition_id == STORED
                   for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())


# --------------------------------------------------------------------------- Frozen Meridian Bind
@pytest.mark.parametrize('pay', ['use', None])
def test_frozen_meridian_bind_owner_chooses_the_cp_payment(tmp_path, pay):
    """Printed "Cost: 1 CP" on a No Action reaction: the owner decides whether to pay.

    Before this lane the table spent the CP automatically whenever the row was present.
    """
    # Adjacent to the lattice, not on it: Catch Step is the offered response there, and the
    # printed trigger only needs the target "on or adjacent to one of your Lattice Spaces".
    combat, table, mid = fixture(tmp_path, ['TAL_ICE_FROZEN_MERIDIAN_BIND'],
                                 foe_position={'x': 1, 'y': 6}, bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Mark foe', target=FOE).candidate_id)
    prompts = reach(table, mid, FOE, {'choice:needle.fracture_response': 'catch',
                                      'choice:needle.meridian_bind': pay})
    payment = asked(prompts, 'choice:needle.meridian_bind')
    assert payment, 'the owner must be asked before the 1 CP is spent'
    assert payment[0]['context']['reactor_id'] == OWNER
    engine = reload(tmp_path, mid)
    frozen = [c for c in engine.state.actors[FOE].conditions.values()
              if c.condition_id == 'condition:typed.restrained' and c.source_actor_id == OWNER]
    if pay == 'use':
        assert engine.state.actors[OWNER].resources['resource:core.qi'] == 99, 'the paid CP leaves the pool'
        assert frozen, 'a failed Strength save must Restrained the target'
    else:
        assert engine.state.actors[OWNER].resources['resource:core.qi'] == 100, 'declining keeps the CP'
        assert not frozen, 'declining does not Restrained the target'


# --------------------------------------------------------------------------- Bitter Edge
@pytest.mark.parametrize('dtype', ['COLD', 'PIERCING'])
def test_bitter_edge_asks_the_damage_type_on_the_coated_strike(tmp_path, dtype):
    """Printed: "it may deal extra Cold or Piercing damage equal to your Proficiency Bonus."

    Before this lane the extra damage was always Cold and the owner was never asked.
    """
    combat, table, mid = fixture(tmp_path, ['TAL_ICE_BITTER_EDGE'], foe_position=dict(FOE_CELL),
                                 owner_kit={'starting_kit': KIT}, bundle_transform=setup)
    prompts = settle(table, mid, candidate(combat, mid, 'Bitter Edge', target=OWNER).candidate_id)
    coat = asked(prompts, 'choice:needle.bitter_coat')
    assert coat, 'weapon and unarmed strikes require a coating choice'
    assert coat[0]['context']['reactor_id'] == OWNER, 'the owner coats one of its own strikes'
    prompts = settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id,
                     {'choice:needle.bitter_type': dtype})
    choice = asked(prompts, 'choice:needle.bitter_type')
    assert choice, 'the damage type is the wielder owner\'s choice'
    assert {o['id'] for o in choice[0]['choice']['options']} == {'COLD', 'PIERCING'}
    engine = reload(tmp_path, mid)
    hit = next(v for v in engine.events
               if v.event_type == 'DAMAGE_COMMITTED' and v.source_definition_id == T + 'BITTER_EDGE')
    assert hit.payload['damage_type'] == dtype


def test_bitter_edge_coated_strike_identity_survives_reload(tmp_path):
    """Printed: "You coat one weapon, natural weapon, or unarmed strike"; others stay bare."""
    combat, table, mid = fixture(tmp_path, ['TAL_ICE_BITTER_EDGE'], foe_position=dict(FOE_CELL),
                                 owner_kit={'starting_kit': KIT}, bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Bitter Edge', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    edge = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == BITTER)
    coated = edge.data.get('strike')
    assert coated, 'the coated strike must be identified in saved state'
    strikes = [source for source, _name in _melee_strikes(engine, engine.state.actors[OWNER])]
    assert strikes, 'the wielder must own at least one strike to coat'
    assert coated in strikes, 'only a strike the wielder owns may be coated'


# --------------------------------------------------------------------------- Crystal Step
@pytest.mark.parametrize('transfer', ['transfer', None])
def test_crystal_step_owner_moves_the_mark_or_declines(tmp_path, transfer):
    """Printed: "If you appear adjacent to a creature with a Fracture Mark, you may immediately
    move that mark to another creature within 10 feet of you."

    Before this lane the table silently moved the mark to the nearest hostile, with no question
    about the donor, the recipient, or whether to move it at all.
    """
    combat, table, mid = fixture_two_foes(tmp_path, ['TAL_ICE_CRYSTAL_STEP'],
                                          positions={FOE: {'x': 1, 'y': 6}, FOE2: {'x': 2, 'y': 8}})
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Mark foe', target=FOE).candidate_id)
    # Slide to the lattice space beside the marked creature, which is what arms the printed clause.
    prompts = settle(table, mid, candidate(combat, mid, 'Crystal Step', at=(2, 6)).candidate_id,
                     {'choice:needle.teleport_destination': 'cell:2,6',
                      'choice:needle.crystal_step_donor': FOE if transfer else None,
                      'choice:needle.crystal_step_target': FOE2 if transfer else None})
    landings = asked(prompts, 'choice:needle.teleport_destination')
    assert landings, 'the owner explicitly chooses where to land'
    from combat.ext.needle import position_of
    offered = {position_of(o['id']) for o in landings[0]['choice']['options']}
    cells = lattice_cells(combat._load_session(mid).engine, OWNER)
    assert {(p.x, p.y) for p in offered} <= cells, 'Crystal Step may only land on your own lattice'
    donor = asked(prompts, 'choice:needle.crystal_step_donor')
    assert donor, 'the owner must be asked before the mark moves'
    assert donor[0]['context']['reactor_id'] == OWNER
    assert {o['id'] for o in donor[0]['choice']['options']} == {FOE}, 'only the adjacent marked creature'
    engine = reload(tmp_path, mid)
    if transfer:
        recipient = asked(prompts, 'choice:needle.crystal_step_target')
        assert recipient and {o['id'] for o in recipient[0]['choice']['options']} == {FOE2}
        assert not marked(engine.state.actors[FOE], OWNER), 'the mark leaves the donor'
        assert marked(engine.state.actors[FOE2], OWNER), 'the mark lands on the chosen recipient'
    else:
        assert not asked(prompts, 'choice:needle.crystal_step_target'), 'declining asks nothing further'
        assert marked(engine.state.actors[FOE], OWNER), 'declining keeps the mark where it was'


def test_crystal_step_cannot_start_off_the_casters_lattice(tmp_path):
    combat, table, mid = fixture_two_foes(tmp_path, ['TAL_ICE_CRYSTAL_STEP'],
                                          positions={FOE: {'x': 1, 'y': 6}, FOE2: {'x': 2, 'y': 8}})
    engine = reload(tmp_path, mid)
    assert not lattice_cells(engine, OWNER)
    assert not any(g['label'] == 'Crystal Step' for g in table.state(mid)['menu']['actions'])
