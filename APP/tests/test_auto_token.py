"""Post-commit Factory tokens; all Anima calls mocked, no live data or GUI."""

import ast
import inspect
import io
import json
import os
from pathlib import Path
import sqlite3
import textwrap
import threading
import zipfile
from types import SimpleNamespace
from contextlib import contextmanager
from copy import deepcopy

import pytest
from PIL import Image

from character_creation import CharacterCreationExecutionService
from character_creation import auto_token as auto
from combat.portraits import TokenStore, portrait_prompt
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.test_cg1_owner_resolution_finalization import _finalization_service_and_run

PID = "0badc0de-0000-4000-8000-00000000000a"
SHEET = {"identity": {"species": "Human", "title": "Bone Monarch"},
         "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.death"]}}


def png(color="red", size=(768, 768)):
    out = io.BytesIO()
    Image.new("RGBA", size, color).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TIANXIA_AUTO_TOKEN", "1")
    monkeypatch.setattr(auto, "reachable", lambda: True)
    package = tmp_path / "portable_characters" / PID / "current.zip"
    package.parent.mkdir(parents=True)
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(SHEET))
    calls = []

    def generate(prompt, seed, *, framing):
        calls.append((prompt, seed, framing))
        return png()

    monkeypatch.setattr(auto.portraits, "anima_generate", generate)
    return tmp_path, calls


def service(root, monkeypatch, *, failed=False):
    """A committed-finalizer double with real SQLite COMMIT, real public wrapper.

    The AST boundary test below separately checks the production finalizer's
    transaction/rollback ordering; these service tests exercise asynchronous work.
    """
    db_path = root / "committed.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE finalized (status TEXT)")
    svc = object.__new__(CharacterCreationExecutionService)
    svc._finalize_lock = threading.Lock()
    svc.db = SimpleNamespace(settings=SimpleNamespace(data_dir=root))

    def committed(*args, **kwargs):
        if failed:
            raise RuntimeError("rolled back")
        with sqlite3.connect(db_path) as conn:
            conn.execute("INSERT INTO finalized VALUES ('CLEAN_AND_FINALIZED')")
        return {"project_id": PID, "run_id": "build", "status": "CLEAN_AND_FINALIZED", "commit": {"sha": "unchanged"}}

    svc._finalize_locked = committed
    done = threading.Event()
    original = auto._work

    def work(*args):
        try:
            with sqlite3.connect(db_path) as conn:
                assert conn.execute("SELECT status FROM finalized").fetchone()[0] == "CLEAN_AND_FINALIZED"
            original(*args)
        finally:
            done.set()

    monkeypatch.setattr(auto, "_work", work)
    return svc, done


@pytest.mark.parametrize("outcome", ["success", "offline", "generation_error"])
def test_finalize_commits_then_background_token_is_best_effort(setup, monkeypatch, outcome, caplog):
    root, calls = setup
    if outcome == "offline":
        monkeypatch.setattr(auto, "reachable", lambda: False)
    elif outcome == "generation_error":
        def fail(*args, **kwargs):
            raise RuntimeError("mock generation failure")
        monkeypatch.setattr(auto.portraits, "anima_generate", fail)
    svc, done = service(root, monkeypatch)
    result = svc.finalize("build")
    assert done.wait(5)
    assert result["status"] == "CLEAN_AND_FINALIZED"
    assert result["commit"] == {"sha": "unchanged"}
    assert result["notes"] == ["Token: Anima will make one in the background if running; reload the sheet to see it"]
    reloaded = {"project_id": PID}
    auto.add_notes(root, reloaded)
    if outcome == "success":
        assert calls[0][0] == portrait_prompt(SHEET)
        assert calls[0][2] == "portrait"
        assert reloaded["notes"] == ["Token: made with Anima"]
        table = TabletopService(None, root)  # fresh service after reload
        assert table._tokens_for([f"actor:factory.{PID}"])
        assert table.picture_path(PID).read_bytes() == png()
        with Image.open(table.token_path(PID)) as token:
            assert token.size == (512, 512) and token.mode == "RGBA"
            assert token.getpixel((0, 0))[3] == 0
            assert token.getpixel((256, 256)) == (255, 0, 0, 255)
        assert ButtonStore(root / "tabletop_buttons").get(PID)["token_circle"] == auto.HEAD
    else:
        assert not TokenStore(root / "tabletop_tokens").path(PID).exists()
        assert "make one from the sheet" in reloaded["notes"][0]
        assert calls == []


