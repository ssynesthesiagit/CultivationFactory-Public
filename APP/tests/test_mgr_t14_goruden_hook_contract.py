"""Keep the damage receipt notification separate from paid defense responses.

The regression reads the public plug-in contract without importing the registry:
documentation-only fixes must not start combat, services or model transports.
"""
import ast
from pathlib import Path


def test_damage_receipt_documents_its_own_notification_contract():
    source = Path(__file__).resolve().parents[1] / "combat" / "ext" / "__init__.py"
    docs = ast.get_docstring(ast.parse(source.read_text(encoding="utf-8")))
    receipt = docs.split("Actual damage-defense receipt checkpoint (A2GINS5):", 1)[1].split(
        "General carrying-capacity compilation query", 1
    )[0]
    assert "damage_defense_receipt(engine, target, amount, damage_type, source_definition_id, source_actor_id) -> None." in receipt
    assert "before_damage_defenses(engine" not in receipt
    for contract in (
        "includes immune packets", "before the separate before_damage_defenses",
        "may be None for world damage", "Quote-only/AI queries do not enter it",
        "must not change HP, defenses, positions", "must return None",
        "No subscribers or no owned consumer means no receipts, state or events",
    ):
        assert contract in receipt


def test_damage_response_keeps_its_distinct_transactional_contract():
    source = Path(__file__).resolve().parents[1] / "combat" / "ext" / "__init__.py"
    docs = ast.get_docstring(ast.parse(source.read_text(encoding="utf-8")))
    response = docs.split("  before_damage_defenses(engine", 1)[1].split("  damage_reduction(", 1)[0]
    for contract in (
        "-> None or list of defense rows", "positive, nonimmune committed packet",
        "May ask", "pay for a response", "No subscribers is inert",
    ):
        assert contract in response
