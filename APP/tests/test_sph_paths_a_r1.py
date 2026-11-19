"""Sword Saint must not infer recorded Blade integration from inventory.

Integration selection has no persisted contract yet; the Blade range stays
with the GM. Exercise real table commits and cold replay with controlled dice.
"""
import pytest

from combat.gate2_rolls import DeterministicRollAuthority
from tests import test_riders_c7 as C7
from tests.h48_table_support import OWNER, FOE, fixture, candidate, assert_reload_verify_replay
from tests.test_auto1_paths_a import SWORD_SAINT, KENSEI, BLADE


@pytest.mark.parametrize("label,critical", [
    ("Dao (Saber / Broadsword) attack", False),
    ("Jian (Straight Sword) attack", False),
    ("Unarmed Strike", True),
])
@pytest.mark.parametrize("blade_fist", [False, True])
def test_table_does_not_treat_carried_blades_as_recorded_integration(tmp_path, monkeypatch, label, critical, blade_fist):
    original = DeterministicRollAuthority.d20

    def natural_19(self, **kwargs):
        while True:
            roll = original(self, **kwargs)
            if kwargs.get("actor_id") != OWNER or not str(kwargs.get("reason", "")).startswith("ATTACK") or roll.natural_result == 19:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", natural_19)
    features = [SWORD_SAINT] + ([KENSEI + "blade_fist"] if blade_fist else [])

    def owner_bundle(bundles):
        bundles[0] = C7.bundle(features, cl=20, items=(BLADE, "tianxia.mortal.weapon.jian"), actor_id=OWNER)

    combat, table, mid, send, commit = fixture(tmp_path, [], seed="SPH-paths-r1", bundle_transform=owner_bundle)
    commit(candidate(table, mid, "Sword Saint Incarnation"))
    assert_reload_verify_replay(combat, mid, tmp_path)
    from combat.gate5_service import CombatService
    combat = CombatService(combat.source_root, tmp_path)
    from combat.tabletop_service import TabletopService
    table = TabletopService(combat, tmp_path)
    before = len(combat._load_session(mid).engine.events)
    commit(candidate(table, mid, label, target=FOE))
    engine = combat._load_session(mid).engine
    attacks = [e for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]
    assert attacks and attacks[-1].payload["natural_result"] == 19
    damage = [e for e in engine.events[before:] if e.event_type == "DAMAGE_ROLLED" and e.actor_id == OWNER]
    assert damage and damage[0].payload["critical"] is critical
    assert_reload_verify_replay(combat, mid, tmp_path)
