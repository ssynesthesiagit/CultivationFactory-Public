from __future__ import annotations

import json
from pathlib import Path

import pytest

from combat.diagnostics import CombatGate1Error
from combat.gate2_mechanics_lock import (
    LockOverallStatus,
    MechanicsLockStatus,
    assert_gate2b_ready,
    load_executable_mechanics_lock,
)
from combat.gate2_stamina_guard import (
    DeterministicD10Authority,
    PendingDamagePacket,
    StaminaGuardDecision,
    StaminaGuardSpike,
)
from combat.gate2a import ALLOWED_PRIMITIVES
from combat.gate2_defaults import load_universal_defaults_lock
from combat.gate2_reconciliation import build_reconciled_gate2_lock, write_reconciled_gate2_lock
from combat.gate2a_cli import build_outputs


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "combat_gate2" / "generated" / "Gate2_Executable_Mechanics_Lock.json"


def packet(*, amount: int = 20, version: int = 7, depth: int = 0) -> PendingDamagePacket:
    return PendingDamagePacket(
        transaction_id="tx:test:001",
        packet_id="packet:test:001",
        source_definition_id="action:ling_qi.music_resonant_note",
        actor_id="ling_qi_early_outer_sect_cl5",
        target_id="an_eui_early_book1_cl5",
        amount=amount,
        state_version=version,
        checkpoint_id="DAMAGE_APPLICATION",
        reaction_depth=depth,
    )


def decision_for(spike: StaminaGuardSpike, p: PendingDamagePacket, *, stamina: int, pb: int, spend: int | None) -> StaminaGuardDecision:
    candidates = spike.candidates(p, current_stamina=stamina, proficiency_bonus=pb)
    return StaminaGuardDecision(
        decision_id=candidates.decision_id,
        packet_id=p.packet_id,
        state_version=p.state_version,
        selection="DECLINE" if spend is None else "SPEND",
        spend=0 if spend is None else spend,
    )


def test_gate2a_lock_is_canonical_strict_and_gate2b_ready() -> None:
    lock = load_executable_mechanics_lock(LOCK_PATH)
    assert lock.status == LockOverallStatus.PASS
    assert lock.material_unresolved_count == 0
    assert len(lock.profiles) == 68
    assert lock.lock_sha256 == lock.calculated_sha256()
    assert lock.allowed_primitive_ids == ALLOWED_PRIMITIVES
    assert_gate2b_ready(lock)
    assert all(p.status != MechanicsLockStatus.MATERIAL_UNRESOLVED for p in lock.profiles)


def test_gate2a_lock_rebuild_is_byte_identical(tmp_path: Path) -> None:
    write_reconciled_gate2_lock(tmp_path / LOCK_PATH.name)
    assert (tmp_path / LOCK_PATH.name).read_bytes() == LOCK_PATH.read_bytes()



def test_gate2a_full_output_rebuild_is_byte_identical(tmp_path: Path) -> None:
    build_outputs(tmp_path)
    expected_root = ROOT / "combat_gate2"
    actual = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    # Gate 2 supersedes the Gate2A-only scope README; the remaining Gate2A-owned
    # generated artifacts must still reproduce exactly.
    actual.pop(Path("README.md"))
    expected = {relative: (expected_root / relative).read_bytes() for relative in actual}
    assert actual == expected

def test_every_profile_is_resolved_and_exact_authority_is_bound() -> None:
    lock = load_executable_mechanics_lock(LOCK_PATH)
    assert lock.material_unresolved_count == 0
    assert any(x.role == "CHARACTER_AUTHORITY_BUNDLE" for x in lock.source_bundle_identities)
    assert sum(x.role.startswith("CHARACTER_AUTHORITY_") and x.role != "CHARACTER_AUTHORITY_BUNDLE" for x in lock.source_bundle_identities) == 4
    for profile in lock.profiles:
        assert not profile.unresolved_fields
        assert profile.resolution_request is None


