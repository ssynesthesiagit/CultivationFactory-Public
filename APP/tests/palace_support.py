"""Synthetic Palace table fixtures shared by the Palace regression files.

The stable formula/two-hit mode isolates signed grants and hit allowances.
Set native=True to exercise the shipped compiled formula and attack packets.
"""
import json

from combat.factory_compiler import compile_character
from combat.ext.taiyin_palace import STATE, PICK, HAZARDS, SOURCE, FOUNDATION
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn
from tests.cw2_service_support import add_action, seal

NAME = 'Perfected — True Moon Yin Palace'


def game(tmp_path, *, stage='Perfected', allies=0, cl=5, score=8, foe_sheet=None, native=False):
    doc = sheet(['ICE_BASE_SHARD_NEEDLE', 'FIRE_BASE_IGNITE'], cl=cl, score=score,
                foundation={'foundation_id': FOUNDATION, 'stage': stage,
                    'resource': {'name': 'Lunar Yin Dew', 'resource_id': 'tianxia.resource.foundation.' + FOUNDATION,
                                 'maximum': 1, 'current': 0}})
    # Foundation acquisition comes from the imported sheet, not manually added effects.
    doc['foundation'] = {'foundation_id': FOUNDATION, 'stage': stage,
                    'resource': {'name': 'Lunar Yin Dew', 'resource_id': 'tianxia.resource.foundation.' + FOUNDATION,
                                 'maximum': 1, 'current': 0}}
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    for action in ([] if native else bundle['action_catalog']):
        typed = action.get('parameters', {}).get('typed', {})
        if typed.get('source') == SOURCE:
            # The export scrambles text: formulas as well as prose. Keep this
            # table fixture's signed CL + key input public-stable; native grant
            # folding, payment and persistence remain under test.
            for eff in typed.get('effects', []):
                if eff.get('type') == 'temp_hp':
                    eff['formula'] = 'text:your cultivation level + your path key ability modifier'
        if typed.get('source') in {'ICE_BASE_SHARD_NEEDLE', 'FIRE_BASE_IGNITE'}:
            action['attack_bonus'] = 100
            typed['attack_bonus'] = 100
            # Two real hit resolutions in one technique exercise the shared allowance.
            for eff in typed.get('effects', []):
                if eff.get('type') == 'attack':
                    eff['count'] = 2
    seal(bundle)

    def setup(bundles):
        # An unrelated Fire control should not depend on public-export
        # parsing of Ignite's menu variants (the native Ice hit is kept).
        add_action(bundles[0], 'Unrelated fire strikes', [
            {'type': 'attack', 'count': 2, 'attack_kind': 'ranged',
             'on_hit': [{'type': 'damage', 'weapon_damage': True, 'applies_to': 'target'}]}],
            typed={'sphere': 'tianxia.sphere.fire', 'attack_bonus': 100,
                   'weapon': {'damage': {'count': 1, 'sides': 4, 'modifier': 0},
                              'damage_type': 'FIRE', 'fixed_damage': 1},
                   'range_ft': 120, 'numbers': {'attack_bonus': 100}})
        packets = [('cold', [], 'cold'), ('necrotic', [], 'necrotic'),
                   ('fire', [], 'fire'), ('force', [], 'force'),
                   *[(tag, [tag], None) for tag in sorted(HAZARDS - {'damage:cold', 'cold'})],
                   ('generic fear', ['frightened'], None),
                   ('generic anti-healing', ['anti_healing'], None)]
        for b in bundles[1:3]:
            for name, tags, damage in packets:
                add_action(b, 'Pressure ' + name, [{'type': 'save', 'ability': 'con', 'dc': 1,
                    'applies_to': 'target', 'save_categories': tags,
                    'on_fail': [{'type': 'damage', 'flat': 1, 'damage_types': [damage], 'applies_to': 'target'}] if damage else [],
                    'on_success': []}])
        add_action(bundles[2], 'Sleep owner', [{'type': 'condition', 'condition': 'asleep',
                                             'applies_to': 'target'}])
        add_action(bundles[2], 'Piercing ward', [{'type': 'resistance', 'applies_to': 'self',
                   'damage_types': ['piercing'], 'duration': 'one_minute'}], target='SELF')
        add_action(bundles[0], 'Capacity check', [
            {'type': 'gain_resource', 'resource_id': 'resource:foundation.lunar_yin_dew',
             'flat': 1, 'applies_to': 'self'},
            {'type': 'gain_resource', 'resource_id': 'resource:foundation.lunar_yin_dew',
             'flat': 1, 'applies_to': 'self'}], target='SELF')
    return fixture(tmp_path, [], owner_bundle=bundle, extra_allies=allies, foe_sheet=foe_sheet,
                   battlefield={'stable_id': 'battlefield:palace-regression', 'display_name': 'Palace regression field',
                                'width_squares': 20, 'height_squares': 14,
                                'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []},
                   bundle_transform=setup, seed='MGR15PALACE')


def activate(combat, table, mid, selected=(OWNER, ALLY)):
    return settle(table, mid, candidate(combat, mid, NAME, target=OWNER).candidate_id,
                  choices={PICK: list(selected)})


def save_mode(combat, table, mid, target, packet, source=FOE):
    turn(table, mid, source)
    settle(table, mid, candidate(combat, mid, 'Pressure ' + packet, target=target).candidate_id)
    events = combat._load_session(mid).engine.events
    return next(e.payload['mode'] for e in reversed(events)
                if e.event_type == 'SAVE_ROLLED' and e.actor_id == target)


