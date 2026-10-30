"""The main/lane integration must retain the placement hook's safety contract."""
import ast
from pathlib import Path
import re


def test_placement_search_contract_preserves_options_and_observed_knowledge():
    """An optimization proof skips ranking; it cannot remove legal choices.

    The integrated architecture guard caught this contract missing entirely.
    Check its arguments and safety guarantees as well as the registered name.
    This reads source only and never initializes a controller or model client.
    """
    source = Path(__file__).resolve().parents[1] / "combat/ext/__init__.py"
    doc = ast.get_docstring(ast.parse(source.read_text(encoding="utf-8"))) or ""
    match = re.search(
        r"(?ms)^  placement_search_possible\(.*?(?=^  [a-z][a-z0-9_]*\(|\Z)",
        doc,
    )
    assert match, "Document the integrated placement_search_possible hook"
    contract = " ".join(match.group().split())
    assert "placement_search_possible(engine, actor, action, root, context) -> False | None" in contract
    assert "observed-knowledge query" in contract
    assert "skips exhaustive ranking only" in contract
    assert "never removes a legal square, ability or aim" in contract
    assert "None is default-inert" in contract
    assert "Providers own their ability and impossibility proof" in contract
