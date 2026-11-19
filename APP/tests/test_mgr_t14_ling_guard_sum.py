"""Returning Source Guard: one signed PB + Path key modifier reduction (MGR-T14-ling-guard-sum-1).

The printed clause reduces the triggering hostile damage by "your Proficiency Bonus + your Path
key ability modifier" -- one sum. The engine's generic amount reader (combat/typed_amounts.py
``static_bonus``) clamps each effect's roll-free bonus at zero (combat/typed_reactions.py
``_generic_amount``), so a record typed as two effects -- one ``"pb"``, one
``"key_ability_modifier"`` -- dropped the key modifier's negative part instead of subtracting it
from the Proficiency Bonus: PB 2 with a -1 key modifier reduced by 2 (printed: 1), and a key
modifier below -PB still reduced by the whole PB (printed: 0). One reviewed effect carrying the
aggregate formula ``"pb+key"`` resolves the signed sum before the single zero clamp.
"""
import pytest
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.ext.returning_source_guard import CONDITION
from tests.h1_support import sheet
from tests.worker2_support import ALLY, FOE, OWNER, fixture, candidate, settle, turn, reload

GUARD = 'foundation.origin_spirit_body_v0_2B.returning_source_guard'
REACTION = 'reaction:typed.' + GUARD
VESSEL_CHOICE = 'choice:needle.origin_spirit_support_value'
DEW = 'resource:foundation.spirit_source_dew'
GENERATE_DEW = 'foundation.origin_spirit_body_v0_2B.generate_spirit_source_dew'
HIT = 5  # the deterministic hostile damage packet


def owner_bundle(pb, con_score, initial=1, actor_id=OWNER):
    """The Awakened Origin-Spirit cultivator owning Returning Source Guard, with
    ``pb`` Proficiency Bonus and a Constitution score that sets the Path key modifier."""
    doc = sheet([GUARD], foundation={
        'foundation_id': 'origin_spirit_body_v0_2B', 'stage': 'Awakened', 'resource': {
            'name': 'Spirit-Source Dew', 'resource_id': 'tianxia.resource.test', 'maximum': 1, 'current': initial}})
    doc['identity']['proficiency_bonus'] = pb
    for ability in doc['ability_scores_and_statistics']['abilities']:
        if ability['ability'] == 'CON':
            ability['score'] = con_score
            ability['modifier'] = (con_score - 10) // 2
    return compile_character(doc, actor_id=actor_id, reaction_plan={'ask': True})


def add_action(bundle, name, effects, *, target_kind='HOSTILE_ENTITY', economy='ACTION', bonus=8, dc=30):
    source = 'action:test.guard.' + bundle['actor_id'].split('.')[-1] + '.' + name.lower().replace(' ', '_')
    row = {'source_definition_id': source, 'display_name': name, 'owner_id': bundle['actor_id'],
           'economy': economy, 'resolution_kind': 'TYPED', 'target_kind': target_kind, 'range_ft': 60,
           'parameters': {'typed': {'source': source, 'range_ft': 60, 'numbers': {'pb': 4, 'key_mod': 2, 'save_dc': dc, 'attack_bonus': bonus},
                                    'effects': effects, 'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 1}}
    bundle['action_catalog'].append(row)
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def setup(tmp_path, pb, con, initial=1):
    def delivery(bundles):
        # A deterministic hostile packet the foe admits against the ally (or the owner).
        add_action(bundles[2], 'Hostile strike', [
            {'type': 'damage', 'flat': HIT, 'damage_types': ['force'], 'applies_to': 'target'}])
    return fixture(tmp_path, [], seed='MGR-T14-guard-sum', owner_bundle=owner_bundle(pb, con, initial),
                   bundle_transform=delivery)


def strike(tmp_path, combat, table, mid, target):
    """The foe's Hostile strike lands on ``target``; the owner answers the guard's
    reaction prompt. Returns the cold-reloaded engine (the reload asserts replay PASS)."""
    turn(table, mid, FOE)
    candidate_id = candidate(combat, mid, 'Hostile strike', target=target).candidate_id
    # This fixture measures Guard's printed sum, reserving the independently
    # owned Vessel bonus now automated by the integrated Foundation plug-in.
    settle(table, mid, candidate_id, picks={REACTION: 'first', VESSEL_CHOICE: None})
    return reload(tmp_path, mid)


def damage_event(engine, target):
    committed = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                 and target in e.target_ids]
    assert committed, 'no damage event reached the protected creature'
    return committed[-1]


def resolved(engine):
    rows = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
            and e.source_definition_id == GUARD]
    assert rows, 'Returning Source Guard never resolved'
    return rows[-1]


def assert_guard_paid_before_new_dew(engine, actor_id=OWNER):
    """Shared donor receipt check, independent of a caller's damage-packet size."""
    spent = [e for e in engine.events if e.actor_id == actor_id
             and e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == GUARD
             and e.payload.get('resource_id') == DEW]
    gained = [e for e in engine.events if e.actor_id == actor_id
              and e.event_type == 'RESOURCE_GAINED'
              and e.source_definition_id == 'passive:' + GENERATE_DEW
              and e.payload.get('resource_id') == DEW]
    settled = [e for e in engine.events if e.actor_id == actor_id
               and e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == GUARD]
    assert len(spent) == len(gained) == len(settled) == 1
    assert spent[0].payload['amount'] == 1 and spent[0].payload['remaining'] == 0
    assert spent[0].sequence < settled[0].sequence < gained[0].sequence
    assert gained[0].payload['gained'] == 1 and gained[0].payload['current'] == 1
    assert engine.state.actors[actor_id].resources[DEW] == 1


def assert_guard_payment(engine, *, regenerated):
    """A later outward-support gain must never hide a missing or double debit."""
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
              and e.actor_id == OWNER and e.source_definition_id == GUARD
              and e.payload.get('resource_id') == DEW]
    assert len(spends) == 1
    assert spends[0].payload['amount'] == 1
    assert spends[0].payload['remaining'] == 0
    assert engine.state.actors[OWNER].reaction_available is False
    receipt = resolved(engine)
    assert receipt.actor_id == OWNER
    assert receipt.payload['checkpoint'] == 'DAMAGE_APPLICATION'
    assert receipt.payload['pending_before'] == HIT
    assert receipt.payload['pending_after'] == HIT - receipt.payload['reduction']
    assert engine.events.index(spends[0]) < engine.events.index(receipt)
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED'
             and e.actor_id == OWNER and e.payload.get('resource_id') == DEW]
    assert len(gains) == int(regenerated)
    if regenerated:
        assert gains[0].source_definition_id == 'passive:' + GENERATE_DEW
        assert gains[0].payload['gained'] == 1
        assert gains[0].payload['current'] == 1
        assert engine.events.index(receipt) < engine.events.index(gains[0])
    assert engine.state.actors[OWNER].resources[DEW] == int(regenerated)


