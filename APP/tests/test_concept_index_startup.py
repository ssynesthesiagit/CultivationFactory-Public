"""Startup-to-build regression with a simulated slow embedding service."""
import asyncio
import json
from pathlib import Path
from threading import Event, current_thread
from types import SimpleNamespace

from app.api import create_app
from app.core import Settings
from character_creation import concept_index as ci
from stage1.service import Stage1ClipboardService


def test_startup_warms_published_documents_before_freezing_build_advice(tmp_path, monkeypatch):
    # Six 32-row batches at 5.5 seconds each, even without the kit catalogs.
    published = [{
        "record_id": f"sphere.{i}", "display_name": f"School {i}", "content_type": "sphere",
        "summary": f"Printed rules for school {i}.", "source": {"source_hash": "a" * 64},
        "content_binding": {"pack_id": "test", "pack_version": "1", "pack_hash": "b" * 64},
        "record_hash": "c" * 64,
    } for i in range(192)]
    monkeypatch.setenv("TIANXIA_CONCEPT_EMBEDDINGS", "1")
    monkeypatch.delenv("TIANXIA_CONCEPT_CACHE", raising=False)

    settings = Settings.from_env(Path(__file__).resolve().parents[1], tmp_path)
    cache = tmp_path / "cache/concept_embeddings.json"
    rows = [Stage1ClipboardService._choice(record) for record in published]
    # Per-request metadata must not make the published text cold again.
    rows[0]["compiler_selection_evidence"] = {"content_lock_hash": "project-specific"}
    request = {"concept": "School 0", "delegated_choice_envelope": {
        "choices_by_slot": {"sphere_priorities": rows},
    }}

    batches = []
    timeout_batches = []
    clock = [0.]
    warm_started, release_warmup = Event(), Event()
    workers = []
    monkeypatch.setattr(ci, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(ci, "DIMENSIONS", 2)

    class FakeEmbeddingClient:
        def __init__(self, endpoint):
            self.endpoint = endpoint

        def embed(self, texts, timeout=None):
            if current_thread().name == "concept-index-warm" and not workers:
                workers.append(current_thread())
                warm_started.set()
                if not release_warmup.wait(10):
                    raise TimeoutError("Startup did not return while warming the index")
            batches.append(list(texts))
            if texts[0].startswith("title: "):
                if timeout is not None and timeout < 5.5:
                    timeout_batches.append(texts)
                    raise TimeoutError("Document batch exceeded its remaining budget")
                clock[0] += 5.5
            return [[1., 0.] for _ in texts]

    monkeypatch.setattr(ci, "EmbeddingClient", FakeEmbeddingClient)

    cold_cache = tmp_path / "cold" / cache.name
    assert ci.freeze_concept_guidance(request, cache_path=cold_cache) == {}
    assert timeout_batches == [batches[-1]]
    assert [len(batch) for batch in batches] == [32] * 6
    assert all(text.startswith("title: ") for batch in batches for text in batch)
    batches.clear()

    app = create_app(settings)
    with app.state.db.transaction() as conn:
        conn.execute(
            """INSERT INTO content_packs
               (pack_id, version, pack_hash, lifecycle_state, authority, manifest_json, installed_at)
               VALUES ('test', '1', ?, 'published', 'canonical', '{}', '2026-01-01')""",
            ("b" * 64,),
        )
        conn.executemany(
            """INSERT INTO catalog_records
               (record_id, content_type, display_name, pack_id, pack_version, authority, publication_state,
                source_path, source_anchor, source_hash, record_hash, data_json)
               VALUES (?, 'sphere', ?, 'test', '1', 'canonical', 'published', '', '', ?, ?, ?)""",
            [(r["record_id"], r["display_name"], r["source"]["source_hash"], r["record_hash"], json.dumps(r))
             for r in published],
        )

    try:
        asyncio.run(app.router.startup())
        assert warm_started.wait(10), "Service startup did not warm the concept index"
    finally:
        release_warmup.set()
        if workers:
            workers[0].join(timeout=15)
    assert not workers[0].is_alive()
    assert sum(len(batch) for batch in batches) >= len(published)
    assert all(text.startswith("title: ") for batch in batches for text in batch)
    batches.clear()

    queries = ["task: search result | query: School 0", "task: search result | query: school 0"]
    advice = ci.freeze_concept_guidance(request, cache_path=cache)
    assert batches == [queries]
    assert advice["requirements"][0]["id"] == "sphere.0"
    assert advice["shortlist"]["sphere"]

    # A different project can use an older description without evicting the shared catalog.
    batches.clear()
    variant = {**rows[0], "description": "An older edition of the rules."}
    variant_request = {**request, "delegated_choice_envelope": {
        "choices_by_slot": {"sphere_priorities": [variant]},
    }}
    assert ci.freeze_concept_guidance(variant_request, cache_path=cache)
    assert batches == [["title: School 0 | text: An older edition of the rules."], queries]
    batches.clear()
    assert ci.freeze_concept_guidance(request, cache_path=cache)
    assert batches == [queries]
