"""Ask-me prompts and hovers must read the same current printed rules.

The negative control is the shadowed forever-cache in tabletop_service: a
second owner edit changes hover text but leaves the prompt on its first read.
No engine state or saved character text is modified by this presentation read.
"""
import json

from combat import status_text, tabletop_service


def test_table_prompt_rules_refresh_with_the_shared_hover_source(tmp_path, monkeypatch):
    app = tmp_path / "APP"
    path = app / "authority" / "typed_mechanics" / "rules_text.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"source": "Original printed rule."}))
    monkeypatch.setattr(status_text, "RULES_TEXT_PATH", path)
    # Point both old and new implementations at the same disposable input;
    # the result must depend on a file edit, not a hard-coded source path.
    monkeypatch.setattr(tabletop_service, "__file__", str(app / "combat" / "tabletop_service.py"))
    monkeypatch.setattr(tabletop_service, "_RULES_TEXTS", None, raising=False)
    status_text.printed_rules.cache_clear()
    try:
        assert tabletop_service._rules_texts()["source"] == "Original printed rule."
        updated = "The owner has clarified the current printed rule."
        path.write_text(json.dumps({"source": updated}))
        assert status_text.printed_rules()["source"] == updated
        assert tabletop_service._rules_texts()["source"] == updated
        path.unlink()
        assert tabletop_service._rules_texts() == {}
    finally:
        status_text.printed_rules.cache_clear()
