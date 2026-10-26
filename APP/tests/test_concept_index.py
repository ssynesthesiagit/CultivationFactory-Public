"""Optional concept advice: fake HTTP embeddings and a local-service smoke.

No model is launched. The real smoke skips only when the existing local
endpoint cannot be reached. All cache files belong to pytest's basetemp.
"""
from dataclasses import replace
from io import BytesIO
import json
import math
from pathlib import Path
from urllib.error import URLError

import pytest

from character_creation import concept_index as ci

BRIEF = "meteor Hammer using earth and lava + Ash cultivation"
HAMMER = "tianxia.mortal.weapon.liu_xing_chui"
SPHERES = ["tianxia.sphere." + name for name in ("ash", "earth", "magma")]


def _records():
    return [ci.Record(HAMMER, "equipment", "Meteor Hammer", "A flexible chain weapon."),
            ci.Record("hammer", "equipment", "Hammer", "A blunt weapon."),
            ci.Record(SPHERES[0], "sphere", "Ash", "Residue and cinders."),
            ci.Record(SPHERES[1], "sphere", "Earth", "Stone and soil."),
            ci.Record(SPHERES[2], "sphere", "Magma", "Molten terrain and lava flows."),
            ci.Record("sphere.fire", "sphere", "Fire", "Flame and burning."),
            ci.Record("insight.stone", "insight", "Stone Meditation", "Meditate on earth.")]


def _fake_vector(text):
    vector = [0] * ci.DIMENSIONS
    text = text.casefold()
    terms = ("meteor hammer", "ash", "earth", "magma", "fire", "hammer", "stone meditation")
    if text.startswith("title: "):
        title = text.split(" | text:", 1)[0].removeprefix("title: ")
        if "meteor hammer" in title:
            title = "meteor hammer"
        vector[terms.index(title) if title in terms else 10] = 1
    else:
        query = text.split(" | query: ", 1)[1].replace("lava", "magma")
        for i, term in enumerate(terms):
            if term in query and not (term == "hammer" and "meteor hammer" in query):
                vector[i] = 1
        if not any(vector):
            vector[11] = 1
    return vector


@pytest.fixture
def fake_server(monkeypatch):
    """Fake OpenAI HTTP server at the urllib boundary; no socket needed.

    The managed sandbox forbids listening sockets. Requests still pass through
    EmbeddingClient's JSON encoder and response validation, including indexes.
    """
    batches = []
    endpoint = "http://127.0.0.1:11499"

    def serve(request, timeout):
        if request.full_url != endpoint + "/v1/embeddings":
            raise URLError("Fake local embedding service is down")
        assert request.get_method() == "POST"
        assert request.get_header("Content-type") == "application/json"
        body = json.loads(request.data)
        batches.append(body["input"])
        vectors = [{"index": i, "embedding": _fake_vector(text)} for i, text in enumerate(body["input"])]
        return BytesIO(json.dumps({"data": list(reversed(vectors))}).encode())

    monkeypatch.setattr(ci, "urlopen", serve)
    yield ci.EmbeddingClient(endpoint), batches


def test_batches_cache_and_only_changed_content_reembedded(tmp_path, fake_server):
    client, batches = fake_server
    rows = _records()
    cache = tmp_path / "index.json"
    first = ci.ConceptIndex(rows, cache, client, batch_size=3)
    first.build()
    assert [len(b) for b in batches] == [3, 3, 1]
    second = ci.ConceptIndex(rows, cache, client)
    second.build()
    assert len(batches) == 3
    assert first.vectors == second.vectors
    ci.ConceptIndex([replace(rows[0], text="Changed printed text."), *rows[1:]], cache, client).build()
    assert len(batches[-1]) == 1
    ci.ConceptIndex([replace(rows[0], text="Changed printed text.", source_sha256="new-authority"), *rows[1:]], cache, client).build()
    assert len(batches[-1]) == 1
    assert not list(tmp_path.glob(".concept-index-*"))


def test_corrupt_cache_rebuilds_and_model_namespace_invalidates(tmp_path, fake_server, monkeypatch):
    client, batches = fake_server
    cache = tmp_path / "index.json"
    cache.write_text("{broken")
    ci.ConceptIndex(_records(), cache, client).build()
    monkeypatch.setattr(ci, "CACHE_VERSION", "changed-model")
    ci.ConceptIndex(_records(), cache, client).build()
    assert len(batches) == 2
    raw = json.loads(cache.read_text())
    raw["vectors"][next(iter(raw["vectors"]))] = [1]
    cache.write_text(json.dumps(raw))
    ci.ConceptIndex(_records(), cache, client).build()
    assert len(batches[-1]) == 1


