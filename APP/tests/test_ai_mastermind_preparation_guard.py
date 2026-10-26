"""Architecture guard (review finding 3): wall-clock preparation_ns never enters a decision.

Only the field's definition and the context builder may name it. Any other combat code that reads it
would make decisions depend on machine speed. Offline; reads source text only.
"""
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ALLOWED = {"gate4_models.py", "gate4_context.py"}


def test_preparation_ns_is_read_only_by_its_definition_and_builder():
    offenders = []
    for path in sorted((APP / "combat").rglob("*.py")):
        if path.name in ALLOWED:
            continue
        if "preparation_ns" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(APP).as_posix())
    assert not offenders, f"wall-clock preparation_ns read outside the context builder: {offenders}"


def test_preparation_ns_is_excluded_from_serialised_context():
    from combat.gate4_models import DecisionContext
    field = DecisionContext.model_fields["preparation_ns"]
    assert field.exclude is True
