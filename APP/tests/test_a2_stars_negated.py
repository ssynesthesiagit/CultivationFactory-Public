"""An immune recipient cannot spend Comet Adept's damage entitlement."""
from combat.ext import stars_insights as si
import pytest
from tests.test_a2_stars_insights import fight, setup_bundle, BOLT, bonus_rolls
from tests.auto_worker1_support import LEFT, RIGHT, act, reload, resolve, turn


def test_comet_keeps_bonus_when_all_recipients_are_immune(tmp_path):
    immune = {"type": "immunity", "damage_types": ["cold"], "applies_to": "self",
              "duration": {"kind": "until_removed"}}
    damage = {"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["cold"]}
    combat, table, mid = fight(tmp_path, [si.COMET, BOLT], prepare=[damage], cause=[immune],
                              cause_target="SELF", bundle_edit=setup_bundle)
    turn(table, mid, RIGHT)
    resolve(lambda answers: act(table, mid, "Cause", answers))
    turn(table, mid, LEFT)
    resolve(lambda answers: act(table, mid, "Prepare", answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp == 1000
    assert si.COMET_USED not in engine.state.actors[LEFT].turn_flags


@pytest.mark.parametrize("native", [False, True])
def test_comet_spends_only_on_positive_damage_then_one_real_roll(native, tmp_path):
    damage = {"type": "damage", "dice": {"count": 1, "sides": 8}, "damage_types": ["cold"]}
    effects = [{"type": "attack", "attack_kind": "cultivation_ranged", "on_hit": [damage]}] if native else [damage]
    def sealed_armor(bundle):
        setup_bundle(bundle)
        if bundle['actor_id'] == RIGHT:
            bundle['typed_passives'].append({'block': 'defense', 'kind': 'reduction',
                'feature_id': 'test:sealed-armor', 'damage_types': ['COLD'], 'amount': 100})
    combat, table, mid = fight(tmp_path, [si.COMET, BOLT], prepare=effects,
                              extra_witness=True, bundle_edit=sealed_armor, prepare_attack_bonus=100)
    resolve(lambda answers: act(table, mid, 'Prepare', answers, target_id=RIGHT))
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp == 1000
    assert si.COMET_USED not in engine.state.actors[LEFT].turn_flags
    witness = 'actor:factory.auto111-witness'
    resolve(lambda answers: act(table, mid, 'Prepare', answers, target_id=witness))
    engine = reload(combat, mid)
    assert [r.modifier for r in bonus_rolls(engine)] == [4, 4]
    assert engine.state.actors[witness].current_hp < 1000
    assert engine.state.actors[LEFT].turn_flags[si.COMET_USED] == si.turn(engine)