def test_nonunit_cache_keeps_normalized_scores(tmp_path, fake_server):
    client, batches = fake_server
    cache = tmp_path / "index.json"
    rows = _records()
    ci.ConceptIndex(rows, cache, client).build()
    raw = json.loads(cache.read_text())
    raw["vectors"] = {key: [2 * x for x in vector] for key, vector in raw["vectors"].items()}
    cache.write_text(json.dumps(raw))
    index = ci.ConceptIndex(rows, cache, client)
    index.build()
    assert len(batches) == 1  # Valid cached values need no service call.
    assert all(sum(x * x for x in v) == pytest.approx(1) for v in index.vectors.values())
    query = [0.4, math.sqrt(0.84), *([0] * (ci.DIMENSIONS - 2))]
    assert next(r for r in index.rank(query) if r["id"] == HAMMER)["score_milli"] == 400
    # Adding a new row also persists the normalized old values during cache replacement.
    expanded = ci.ConceptIndex([*rows, ci.Record("new", "sphere", "New", "New")], cache, client)
    expanded.build()
    assert all(sum(x * x for x in v) == pytest.approx(1)
               for v in json.loads(cache.read_text())["vectors"].values())


def test_partial_server_failure_retains_completed_batches(tmp_path, fake_server):
    client, batches = fake_server

    class FlakyClient:
        endpoint = client.endpoint
        calls = 0

        def embed(self, texts):
            self.calls += 1
            if self.calls == 2:
                raise URLError("Fake server stopped during index warm-up")
            return client.embed(texts)

    cache = tmp_path / "index.json"
    with pytest.raises(URLError):
        ci.ConceptIndex(_records(), cache, FlakyClient(), batch_size=3).build()
    assert len(json.loads(cache.read_text())["vectors"]) == 3
    ci.ConceptIndex(_records(), cache, client).build()
    assert [len(batch) for batch in batches] == [3, 4]


def test_qian_shortlist_requirements_and_prefixes(tmp_path, fake_server):
    client, batches = fake_server
    index = ci.ConceptIndex(_records(), tmp_path / "index.json", client)
    index.build()
    advice = ci.guidance(index, BRIEF)
    assert advice["shortlist"]["equipment"][0]["id"] == HAMMER
    assert {r["id"] for r in advice["requirements"]} == {HAMMER, *SPHERES[:2]}
    assert {r["id"] for r in advice["suggestions"]} == {SPHERES[2]}
    assert all(type(r["score_milli"]) is int for r in advice["requirements"])
    assert all(t.startswith("title: ") and " | text: " in t for t in batches[0])
    assert all(t.startswith("task: search result | query: ") for t in batches[-1])
    assert ("hammer", "hammer") not in ci.concept_phrases(BRIEF, _records())


def test_coverage_checks_acquisitions_and_actual_equipment(tmp_path, fake_server):
    client, _ = fake_server
    index = ci.ConceptIndex(_records(), tmp_path / "index.json", client)
    index.build()
    request = {"concept_guidance": ci.guidance(index, BRIEF),
               "planning_preferences_by_slot": {"item_priorities": [HAMMER], "sphere_priorities": SPHERES},
               "owner_descriptive_fields": {"concept": "Promises a meteor hammer and Ash/Earth/Magma"}}
    assert len(ci.coverage_warnings(request, [])) == 3
    assert len(ci.coverage_warnings(request, SPHERES)) == 1
    kit = {"items": [{"item_id": HAMMER}], "treasure_weapon": {"chassis_id": HAMMER}}
    assert ci.coverage_warnings(request, SPHERES, kit) == []
    assert len(ci.coverage_warnings(request, [], kit)) == 2
    assert all("tianxia." not in warning for warning in ci.coverage_warnings(request, []))


class MisleadingWhipClient:
    """Deterministic local client: chain-whip queries favor the wrong whip."""
    endpoint = "fake://misleading-whip"

    def __init__(self):
        self.queries = []

    def embed(self, texts):
        vectors = []
        for text in texts:
            vector = [0] * ci.DIMENSIONS
            if text.startswith("title: Ruan Bian (Whip) |"):
                coordinate = 0
            elif text.startswith("title: Jie Bian ("):
                coordinate = 1
            elif text.startswith("task: search result | query: "):
                query = text.split(" | query: ", 1)[1]
                self.queries.append(query)
                coordinate = 0 if query in {"chain whip", "chain whips", "whip"} else 2
            else:
                coordinate = 2
            vector[coordinate] = 1
            vectors.append(vector)
        return vectors


@pytest.mark.parametrize("phrase", ["chain whip", "chain whips", "sectional steel whip"])
def test_catalog_gear_aliases_override_misleading_embeddings(phrase, tmp_path):
    from factory_authoring.starting_kits import owner_named_gear

    client = MisleadingWhipClient()
    index = ci.ConceptIndex(ci.records_from_request({}), tmp_path / "index.json", client)
    index.build()
    query = client.embed([f"task: search result | query: {phrase}"])[0]
    if phrase.startswith("chain whip"):
        assert index.rank(query, "equipment")[0]["id"] == "tianxia.mortal.weapon.ruan_bian"
    concept = f"A fighter carrying a meteor hammer and {phrase}"
    gear = owner_named_gear(concept)
    owned = [HAMMER, "tianxia.mortal.weapon.jie_bian"]
    assert gear["item_ids"] == owned
    advice = ci.guidance(index, concept)
    assert {row["id"] for row in advice["requirements"]} == set(owned)
    assert not advice["suggestions"]
    assert ci.coverage_warnings({"owner_gear_requirements": gear["items"],
                                 "concept_guidance": advice}, [],
                                {"items": [{"item_id": item} for item in owned]}) == []
    # A separate utility chain is still a real uncovered concept.
    utility = ci.guidance(index, "A fighter with a chain")
    warnings = ci.coverage_warnings({"owner_gear_requirements": gear["items"],
                                     "concept_guidance": utility}, [],
                                    {"items": [{"item_id": item} for item in owned]})
    assert len(warnings) == 1
    assert "asks for chain" in warnings[0]


