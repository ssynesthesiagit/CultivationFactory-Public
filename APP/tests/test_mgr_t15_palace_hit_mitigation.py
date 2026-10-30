"""Palace PB is part of the original hit, including through table persistence."""
from combat.ext.taiyin_palace import FOUNDATION, SOURCE, PICK, USED
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.cw2_service_support import add_action
from tests.worker2_support import OWNER, FOE, fixture, candidate, settle, reload, turn


def test_odd_cold_hit_and_pb_share_resistance_before_commit_and_reload(tmp_path):
    doc = sheet([], cl=5)
    doc['identity']['proficiency_bonus'] = 3
    doc['foundation'] = {'foundation_id': FOUNDATION, 'stage': 'Perfected',
        'resource': {'name': 'Lunar Yin Dew',
                     'resource_id': 'tianxia.resource.foundation.' + FOUNDATION,
                     'maximum': 1, 'current': 0}}
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def setup(bundles):
        add_action(bundles[0], 'Aligned cold strikes', [
            {'type': 'attack', 'count': 2, 'attack_kind': 'ranged',
             'on_hit': [{'type': 'damage', 'weapon_damage': True,
                         'applies_to': 'target'}]}],
            typed={'sphere': 'tianxia.sphere.ice', 'attack_bonus': 100,
                   # Native fixed damage avoids random dice (and critical dice)
                   # while still exercising the real typed hit and mitigation.
                   'weapon': {'damage': {'count': 1, 'sides': 4, 'modifier': 0},
                              'damage_type': 'COLD', 'fixed_damage': 5},
                   'range_ft': 120, 'numbers': {'attack_bonus': 100}})
        add_action(bundles[2], 'Cold ward', [
            {'type': 'resistance', 'applies_to': 'self',
             'damage_types': ['cold'], 'duration': 'one_minute'}], target='SELF')

    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle,
        bundle_transform=setup, seed='PALACE-MITIGATION',
        battlefield={'stable_id': 'battlefield:palace-mitigation',
                     'display_name': 'Palace mitigation field',
                     'width_squares': 20, 'height_squares': 14,
                     'square_size_ft': 5, 'starting_positions': {}, 'terrain_regions': []})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Cold ward', target=FOE).candidate_id)
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    palace = next(c for c in engine.legal_candidates()
                  if (engine.action_catalog.get(c.source_definition_id)
                      and engine.action_catalog[c.source_definition_id].parameters.get('typed', {}).get('source') == SOURCE)
                  and c.target_ids == (OWNER,))
    settle(table, mid, palace.candidate_id, choices={PICK: [OWNER]})
    assert reload(tmp_path, mid).state.actors[OWNER].proficiency_bonus == 3

    def strike(expected):
        engine = combat._load_session(mid).engine
        start = len(engine.events)
        hp = engine.state.actors[FOE].current_hp
        settle(table, mid, candidate(combat, mid, 'Aligned cold strikes', target=FOE).candidate_id)
        engine = reload(tmp_path, mid)
        packets = [e.payload for e in engine.events[start:]
                   if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
        # floor((5 + 3) / 2), then floor(5 / 2), NOT 2 + 1 + 2.
        assert [p['hp_damage'] for p in packets] == expected
        assert engine.state.actors[FOE].current_hp == hp - sum(expected)
        assert engine.state.actors[OWNER].turn_flags[USED] == 1

    strike([4, 2])
    # A second technique on this same turn has no remaining Palace allowance,
    # including after committing and cold-reloading the first technique.
    strike([2, 2])
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    strike([4, 2])
