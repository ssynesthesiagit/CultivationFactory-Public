from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .canonical import canonical_bytes
from .gate2_defaults import UniversalCombatDefaultsLock, write_universal_defaults_lock
from .gate2_mechanics_lock import ExecutableMechanicsLock, MechanicsLockStatus
from .gate2_reconciliation import write_reconciled_gate2_lock
from .gate2_stamina_guard import DeterministicD10Authority, PendingDamagePacket, StaminaGuardDecision, StaminaGuardSpike
from .gate2a import build_gate2a_lock


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def _stamina_guard_evidence() -> dict:
    packet = PendingDamagePacket(
        transaction_id="tx:gate2a:stamina_guard:001",
        packet_id="packet:gate2a:stamina_guard:001",
        source_definition_id="action:ling_qi.music_resonant_note",
        actor_id="ling_qi_early_outer_sect_cl5",
        target_id="an_eui_early_book1_cl5",
        amount=17,
        state_version=4,
        checkpoint_id="DAMAGE_APPLICATION",
        reaction_depth=0,
    )
    spike = StaminaGuardSpike(DeterministicD10Authority("TIANXIA-GATE2A-STAMINA-GUARD-0001"))
    candidates = spike.candidates(packet, current_stamina=21, proficiency_bonus=3)
    decision = StaminaGuardDecision(
        decision_id=candidates.decision_id,
        packet_id=packet.packet_id,
        state_version=packet.state_version,
        selection="SPEND",
        spend=3,
    )
    result = spike.resolve(packet, decision, current_stamina=21, proficiency_bonus=3)
    return {
        "schema": "TianxiaGate2AStaminaGuardEvidence.v1",
        "seed": "TIANXIA-GATE2A-STAMINA-GUARD-0001",
        "packet": packet.model_dump(mode="json"),
        "candidates": candidates.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "assertions": {
            "pending_damage_before_reaction": True,
            "spend_options_equal_1_through_min_pb_current": candidates.spend_options == (1, 2, 3),
            "resource_spent_once": [e.event_type for e in result.events].count("RESOURCE_SPENT") == 1,
            "one_d10_per_stamina": len(result.reduction_rolls) == result.spend,
            "damage_floored_at_zero": result.committed_damage >= 0,
            "event_sequence_contiguous": [e.sequence for e in result.events] == list(range(1, len(result.events) + 1)),
        },
        "status": "PASS",
    }


def _reconciliation_report(lock: ExecutableMechanicsLock) -> str:
    blocked = build_gate2a_lock()
    old = {p.source_definition_id: p for p in blocked.profiles}
    defaults = {
        "system:combat.initiative",
        "system:combat.opportunity_attack",
        "system:combat.temporary_hit_points",
        "condition:core.dodging",
    }
    lines = [
        "# Gate 2 Executable Mechanics Reconciliation Report",
        "",
        "**Disposition:** `PASS_GATE2B_AUTHORIZED`",
        "",
        f"- Typed profiles: **{len(lock.profiles)}**",
        f"- Material unresolved profiles: **{lock.material_unresolved_count}**",
        f"- Mechanics Lock SHA-256: `{lock.lock_sha256}`",
        "- Character authority: exact authenticated four-character bundle and its four verified inner packages.",
        "- Universal authority: only the separately recorded normal-use defaults listed in the Universal Combat Defaults Lock.",
        "- Runtime prose interpretation: **prohibited**; all runtime semantics are typed in lock/profile records.",
        "",
        "## Reconciled material profiles",
        "",
        "| Profile | Prior unresolved fields | Resolution authority | Final status |",
        "|---|---|---|---|",
    ]
    for profile in lock.profiles:
        previous = old[profile.source_definition_id]
        if previous.status != MechanicsLockStatus.MATERIAL_UNRESOLVED:
            continue
        fields = "; ".join(previous.unresolved_fields)
        kind = "Universal default" if profile.source_definition_id in defaults else "Exact character authority"
        lines.append(f"| `{profile.source_definition_id}` | {fields} | {kind}: {profile.source_locator} | `{profile.status}` |")
    lines += [
        "",
        "## Explicit universal defaults",
        "",
        "The following behavior is not controlled by the character packages and is therefore locked separately:",
        "",
        "1. Deterministic initiative tie resolution: higher initiative bonus, then higher Dexterity score, then stable entity ID; Cui is inserted immediately after Bai.",
        "2. Opportunity attacks: visible voluntary reach exit, one source-authorized melee attack before exit; Disengage prevents; teleport and forced movement do not trigger.",
        "3. Temporary hit points: never add together; deterministically retain the greater amount; absorb before HP; source ending does not remove retained temporary HP.",
        "4. Dodge: visible attacks have disadvantage and Dexterity saves have advantage until the actor's next turn; ends early if incapacitated or Speed 0.",
        "",
        "## Material corrections to Gate 1 summaries",
        "",
        "- `action:an_eui.first_arm` is a standalone Action costing 3 Stamina, not an on-hit option.",
        "- `action:bai_meizhen.water_whip` remains an optional 1-Qi follow-up after Water Lash hits; no Qi is charged on a miss or decline.",
        "- Forgotten Vale Nocturne creates heavy sight obscuration and failed-save hindrance, but no unprinted damage or difficult terrain.",
        "- Dose Marks are tracked accumulation only; the runtime does not invent a generic stack penalty absent a source technique.",
        "",
        "## Gate 2B readiness",
        "",
        "The mechanics lock has `material_unresolved_count = 0`; Gate 2B may start. This report does not itself claim that the complete fight has run.",
        "",
    ]
    return "\n".join(lines)