def test_service_resolved_chain_whip_ignores_embedding_mismatch(
        tmp_path, factory_environment, monkeypatch):
    import test_cg1_character_creation_modes as modes

    client = MisleadingWhipClient()
    monkeypatch.setattr(ci, "EmbeddingClient", lambda *args, **kwargs: client)
    monkeypatch.setenv("TIANXIA_CONCEPT_EMBEDDINGS", "1")
    monkeypatch.setenv("TIANXIA_CONCEPT_CACHE", str(tmp_path / "index.json"))
    monkeypatch.setattr(modes, "_PINNED_VENDOR_DIR", Path(factory_environment["settings"].vendor_dir))
    submitted, reloaded = modes._coordinated_gear_submission_and_reload(
        tmp_path, factory_environment, "A fighter carrying a meteor hammer and chain whip",
        [HAMMER, "tianxia.mortal.weapon.jie_bian"],
    )
    assert "chain whip" in client.queries  # Real indexing/guidance, no frozen-advice stub.
    assert submitted["status"] == reloaded["status"] == "READY_FOR_REVIEW"
    assert submitted["warnings"] == reloaded["warnings"] == []
    assert reloaded["request"]["concept_guidance"] == submitted["request"]["concept_guidance"]


@pytest.mark.parametrize("phrase, gear_id", [
    ("staff", "tianxia.mortal.focus.qi_focus_staff"),
    ("spear", "tianxia.mortal.weapon.duan_qiang"),
    ("mountain-pattern grand shell", "tianxia.mortal.armor.mountain_pattern_grand_shell"),
])
def test_owner_gear_policy_owns_coverage_without_hiding_other_concepts(phrase, gear_id):
    request = {"owner_gear_warnings": ["Owner gear advice"], "concept_guidance": {
        "requirements": [
            {"id": gear_id, "name": "Gear", "category": "equipment", "phrase": phrase,
             "match": "owner_named"},
            {"id": "waterskin", "name": "Waterskin", "category": "equipment", "phrase": "waterskin",
             "match": "owner_named"},
            {"id": SPHERES[0], "name": "Ash", "category": "sphere", "phrase": "ash",
             "match": "owner_named"},
        ],
    }}
    warnings = ci.coverage_warnings(request, [])
    assert len(warnings) == 2
    assert "does not include Waterskin" in warnings[0]
    assert "does not include Ash" in warnings[1]
    assert ci.coverage_warnings(request, SPHERES, {"items": [{"item_id": "waterskin"}]}) == []
    # Standalone concept coverage still checks gear when no owner-gear policy
    # is present; planning preferences alone cannot claim it was acquired.
    assert len(ci.coverage_warnings({"concept_guidance": request["concept_guidance"]}, [])) == 3


