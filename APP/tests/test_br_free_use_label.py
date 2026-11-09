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


def test_the_printed_variant_name_is_compiled_onto_the_grant_not_resolved_at_prompt_time():
    """BRS1F12R/F8R addendum 2 kept, BRS1F25 finding 4: the printed name reaches the player through the
    compiled grant's title (combat data), so the label reader never imports the authoring files; a titleless
    variant grant still reads in plain words rather than showing the engine state key."""
    import inspect

    assert "factory_authoring" not in inspect.getsource(free_uses)
    grant = {"state": "br_variant:tianxia.brvariant.air.bellows-body", "of": ["Gather Current"], "key": "k"}
    assert free_uses.grant_label(grant) == "Body Refining variant"
    # The compiled declaration supplies the printed name: the prompt reads the grant's title.
    from tests.test_body_refining_riders import sphere, variants

    _rows, bundle = variants(sphere("tianxia.sphere.air", talents=["AIR_BASE_GATHER_CURRENT"]))
    free = [action for action in bundle["action_catalog"] if action["display_name"].endswith("(free)")
            and "Gather Current" in action["display_name"]]
    assert free, "Gather Current is offered once free by the Air variant"
    title = free[0]["parameters"]["free_use"]["title"]
    assert title and "tianxia" not in title and "br_variant" not in title
    assert free_uses.grant_label(free[0]["parameters"]["free_use"]) == title


def test_unregistered_predicate_gate_fails_closed_instead_of_raising():
    """BRS1F12R 6: a grant naming an unregistered predicate is unavailable, never a KeyError."""
    from types import SimpleNamespace
    actor = SimpleNamespace(turn_flags={})
    grant = {"always": True, "requires": "no.such.predicate", "state": "br_variant:x", "key": "k", "once": "turn", "of": []}
    assert free_uses._live(None, actor, grant) is False


def test_funding_option_ids_carry_no_internal_authority_id(monkeypatch):
    """BRS1F8R finding 2: the funding choice publishes each grant key as an option id; it must not
    contain the authority id (tianxia.brvariant...) or the br_variant state word."""
    rows = [{"id": "tianxia.brvariant.air.air-bellows-body", "picker_label": "Air Bellows Body",
             "riders": [{"kind": "free_use", "clause": 1, "once": "turn", "of": ["Gather Current"]}]},
            {"id": "tianxia.brvariant.water.tidal-body", "picker_label": "Tidal Body",
             "riders": [{"kind": "free_use", "clause": 1, "once": "turn", "of": ["Gather Current"]}]}]
    monkeypatch.setattr(authority, "owned", lambda sheet: rows)
    keys = [d["key"] for d in br_variants._free_use_declarations({"owner_sheet": {}})]
    assert len(keys) == 2 and len(set(keys)) == 2  # same clause number on two variants stays distinct
    for key in keys:
        assert "tianxia" not in key and "br_variant" not in key and ":" not in key
