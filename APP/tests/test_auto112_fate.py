"""AUTO112: Hallow Mandate judges the owner's chosen creature category.

Printed text (owner rules_text.json TAL_FATE_HALLOW_MANDATE_EDICT):
  "Choose aberrations, celestials, elementals, fey, fiends, undead, demons, ghosts, or another
   supernatural category appropriate to the campaign."
  "Creatures of the chosen kind have Disadvantage on attack rolls against your allies inside the aura."
  "At CL 10, allies inside the aura have Advantage on saving throws against being Charmed, Frightened, or
   possessed by creatures of the chosen kind."

Each case runs through TabletopService and reloads through a fresh service (mechanical replay PASS).
"""
import pytest

from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

HALLOW = 'TAL_FATE_HALLOW_MANDATE_EDICT'
CHARM = [{'type': 'save', 'ability': 'CHA', 'on_fail': [{'type': 'condition', 'condition': 'charmed', 'applies_to': 'target'}]}]


def _prepare(bundles, foe_kind):
    for bundle, initiative in zip(bundles, [100, -100, 0]):
        bundle['actor_template']['initiative_bonus'] = initiative
        bundle['actor_template']['maximum_hp'] = 300
        seal(bundle)
    bundles[2]['actor_template']['creature_types'] = [foe_kind]
    bundles[2]['actor_template']['saving_throws']['CHA'] = 100
    add_action(bundles[2], 'Foe strike', [{'type': 'attack', 'attack_bonus': 100, 'attack_kind': 'cultivation',
                                            'on_hit': [{'type': 'damage', 'damage_type': 'FORCE', 'flat': 4}]}],
               target='HOSTILE_ENTITY')
    add_action(bundles[2], 'Foe charm', CHARM)
    seal(bundles[2])


@pytest.mark.parametrize('kind,foe_kind,expect', [
    ('undead', 'undead', 'DISADVANTAGE'),
    ('undead', 'fey', 'NORMAL'),
    (None, 'undead', 'NORMAL'),
])
def test_hallow_judged_kind_attacks_ally_with_disadvantage(tmp_path, kind, foe_kind, expect):
    combat, table, mid = fixture(tmp_path, [HALLOW], bundle_transform=lambda bs: _prepare(bs, foe_kind))
    settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id,
           {'choice:needle.hallow_kind': kind})
    engine = reload(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if z.active)
    # The chosen category is saved on the aura and survives a commit + reload.
    assert zone.trigger_profile['fate_hallow_kind'] == (kind or '')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe strike', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    strike = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE)
    assert strike.payload['mode'] == expect


@pytest.mark.parametrize('foe_kind,expect', [('undead', 'ADVANTAGE'), ('fey', 'NORMAL')])
def test_hallow_cl10_ally_saves_against_charm_from_judged_kind(tmp_path, foe_kind, expect):
    combat, table, mid = fixture(tmp_path, [HALLOW], cl=15, bundle_transform=lambda bs: _prepare(bs, foe_kind))
    settle(table, mid, candidate(combat, mid, 'Hallow Mandate Edict').candidate_id,
           {'choice:needle.hallow_kind': 'undead'})
    reload(tmp_path, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe charm', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    check = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY)
    assert check.payload['mode'] == expect