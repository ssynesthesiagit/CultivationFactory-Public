"""Review F1/F2: physical weapon ancestry and native relocation at the table.

All state changes go through sealed effects, table commits and cold replay.
No live model clients or browser calls.
"""
import copy
import pytest
from combat.canonical import canonical_sha256
from combat import carry
from combat.item_uses import carried_item
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import fixture, reload, turn, settle, OWNER, ALLY, FOE
from tests.test_a2_blacksmith import seal, press
from tests.test_a2_blacksmith_second_pass import QUENCH, die
from tests.test_mgr_t13_blacksmith_carriers import setup, select, hammer, marks


@pytest.mark.parametrize('anchor', ['smith', 'ally'])
def test_inactive_anchor_modifier_expiry_remains_inert(anchor):
    from tests.test_auto17_blacksmith import _engine, _bundle, ME, ALLY as OTHER
    from combat.ext.effect_durations import sweep, token
    from combat.gate2_runtime_models import ModifierInstance
    e = _engine(_bundle([]))
    holder = e.state.actors[ME if anchor == 'smith' else OTHER]
    holder.active = False
    holder.modifiers['expiry-probe'] = ModifierInstance(
        modifier_id='expiry-probe', source_definition_id='test:expiry-probe',
        source_actor_id=holder.entity_id, target_id=holder.entity_id, target_field='speed_ft',
        operation='ADD', value=10, applies_to='ALL',
        expires_on=token('end', holder.entity_id, holder.turns_started))
    before = len(e.events)
    sweep(e, holder, 'END_OF_TURN', holder.entity_id)
    assert 'expiry-probe' not in holder.modifiers
    assert any(ev.event_type == 'MODIFIER_REMOVED' for ev in e.events[before:])
    assert not any('forge_mark_expires_one_at_a_time' in str(ev.payload) for ev in e.events[before:])


@pytest.mark.parametrize('ancestry', ['opportunity_of', 'weapon_source_id', 'delivered_by', 'maneuver_of', 'variant_of'])
@pytest.mark.parametrize('native', [False, True])
def test_derived_marked_attack_uses_physical_parent(tmp_path, monkeypatch, ancestry, native):
    die(monkeypatch)
    def build(bundles):
        setup()(bundles)
        for b in bundles:
            base = next(a for a in b['action_catalog'] if a['display_name'] == 'Item strike')
            base['parameters']['typed'].pop('inventory_key')
            derived = copy.deepcopy(base)
            derived.update(source_definition_id=base['source_definition_id'] + '.derived',
                           display_name='Derived strike')
            derived['parameters']['typed'][ancestry] = base['source_definition_id']
            if native:
                derived.update(resolution_kind='ATTACK', attack_bonus=2,
                               damage={'count': 1, 'sides': 2, 'modifier': 9}, damage_type='SLASHING')
                derived['parameters']['attack_kind'] = 'weapon'
            b['action_catalog'].append(derived)
            b['actor_template']['action_ids'].append(derived['source_definition_id'])
            b.pop('bundle_sha256'); b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid = fixture(tmp_path, [QUENCH], bundle_transform=build)
    select(combat, table, mid); hammer(combat, table, mid)
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    prompts = press(combat, table, mid, 'Derived strike', FOE,
                    picks={'choice:needle.blacksmith_quench': ['quench']})
    e = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.blacksmith_quench' for p in prompts)
    assert e.state.actors[FOE].current_hp < before
    assert marks(e) == 0 and not e.state.actors[OWNER].reaction_available


KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.dao', 'name': 'Dao (Saber)', 'quantity': 1}]}}
TRAITOR = 'TAL_FENCING_TRAITOROUS_BLADE'


