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


def test_titleless_talent_state_grant_keeps_a_readable_name():
    """BRS1F11R finding 1: a talent state grant with no title is named in plain words, not 'Active talent state'."""
    grant = {"state": "court_of_charged_paths", "of": ["Gather Charge"], "key": "k"}
    assert free_uses.grant_label(grant) == "Court Of Charged Paths"
    assert free_uses.grant_label({"state": "br_variant:tianxia.brvariant.air.x", "key": "k"}) == "Body Refining variant"


def test_titleless_variant_grant_names_the_printed_ability_not_the_generic_fallback():
    """BRS1F12R/F8R addendum 2: a titleless br_variant grant names the variant in plain words (its picker label),
    resolved from the authority id; before this fix it fell back to the generic 'Body Refining variant'."""
    grant = {"state": "br_variant:tianxia.brvariant.air.bellows-body", "of": ["Gather Current"], "key": "k"}
    label = free_uses.grant_label(grant)
    assert label == authority.variant("tianxia.brvariant.air.bellows-body")["picker_label"]
    assert "Bellows Body" in label
    assert "br_variant" not in label and "tianxia" not in label


def test_unregistered_predicate_gate_fails_closed_instead_of_raising():
    """BRS1F12R 6: a grant naming an unregistered predicate is unavailable, never a KeyError."""
    from types import SimpleNamespace
    actor = SimpleNamespace(turn_flags={})
    grant = {"always": True, "requires": "no.such.predicate", "state": "br_variant:x", "key": "k", "once": "turn", "of": []}
    assert free_uses._live(None, actor, grant) is False
