"""Wax-Tempered Body: once per scene, Advantage on the saving throw against being Grappled, Restrained or knocked Prone."""
from tests.test_a2_foundations3 import add_action
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn

INSIGHT = 'insight.wax-tempered-body'
YIELD = 'reaction:typed.insight.wax-tempered-body'
GRAPPLE = {'type': 'save', 'ability': 'STR', 'dc': 40, 'save_categories': ['grappled'],
           'on_fail': [{'type': 'condition', 'condition': 'grappled', 'applies_to': 'target'}], 'on_success': []}


def _setup(tmp_path, insights=(INSIGHT,)):
    def delivery(bundles):
        for name, tag, condition in (('Grapple pressure', 'grappled', 'grappled'), ('Fright pressure', 'frightened', 'frightened')):
            add_action(bundles[2], name, [{'type': 'save', 'ability': 'STR', 'dc': 40, 'save_categories': [tag],
                       'on_fail': [{'type': 'condition', 'condition': condition, 'applies_to': 'target'}], 'on_success': []}],
                       dc=40, economy='NONE')
        # The foe grapples the owner's ally; the owner grapples the foe (the foe's save must not be shaped by the owner's Wax).
        add_action(bundles[2], 'Grapple anyone', [GRAPPLE], dc=40, economy='NONE', target_kind='ANY_CREATURE')
        add_action(bundles[0], 'Owner grapple', [GRAPPLE], dc=40, economy='NONE')
    return fixture(tmp_path, [], seed='NEXT4', owner_insights=insights, bundle_transform=delivery, owner_path=None)


def _save(combat, table, mid, name, answer='USE', target=OWNER):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, choices={YIELD: answer})


def _modes(tmp_path, mid, who=OWNER):
    engine = reload(tmp_path, mid)
    return [e.payload['mode'] for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == who]


def test_a_grapple_save_rolls_with_advantage_once_per_scene(tmp_path):
    combat, table, mid = _setup(tmp_path)
    turn(table, mid, FOE)
    _save(combat, table, mid, 'Grapple pressure')
    _save(combat, table, mid, 'Grapple pressure')
    assert _modes(tmp_path, mid) == ['ADVANTAGE', 'NORMAL']


def test_declining_keeps_the_use(tmp_path):
    combat, table, mid = _setup(tmp_path)
    turn(table, mid, FOE)
    _save(combat, table, mid, 'Grapple pressure', answer=None)
    _save(combat, table, mid, 'Grapple pressure')
    assert _modes(tmp_path, mid) == ['NORMAL', 'ADVANTAGE']


def test_a_save_against_something_else_is_not_helped(tmp_path):
    combat, table, mid = _setup(tmp_path)
    turn(table, mid, FOE)
    _save(combat, table, mid, 'Fright pressure')
    assert _modes(tmp_path, mid) == ['NORMAL']


def test_without_the_insight_there_is_no_advantage(tmp_path):
    combat, table, mid = _setup(tmp_path, insights=())
    turn(table, mid, FOE)
    _save(combat, table, mid, 'Grapple pressure')
    assert _modes(tmp_path, mid) == ['NORMAL']


def test_an_ally_saving_against_a_grapple_is_not_helped_and_the_use_is_kept(tmp_path):
    combat, table, mid = _setup(tmp_path)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Grapple anyone', target=ALLY).candidate_id, choices={YIELD: 'USE'})
    assert YIELD not in [p['context']['reaction_source_id'] for p in prompts], 'the owner was offered Yielding Wax for an ally\'s save'
    assert _modes(tmp_path, mid, ALLY) == ['NORMAL']
    _save(combat, table, mid, 'Grapple pressure')
    assert _modes(tmp_path, mid) == ['ADVANTAGE'], 'the ally\'s save spent the owner\'s once-per-scene use'


def test_an_enemy_saving_against_the_owners_grapple_is_not_shaped_by_the_owners_wax(tmp_path):
    combat, table, mid = _setup(tmp_path)
    prompts = settle(table, mid, candidate(combat, mid, 'Owner grapple', target=FOE).candidate_id, choices={YIELD: 'USE'})
    assert YIELD not in [p['context']['reaction_source_id'] for p in prompts], 'the owner was offered Yielding Wax for an enemy\'s save'
    assert _modes(tmp_path, mid, FOE) == ['NORMAL'], 'the enemy rolled with Disadvantage from the owner\'s Wax'
