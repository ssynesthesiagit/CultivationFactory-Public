"""Public synthetic table regressions for perceived Duel targets and saved cards."""
import json

import pytest

from combat.canonical import canonical_sha256
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.target_knowledge import can_see, located
from combat.targeting import line_of_effect
from tests.h1_support import ROOT
from tests.worker2_support import OWNER, FOE, ALLY, fixture, candidate, settle, reload, turn
from combat.factory_compiler import compile_character
import zipfile
from tests.h1_support import sheet

BASE = 'tianxia.subpath.qi.hidden_thunder_draw_saber_cultivator.feature.'
DUEL = BASE + 'one_breath_duel'
CONDITION = 'condition:typed.hidden_thunder_duel'


def declaration_fixture(tmp_path, _talents, *, cl=10, owner_features=(), named=False,
                        positions=None, foe_position=None):
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
    combat, table = CombatService(ROOT, tmp_path), None
    table = TabletopService(combat, tmp_path)
    places = positions or {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6},
                           FOE: foe_position or {'x': 6, 'y': 6}}
    mid = combat._finish_factory_match(bundles, ids,
        {OWNER: 'team:factory', ALLY: 'team:factory', FOE: 'team:opponents'}, places,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [OWNER, ALLY], [FOE], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='HIDDEN-THUNDER-DUEL', display_name='Hidden-Thunder Duel',
        maximum_rounds=15)['match_id']
    turn(table, mid, OWNER)
    return combat, table, mid


def held(engine):
    return [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == CONDITION]


def duel_options(engine):
    return [c for c in engine.legal_candidates() if c.target_ids == (FOE,)
            and engine.action_catalog.get(c.source_definition_id)
            and engine.action_catalog[c.source_definition_id].display_name == 'One-Breath Duel']


@pytest.mark.parametrize('sense,solid,feet,legal', [
    ('tremorsense', False, 25, True),
    ('spiritual_truesight', False, 25, True),
    (None, False, 25, False),
    ('tremorsense', True, 25, False),
    ('tremorsense', False, 65, False),
])
def test_perceived_duel_table_and_ai_keep_effect_path_and_range(tmp_path, sense, solid, feet, legal):
    def prepare(bundles):
        bundles[0]['senses'] = {'rows': [
            {'sense': sense, 'range_ft': 120, 'when': 'always'}
        ] if sense else []}
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])

    def curtain(arena):
        if solid:
            return  # Preserve the public arena's real central pillar.
        arena['obstacles'] = []
        arena['terrain_regions'] = [{'region_id': 'curtain',
            'terrain_type': 'SIGHT_BLOCKED', 'movement_cost': 0,
            'cells': [{'x': 4, 'y': 1}]}]
    positions = ({OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 12, 'y': 6}}
                 if solid else {OWNER: {'x': 1, 'y': 1}, ALLY: {'x': 1, 'y': 2},
                                FOE: {'x': 1 + feet // 5, 'y': 1}})
    combat, table, mid = fixture(tmp_path, [], cl=10, owner_features=[DUEL],
        named=True, bundle_transform=prepare, battlefield_transform=curtain, positions=positions)
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert not can_see(engine, owner, foe)
    assert located(engine, owner, foe) is bool(sense)
    assert line_of_effect(engine, owner, target=foe) is (not solid)
    assert bool(duel_options(engine)) is legal
    if legal:
        # Opt-in is local to this owned compiled selector, never a global
        # permission for every non-attack or a way around explicit sight.
        from combat.recipients import allowed
        action = engine.action_catalog[duel_options(engine)[0].source_definition_id]
        typed = action.parameters['typed']
        for overrides in [{'requires_perception': False}, {'requires_seen_target': True}]:
            ordinary = action.model_copy(update={'parameters': {
                **action.parameters, 'typed': {**typed, **overrides}}})
            assert not allowed(engine, owner, foe, ordinary)
    manual = [o for group in table.state(mid)['menu']['actions'] if group['label'] == 'One-Breath Duel'
              for o in group['options'] if o['target_ids'] == [FOE]]
    assert bool(manual) is legal
    policy, _ = PolicyLibrary(ROOT).for_actor(OWNER)
    ai = [c for c in build_decision_context(engine, policy, for_ai=True).legal_candidates
          if c.display_name == 'One-Breath Duel' and c.target_ids == (FOE,)]
    assert bool(ai) is legal
    if legal:
        settle(table, mid, duel_options(engine)[0].candidate_id)
        restored = reload(tmp_path, mid)
        assert held(restored)[0].data['target_id'] == FOE
        assert restored.state.actors[OWNER].resources['resource:core.qi'] == 96


def condition_cards(value):
    if isinstance(value, dict):
        if value.get('condition_id') == CONDITION and 'rule_text' in value:
            yield value
        for child in value.values():
            yield from condition_cards(child)
    elif isinstance(value, list):
        for child in value:
            yield from condition_cards(child)


def test_duel_status_resolves_current_target_after_reload_and_replacement(tmp_path):
    combat, table, mid = declaration_fixture(tmp_path, [], owner_features=[DUEL], named=True)
    for target, name in [(FOE, 'Mara'), (ALLY, 'Tobin')]:
        settle(table, mid, candidate(combat, mid, 'One-Breath Duel', target=target).candidate_id)
        engine = reload(tmp_path, mid)
        assert held(engine)[0].data['target_id'] == target
        assert name not in json.dumps(held(engine)[0].data), 'Persist identity, not a copied name'
        cold_table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        cards = list(condition_cards(cold_table.state(mid)))
        assert cards
        assert all(name in c['display_name'] and name in c['rule_text'] for c in cards)
        assert all(target not in c['rule_text'] for c in cards)
        if target == FOE:
            turn(table, mid, ALLY)
            turn(table, mid, OWNER)


def test_duel_status_does_not_reveal_unseen_or_missing_identity(tmp_path):
    from combat.ext.hidden_thunder import describe_duel
    combat, table, mid = declaration_fixture(tmp_path, [], owner_features=[DUEL], named=True,
                                           foe_position={'x': 12, 'y': 6})
    engine = reload(tmp_path, mid)
    for target in [FOE, 'actor:missing']:
        card = describe_duel(engine, engine.state.actors[OWNER],
                             {'condition_id': CONDITION}, {'target_id': target})
        assert 'The selected creature' in card['rules']
        assert 'Mara' not in json.dumps(card) and target not in json.dumps(card)
