from pathlib import Path


def test_history_projection_contract_is_default_inert_and_source_owned():
    contract = Path(__file__).parents[1] / "combat" / "ext" / "__init__.py"
    text = contract.read_text(encoding="utf-8")
    assert "the default is inert, and a provider acts only for its owned source" in text
    assert "no provider is inert" not in text
