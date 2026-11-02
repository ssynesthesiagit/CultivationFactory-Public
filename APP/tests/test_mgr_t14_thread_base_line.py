"""Guide's real acquisition, table intent, saved grant and attack receipts."""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from combat.tabletop_service import TabletopService
from combat.ext.thread_base_line import DRAW, grants
from combat.shot_geometry import reduce_cover
from tests.h1_support import ROOT, sheet
from tests.test_a2_thread import cold, settle
from tests.test_r4_integration import P, F, S, candidate, reach, send


def fight(tmp_path, cover=2, *, peer=False, miss=False):
    ids = [P, F, S]
    bundles = []
    for aid in ids:
        doc = sheet([DRAW] if aid == P or peer and aid == S else [], cl=20)
        if 'spheres_and_talents' in doc:
            # Use the source's automatic base package, never a learned-talent
            # duplicate of the base row. No talent modifiers are present.
            doc['spheres_and_talents']['learned_talent_record_ids'] = []
        doc['identity']['display_name'] = aid.rsplit('-', 1)[-1]
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 2000
        doc['ability_scores_and_statistics']['technique_attack_bonus'] = -1000 if miss else 1000
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid))
    arena = to_battlefield(normalize_map({'width_squares': 9, 'height_squares': 9,
        'terrain': [] if not cover else [{'type': 'SIMPLE_COVER',
                                         'cells': [[4, 6], [4, 7]]}]}))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, ids,
        {P: 'team:a', F: 'team:b', S: 'team:a' if peer else 'team:b'},
        {P: {'x': 3, 'y': 6}, F: {'x': 8, 'y': 6}, S: {'x': 3, 'y': 7}},
        arena, ids, [], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='A2THREAD', display_name='Thread base line', maximum_rounds=10)['match_id']
    reach(table, mid, P)
    return combat, table, mid


def attack(table, mid, option='Guide', target=F):
    # Actual paid Qi Thread avoids relying on the unresolved mundane-stock path.
    settle(table, mid, candidate(table, mid, 'Draw the Line: ' + option + ' (Qi Thread)', target), decline=True)


def rolls(engine, actor=P):
    return [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == actor]


@pytest.mark.parametrize('cover', [0, 2])
def test_guide_next_roll_uses_only_half_cover_and_consumes_after_reload(tmp_path, cover):
    _, table, mid = fight(tmp_path, cover)
    attack(table, mid)
    e = cold(tmp_path, mid)
    assert grants(e.state.actors[F], P)
    assert rolls(e)[-1].payload['cover_bonus'] == cover
    assert e.state.actors[F].current_hp == 2000  # no unprinted base damage
    assert e.state.actors[P].resources['resource:core.qi'] == 29
    # Pure menu/preview queries must not spend the next-roll grant.
    table.state(mid)
    table.state(mid)
    assert grants(cold(tmp_path, mid).state.actors[F], P)
    reach(table, mid, F)
    reach(table, mid, P)
    attack(table, mid, 'Snare')
    e = cold(tmp_path, mid)
    assert rolls(e)[-1].payload['cover_bonus'] == (0 if cover == 2 else cover)
    assert not grants(e.state.actors[F], P)
    assert e.state.actors[F].current_hp == 2000


def test_guide_wrong_owner_attack_does_not_consume_and_other_cover_is_unchanged(tmp_path):
    _, table, mid = fight(tmp_path, peer=True)
    attack(table, mid)
    reach(table, mid, S)
    attack(table, mid, 'Snare')
    e = cold(tmp_path, mid)
    assert rolls(e, S)[-1].payload['cover_bonus'] == 2
    assert grants(e.state.actors[F], P)
    assert reduce_cover(e, e.state.actors[S], e.state.actors[F], 2) == 2
    assert reduce_cover(e, e.state.actors[P], e.state.actors[S], 2) == 2
    assert reduce_cover(e, e.state.actors[P], e.state.actors[F], 99) == 99
    assert reduce_cover(e, e.state.actors[P], e.state.actors[F], 5) == 5


def test_guide_unused_grant_ends_after_sources_next_turn(tmp_path):
    _, table, mid = fight(tmp_path)
    attack(table, mid)
    reach(table, mid, F)
    reach(table, mid, P)
    assert grants(cold(tmp_path, mid).state.actors[F], P)
    menu = table.state(mid)['menu']
    assert send(table, mid, menu['end_turn'])['status'] == 'COMMITTED'
    assert not grants(cold(tmp_path, mid).state.actors[F], P)


def test_guide_missed_thread_attack_grants_nothing(tmp_path):
    _, table, mid = fight(tmp_path, miss=True)
    attack(table, mid)
    e = cold(tmp_path, mid)
    assert not rolls(e)[-1].payload['provisional_hit']
    assert not grants(e.state.actors[F], P)
