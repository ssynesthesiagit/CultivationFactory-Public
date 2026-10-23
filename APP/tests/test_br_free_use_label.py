"""BRS1F9 finding 2: the free-use funding prompt names the plain variant, never the internal id."""
from combat.ext import br_variants, free_uses
from factory_authoring import body_refining_variants as authority


def test_funding_label_is_the_plain_variant_name_not_the_authority_id(monkeypatch):
    row = {"id": "tianxia.brvariant.air.air-bellows-body", "picker_label": "Air Bellows Body",
           "riders": [{"kind": "free_use", "clause": "c1", "once": "turn", "of": ["Gather Current"]}]}
    monkeypatch.setattr(authority, "owned", lambda sheet: [row])
    decls = br_variants._free_use_declarations({"owner_sheet": {}})
    assert len(decls) == 1
    label = free_uses.grant_label(decls[0])
    assert label == "Air Bellows Body"
    assert "br_variant" not in label and "tianxia" not in label


def test_funding_label_never_falls_back_to_the_state_key():
    grant = {"state": "br_variant:tianxia.brvariant.air.air-bellows-body", "of": ["Gather Current"], "key": "k"}
    assert "br_variant" not in free_uses.grant_label(grant)