def test_existing_token_never_starts_anima(setup, monkeypatch):
    root, calls = setup
    store = TokenStore(root / "tabletop_tokens")
    existing = png("blue", (512, 512))
    store.save(PID, existing)
    svc, _ = service(root, monkeypatch)
    result = svc.finalize("build")
    assert result["status"] == "CLEAN_AND_FINALIZED"
    assert calls == [] and store.path(PID).read_bytes() == existing


def test_manual_save_during_generation_wins(setup, monkeypatch):
    root, _ = setup
    store = TokenStore(root / "tabletop_tokens")
    existing = png("blue", (512, 512))
    def generate(*args, **kwargs):
        store.save(PID, existing)
        return png()
    monkeypatch.setattr(auto.portraits, "anima_generate", generate)
    auto._work(root, PID, threading.Lock())
    assert store.path(PID).read_bytes() == existing
    assert not (root / "tabletop_pictures").exists()


def test_atomic_no_replace_preserves_existing_image(setup):
    root, _ = setup
    store = TokenStore(root / "tabletop_tokens")
    first = png("blue")
    store.save(PID, first)
    store.save(PID, png(), overwrite=False)
    assert store.path(PID).read_bytes() == first
    assert list(store.root.iterdir()) == [store.path(PID)]


def test_finalize_does_not_wait_for_generation(setup, monkeypatch):
    root, _ = setup
    entered, release = threading.Event(), threading.Event()
    def generate(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return png()
    monkeypatch.setattr(auto.portraits, "anima_generate", generate)
    svc, done = service(root, monkeypatch)
    try:
        assert svc.finalize("build")["status"] == "CLEAN_AND_FINALIZED"
        assert entered.wait(5) and not done.is_set()
    finally:
        release.set()
        assert done.wait(5)


def test_publication_waits_for_other_finalize_lock(setup, monkeypatch):
    root, _ = setup
    lock = threading.Lock()
    generated, release = threading.Event(), threading.Event()
    def generate(*args, **kwargs):
        generated.set()
        assert release.wait(5)
        return png()
    monkeypatch.setattr(auto.portraits, "anima_generate", generate)
    worker = threading.Thread(target=auto._work, args=(root, PID, lock))
    worker.start()
    assert generated.wait(5)
    with lock:
        release.set()
        assert not TokenStore(root / "tabletop_tokens").path(PID).exists()
    worker.join(5)
    assert not worker.is_alive()
    assert TokenStore(root / "tabletop_tokens").url(PID)


@pytest.mark.parametrize("flag", ["0", "false", "off", "no"])
def test_disabled_hook_does_nothing(setup, monkeypatch, flag):
    root, calls = setup
    monkeypatch.setenv("TIANXIA_AUTO_TOKEN", flag)
    svc, _ = service(root, monkeypatch)
    assert "notes" not in svc.finalize("build")
    assert calls == []


def test_default_is_on(monkeypatch):
    monkeypatch.delenv("TIANXIA_AUTO_TOKEN", raising=False)
    assert auto.enabled()


def test_rollback_cannot_reach_hook(setup, monkeypatch):
    root, _ = setup
    svc, done = service(root, monkeypatch, failed=True)
    started = []
    monkeypatch.setattr(auto, "start", lambda *args: started.append(args))
    with pytest.raises(RuntimeError, match="rolled back"):
        svc.finalize("build")
    assert started == [] and not done.is_set()
    # Production source proof: hook lies after the outer try/finally, and
    # never in _finalize_locked (including its restore/error/cleanup paths).
    tree = ast.parse(textwrap.dedent(inspect.getsource(CharacterCreationExecutionService.finalize)))
    body = tree.body[0].body
    finalizer_try = next(node for node in body if isinstance(node, ast.Try))
    hook = next(node for node in body if isinstance(node, ast.If) and any(
        isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "start"
        for call in ast.walk(node)))
    assert body.index(hook) > body.index(finalizer_try)
    locked_source = inspect.getsource(CharacterCreationExecutionService._finalize_locked)
    assert "auto_token" not in locked_source
    assert locked_source.index("CLEAN_AND_FINALIZED") < locked_source.rindex("return self.get(run_id)")
    assert locked_source.index("CG1_FINALIZATION_ROLLED_BACK") < locked_source.index("with self.db.transaction()")


def test_thread_start_error_does_not_affect_finalize(setup, monkeypatch):
    root, _ = setup
    svc, _ = service(root, monkeypatch)
    def fail(*args, **kwargs):
        raise RuntimeError("thread failure")
    monkeypatch.setattr(auto.threading.Thread, "start", fail)
    assert svc.finalize("build")["status"] == "CLEAN_AND_FINALIZED"


def test_note_failure_does_not_affect_finalized_run_read(setup, monkeypatch):
    root, _ = setup
    svc, _ = service(root, monkeypatch)
    result = {"project_id": PID, "status": "CLEAN_AND_FINALIZED", "commit": {"sha": "unchanged"}}
    conn = sqlite3.connect(root / "committed.sqlite")
    conn.execute("CREATE TABLE character_creation_runs (run_id TEXT)")
    conn.execute("INSERT INTO character_creation_runs VALUES ('build')")
    svc.db.connection = lambda: conn
    svc._public = lambda row: deepcopy(result)
    def fail(*args):
        raise OSError("status read failed")
    monkeypatch.setattr(auto, "add_notes", fail)
    try:
        actual = CharacterCreationExecutionService.get(svc, "build")
        assert actual == {**result, "finalize_in_progress": False}
    finally:
        conn.close()


def test_probe_is_short_and_does_not_queue_a_job(monkeypatch):
    observed = []
    def offline(url, *, timeout):
        observed.append((url, timeout))
        raise OSError("offline")
    monkeypatch.setattr(auto.urllib.request, "urlopen", offline)
    assert not auto.reachable()
    assert observed == [(auto.portraits.ANIMA_URL.rstrip("/") + "/system_stats", 0.5)]


def test_probe_wall_time_is_bounded_even_if_dns_stalls(monkeypatch):
    import time
    release = threading.Event()
    completed = threading.Event()
    def stuck(*args, **kwargs):
        try:
            release.wait(5)
            raise OSError("offline")
        finally:
            completed.set()
    monkeypatch.setattr(auto.urllib.request, "urlopen", stuck)
    started = time.monotonic()
    try:
        assert not auto.reachable()
        assert time.monotonic() - started < 1
    finally:
        release.set()
        assert completed.wait(5)


def test_existing_picture_is_preserved_with_its_remembered_circle(setup):
    root, _ = setup
    picture = png("blue", (768, 1152))
    TokenStore(root / "tabletop_pictures", kind="picture").save(PID, picture)
    buttons = ButtonStore(root / "tabletop_buttons")
    circle = {"x": 0.5, "y": 0.31, "r": 0.19}
    buttons.save_token_look(PID, "blue robes", circle=circle)
    auto._work(root, PID, threading.Lock())
    assert TokenStore(root / "tabletop_pictures", kind="picture").path(PID).read_bytes() == picture
    assert TokenStore(root / "tabletop_tokens").path(PID).read_bytes() == auto.circle_token(picture, circle=circle)
    assert buttons.get(PID)["token_circle"] == circle


@pytest.mark.parametrize("outcome", ["success", "offline", "generation_error", "rollback", "commit_error"])
def test_production_finalize_boundary_with_pipeline_doubles(setup, monkeypatch, outcome):
    """Real _finalize_locked control flow and SQLite transaction, fake compile/release.

    Exercise the actual success and restore branches without compiling a full
    character or contacting a provider. The generator sees the durable status.
    """
    root, calls = setup
    svc, run, _ = _finalization_service_and_run(owner_resolutions=False)
    run["project_id"] = PID
    run["created_at"] = "2026-10-01T00:00:00Z"
    run["request"]["typed_choice_snapshot"] = {"snapshot_sha256": "snapshot"}
    db_path = root / "production.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE character_creation_runs
          (run_id TEXT, owner_decision TEXT, commit_json TEXT, final_revision INTEGER,
           output_json TEXT, status TEXT, updated_at TEXT, completed_at TEXT)""")
        conn.execute("INSERT INTO character_creation_runs(run_id,status) VALUES (?,?)", (run["run_id"], run["status"]))
        if outcome == "commit_error":
            conn.execute("""CREATE TRIGGER fail_commit BEFORE UPDATE ON character_creation_runs
                            BEGIN SELECT RAISE(ABORT, 'mock commit failure'); END""")

    @contextmanager
    def transaction():
        with sqlite3.connect(db_path) as conn:
            yield conn

    svc.db = SimpleNamespace(settings=SimpleNamespace(data_dir=root), transaction=transaction)
    def get(run_id):
        result = deepcopy(run)
        with sqlite3.connect(db_path) as conn:
            result["status"], commit = conn.execute("SELECT status,commit_json FROM character_creation_runs").fetchone()
        result["commit"] = json.loads(commit) if commit else {}
        return result
    svc.get = get
    svc._approved_candidate_for_finalization = lambda *args: {
        "candidate_identity": "reviewed", "deterministic": True,
        "independent_compilations": 2, "identities": {}}
    svc.candidate_gm_authoring = SimpleNamespace(candidate_compilation_authority=lambda *args, **kwargs: {})
    svc._require_frozen_choice_snapshot = lambda *args: {}
    svc._snapshot_data = lambda path, **kwargs: path.mkdir()
    svc._assert_completed_release_gate = lambda *args: None
    stable = {"factory_authoring": {}, "command5": {}, "consumer": {}, "portable_audit": {}, "clean_import": {}}
    svc.production_release = SimpleNamespace(_stable=lambda release: stable)
    restored = []
    svc._restore_data = lambda *args: restored.append(True)
    svc._tree_hashes = lambda *args: {}
    svc._snapshot_excluded_names = lambda: frozenset()
    svc._record_finalize_failure = lambda *args: None
    svc._record_stage_timings = lambda *args: None
    svc._append_attempt = lambda *args, **kwargs: None
    svc._latest_attempt_id = lambda *args: None
    def execute(*args, **kwargs):
        if outcome == "rollback":
            raise RuntimeError("mock live failure")
        return {"_production_release": {"production_artifact_identity": "release"}}
    svc._execute_live = execute
    done = threading.Event()
    original = auto._work
    def work(*args):
        try:
            assert get(run["run_id"])["status"] == "CLEAN_AND_FINALIZED"
            original(*args)
        finally:
            done.set()
    monkeypatch.setattr(auto, "_work", work)
    if outcome == "offline":
        monkeypatch.setattr(auto, "reachable", lambda: False)
    elif outcome == "generation_error":
        def fail(*args, **kwargs):
            raise RuntimeError("mock generator failure")
        monkeypatch.setattr(auto.portraits, "anima_generate", fail)
    if outcome in {"rollback", "commit_error"}:
        started = []
        monkeypatch.setattr(auto, "start", lambda *args: started.append(args))
        with pytest.raises(Exception) as caught:
            svc.finalize(run["run_id"])
        assert started == [] and not done.is_set()
        assert get(run["run_id"])["status"] == "READY_FOR_REVIEW"
        if outcome == "rollback":
            assert caught.value.code == "CG1_FINALIZATION_ROLLED_BACK"
            assert restored == [True]
        else:
            assert isinstance(caught.value, sqlite3.IntegrityError)
    else:
        result = svc.finalize(run["run_id"])
        committed = get(run["run_id"])["commit"]
        assert done.wait(5)
        assert result["status"] == "CLEAN_AND_FINALIZED"
        assert result["commit"] == get(run["run_id"])["commit"] == committed
        assert bool(TokenStore(root / "tabletop_tokens").url(PID)) == (outcome == "success")


def test_crop_has_browser_head_geometry():
    source = Image.new("RGBA", (768, 768))
    # A linear gradient makes the source location at the output center visible.
    source.putdata([(x % 256, y % 256, 0, 255) for y in range(768) for x in range(768)])
    out = io.BytesIO()
    source.save(out, format="PNG")
    with Image.open(io.BytesIO(auto.circle_token(out.getvalue()))) as token:
        r, g, _, a = token.getpixel((256, 256))
        assert abs(r - 128) <= 2 and abs(g - 66) <= 2 and a == 255


@pytest.mark.skipif(os.environ.get("TOKEN1_BROWSER_CHECK") != "1", reason="Lead runs browser check outside sandbox")
def test_browser_save_geometry_opt_in():
    from playwright.sync_api import sync_playwright
    script = (Path(__file__).resolve().parents[1] / "static/tabletop/portrait.js").read_text()
    head = "function headCircle" + script.split("function headCircle", 1)[1].split("function injectStyle", 1)[0]
    cut = "function cut" + script.split("function cut", 1)[1].split("function wireCanvas", 1)[0]
    defaults = script.split("const HEAD = ", 1)[1].split(";", 1)[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"], headless=True)
        try:
            page = browser.new_page()
            result = page.evaluate("""async () => {
              const HEAD = """ + defaults + ";" + head + cut + """
              const src = document.createElement('canvas'); src.width = src.height = 768;
              const s = src.getContext('2d'); s.fillStyle = 'red'; s.fillRect(0,0,768,768);
              const image = new Image(); image.src = src.toDataURL(); await image.decode();
              const c = document.createElement('canvas'); c.width = c.height = 512;
              const ctx = c.getContext('2d'); cut(ctx, 512, image, headCircle(image, 'portrait'));
              return {corner: [...ctx.getImageData(0,0,1,1).data],
                      center: [...ctx.getImageData(256,256,1,1).data], png: c.toDataURL().slice(0,22)};
            }""")
            assert result == {"corner": [0, 0, 0, 0], "center": [255, 0, 0, 255], "png": "data:image/png;base64,"}
        finally:
            browser.close()