@pytest.mark.parametrize("concept, purchases, status, warning_count", [
    ("A fighter carrying a staff and sickle", ["tianxia.mortal.weapon.lian"], "READY_FOR_REVIEW", 0),
    ("A fighter with a staff, a sickle, and a crossbow", ["tianxia.mortal.weapon.nu_gong"], "NEEDS_REVIEW", 1),
])
def test_service_owner_gear_coverage_persists_one_authority(
        concept, purchases, status, warning_count, tmp_path, factory_environment, monkeypatch):
    """Real kit submission/reload with frozen advice, independent of embeddings."""
    import test_cg1_character_creation_modes as modes
    from app.core import canonical_json
    from catalog.service import CatalogService
    from character_creation.constructed_arts.records import construct_starting_kit, build_starting_kit_record
    from project_store.service import ProjectStore
    from tests.r4v_harness import provision_external_test_key

    advice = {"shortlist": {}, "requirements": [
        {"id": "tianxia.mortal.focus.qi_focus_staff", "name": "Qi Focus (Staff)",
         "category": "equipment", "phrase": "staff", "match": "owner_named"},
        {"id": "tianxia.mortal.weapon.lian", "name": "Lian (Sickle)",
         "category": "equipment", "phrase": "sickle", "match": "owner_named"},
    ]}
    monkeypatch.setattr(ci, "freeze_concept_guidance", lambda request, **_: advice)
    monkeypatch.setattr(modes, "_PINNED_VENDOR_DIR", Path(factory_environment["settings"].vendor_dir))
    service, _, db = modes.make(tmp_path)
    provision_external_test_key(db.settings.data_dir)
    CatalogService(db).rebuild_core(factory_environment["root"])
    store = ProjectStore(db)
    pack = modes.pinned_content_lock()["packs"][0]
    with db.transaction() as conn:
        seal = store.verified_pack_seal(conn, pack["pack_id"], pack["version"], pack["content_hash"])
        store._snapshot_pack_seals(conn, "p", [seal], locked_at="now")
        project = json.loads(conn.execute("SELECT project_json FROM projects WHERE project_id='p'").fetchone()[0])
        project["user_locks"].append({"field": "concept", "value": concept})
        conn.execute("UPDATE projects SET project_json=? WHERE project_id='p'", (canonical_json(project),))
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="owner-gear-coverage")
    assert run["request"]["concept_guidance"] == advice
    assert run["request"]["owner_gear_requirements"]
    seed = "owner-gear-coverage"
    decision = {"path_option": "option_b", "picks": {"background:1": 2}, "purchases": purchases}
    kit = construct_starting_kit(background_id="tianxia.background.village_child",
                               path_id="tianxia.path.spirit_awakening", seed=seed, **decision)
    response = modes.bound_plan(run)
    response["owner_descriptive_fields"]["concept"] = concept
    response["canonical_selection_intent"] = {
        "acquisition_intent": {"starting_kit": decision},
        "selected_by_slot": {"background_choice": ["tianxia.background.village_child"],
                             "path_choice": ["tianxia.path.spirit_awakening"]},
        "bounded_choices": {},
    }
    response["materialization_receipt"] = {"canonical_intent_hash": seed}
    response["stage2_proposal"]["choices"].append({"kind": "equipment_acquisition", "effective_cl": 1,
                                                 "record_id": build_starting_kit_record(kit)["record_id"]})
    submitted = service.submit_manual(run["run_id"], response_text=canonical_json(response),
                                      request_sha256=run["request"]["request_sha256"])
    assert submitted["validation"]["valid"], submitted["validation"]
    assert submitted["dry_run"]["independent_compilations"] == 2
    assert submitted["status"] == status
    assert submitted["quality"]["status"] == ("CLEAN" if not warning_count else "NEEDS_REVIEW")
    assert len(submitted["warnings"]) == warning_count
    if warning_count:
        assert submitted["warnings"][0]["code"] == "CG1_OWNER_NAMED_GEAR_UNAVAILABLE"
        assert "Lian (Sickle)" in submitted["warnings"][0]["message"]
    reloaded = service.get(run["run_id"])
    assert reloaded["status"] == submitted["status"]
    assert reloaded["quality"] == submitted["quality"]
    assert reloaded["warnings"] == submitted["warnings"]


def test_freeze_and_fallback_leave_request_unchanged(tmp_path, fake_server, monkeypatch):
    client, _ = fake_server
    request = {"concept": BRIEF}
    monkeypatch.setenv("TIANXIA_CONCEPT_EMBEDDINGS", "1")
    monkeypatch.setenv("TIANXIA_CONCEPT_CACHE", str(tmp_path / "index.json"))
    monkeypatch.setenv("TIANXIA_EMBEDDING_ENDPOINT", client.endpoint)
    monkeypatch.setattr(ci, "records_from_request", lambda _: _records())
    assert ci.freeze_concept_guidance(request)["requirements"]
    assert request == {"concept": BRIEF}
    monkeypatch.setenv("TIANXIA_EMBEDDING_ENDPOINT", "http://127.0.0.1:11498")
    assert ci.freeze_concept_guidance(request) == {}
    assert request == {"concept": BRIEF}
    monkeypatch.setenv("TIANXIA_CONCEPT_EMBEDDINGS", "0")
    assert ci.freeze_concept_guidance(request) == {}


def test_unknown_phrases_do_not_invent_requirements(tmp_path, fake_server):
    client, _ = fake_server
    index = ci.ConceptIndex(_records(), tmp_path / "index.json", client)
    index.build()
    assert ci.guidance(index, "purple time traveler")["requirements"] == []


@pytest.mark.parametrize("brief, expected", [
    ("An Earth cultivator without a meteor hammer", {SPHERES[1]}),
    ("Earth or Ash", set()),
    ("a sword or a spear", set()),
    ("not fire", set()),
    ("not using fire", set()),
    ("without wielding a meteor hammer", set()),
    ("neither Earth nor Ash", set()),
    ("do not use fire", set()),
    ("without fire and ash, with Earth", {SPHERES[1]}),
    ("Earth/Ash", set()),
    ("Earth, Ash, or Fire", set()),
    ("Earth; a sword or a spear", {SPHERES[1]}),
    ("without fire, ash and a meteor hammer", set()),
    ("Earth without fire, ash and a meteor hammer", {SPHERES[1]}),
    ("can't use fire", set()),
    ("don’t use fire", set()),
    ("not fire but Earth and a meteor hammer", {SPHERES[1], HAMMER}),
])
def test_excluded_and_alternative_phrases_are_not_requirements(brief, expected, tmp_path, fake_server):
    client, _ = fake_server
    rows = [*_records(), ci.Record("sword", "equipment", "Sword", "Blade"),
            ci.Record("spear", "equipment", "Spear", "Point")]
    index = ci.ConceptIndex(rows, tmp_path / "index.json", client)
    index.build()
    advice = ci.guidance(index, brief)
    assert {r["id"] for r in advice["requirements"]} == expected
    assert advice["suggestions"] == []
    assert ci.coverage_warnings({"concept_guidance": advice}, list(expected)) == []


