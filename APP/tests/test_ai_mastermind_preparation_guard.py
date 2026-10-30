"""Decision inputs must not contain machine-dependent preparation timing."""
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def test_preparation_timing_is_not_part_of_decision_context():
    from combat.gate4_models import DecisionContext
    assert "preparation_ns" not in DecisionContext.model_fields


def test_preparation_timing_is_not_read_by_combat_code():
    offenders = [
        path.relative_to(APP).as_posix()
        for path in sorted((APP / "combat").rglob("*.py"))
        if "preparation_ns" in path.read_text(encoding="utf-8")
    ]
    assert not offenders
