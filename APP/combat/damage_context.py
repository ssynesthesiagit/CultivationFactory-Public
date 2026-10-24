"""Explicit, ephemeral provenance for a confirmed attack's damage packet."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AttackDamage:
    source_id: str
    attacker_id: str
    target_id: str
    attack_index: int
    roll_id: str
    natural_result: int
    total: int
    critical: bool
    kind: str = 'other'
    component: str = 'primary'
    critical_cancelled: bool = False
