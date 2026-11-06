"""Keep the damage receipt notification separate from paid defense responses.

The regression reads the public plug-in contract without importing the registry:
documentation-only fixes must not start combat, services or model transports.
"""
import ast
from pathlib import Path


def _docs():
    source = Path(__file__).resolve().parents[1] / "combat" / "ext" / "__init__.py"
    return ast.get_docstring(ast.parse(source.read_text(encoding="utf-8")))


def test_damage_receipt_documents_its_own_notification_contract():
    docs = _docs()
    receipt = docs.split("Actual damage-defense receipt checkpoint (A2GINS5):", 1)[1].split(
        "General carrying-capacity compilation query", 1
    )[0]
    assert "damage_defense_receipt" not in docs
    for contract in (
        "Quote-only/AI queries do not enter it.",
        "must not change HP, defenses,",
    ):
        assert contract in receipt


def test_damage_response_keeps_its_distinct_transactional_contract():
    docs = _docs()
    response = docs.split("  before_damage_defenses(engine, target, amount, damage_type, source_definition_id", 1)[1].split(
        "  damage_reduction(", 1)[0]
    for contract in (
        "-> None or list of defense rows", "positive, nonimmune committed packet",
        "May ask", "pay for a response", "No subscribers is inert",
    ):
        assert contract in response