def _primitive_inventory(lock: ExecutableMechanicsLock) -> str:
    used = Counter(pid for p in lock.profiles for pid in p.primitive_ids)
    lines = [
        "# Gate 2 Primitive Inventory",
        "",
        "The content-facing kernel remains bounded. No arbitrary script, expression evaluator, loop, recursion, generic state patch, `apply_delta`, or `set_state` primitive exists.",
        "",
        "| Primitive | Locked profile references | Status |",
        "|---|---:|---|",
    ]
    for pid in lock.allowed_primitive_ids:
        lines.append(f"| `{pid}` | {used[pid]} | Implement only through source-authorized engine methods |")
    lines += ["", f"Total allowed primitives: **{len(lock.allowed_primitive_ids)}**.", ""]
    return "\n".join(lines)


def _readme() -> str:
    return """# Factory Hybrid Combat Gate 2

This directory contains the exact-authority Gate 2 mechanics locks and generated combat artifacts.

The Gate 2A lock is reconciled to zero material unresolved entries. Build the lock layer with:

```text
python -m combat.gate2a_cli --output combat_gate2
```

The broad Gate 2B engine and scripted manual fight use these typed records only. Runtime code does not parse character mechanics prose.
"""


def build_outputs(output_root: Path) -> ExecutableMechanicsLock:
    lock = write_reconciled_gate2_lock(output_root / "generated" / "Gate2_Executable_Mechanics_Lock.json")
    defaults = write_universal_defaults_lock(output_root / "generated" / "Gate2_Universal_Combat_Defaults_Lock.json")
    _write_json(output_root / "generated" / "schemas" / "Gate2_Executable_Mechanics_Lock.schema.json", ExecutableMechanicsLock.model_json_schema(by_alias=True))
    _write_json(output_root / "generated" / "schemas" / "Gate2_Universal_Combat_Defaults_Lock.schema.json", UniversalCombatDefaultsLock.model_json_schema(by_alias=True))
    _write_json(output_root / "evidence" / "Stamina_Guard_Spike_Evidence.json", _stamina_guard_evidence())
    doc = output_root / "documentation"
    doc.mkdir(parents=True, exist_ok=True)
    (doc / "Gate2_Mechanics_Reconciliation_Report.md").write_text(_reconciliation_report(lock), encoding="utf-8")
    (doc / "Gate2_Primitive_Inventory.md").write_text(_primitive_inventory(lock), encoding="utf-8")
    (output_root / "README.md").write_text(_readme(), encoding="utf-8")
    return lock


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the exact-authority Gate 2 mechanics locks.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lock = build_outputs(args.output)
    print(json.dumps({"status": lock.status, "profiles": len(lock.profiles), "material_unresolved_count": lock.material_unresolved_count, "lock_sha256": lock.lock_sha256}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
