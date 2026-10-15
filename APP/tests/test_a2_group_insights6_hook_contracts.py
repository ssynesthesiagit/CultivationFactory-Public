"""Keep the shared Insights6 API discoverable in the extension registry."""
import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize("contract, required", [
    ("activation_accounting(engine)", (
        "bool or None", "pure query", "transaction", "False", "True",
        "default-inert", "never serialized",
    )),
    ("reaction_range_bonus(engine, actor, feature_id)", (
        "nonnegative int or None", "pure query", "feet", "add", "default-inert",
        "typed_reactions", "void_riders",
    )),
    ("repeat_save_final(engine, resolution)", (
        "None", "after rewrites and condition settlement", "success",
        "failed die", "transaction", "default-inert",
    )),
    ("source_sphere and source_categories", (
        "originating action", "tuple", "category:", "None", "empty",
        "exact condition", "never saved",
    )),
])
def test_registry_documents_shared_hook_contract(contract, required):
    registry = Path(__file__).resolve().parents[1] / "combat/ext/__init__.py"
    documentation = ast.get_docstring(ast.parse(registry.read_text()))
    assert contract in documentation, f"Missing central API contract: {contract}"
    section = documentation.split(contract, 1)[1].split("\n\n", 1)[0]
    for term in required:
        assert term in section, f"{contract} does not document {term}"