def test_required_gate2_profile_ids_are_covered() -> None:
    ids = {p.source_definition_id for p in load_executable_mechanics_lock(LOCK_PATH).profiles}
    required = {
        "system:combat.initiative",
        "system:combat.attack_natural_results",
        "system:combat.saving_throw_modifiers",
        "system:combat.opportunity_attack",
        "system:combat.cover_and_line_of_sight",
        "system:combat.concentration",
        "system:combat.temporary_hit_points",
        "system:combat.nonlethal_defeat",
        "system:hazard.sect_training_court.qi_disruption",
        "action:an_eui.scouring_destruction_blast",
        "action:an_eui.paired_bi_shou_assault",
        "action:an_eui.paired_strike",
        "action:an_eui.ruin_tempered_armament_quick",
        "action:an_eui.first_arm",
        "reaction:an_eui.sheath_bone_guard",
        "reaction:core.stamina_guard",
        "passive:an_eui.severance_edge",
        "talent:an_eui.stomping_step",
        "action:lee_jia.gather_charge",
        "action:lee_jia.lightning_lash",
        "action:lee_jia.hidden_sleeve_shock_talisman",
        "talent:lee_jia.aura_reading_countercurrent",
        "talent:lee_jia.spark_step",
        "passive:lee_jia.reed_flex",
        "action:ling_qi.forgotten_vale_nocturne",
        "action:ling_qi.dissonant_note",
        "action:ling_qi.sound_resonant_note",
        "action:ling_qi.music_resonant_note",
        "action:ling_qi.keep_the_measure",
        "reaction:ling_qi.qi_armor",
        "reaction:ling_qi.rhythmic_guard",
        "passive:ling_qi.mirror_trace",
        "action:bai_meizhen.blackwater_serpent_court",
        "action:bai_meizhen.command_cui",
        "action:bai_meizhen.numbing_venom_palm",
        "action:bai_meizhen.water_lash",
        "action:bai_meizhen.water_whip",
        "reaction:bai_meizhen.water_shield",
        "reaction:bai_meizhen.spirit_intercession",
        "passive:bai_meizhen.serpent_kinship",
        "creature:bai_cui",
    }
    assert required <= ids


def test_lock_runtime_has_no_descriptive_prose_interpreter() -> None:
    lock_document = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield key
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)
    forbidden = {"script", "script_body", "expression", "code", "state_patch", "apply_delta"}
    assert forbidden.isdisjoint({key.lower() for key in keys(lock_document)})
    source = (ROOT / "combat" / "gate2_mechanics_lock.py").read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


def test_stamina_guard_decline_commits_original_damage_without_spend() -> None:
    spike = StaminaGuardSpike(DeterministicD10Authority("seed:decline"))
    p = packet(amount=13)
    result = spike.resolve(p, decision_for(spike, p, stamina=5, pb=3, spend=None), current_stamina=5, proficiency_bonus=3)
    assert result.spend == 0
    assert result.stamina_after == 5
    assert result.committed_damage == 13
    assert [e.event_type for e in result.events] == [
        "REACTION_WINDOW_OPENED", "REACTION_DECLINED", "REACTION_RESOLVED", "DAMAGE_COMMITTED"
    ]


def test_stamina_guard_maximum_is_min_pb_and_current_stamina() -> None:
    spike = StaminaGuardSpike(DeterministicD10Authority("seed:max"))
    p = packet()
    assert spike.candidates(p, current_stamina=2, proficiency_bonus=3).spend_options == (1, 2)
    assert spike.candidates(p, current_stamina=8, proficiency_bonus=3).spend_options == (1, 2, 3)