# Lead's existing-service measurements, using the production search/document
# prefixes. Each case has a unit query and documents with the measured cosine
# in coordinate 0 plus an orthogonal residual. These are calibration fixtures,
# not a claim to reproduce the model's full embedding space.
MEASURED_CASES = [
    ("lava", [("Magma", .681), ("Ash", .634), ("Fire", .631)]),
    ("lava cultivation", [("Magma", .622), ("Ash", .591)]),
    ("earth", [("Earth", .694), ("Ash", .633), ("Magma", .630)]),
    ("ash cultivation", [("Ash", .710)]),
    ("meteor hammer", [("Meteor Hammer", .759), ("Maul", .661), ("Spear", .600)]),
    ("fire", [("Fire", .735)]),
    ("poison", [("Poison", .790)]),
    ("shadow step", [("Shadow", .697), ("Poison", .573)]),
]


@pytest.fixture
def measured_server(monkeypatch):
    def make(scores):
        rows = [ci.Record(name.lower().replace(" ", "_"),
                          "equipment" if name in {"Meteor Hammer", "Maul", "Spear", "Torch"} else "sphere",
                          name, "Calibration fixture") for name, _ in scores]

        def serve(request, timeout):
            body = json.loads(request.data)
            data = []
            for i, text in enumerate(body["input"]):
                vector = [0.] * ci.DIMENSIONS
                if text.startswith("title: "):
                    assert " | text: " in text
                    title = text.split(" | text: ", 1)[0].removeprefix("title: ")
                    j = next(j for j, (name, _) in enumerate(scores) if name == title)
                    vector[0] = scores[j][1]
                    vector[j + 1] = math.sqrt(1 - vector[0] ** 2)
                else:
                    assert text.startswith("task: search result | query: ")
                    query = text.split(" | query: ", 1)[1].casefold().removesuffix(" cultivation")
                    names = {name.casefold() for name, _ in scores}
                    vector[0 if query in names | {"lava", "shadow step"} else -1] = 1
                data.append({"index": i, "embedding": vector})
            return BytesIO(json.dumps({"data": data}).encode())

        monkeypatch.setattr(ci, "urlopen", serve)
        return rows, ci.EmbeddingClient("http://fake-calibration")
    return make


@pytest.mark.parametrize("phrase,scores", MEASURED_CASES)
def test_measured_top_matches_and_relative_acceptance(phrase, scores, tmp_path, measured_server):
    rows, client = measured_server(scores)
    index = ci.ConceptIndex(rows, tmp_path / "index.json", client)
    index.build()
    query = client.embed([f"task: search result | query: {phrase}"])[0]
    assert [(r["name"], r["score_milli"]) for r in index.rank(query)] == [
        (name, round(1000 * score)) for name, score in scores]
    advice = ci.guidance(index, phrase)
    assert advice["threshold_milli"] == 600 and advice["margin_milli"] == 30
    assert [r["name"] for r in (*advice["requirements"], *advice["suggestions"])] == [scores[0][0]]
    if phrase.startswith("lava"):
        assert advice["requirements"] == []
        assert advice["suggestions"][0]["match"] == "semantic"
        prompt = ci.prompt_guidance({"concept_guidance": advice})
        assert "Likely relevant (advice only" in prompt
        assert "Honor these concrete concepts" not in prompt
        assert ci.coverage_warnings({"concept_guidance": advice}, []) == []


def test_element_phrase_is_not_outscored_by_gear_across_categories(tmp_path, measured_server):
    """Fixed vectors reproduce the bug: Torch (.745) tops Magma (.681) across all categories."""
    rows, client = measured_server([("Torch", .745), ("Magma", .681), ("Ash", .634)])
    index = ci.ConceptIndex(rows, tmp_path / "index.json", client)
    index.build()
    query = client.embed(["task: search result | query: lava"])[0]
    assert index.rank(query)[0]["name"] == "Torch"
    advice = ci.guidance(index, "lava")
    assert advice["requirements"] == []
    assert [(r["name"], r["category"], r["match"]) for r in advice["suggestions"]] == [
        ("Magma", "sphere", "semantic")]
    assert ci.coverage_warnings({"concept_guidance": advice}, []) == []


def test_gear_noun_selects_equipment_and_element_selects_family(tmp_path, measured_server):
    rows, client = measured_server([("Torch", .745), ("Magma", .681), ("Ash", .634)])
    index = ci.ConceptIndex(rows, tmp_path / "index.json", client)
    index.build()
    query = client.embed(["task: search result | query: lava"])[0]
    assert [r["name"] for r in ci.semantic_candidates(index.rank(query), "lava")] == ["Magma", "Ash"]
    assert [r["name"] for r in ci.semantic_candidates(index.rank(query), "lava weapon")] == ["Torch"]


@pytest.mark.parametrize("scores", [
    [("Magma", .599), ("Ash", .560)],
    [("Magma", .620), ("Ash", .600)],
    [("Magma", .620), ("Ash", .620)],
])
def test_semantic_advice_requires_floor_and_clear_margin(scores, tmp_path, measured_server):
    rows, client = measured_server(scores)
    index = ci.ConceptIndex(rows, tmp_path / "index.json", client)
    index.build()
    advice = ci.guidance(index, "lava")
    assert advice["suggestions"] == advice["requirements"] == []
    assert len(advice["shortlist"]["sphere"]) == 2  # Weak advice still cannot hide choices.


