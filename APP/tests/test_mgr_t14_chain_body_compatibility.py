"""Public data compatibility checks for the Chain Body feature records."""
import json
from pathlib import Path

PREFIX = "tianxia.subpath.body.heaven_binding_chain_body.feature."


def effect_rows(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from effect_rows(child)
    elif isinstance(value, list):
        for child in value:
            yield from effect_rows(child)


def test_chain_body_records_keep_their_source_identity_and_effect_contracts():
    source = Path(__file__).parents[1] / "authority/typed_mechanics/reviewed_final.d/riders_c7.json"
    mechanics = json.loads(source.read_text(encoding="utf-8"))["mechanics"]
    prefix = PREFIX
    expected = {
        "chain_body_integration": {("path_passive", "kind", "integrated_weapon"),
                                  ("path_passive", "kind", "chain_tether")},
        "drag_the_heavens": {("chain_move_toward", None, None)},
        "thousand_link_meridian_network": {("path_passive", "kind", "chain_tether")},
        "heaven_binding_prison": {("prison_tether", None, None)},
    }

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


def test_guardian_chain_is_a_gm_rider_with_no_prone_and_no_movement_option():
    """Guardian Chain's printed results follow only when its reduction leaves nothing.

    "If reduced to 0, move the protected creature 10 feet toward you" and "reduce forced movement by 20 feet; if
    reduced to 0, prevent Prone ... move it 5 feet" were carried as typed options, so the sealed engine ran the
    movement and the Prone whatever the reduction came to.  Settling a shared damage packet and the final distance
    another effect measured is a system the engine does not have, so the record is a GM rider that keeps the printed
    text and offers the table no option, no Prone and no movement (the person running the game resolves the tail).
    """
    app = Path(__file__).parents[1]
    records = {label: json.loads((app / relative).read_text(encoding="utf-8"))["mechanics"][PREFIX + "guardian_chain"]
               for label, relative in (("reviewed", "authority/typed_mechanics/reviewed_final.d/riders_c7.json"),
                                       ("built", "authority/Tianxia_Typed_Mechanics_Authority_R1.json"))}
    for label, record in records.items():
        assert not record.get("effects"), label
        assert not record.get("options"), label
        assert not [row for row in effect_rows(record)
                    if row.get("type") in {"movement", "forced_movement", "condition"}], label
        text = " ".join(record["riders"])
        for printed in ("Catch the Attack", "Anchor the Body", "3d10", "Constitution modifier",
                        "10 feet", "20 feet", "Prone", "Tethered"):
            assert printed in text, (label, printed)