def test_stamina_guard_spend_is_atomic_deterministic_and_zero_floored() -> None:
    p = packet(amount=2)
    first = StaminaGuardSpike(DeterministicD10Authority("seed:atomic"))
    second = StaminaGuardSpike(DeterministicD10Authority("seed:atomic"))
    r1 = first.resolve(p, decision_for(first, p, stamina=21, pb=3, spend=3), current_stamina=21, proficiency_bonus=3)
    r2 = second.resolve(p, decision_for(second, p, stamina=21, pb=3, spend=3), current_stamina=21, proficiency_bonus=3)
    assert r1.model_dump(mode="json") == r2.model_dump(mode="json")
    assert r1.stamina_after == 18
    assert len(r1.reduction_rolls) == 3
    assert r1.committed_damage == 0
    types = [e.event_type for e in r1.events]
    assert types[0] == "REACTION_WINDOW_OPENED"
    assert types[1] == "RESOURCE_SPENT"
    assert types[-2:] == ["REACTION_RESOLVED", "DAMAGE_COMMITTED"]


def test_stamina_guard_rejects_stale_invalid_duplicate_and_excess_depth() -> None:
    spike = StaminaGuardSpike(DeterministicD10Authority("seed:errors"))
    p = packet(amount=20)
    good = decision_for(spike, p, stamina=3, pb=3, spend=1)
    stale = good.model_copy(update={"state_version": p.state_version - 1})
    with pytest.raises(CombatGate1Error) as caught:
        spike.resolve(p, stale, current_stamina=3, proficiency_bonus=3)
    assert caught.value.diagnostic.code == "COMBAT_GATE2_STALE_REACTION_DECISION"

    invalid = good.model_copy(update={"spend": 4})
    with pytest.raises(CombatGate1Error) as caught:
        spike.resolve(p, invalid, current_stamina=3, proficiency_bonus=3)
    assert caught.value.diagnostic.code == "COMBAT_GATE2_INVALID_STAMINA_GUARD_SPEND"

    spike.resolve(p, good, current_stamina=3, proficiency_bonus=3)
    with pytest.raises(CombatGate1Error) as caught:
        spike.resolve(p, good, current_stamina=3, proficiency_bonus=3)
    assert caught.value.diagnostic.code == "COMBAT_GATE2_REACTION_ALREADY_CONSUMED"

    deep_spike = StaminaGuardSpike(DeterministicD10Authority("seed:depth"))
    deep = packet(depth=2)
    deep_decision = decision_for(deep_spike, deep, stamina=3, pb=3, spend=1)
    with pytest.raises(CombatGate1Error) as caught:
        deep_spike.resolve(deep, deep_decision, current_stamina=3, proficiency_bonus=3)
    assert caught.value.diagnostic.code == "COMBAT_GATE2_REACTION_DEPTH_EXCEEDED"


def test_exact_character_corrections_are_locked() -> None:
    lock = load_executable_mechanics_lock(LOCK_PATH)
    profiles = {p.source_definition_id: p for p in lock.profiles}
    first_arm = profiles["action:an_eui.first_arm"]
    assert first_arm.profile_kind.value == "ATTACK_THEN_SAVE"
    assert first_arm.economy.value == "ACTION"
    assert [(c.resource_id, c.amount) for c in first_arm.costs] == [("resource:an_eui.stamina", 3)]
    water_whip = profiles["action:bai_meizhen.water_whip"]
    assert water_whip.profile_kind.value == "ON_HIT_OPTION"
    assert water_whip.prerequisites == ("CURRENT_TRANSACTION_WATER_LASH_HIT", "TRIGGER_WINDOW_OPEN")
    assert water_whip.costs[0].optional is True


def test_universal_defaults_lock_is_canonical_and_separate() -> None:
    path = ROOT / "combat_gate2" / "generated" / "Gate2_Universal_Combat_Defaults_Lock.json"
    lock = load_universal_defaults_lock(path)
    assert lock.lock_sha256 == lock.calculated_sha256()
    assert [x.default_id for x in lock.defaults] == [
        "default:combat.dodge",
        "default:combat.initiative_ties",
        "default:combat.opportunity_attack",
        "default:combat.temporary_hit_points",
    ]