def test_frozen_owner_title_is_included_and_generated_name_excluded():
    request = {"concept": "earth", "name": "Magma", "stage1_prompt": {"envelope": {"user_locks": [
        {"field": "character.identity.title", "value": "Ash Cultivator"}]}}}
    assert ci.owner_brief(request) == "earth Ash Cultivator"


def test_qian_prompt_measurement_and_printed_catalog_aliases(tmp_path, fake_server):
    from character_creation.creative_controller.linear_menus import build_step_menu, CommittedState
    from character_creation.creative_controller.linear_prompt import build_step_prompt

    client, _ = fake_server
    catalog = json.loads((ci.APP_ROOT / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text())
    request = {"request_sha256": "a" * 64, "concept": BRIEF, "delegated_choice_envelope": {
        "choices_by_slot": {"sphere_priorities": catalog["spheres"]}}}
    rows = [r for r in ci.records_from_request(request) if r.category in {"sphere", "equipment"}]
    index = ci.ConceptIndex(rows, tmp_path / "sample-index.json", client)
    index.build()
    advice = ci.guidance(index, BRIEF)
    assert {r["id"] for r in advice["requirements"]} == {HAMMER, *SPHERES[:2]}
    assert {r["id"] for r in advice["suggestions"]} == {SPHERES[2]}
    envelope = {"envelope_sha256": "b" * 64, "choices_by_slot": {"path_choice": [
        {"choice_id": "tianxia.path.qi_cultivation", "name": "Qi Cultivation"},
        {"choice_id": "tianxia.path.body_refining", "name": "Body Refining"},
        {"choice_id": "tianxia.path.spirit_awakening", "name": "Spirit Awakening"},
    ]}}
    state = CommittedState.empty()
    menu = build_step_menu(request, envelope, state, step_id="path_choice")
    before = build_step_prompt(request, envelope, state, menu)
    request["concept_guidance"] = advice
    after = build_step_prompt(request, envelope, state, menu)
    measurement = {"embedding_source": "deterministic fake HTTP server; real printed catalog records",
        "brief": BRIEF, "indexed_record_count": len(rows), "shortlist": advice["shortlist"],
        "requirements": advice["requirements"], "step_prompt_before_utf8_bytes": len(before.encode()),
        "step_prompt_after_utf8_bytes": len(after.encode()),
        "all_indexed_document_utf8_bytes": sum(len(r.document.encode()) for r in rows),
        "guidance_utf8_bytes": len(ci.prompt_guidance(request).encode())}
    (tmp_path / "prompt-measurement.json").write_text(json.dumps(measurement, indent=2))


def test_provider_payload_exposes_guidance_without_changing_legal_choices():
    from character_creation.service import _provider_payload, _provider_wire_compact_payload
    from test_compact_provider_prompt import _request
    request = _request()
    baseline = _provider_payload({"request": request}, cue_limit=100, display_limit=50)
    advice = {"schema": "TianxiaFoundry.ConceptGuidance.v1", "shortlist": {"sphere": [
        {"id": "sphere.fire", "name": "Fire", "category": "sphere", "score_milli": 950}]}, "requirements": []}
    request["concept_guidance"] = advice
    after = _provider_wire_compact_payload(_provider_payload({"request": request}, cue_limit=100, display_limit=50))
    assert after["most_relevant_to_owner_concept"] == advice
    assert after["allowed_choices_by_slot"] == baseline["allowed_choices_by_slot"]


def test_selectable_inventory_includes_features_and_catalogs():
    request = {"delegated_choice_envelope": {"choices_by_slot": {
        "path_choice": {"path.qi": {"name": "Qi Cultivation", "features": [
            {"record_id": "feature.qi", "name": "Qi Armor", "description": "Armor."}]}},
        "foundation_choice": [{"choice_id": "f", "name": "Foundation", "selectable": False}],
        "sphere_priorities": [{"choice_id": "s", "name": "Earth", "automatic_base_abilities": [
            {"record_id": "base", "name": "Automatic ability"}]}],
        "item_priorities": [{"choice_id": HAMMER, "name": "Liu Xing Chui (Meteor Hammer)"}],
    }}}
    rows = ci.records_from_request(request)
    assert any(r.id == "path.qi" and r.category == "path" for r in rows)
    assert any(r.id == "feature.qi" and r.category == "feature" for r in rows)
    assert not any(r.id in {"f", "base"} for r in rows)
    assert any(r.id == HAMMER and r.category == "equipment" and "Meteor Hammer" in r.aliases for r in rows)
    assert any(r.id.startswith("tianxia.treasure.") for r in rows)
    assert len(rows) > 500


def test_semantic_menus_keep_full_legal_choices_and_prompts(tmp_path, fake_server):
    from character_creation.creative_controller.linear_menus import build_step_menu, CommittedState
    from character_creation.creative_controller.linear_prompt import build_step_prompt
    client, _ = fake_server
    rows = [ci.Record("path.a", "path", "Fire", "Flames"), ci.Record("path.b", "path", "Magma", "Lava")]
    index = ci.ConceptIndex(rows, tmp_path / "index.json", client)
    index.build()
    request = {"request_sha256": "a" * 64, "concept": "lava"}
    envelope = {"envelope_sha256": "b" * 64, "choices_by_slot": {"path_choice": [
        {"choice_id": r.id, "name": r.name} for r in rows]}}
    baseline = build_step_menu(request, envelope, CommittedState.empty(), step_id="path_choice")
    request["concept_guidance"] = ci.guidance(index, "lava")
    menu = build_step_menu(request, envelope, CommittedState.empty(), step_id="path_choice")
    assert menu.options[0].choice_ids == ("path.b",)
    assert {o.choice_ids for o in baseline.options} == {o.choice_ids for o in menu.options}
    prompt = build_step_prompt(request, envelope, CommittedState.empty(), menu)
    assert "Most relevant to the owner's concept" in prompt
    assert prompt.index("Most relevant") < prompt.index("Options:")


def test_service_persists_concept_warnings_after_compilation(tmp_path, factory_environment, monkeypatch):
    """Exercise real request hashing/compilation/warning persistence in a test DB."""
    import test_cg1_character_creation_modes as modes
    from app.core import canonical_json

    monkeypatch.setattr(modes, "_PINNED_VENDOR_DIR", Path(factory_environment["settings"].vendor_dir))
    advice = {"schema": "TianxiaFoundry.ConceptGuidance.v1", "shortlist": {}, "requirements": [
        {"id": SPHERES[0], "name": "Ash", "category": "sphere", "phrase": "ash", "score_milli": 900,
         "match": "owner_named"},
    ]}
    monkeypatch.setattr(ci, "freeze_concept_guidance", lambda request, **_: advice)
    service, _, db = modes.make(tmp_path)
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="embed-warning-test")
    assert run["request"]["concept_guidance"] == advice
    result = service.submit_manual(run["run_id"], response_text=canonical_json(modes.bound_plan(run)),
                                   request_sha256=run["request"]["request_sha256"])
    assert result["dry_run"]["independent_compilations"] == 2
    assert result["quality"]["status"] == "NEEDS_REVIEW"
    assert len(result["warnings"]) == 1
    assert "does not include Ash" in result["warnings"][0]
    restored = service.get(run["run_id"])
    assert restored["warnings"] == result["warnings"]
    assert restored["request"]["concept_guidance"] == advice