def test_compiled_opportunity_attack_keeps_marked_weapon(tmp_path, monkeypatch):
    die(monkeypatch)
    target = FOE + '1'
    combat, table, mid = fixture(tmp_path, [QUENCH], ally_talents=[TRAITOR], extra_foes=1,
        owner_kit=KIT, ally_kit=KIT, foe_kit=KIT, bundle_transform=native_bundles,
        positions={OWNER: {'x': 3, 'y': 5}, ALLY: {'x': 4, 'y': 6},
                   FOE: {'x': 4, 'y': 5}, target: {'x': 4, 'y': 7}})
    e = reload(tmp_path, mid)
    key = carry.carrying_of(e, ALLY)['items'][0]['key']
    source = carry.item_of(carry.carrying_of(e, ALLY), key=key)['weapon_action']
    opportunity = next(a for a in e.action_catalog.values() if a.owner_id == ALLY
                       and a.display_name == 'Opportunity Attack')
    assert opportunity.parameters['typed']['opportunity_of'] == source
    assert 'inventory_key' not in opportunity.parameters['typed']
    select(combat, table, mid, key=key); hammer(combat, table, mid)
    turn(table, mid, target)
    e = reload(tmp_path, mid)
    before = e.state.actors[target].current_hp
    move = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
                and (c.destination.x, c.destination.y) == (4, 8))
    prompts = settle(table, mid, move.candidate_id, picks={
        'reaction:typed.opportunity_attack': 'first', 'choice:needle.blacksmith_quench': ['quench']})
    e = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.blacksmith_quench' for p in prompts)
    assert e.state.actors[target].current_hp < before
    assert marks(e, key=key) == 0 and not e.state.actors[OWNER].reaction_available
    assert any(ev.event_type == 'ATTACK_ROLLED' and ev.actor_id == ALLY
               and ev.source_definition_id == opportunity.source_definition_id for ev in e.events)


def native_bundles(bundles, *, owner_talents=(QUENCH,)):
    """Compile real original/borrowed weapon actions, as the match builder does."""
    weapons = [w for b in bundles for w in b['weapons']]
    for i, b in enumerate(bundles):
        talents = list(owner_talents) if b['actor_id'] == OWNER else [TRAITOR] if b['actor_id'] == ALLY else []
        doc = sheet(talents, cl=15, kit=KIT)
        doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
        bundles[i] = compile_character(doc, actor_id=b['actor_id'], reaction_plan={'ask': True},
            held_weapons=[w for w in weapons if w['owner_action'] not in b['actor_template']['action_ids']])
    for b in bundles:
        for action in b['action_catalog']:
            typed = action['parameters'].get('typed') or {}
            if typed.get('weapon') and any(e.get('attack_kind') == 'weapon' for e in typed.get('effects') or []):
                # One deterministic miss by two, preserving compiler identity.
                typed['numbers']['attack_bonus'] = 2
                for effect in typed['effects']:
                    if effect.get('type') == 'attack':
                        effect['count'] = 1
        seal(b, 'Native handover', [{'type': 'transfer_object', 'from': 'thief', 'as': 'plant',
             'item': bundles[2]['carrying']['items'][0]['key']}], target='ANY_CREATURE')
        seal(b, 'Native catch disarm', [{'type': 'condition', 'condition': 'disarmed', 'applies_to': 'target'}], target='ANY_CREATURE')
        seal(b, 'Defeat original owner', [{'type': 'damage', 'flat': 1000,
             'damage_types': ['force'], 'applies_to': 'target'}], target='ANY_CREATURE')
        b.pop('bundle_sha256'); b['bundle_sha256'] = canonical_sha256(b)


