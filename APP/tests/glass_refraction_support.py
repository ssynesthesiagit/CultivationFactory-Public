"""Shared helpers for the Glass Heart Refraction tests: owner declaration and a real bearer fight.

Synthetic table fixtures only: no live models, private inputs or GUI.
"""
import json
import zipfile
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.glass_heart_refraction import CHOICE, SOURCE
from non_sphere_authority.foundation_mechanics import resolve_initial_foundation_state, verified_foundation_records
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, settle, reload


def declare(combat, table, mid, scene='Major combat', actor_id=OWNER):
    """Owner/GM scene adjudication only; the character decides on their own turn."""
    forms = table.source_inputs(mid)
    return table.record_source_input(mid, SOURCE, actor_id,
        {'scene': scene,
         'reason': 'The mirror tribunal has become a decisive confrontation. I acknowledge the painful truth.'},
        forms['state_version'])


def available(engine):
    return [c for c in engine.legal_candidates() if SOURCE in c.source_definition_id]


def _glass_fight(tmp_path, *, match_seed=None):
    """A real Perfected glass fight, created without advancing any turn.

    ``match_seed`` pins the initiative deal (the journey path derives it from a
    random journey id), so a test can put a chosen creature first.
    """
    root = Path(__file__).resolve().parents[1]
    doc = sheet([], cl=15)
    initial = resolve_initial_foundation_state(verified_foundation_records()['glass_heart_meridian_v0_2A'],
        ['tianxia.path.qi_cultivation'], stage='Awakened')
    doc['foundation'] = {**initial, 'stage': 'Perfected'}
    docs = [doc, sheet([], cl=15), sheet([], cl=15)]
    ids = [OWNER, ALLY, FOE]
    for d, aid in zip(docs, ids):
        package = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.') / 'current.zip'
        package.parent.mkdir(parents=True)
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(d))
    bundles = [compile_character(d, actor_id=aid, reaction_plan={'ask': True}) for d, aid in zip(docs, ids)]
    combat = CombatService(root, tmp_path)
    table = TabletopService(combat, tmp_path)
    positions = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 5, 'y': 6}}
    teams = {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'}
    modes = {aid: 'MANUAL' for aid in ids}
    if match_seed is not None:
        result = combat._finish_factory_match(bundles, ids, teams, positions,
            combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
            ids, [], control_modes=modes, match_seed=match_seed,
            display_name='Glass Heart Refraction test', maximum_rounds=12)
        return combat, table, result['match_id']
    state = combat.journeys.create(bundles,
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        positions, {aid: 1000 for aid in ids}, modes)
    jid = state['journey_id']
    mid = combat.journey_start_combat(jid, state['revision'], teams, maximum_rounds=12)['match_id']
    return combat, table, mid


def _to_next_owner_turn(table, mid, choices):
    """Advance initiative and answer every raised choice; return the prompts."""
    if table.state(mid)['menu']['actor_id'] == OWNER:
        settle(table, mid, table.state(mid)['menu']['end_turn'])  # leave the bearer's first turn
    prompts = []
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == OWNER:
            return prompts
        prompts += settle(table, mid, table.state(mid)['menu']['end_turn'], choices=choices)
    raise AssertionError('No bearer turn')


def _asked(prompts):
    return [p for p in prompts if (p.get('context') or {}).get('reaction_source_id') == CHOICE]