@pytest.mark.parametrize("shape", ["suggestions", "requirements"])
def test_service_semantic_advice_preserves_kit_choices_and_coin(
        shape, tmp_path, factory_environment, monkeypatch):
    """Service→kit menus→compiled kit: inferred gear cannot spend player coin.

    The legacy shape deliberately carries match=semantic under requirements
    to cover defensive reads of previously frozen advice as well.
    """
    import test_cg1_character_creation_modes as modes
    from character_creation.creative_controller.linear_menus import (
        CommittedState, build_step_menu, owner_kit_plan,
    )
    from character_creation.creative_controller.linear_walk import commit_option
    from app.core import canonical_json
    from factory_authoring.starting_kits import resolve_starting_kit

    monkeypatch.setattr(modes, "_PINNED_VENDOR_DIR", Path(factory_environment["settings"].vendor_dir))
    advice = {"shortlist": {}, "requirements": [], shape: [
        {"id": HAMMER, "name": "Meteor Hammer", "category": "equipment",
         "phrase": "falling star weapon", "score_milli": 759, "match": "semantic"},
        {"id": SPHERES[2], "name": "Magma", "category": "sphere",
         "phrase": "lava", "score_milli": 681, "match": "semantic"},
    ]}
    monkeypatch.setattr(ci, "freeze_concept_guidance", lambda request, **_: advice)
    service, _, _ = modes.make(tmp_path)
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="semantic-choices")
    request = run["request"]
    assert request["concept_guidance"] == advice
    assert not request.get("owner_gear_preferences")
    assert not request.get("owner_gear_requirements")
    baseline_request = {k: v for k, v in request.items() if k != "concept_guidance"}
    state = CommittedState(by_slot={"background_choice": ["tianxia.background.military_brat"],
                                   "path_choice": ["tianxia.path.qi_cultivation"]})
    assert owner_kit_plan(request, {}, state) is None
    menu = build_step_menu(request, {}, state, step_id="starting_kit_option")
    assert [o.choice_ids for o in menu.options] == [("option_a",), ("option_b",)]
    for option in menu.options:
        picked = commit_option(menu, option.option_id, state)
        assert "purchases" not in picked.bounded["starting_kit"]
        for step_id in ("starting_kit_choice:background:1", "starting_kit_choice:path:1"):
            after = build_step_menu(request, {}, picked, step_id=step_id)
            before = build_step_menu(baseline_request, {}, picked, step_id=step_id)
            assert (None if after is None else {o.choice_ids for o in after.options}) == (
                None if before is None else {o.choice_ids for o in before.options})
        if option.choice_ids == ("option_b",):
            intent = {"target_cl": 1, "selected_by_slot": state.by_slot,
                      "acquisition_intent": {"starting_kit": picked.bounded["starting_kit"]}}
            kit = service._starting_kit_construction(intent, "a" * 64, 1)[0]["resolved"]
            plain = resolve_starting_kit(state.by_slot["background_choice"][0], state.by_slot["path_choice"][0],
                                        path_option="option_b", seed="a" * 64)
            assert kit["coin_cc"] == plain["coin_cc"]
            assert not any(item["source"] == "purchase" for item in kit["items"])
    result = service.submit_manual(run["run_id"], response_text=canonical_json(modes.bound_plan(run)),
                                   request_sha256=request["request_sha256"])
    assert result["quality"]["status"] == "CLEAN"
    assert result["warnings"] == service.get(run["run_id"])["warnings"] == []


