"""Public data compatibility checks for the Chain Body feature records."""
import json
from pathlib import Path


def test_chain_body_records_keep_their_source_identity_and_effect_contracts():
    source = Path(__file__).parents[1] / "authority/typed_mechanics/reviewed_final.d/riders_c7.json"
    mechanics = json.loads(source.read_text(encoding="utf-8"))["mechanics"]
    prefix = "tianxia.subpath.body.heaven_binding_chain_body.feature."
    expected = {
        "chain_body_integration": {("path_passive", "kind", "integrated_weapon"),
                                  ("path_passive", "kind", "chain_tether")},
        "drag_the_heavens": {("chain_move_toward", None, None)},
        "thousand_link_meridian_network": {("path_passive", "kind", "chain_tether")},
        "heaven_binding_prison": {("prison_tether", None, None)},
    }

    def effect_rows(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from effect_rows(child)
        elif isinstance(value, list):
            for child in value:
                yield from effect_rows(child)

    for feature, required in expected.items():
        row = mechanics[prefix + feature]
        assert row["mechanic_id"] == prefix + feature
        effects = list(effect_rows(row.get("effects", [])))
        # Match each required source contract at any nesting depth.
        for effect_type, key, value in required:
            assert any(effect.get("type") == effect_type and
                       (key is None or effect.get(key) == value)
                       for effect in effects)

        if feature == "thousand_link_meridian_network":
            assert any(effect.get("type") == "path_passive" and
                       "+2d8" in effect.get("evidence", "")
                       for effect in effects)
