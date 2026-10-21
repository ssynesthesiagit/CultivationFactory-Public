"""CW2r1 Beastmastery finding: Pack Attack counts an allied Tame Creature of another Tamer.

Only the Beastmastery case of the CW2r1 review batch applies to this lane
(AUTO106); the Fate, Formations and Dark cases belong to their own spheres and
their source rows do not exist on this branch.
"""
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.cw2_service_support import add_action
from tests.h1_support import sheet
from tests.worker2_support import settle, settle_turn as turn, reload
from tests.worker2_support import ROOT, OWNER, ALLY, FOE, candidate


@pytest.mark.parametrize('assistance', ['near', 'distant', 'incapacitated'])
def test_pack_attack_with_another_allied_tamers_beast(tmp_path, assistance):
    owner = compile_character(sheet(['TAL_BEASTMASTERY_BEAST_TAMER',
        'tianxia.talent.beastmastery.pack_attack']), actor_id=OWNER,
        reaction_plan={'ask': True}, summon_plan={'beasts': ['wolf'], 'mount': ''})
    ally = compile_character(sheet(['TAL_BEASTMASTERY_BEAST_TAMER']), actor_id=ALLY,
        summon_plan={'beasts': ['wolf'], 'mount': ''})
    foe = compile_character(sheet([]), actor_id=FOE)
    add_action(owner, 'Prepare incapacitation', [{'type': 'condition', 'condition': 'incapacitated',
        'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])
    combat = CombatService(ROOT, tmp_path); table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match([owner, ally, foe], [OWNER, ALLY, FOE],
        {OWNER: 'team:factory', ALLY: 'team:factory', FOE: 'team:opponents'},
        {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 14 if assistance == 'distant' else 4, 'y': 6},
         FOE: {'x': 3, 'y': 4}}, combat.factory_arenas()['battlefield:factory_pillar_arena'],
        [OWNER, ALLY], [FOE], control_modes={a: 'MANUAL' for a in [OWNER, ALLY, FOE]},
        match_seed='AUTO29', display_name='CW2r1 two allied Tamers', maximum_rounds=10)['match_id']
    attacker, partner = owner['summons'][0]['actor_id'], ally['summons'][0]['actor_id']
    if assistance == 'incapacitated':
        turn(table, mid, OWNER)
        settle(table, mid, candidate(combat, mid, 'Prepare incapacitation', target=partner).candidate_id)
    turn(table, mid, attacker)
    e = reload(tmp_path, mid)
    assert e.state.actors[partner].summon['owner'] == ALLY
    assert (e._distance_actor_to_actor(e.state.actors[partner], e.state.actors[FOE]) <= 5) == (assistance != 'distant')
    settle(table, mid, candidate(combat, mid, 'Bite', target=FOE).candidate_id)
    attack = next(e for e in reversed(reload(tmp_path, mid).events)
                  if e.event_type == 'ATTACK_ROLLED' and e.actor_id == attacker)
    assert attack.payload['mode'] == ('ADVANTAGE' if assistance == 'near' else 'NORMAL')