@pytest.mark.parametrize("brief", ["without a meteor hammer", "Earth or Ash", "not fire", "a sword or a spear"])
def test_service_excluded_intent_keeps_clean_warning_state(
        brief, tmp_path, factory_environment, fake_server, monkeypatch):
    import test_cg1_character_creation_modes as modes
    from app.core import canonical_json

    client, _ = fake_server
    index = ci.ConceptIndex(_records(), tmp_path / "index.json", client)
    index.build()
    advice = ci.guidance(index, brief)
    assert advice["requirements"] == []
    monkeypatch.setattr(ci, "freeze_concept_guidance", lambda request, **_: advice)
    monkeypatch.setattr(modes, "_PINNED_VENDOR_DIR", Path(factory_environment["settings"].vendor_dir))
    service, _, _ = modes.make(tmp_path)
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="excluded-intent")
    result = service.submit_manual(run["run_id"], response_text=canonical_json(modes.bound_plan(run)),
                                   request_sha256=run["request"]["request_sha256"])
    restored = service.get(run["run_id"])
    assert result["quality"]["status"] == restored["quality"]["status"] == "CLEAN"
    assert result["warnings"] == restored["warnings"] == []


def test_service_keeps_explicit_gear_preferences_separate_from_advice(
        tmp_path, factory_environment, monkeypatch):
    import test_cg1_character_creation_modes as modes
    from app.core import canonical_json

    monkeypatch.setattr(modes, "_PINNED_VENDOR_DIR", Path(factory_environment["settings"].vendor_dir))
    advice = {"shortlist": {}, "requirements": [], "suggestions": [
        {"id": HAMMER, "name": "Meteor Hammer", "category": "equipment",
         "phrase": "falling star weapon", "match": "semantic", "score_milli": 759}]}
    monkeypatch.setattr(ci, "freeze_concept_guidance", lambda request, **_: advice)
    service, _, db = modes.make(tmp_path)
    project = modes.stub_project_document()
    dagger = "tianxia.mortal.weapon.bi_shou"
    project["user_locks"].append({"field": "character_sheet.gear_preferences", "value": [dagger]})
    with db.transaction() as conn:
        conn.execute("UPDATE projects SET project_json=? WHERE project_id='p'", (canonical_json(project),))
    run = service.start("p", execution_mode="MANUAL_CHAT", idempotency_key="explicit-gear")
    assert run["request"]["owner_gear_preferences"] == [dagger]


@pytest.mark.parametrize("raw", [[1], [0] * ci.DIMENSIONS, [float("nan")] * ci.DIMENSIONS])
def test_invalid_vectors_are_rejected(raw):
    with pytest.raises(ValueError):
        ci._vector(raw)


def test_real_local_embedding_service_smoke(tmp_path):
    client = ci.EmbeddingClient(timeout=3)
    try:
        vector = client.embed(["task: search result | query: meteor hammer"])[0]
    except (URLError, TimeoutError, ConnectionError):
        pytest.skip("Existing local embedding service is unreachable; no service was launched")
    assert len(vector) == 768
    assert sum(v * v for v in vector) == pytest.approx(1.0)
    catalog = json.loads((ci.APP_ROOT / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text())
    rows = [ci.Record(r["canonical_sphere_id"], "sphere", r["display_name"], r["full_exact_source_text"][:900])
            for r in catalog["spheres"]]
    rows += [r for r in ci.records_from_request({}) if r.category == "equipment"]
    index = ci.ConceptIndex(rows, tmp_path / "real-index.json", client, budget_seconds=60)
    index.build()
    intended = [
        ("fire", "sphere", "Fire"), ("lava", "sphere", "Magma"), ("earth", "sphere", "Earth"),
        ("ash cultivation", "sphere", "Ash"), ("meteor hammer", "equipment", "Meteor Hammer"),
        ("poison", "sphere", "Poison"), ("shadow step", "sphere", "Shadow"),
    ]
    vectors = client.embed([f"task: search result | query: {phrase}" for phrase, _, _ in intended])
    for (phrase, category, name), query in zip(intended, vectors):
        best = index.rank(query, category)[0]
        assert name.casefold() in best["name"].casefold(), (phrase, best)
    fire = ci.guidance(index, "fire")
    assert any(row["name"] == "Fire" and row["category"] == "sphere" for row in fire["requirements"])
    assert not any(row["category"] == "equipment" for row in (*fire["suggestions"], *fire["requirements"]))