@pytest.mark.parametrize('route,defeated', [('handover', False), ('catch', False), ('handover', True), ('catch', True)])
def test_native_relocated_mark_survives_original_owner_and_reload(tmp_path, monkeypatch, route, defeated):
    die(monkeypatch)
    combat, table, mid = fixture(tmp_path, [QUENCH], ally_talents=[TRAITOR],
        owner_kit=KIT, ally_kit=KIT, foe_kit=KIT, bundle_transform=native_bundles,
        foe_position={'x': 4, 'y': 5}, extra_foes=1)
    initial = reload(tmp_path, mid)
    key = carry.carrying_of(initial, FOE)['items'][0]['key']
    source = carry.item_of(carry.carrying_of(initial, FOE), key=key)['weapon_action']
    select(combat, table, mid, owner=FOE, key=key); hammer(combat, table, mid)
    if route == 'handover':
        turn(table, mid, FOE)
        press(combat, table, mid, 'Native handover', ALLY)
        turn(table, mid, ALLY)
    else:
        turn(table, mid, ALLY)
        prompts = press(combat, table, mid, 'Native catch disarm', FOE, picks={
            'choice:needle.traitorous_blade': ['catch'], 'choice:needle.traitorous_attack': ['pass']})
        assert any(p['context']['reaction_source_id'] == 'choice:needle.traitorous_blade' for p in prompts)
    e = reload(tmp_path, mid)
    record = next(c.data for c in e.state.actors[FOE].conditions.values() if c.data.get('held_by') == ALLY)
    assert record['disables_action'] == source
    assert ('item_key' in record) == (route == 'handover')
    assert carried_item(e, FOE, key)['carrier'] == ALLY
    if defeated:
        press(combat, table, mid, 'Defeat original owner', FOE)
        e = reload(tmp_path, mid)
        assert not e.state.actors[FOE].active
        assert carried_item(e, FOE, key)['carrier'] == ALLY
        from combat.ext.blacksmith_forge import owner_has_marks
        assert owner_has_marks(e, e.state.actors[OWNER])
    # The actual compiled borrowed action is reachable with the original mark.
    borrowed = next(a for a in e.action_catalog.values() if a.owner_id == ALLY
        and a.parameters.get('requires_held_weapon') == source and '#' not in a.source_definition_id)
    assert borrowed.source_definition_id != source
    assert 'inventory_key' not in borrowed.parameters['typed']
    # Inspect availability and preview purity; then work on the same physical item.
    snapshot = e.state.model_dump(mode='json')
    e.legal_candidates()
    assert e.state.model_dump(mode='json') == snapshot
    target = FOE + '1'
    before = e.state.actors[target].current_hp
    candidate = next(c for c in e.legal_candidates() if c.source_definition_id == borrowed.source_definition_id
                     and c.target_ids == (target,))
    prompts = settle(table, mid, candidate.candidate_id,
                     picks={'choice:needle.blacksmith_quench': ['quench']})
    e = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.blacksmith_quench' for p in prompts)
    assert e.state.actors[target].current_hp < before
    assert marks(e, owner=FOE, key=key) == 0
    assert not e.state.actors[OWNER].reaction_available
    turn(table, mid, OWNER)
    select(combat, table, mid, owner=FOE, key=key)
    hammer(combat, table, mid)
    e = reload(tmp_path, mid)
    assert marks(e, owner=FOE, key=key) == 1
    if defeated:
        # Independently dated marks still expire one at a time on the inactive
        # storage anchor. Clock arithmetic is isolated to this cold-loaded clone.
        from combat.ext.blacksmith_forge import set_marks
        from combat.ext.effect_durations import sweep
        smith, anchor = e.state.actors[OWNER], e.state.actors[FOE]
        assert set_marks(e, smith, anchor, 1, QUENCH) == 0  # no actor-mark revival
        assert set_marks(e, smith, anchor, 1, QUENCH, item_key='absent') == 0
        e.state.round_number += 5
        assert set_marks(e, smith, anchor, 1, QUENCH, item_key=key) == 1
        e.state.round_number += 5
        sweep(e, smith, 'TEST')
        assert marks(e, owner=FOE, key=key) == 1
        assert owner_has_marks(e, smith)
        e.state.round_number += 5
        sweep(e, smith, 'TEST')
        assert marks(e, owner=FOE, key=key) == 0
        assert not owner_has_marks(e, smith)
        e.state.actors[ALLY].active = False
        assert set_marks(e, smith, anchor, 1, QUENCH, item_key=key) == 0
