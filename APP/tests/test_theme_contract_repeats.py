"""A local model may repeat a cited record ID; the grammar cannot forbid it."""

from factory_authoring.theme_contract import build_gm_themes_schema, validate_gm_themes


def _theme(ids):
    return {
        "display_name": "a", "core_theme": "b", "principles": ["c", "d"], "strengths": ["e", "f"],
        "risks": ["g", "h"], "roleplay_expression": "i", "tactical_expression": "j", "gm_usage_notes": "k",
        "relevant_record_ids": ids, "mechanical_effects": [],
    }


def test_model_schema_omits_unique_items_and_server_drops_repeats():
    schema = build_gm_themes_schema(["rec.a", "rec.b"])
    ids_schema = schema["properties"]["i_ching"]["properties"]["relevant_record_ids"]
    assert "uniqueItems" not in ids_schema
    # The grammar still bounds the list to the allowed set's size (build 34 ran away).
    assert ids_schema["maxItems"] == 2
    themes = validate_gm_themes({"dao": _theme(["rec.a"]), "i_ching": _theme(["rec.b", "rec.a", "rec.b"])}, ["rec.a", "rec.b"])
    assert themes["i_ching"]["relevant_record_ids"] == ["rec.b", "rec.a"]
