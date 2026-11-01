"""The owner's 22 free ranged hit edits reach hover text, bundles and a committed/reloaded table fight."""
import hashlib
import json

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import Context, _effect_dice
from tests.h1_support import ROOT, sheet, script
from tests.test_lock2_persistence import act

IDS = '''ASH_BASE_CINDER_BRAND BLOOD_BASE_BLOOD_THREAD TAL_CHAINS_CHAIN_LASH_BASE
DISEASE_BASE_SOW_THE_FEVER_SEED TAL_DREAM_DREAM_NEEDLE EARTH_BASE_WEIGHT_SEEKING_CLOD
FIRE_TAL_FLAME_LASH FIRE_BASE_IGNITE TAL_FLOWERS_PETAL_DART TAL_FORCE_IMPACT
GLASS_BASE_GLASS_SHARD ICE_BASE_SHARD_NEEDLE TAL_MAGMA_MAGMA_GLOB POISON_BASE_DELIVER_THE_DOSE
tianxia.talent.shadow.shadow_fang TAL_SMOKE_CINDER_WISP TAL_SPACE_SPATIAL_EDGE STARS_BASE_STARBOLT
SWORD_BASE_SWORD_BEYOND_HAND TAL_VERDANT_GROWTH_SEED_THORN_STRIKE TAL_VOID_VOID_NEEDLE WATER_BASE_WATER_LASH'''.split()
BASE = ROOT / 'authority/typed_mechanics'
PLAYER, FOE = 'actor:factory.mod1-player', 'actor:factory.mod1-foe'


def main_hits(node):
    """Main attack damage only: optional extra damage and modifiers are separate effects."""
    if isinstance(node, list):
        for item in node:
            yield from main_hits(item)
    elif isinstance(node, dict):
        # force_impact_wall is the Impact wall-section copy of an attack row (61ea62bc); its main damage is the same row.
        if node.get('type') in ('attack', 'force_impact_wall'):
            # Reviewed plug-ins may wrap the main damage to replace its dice
            # for an owned state. Inspect that row without treating optional
            # extra damage, saves or modifiers as the main attack damage.
            rows = []
            for row in node.get('on_hit', []):
                if row.get('type') == 'damage':
                    rows.append(row)
                elif row.get('type') not in ('attack', 'save', 'extra_damage', 'damage_modifier'):
                    rows.extend(child for child in row.get('effects', []) if child.get('type') == 'damage')
            hit = next(iter(rows), None)
            if hit:
                yield hit
        for item in node.values():
            yield from main_hits(item)


@pytest.fixture(scope='module')
def data():
    from tools.typed_mechanics_helpers import source_texts
    return (json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text()),
            json.loads((BASE / 'rules_text.json').read_text()),
            json.loads((BASE / 'owner_text_edits.json').read_text())['records'], source_texts())


@pytest.mark.parametrize('mid', IDS)
def test_owner_edit_hover_hash_and_main_hit_typing(mid, data):
    authority, texts, edits, sources = data
    [pair] = edits[mid]['replace']
    assert '+ your Path key ability modifier' in pair['new']
    assert pair['new'] in texts[mid]
    assert '"I want to add the cultivation mod to void needle as well"' in edits[mid]['why']
    record = authority['mechanics'][mid]
    assert record['source']['text_sha256'] == hashlib.sha256(sources[mid].encode()).hexdigest()
    report = next(row for row in authority['owner_text_edits'] if row['mechanic_id'] == mid)
    assert report == {'mechanic_id': mid, 'status': 'typed_from_edited_text', 'problems': []}
    hits = list(main_hits([record['effects'], record.get('options', [])]))
    assert hits and all(hit['formula'] == 'key_ability_modifier' for hit in hits)
    from tools.typed_mechanics_helpers import _FINAL_FIELDS
    reviews = [BASE / 'reviewed_final.json', *sorted((BASE / 'reviewed_final.d').glob('*.json'))]
    finals = [rows[mid] for path in reviews if mid in (rows := json.loads(path.read_text()).get('mechanics', {}))]
    assert len(finals) == 1  # Updating an existing review must not introduce a second review.
    assert all(finals[0].get(field) == record.get(field) for field in _FINAL_FIELDS)


