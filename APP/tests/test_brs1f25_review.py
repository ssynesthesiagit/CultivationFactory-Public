"""BRS1F25 regressions: one test per finding of the BRS1F24 lead review.

Every test here fails on the BRS1F24 head 55c6b604, except the pin guard, which fails as soon as
the committed pin drifts from the builder output (that is what a stale pin is):
1. the choice-owner marker read a key the authority row does not have (so the printed "choose one
   benefit" was never routed to a seat) and appended an unmarked bookkeeping row that leaked onto
   the sheet as an ability;
2. a stale Body Refining authority pin raised a 500 from every character's insight listing;
3. a saved fight's Short Rest was a second copy of the engine's rest rule;
4. combat imported the authoring data for a player label, and one combat plug-in imported two other
   plug-ins' rules.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import zipfile
from types import SimpleNamespace

import pytest

from combat import effect_endings
from combat.ext import br_variants as bv
from combat.ext import free_uses, journey_setup, load_plug_ins, sand_terrain, thrown_equipment, zone_kinds
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ConditionInstance
from tests.body_refining_support import PID, ROOT, install, service, sheet
from tests.test_auto_support import ME, _engine

ACTOR = ME

FORCE_VARIANT = "tianxia.brvariant.force.force-tempered-body"


# ------------------------------------------------------------------ finding 1: the sheet leak
def test_choice_owner_marker_routes_the_printed_choice_from_compiled_data(monkeypatch):
    """The authority row names the variant by "id"; the routing row is bookkeeping, never an ability."""
    row = {"id": FORCE_VARIANT, "riders": [{"kind": "choice"}]}
    monkeypatch.setattr(bv.authority, "owned", lambda owner_sheet: [row])
    info = {"owner_sheet": {}, "passives": []}
    bv.choice_owner_marker(info)
    assert info["passives"] == [{"feature_id": FORCE_VARIANT, "choice_owner": True, "ownership_only": True}]


def test_the_moon_cleaver_routing_row_is_bookkeeping_only():
    """Finding 1, shared path: the Moon-Cleaver marker hides its routing row the same way."""
    info = {"owned_ids": ["TAL_AXES_MOON_CLEAVER_RETURN"], "passives": []}
    thrown_equipment.moon_choice_owner(info)
    (row,) = info["passives"]
    assert row["feature_id"] == "TAL_AXES_MOON_CLEAVER_RETURN" and row["choice_owner"] is True
    assert row["ownership_only"] is True, "a bare routing row puts the technique id in the sheet's automated list"


def test_a_body_refiners_choice_owner_is_routed_but_never_listed_on_the_sheet(tmp_path):
    """The seat still owns the printed choice (marker present), and the sheet shows no variant id."""
    install(tmp_path, sheet(spheres=["tianxia.sphere.force"]))
    tabletop = service(tmp_path)
    _sheet, bundle, _summary = tabletop._bundle_and_summary(PID)
    owners = [row for row in bundle["typed_passives"] if row.get("choice_owner")]
    assert owners, "the Force variant's printed choose-one row is a choice owner"
    assert all(row.get("ownership_only") for row in owners), "bookkeeping rows are never player abilities"
    listed = tabletop.sheet(PID)["features"]["automated_passives"]
    assert not [value for value in listed if "brvariant" in value], listed


# ------------------------------------------------------- finding 2: stale pin blast radius
def test_a_stale_pin_only_fails_the_body_refining_lookup_not_the_insight_catalog(monkeypatch):
    from app.core import FoundryError
    from canonical_catalog import service as catalog_service
    from factory_authoring import body_refining_variants

    def stale():
        raise ValueError("Body Refining version authority hash does not verify")

    monkeypatch.setattr(body_refining_variants, "authored_insights", stale)
    catalog = catalog_service.CanonicalCatalogAuthorityService(ROOT)
    listing = catalog.list_insights()
    assert listing["count"] > 0, "every character still gets the CAT3 insight catalog"
    assert not [row for row in listing["records"] if row["canonical_insight_id"] == "insight.ashen-body"]
    with pytest.raises(FoundryError) as caught:
        catalog.get_insight("insight.ashen-body")
    assert caught.value.code == "CANONICAL_BODY_REFINING_PIN_STALE"


@pytest.fixture
def corpus_source(tmp_path):
    """Recreate the extract byte-for-byte without publishing its private Markdown.

    The fixture stores only section metadata and line ranges. All rule prose is
    loaded from the exact Factory archive already cleared for public tests.
    """
    recipe = json.loads((ROOT / "tests/fixtures/body_refining_source_rules.json").read_text())
    provenance = recipe["provenance"]
    with zipfile.ZipFile(ROOT / "BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip") as archive:
        (member,) = [name for name in archive.namelist() if name.endswith("/" + provenance["path"])]
        corpus = archive.read(member)
    assert hashlib.sha256(corpus).hexdigest() == provenance["markdown_sha256"]
    lines = corpus.decode().splitlines()
    parts = ["# Body Refining source extracts\n\n<!-- provenance " + json.dumps(provenance) + " -->\n\n"]
    for section in recipe["sections"]:
        meta = section["metadata"]
        start, end = meta["source_lines"]
        body = "\n".join(lines[start - 1:end]).rstrip("\n") + "\n" * section["trailing_newlines"]
        parts.append("<!-- " + section["kind"] + " " + json.dumps(meta, ensure_ascii=False) + " -->\n"
                     + body + "\n<!-- end -->\n\n")
    source = tmp_path / "source.md"
    source.write_text("".join(parts).rstrip("\n") + "\n")
    return source


def test_public_corpus_recreates_the_exact_builder_input(corpus_source):
    """F31: public inputs reproduce the full original extract, not a reduced substitute."""
    from factory_authoring import body_refining_builder, body_refining_variants

    assert hashlib.sha256(corpus_source.read_bytes()).hexdigest() == (
        body_refining_variants.access()["source"]["excerpts_sha256"])
    assert "SOURCE" not in vars(body_refining_builder), "the reusable builder must accept its source from the caller"


def test_the_committed_authority_pin_matches_the_builder_output(corpus_source):
    """A stale pin can never ship: rebuilding from the corpus reproduces the committed bytes and pin."""
    from factory_authoring import body_refining_variants
    from factory_authoring.body_refining_builder import build, encoded

    payload = encoded(build(corpus_source))
    assert payload == body_refining_variants.AUTHORITY.read_bytes(), "rebuild the authority: builder output differs"
    assert hashlib.sha256(payload).hexdigest() == body_refining_variants.AUTHORITY_SHA256, "update the pinned hash"


# --------------------------------------------------------- finding 3: the short-rest rule
def _rest_rows():
    """One rest-scoped and one permanent condition, as the engine records both."""
    def row(instance_id, expires_on):
        return ConditionInstance(instance_id=instance_id, condition_id="condition:test." + instance_id,
                                 source_definition_id="test:source", source_actor_id="actor:a", target_id="actor:a",
                                 applied_sequence=0, expires_on=expires_on, data={})

    return {"rest": row("rest", effect_endings.SHORT_REST_EXPIRY),
            "permanent": row("permanent", "UNTIL_REMOVED")}


def test_a_saved_fight_rest_ends_exactly_the_engines_rest_scoped_rows():
    """The saved boundary uses the engine's ending path, not just its expiry predicate.

    Permanent conditions survive, and the actual expiry event is saved for replay.
    """
    assert effect_endings.ends_at_short_rest(effect_endings.SHORT_REST_EXPIRY)
    assert not effect_endings.ends_at_short_rest("UNTIL_REMOVED")
    assert not effect_endings.ends_at_short_rest(None)
    snapshot = {"current_hp": 10, "maximum_hp": 40, "temporary_hp": 0, "active": 1, "life_state": "",
                "conditions": {key: json.dumps(value.model_dump(mode="json", exclude_none=True), sort_keys=True)
                               for key, value in _rest_rows().items()},
                "death_saves": {"ok": 0, "bad": 0}}
    from tests.test_brs1f14r_short_rest_boundary import session_with
    session = session_with(snapshot)
    journey_setup.end_rest_scoped_conditions(session, 'actor:a')
    snapshot = session.state["actors"]['actor:a']["encounter_snapshot"]
    assert set(snapshot["conditions"]) == {"permanent"}, "the saved fight ends only the rest-scoped condition"
    events = [json.loads(row) for row in session.state["events"][-1]["combat_events"]]
    assert any(event["event_type"] == "CONDITION_REMOVED"
               and event["payload"]["checkpoint"] == "SHORT_REST" for event in events)


# --------------------------------------------- finding 4: layering (label and zone kinds)
def test_combat_names_a_free_use_from_its_compiled_data_not_the_authoring_files():
    """The printed name is compiled onto the grant as its title; the label reader has no authoring import."""
    assert "factory_authoring" not in inspect.getsource(free_uses)
    assert free_uses.grant_label({"title": "Air Bellows Body", "state": "br_variant:" + FORCE_VARIANT,
                                  "key": "k"}) == "Air Bellows Body"
    assert free_uses.grant_label({"state": "br_variant:" + FORCE_VARIANT, "key": "k"}) == "Body Refining variant"


def test_named_zone_kinds_are_answered_by_the_plug_in_that_owns_the_ground():
    """br_variants asks the registered kind; Sand and Air register their own rule and are never imported."""
    source = inspect.getsource(bv)
    assert "sand_terrain" not in source and "air_currents" not in source, "one plug-in must not import another"
    load_plug_ins()
    assert zone_kinds.KINDS["sand"] is sand_terrain.is_sand_zone
    assert zone_kinds.KINDS["current"].__name__ == "is_current"
    sand = SimpleNamespace(active=True, owner_id=ACTOR, trigger_profile={"visual": {"material": "sand"}})
    stone = SimpleNamespace(active=True, owner_id=ACTOR, trigger_profile={"visual": {"material": "stone"}})
    owner = SimpleNamespace(entity_id=ACTOR)
    assert zone_kinds.matches(None, owner, sand, "sand") and not zone_kinds.matches(None, owner, stone, "sand")
    bundle = compile_character(sheet(spheres=["tianxia.sphere.ash"]), actor_id=ACTOR)
    engine = _engine(bundle)
    assert bv._zone(engine, engine.state.actors[ACTOR], "ash") is False
