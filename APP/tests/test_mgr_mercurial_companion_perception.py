"""Quicksilver Step's companion choice offers only creatures the actor perceives.

Review finding (MGR-T14 Sol, 2026-10-19): step_begin recorded every nearby creature and carry_companion offered
them by name. A hidden or invisible neighbour the actor cannot perceive must not be offered.
"""
from combat import senses
from tests.worker2_support import OWNER, ALLY, fixture, candidate, settle, reload
from tests.cw2_service_support import add_action

QUICKSILVER_STEP = 'tianxia.subpath.qi.mercurial_cultivator.feature.quicksilver_step'


def test_quicksilver_companion_prompt_omits_unperceived_neighbour(tmp_path):
    def prepare(bundles):
        add_action(bundles[0], 'Invisible', [{'type': 'condition', 'condition': 'invisible',
            'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])
    combat, table, mid = fixture(tmp_path, [QUICKSILVER_STEP], cl=14, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, 'Invisible', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    assert engine._distance_actor_to_actor(owner, ally) <= 5
    assert not senses.perceives(engine, owner, ally)
    prompts = settle(table, mid, candidate(combat, mid, 'Quicksilver Step').candidate_id, choices={
        'choice:needle.teleport_destination': 'first', 'choice:needle.mercurial.companion': None,
        'choice:needle.mercurial.arrival': ['temporary_hp']})
    offered = [o['id'] for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.mercurial.companion'
               for o in p['choice']['options']]
    assert ALLY not in offered