@pytest.mark.parametrize('mid', IDS)
@pytest.mark.parametrize('cl', [1, 5, 11, 17])
@pytest.mark.parametrize('key,score', [('WIS', 18), ('DEX', 8)])
def test_every_compiled_attack_option_keeps_key_modifier(mid, cl, key, score):
    doc = sheet([mid], cl=cl, key=key, score=score)
    # Distinguish the Path key from the other abilities.
    for ability in doc['ability_scores_and_statistics']['abilities']:
        if ability['ability'] != key:
            ability.update(score=12, modifier=1)
    bundle = compile_character(doc, actor_id=PLAYER)
    rows = [row['parameters']['typed'] for row in bundle['action_catalog']
            if row.get('parameters', {}).get('typed', {}).get('source') == mid
            or row.get('parameters', {}).get('typed', {}).get('option_of') == mid]
    assert rows, mid
    for row in rows:
        hits = list(main_hits(row['effects']))
        assert hits, (mid, row)
        assert all(hit['formula'] == 'key_ability_modifier' for hit in hits)
        assert row['numbers']['key_mod'] == (score - 10) // 2
        ctx = Context(None, None, None, None, row, [], None, {})
        for hit in hits:
            dice = ctx.dice(_effect_dice(ctx, hit), flat=int(hit.get('flat') or 0), formula=hit['formula'])
            assert dice.modifier == (score - 10) // 2


def test_ignite_burn_and_overheat_extra_are_unchanged(data):
    record = data[0]['mechanics']['FIRE_BASE_IGNITE']
    assert 'increase Burn damage by your Path key ability modifier, minimum 1;' in data[1]['FIRE_BASE_IGNITE']
    burn = next(option for option in record['options'] if option['label'] == 'Increase Burn Damage')
    [extra] = [hit for attack in burn['effects'] for hit in attack.get('on_hit', []) if hit['type'] == 'damage_modifier']
    assert extra['formula'] == 'key_ability_modifier'
    assert 'Augment - 1 CP: Roll one additional damage die for Ignite.' in data[1]['FIRE_BASE_IGNITE']


@pytest.mark.parametrize('critical,dice_count', [(False, 2), (True, 4)])
@pytest.mark.parametrize('stored_before_edit', [False, True])
def test_void_needle_table_hit_and_crit_keep_flat_modifier_on_reload(tmp_path, monkeypatch, critical, dice_count, stored_before_edit):
    original = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, *args, **kwargs):
        script(engine, [20 if critical else 19, *([1] * 40)])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', hit)
    attacker = sheet(['TAL_VOID_VOID_NEEDLE'], key='WIS', score=18, cl=5)
    bundles = [compile_character(attacker, actor_id=PLAYER), compile_character(sheet([]), actor_id=FOE)]
    if stored_before_edit:
        # A historical saved bundle contains its old hit formula, independent of today's authority.
        for action in bundles[0]['action_catalog']:
            for damage in main_hits(action.get('parameters', {}).get('typed', {})):
                damage['formula'] = 'none'
    modifier = 0 if stored_before_edit else 4
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [PLAYER, FOE], {PLAYER: 'team:factory', FOE: 'team:opponents'},
        {PLAYER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [PLAYER], [FOE],
        control_modes={PLAYER: 'MANUAL', FOE: 'MANUAL'}, match_seed='MOD1',
        display_name='Ranged modifier regression', maximum_rounds=20)['match_id']
    while table.state(mid)['menu']['actor_id'] != PLAYER:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    state = table.state(mid)
    session = combat._load_session(mid)
    hp = session.engine.state.actors[FOE].current_hp
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.display_name == 'Void Needle: Empty Vitality' and c.target_ids == (FOE,))
    assert table.act(mid, candidate.candidate_id, state['menu']['decision_id'], state['menu']['state_version'],
                     state['last_sequence'], [])['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)
    boundary = fresh.history(mid)['boundaries'][-1]
    rolls = [e['payload'] for e in boundary['events'] if e['event_type'] == 'DAMAGE_ROLLED']
    assert [roll['expression'] for roll in rolls] == [f'{dice_count}d8+{modifier}']
    assert fresh._load_session(mid).engine.state.actors[FOE].current_hp == hp - dice_count - modifier
