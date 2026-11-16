"""GHOSTMARK1BF7: the table state never publishes the ids of creatures the viewer cannot see.

The browser asks, by id, about the creatures it remembers; the service answers only which of those are still in
the fight. A creature nobody asked about (for example one out of sight) must not appear anywhere in the payload.
"""
import json
from pathlib import Path

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import normalize_map, to_battlefield
from tests.test_save_reload_equivalence import _install_factory

APP = Path(__file__).resolve().parents[1]


def _match(tmp_path, far=False):
    ids, bundles = _install_factory(tmp_path, 'rosterids', [], None)
    combat = CombatService(APP, tmp_path)
    document = normalize_map(json.loads((APP / 'combat/maps/builtin-realm-waterfall-gorge.json').read_text()))
    arena = to_battlefield(document)
    # far=True puts the two fighters at opposite team starts (about 39 squares apart), so neither is shown to the other.
    spots = ({ids[0]: {'x': 5, 'y': 16, 'z': 0}, ids[1]: {'x': 44, 'y': 16}} if far else
             {ids[0]: {'x': 23, 'y': 32, 'z': 0}, ids[1]: {'x': 23, 'y': 24}})
    mid = combat._finish_factory_match(bundles, ids,
        {ids[0]: 'team:a', ids[1]: 'team:b'},
        spots,
        arena, [ids[0]], [ids[1]], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='ROSTERIDS', display_name='Roster ids', maximum_rounds=10)['match_id']
    return TabletopService(combat, tmp_path), mid, ids


def test_state_publishes_no_roster_ids_without_a_request(tmp_path):
    service, mid, ids = _match(tmp_path)
    state = service.state(mid, fog=True, fog_view='own', fog_actor_ids=(ids[0],))
    assert 'roster_ids' not in state
    assert 'remembered_in_match' not in state
    visible = {a['entity_id'] for a in state['presentation']['actors']}
    text = json.dumps(state)
    for aid in ids:
        if aid not in visible:
            # An unseen creature's id (and so its existence) is not published.
            assert f'"{aid}"' not in text


def test_remembered_ids_answer_only_for_creatures_this_viewer_was_shown(tmp_path):
    # Regression (GHOSTMARK1BF8R blocking): a fog-limited viewer who never saw a fighter must get no answer about it,
    # even though it is in the fight. The answer is per viewer: ids[1] is shown to ids[1]'s own view only.
    service, mid, ids = _match(tmp_path, far=True)
    own_view = service.state(mid, fog=True, fog_view='own', fog_actor_ids=(ids[1],))
    assert ids[1] in own_view['fog_perception'][ids[1]]['creatures']
    hidden = service.state(mid, fog=True, fog_view='own', fog_actor_ids=(ids[0],),
                           remembered_ids=(ids[1], 'not-in-this-fight'))
    assert ids[1] not in hidden['fog_perception'][ids[0]]['creatures']
    assert hidden['remembered_in_match'] == []
    # The viewer who was shown ids[1] gets the confirmation: still in the fight, and nothing else.
    seen = service.state(mid, fog=True, fog_view='own', fog_actor_ids=(ids[1],),
                         remembered_ids=(ids[1], 'not-in-this-fight'))
    assert seen['remembered_in_match'] == [ids[1]]
    assert 'roster_ids' not in seen