def assert_scoped_ally_allowance(engine):
    """The printed next-maintenance grant replaces the old blanket CON bonus."""
    assert not engine.state.actors[OWNER].conditions
    conditions = list(engine.state.actors[ALLY].conditions.values())
    assert len(conditions) == 1
    grant = conditions[0]
    assert grant.condition_id == CONDITION
    assert grant.source_actor_id == OWNER and grant.source_definition_id == GUARD
    assert grant.data['pressure_source_id'] == damage_event(engine, ALLY).source_definition_id
    assert grant.data['pressure_actor_id'] == FOE
    assert grant.data['pressure_kind'] == 'damage'
    assert 'save_mode' not in grant.data and 'save_modes' not in grant.data
    assert grant.expires_on


# (Proficiency Bonus, Constitution score, printed reduction) -- the signed boundaries:
# a key modifier below zero, one below -PB, and a positive control.
@pytest.mark.parametrize('pb,con,reduction', [(2, 8, 1), (2, 4, 0), (2, 16, 5)])
def test_guard_reduces_ally_damage_by_signed_pb_plus_key(tmp_path, pb, con, reduction):
    combat, table, mid = setup(tmp_path, pb, con)
    engine = strike(tmp_path, combat, table, mid, ALLY)
    assert engine.state.actors[ALLY].current_hp == 60 - (HIT - reduction)
    assert damage_event(engine, ALLY).payload['hp_damage'] == HIT - reduction
    # one aggregate: the printed sum, not the Proficiency Bonus plus the key modifier twice
    assert resolved(engine).payload['reduction'] == reduction
    # Printed outward support generates replacement Dew only for a positive
    # reduction to someone else. Payment is proved by its earlier debit receipt.
    assert_guard_payment(engine, regenerated=reduction > 0)
    # This branch automates the printed scoped rider, including a zero numeric
    # reduction. It must still never restore the old blanket CON Advantage.
    assert_scoped_ally_allowance(engine)


def test_guard_reduces_own_damage_by_signed_pb_plus_key(tmp_path):
    combat, table, mid = setup(tmp_path, 2, 8)
    engine = strike(tmp_path, combat, table, mid, OWNER)
    assert engine.state.actors[OWNER].current_hp == 60 - (HIT - 1)
    assert damage_event(engine, OWNER).payload['hp_damage'] == HIT - 1
    assert resolved(engine).payload['reduction'] == 1
    assert_guard_payment(engine, regenerated=False)
    for actor_id in (OWNER, ALLY):
        assert not engine.state.actors[actor_id].conditions, (
            f'Returning Source Guard added an automated condition to {actor_id}: '
            f'{engine.state.actors[actor_id].conditions}')


def test_guard_without_dew_never_pays_or_reduces(tmp_path):
    combat, table, mid = setup(tmp_path, 2, 8, initial=0)
    turn(table, mid, FOE)
    candidate_id = candidate(combat, mid, 'Hostile strike', target=ALLY).candidate_id
    prompts = settle(table, mid, candidate_id, picks={REACTION: None})
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts), (
        'Returning Source Guard must not be offered without Spirit-Source Dew')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].current_hp == 60 - HIT
    assert damage_event(engine, ALLY).payload['hp_damage'] == HIT
    assert not [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == GUARD]


def test_guard_reload_replays_the_reduced_damage(tmp_path):
    combat, table, mid = setup(tmp_path, 2, 8)
    engine = strike(tmp_path, combat, table, mid, ALLY)
    engine = reload(tmp_path, mid)  # a cold reload replays the committed fight
    assert engine.state.actors[ALLY].current_hp == 60 - (HIT - 1)
    assert_guard_payment(engine, regenerated=True)
    assert_scoped_ally_allowance(engine)


def test_declining_guard_keeps_prior_dew_without_payment_or_regeneration(tmp_path):
    combat, table, mid = setup(tmp_path, 2, 8)
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Hostile strike', target=ALLY).candidate_id
    prompts = settle(table, mid, cid, picks={REACTION: None})
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    engine = reload(tmp_path, mid)
    assert damage_event(engine, ALLY).payload['hp_damage'] == HIT
    assert engine.state.actors[ALLY].current_hp == 60 - HIT
    assert engine.state.actors[OWNER].resources[DEW] == 1
    assert engine.state.actors[OWNER].reaction_available is True
    assert not [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == GUARD]
    assert not [e for e in engine.events if e.event_type in ('RESOURCE_SPENT', 'RESOURCE_GAINED')
                and e.actor_id == OWNER and e.payload.get('resource_id') == DEW]
