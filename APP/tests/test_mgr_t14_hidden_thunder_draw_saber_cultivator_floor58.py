"""Paid source-sheet declarations and cold mechanical replay.

This file does not certify source acquisition or whole printed records.
"""
import pytest
from combat.ext.effect_durations import parse_round
import json
import zipfile
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import OWNER, FOE, ALLY, candidate, settle, reload, turn
BASE = 'tianxia.subpath.qi.hidden_thunder_draw_saber_cultivator.feature.'
DUEL = BASE + 'one_breath_duel'
CONDITION = 'condition:typed.hidden_thunder_duel'



def fixture(tmp_path, _talents, *, cl=10, owner_features=(), named=False, positions=None, foe_position=None):
    # Legal Qi key ability; source-sheet ownership is deliberately distinguished
    # from a native Restricted Scripture acquisition transaction in this audit.
    ids = [OWNER, ALLY, FOE]
    documents = [sheet(list(owner_features), cl=cl, key='CHA', name='Wren' if named else None),
                 sheet([], cl=cl, key='CHA', name='Tobin' if named else None),
                 sheet([], cl=cl, key='CHA', name='Mara' if named else None)]
    for aid, document in zip(ids, documents):
        document['ability_scores_and_statistics']['primary_resource']['maximum'] = 2 * cl
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    bundles = [compile_character(document, actor_id=aid, reaction_plan={'ask': True})
               for aid, document in zip(ids, documents)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    places = positions or {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6},
                           FOE: foe_position or {'x': 6, 'y': 6}}
    mid = combat._finish_factory_match(bundles, ids,
        {OWNER: 'team:factory', ALLY: 'team:factory', FOE: 'team:opponents'}, places,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [OWNER, ALLY], [FOE], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='HIDDEN-THUNDER-DUEL', display_name='Hidden-Thunder Duel', maximum_rounds=15)['match_id']
    turn(table, mid, OWNER)
    return combat, table, mid


def held(engine):
    return [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == CONDITION]


@pytest.mark.parametrize('initial_target', [FOE, ALLY, OWNER])
def test_duel_paid_declaration_reloads_and_replaces_one_target(tmp_path, initial_target):
    combat, table, mid = fixture(tmp_path, [], cl=10, owner_features=[DUEL], named=True)
    settle(table, mid, candidate(combat, mid, 'One-Breath Duel', target=initial_target).candidate_id)
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources['resource:core.qi'] == 16
    assert not owner.bonus_action_available
    assert len(held(engine)) == 1
    assert held(engine)[0].data['target_id'] == initial_target
    assert parse_round(held(engine)[0].expires_on) == (engine.state.round_number + 10, engine.state.current_slot_index)
    assert not any(e.event_type == 'RESOURCE_GAINED' and e.source_definition_id == held(engine)[0].source_definition_id
                   for e in engine.events)
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'One-Breath Duel', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    assert len(held(engine)) == 1
    assert held(engine)[0].data['target_id'] == ALLY
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 12


@pytest.mark.parametrize('owned,cl', [(False, 10), (True, 9)])
def test_duel_wrong_owner_and_below_gate(tmp_path, owned, cl):
    combat, table, mid = fixture(tmp_path, [], cl=cl, owner_features=[DUEL] if owned else [])
    engine = reload(tmp_path, mid)
    assert not any(c.source_definition_id in engine.action_catalog
                   and engine.action_catalog[c.source_definition_id].display_name == 'One-Breath Duel'
                   for c in engine.legal_candidates())
    assert not held(engine)


@pytest.mark.parametrize('cells,legal', [(12, True), (13, False)])
def test_duel_sixty_foot_boundary(tmp_path, cells, legal):
    combat, table, mid = fixture(tmp_path, [], cl=10, owner_features=[DUEL],
                               positions={OWNER: {'x': 1, 'y': 1}, ALLY: {'x': 1, 'y': 2},
                                          FOE: {'x': 1 + cells, 'y': 1}})
    engine = reload(tmp_path, mid)
    options = [c for c in engine.legal_candidates() if c.target_ids == (FOE,)
               and c.source_definition_id in engine.action_catalog
               and engine.action_catalog[c.source_definition_id].display_name == 'One-Breath Duel']
    assert bool(options) == legal
    if legal:
        settle(table, mid, options[0].candidate_id)
        assert held(reload(tmp_path, mid))[0].data['target_id'] == FOE
    else:
        assert engine.state.actors[OWNER].resources['resource:core.qi'] == 20


def test_duel_needs_actual_perception_not_only_range(tmp_path):
    # The native centre pillar blocks sight across this 45-foot route.
    combat, table, mid = fixture(tmp_path, [], cl=10, owner_features=[DUEL],
                               foe_position={'x': 12, 'y': 6})
    engine = reload(tmp_path, mid)
    assert not any(c.target_ids == (FOE,) and c.source_definition_id in engine.action_catalog
                   and engine.action_catalog[c.source_definition_id].display_name == 'One-Breath Duel'
                   for c in engine.legal_candidates())
    assert not held(engine)


def test_duel_expires_on_native_one_minute_clock(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=10, owner_features=[DUEL])
    settle(table, mid, candidate(combat, mid, 'One-Breath Duel', target=FOE).candidate_id)
    for _ in range(9):
        turn(table, mid, ALLY)
        turn(table, mid, OWNER)
    assert held(reload(tmp_path, mid))
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    assert not held(reload(tmp_path, mid))
