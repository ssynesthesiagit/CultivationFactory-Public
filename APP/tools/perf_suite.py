"""Offline whole-game work budgets. Run from APP, through HeavyQ.

python tools/perf_suite.py --source /scratch/menuspeed-data \
    --match-id "$OWNER_MATCH" --match-id "$OTHER_MATCH" --scratch /var/tmp/perf-run \
    --output /var/tmp/perf-results.json

The source is read only. Only requested fights and their installed characters
are copied. Factory uses a reflink of the supplied quiescent database, or a new
database without --source. Its paired integrity files stay in disposable scratch.
No live database, provider credentials, HTTP server or GUI is used. Wall times
are diagnostic, never gates. cProfile counts actual
calls without replacing engine methods. The public provider-free REC1-P1CR4
recipe supplies Factory choices. Results contain no sheets.
"""
from __future__ import annotations

import argparse
import base64
import cProfile
from contextlib import contextmanager
import json
import os
from pathlib import Path
import pstats
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
BUDGET_FILE = Path(__file__).with_name("perf_suite_budgets.json")
COUNTERS = {"load_match", "legal_candidates", "candidate_allowed", "_compile_once",
            "_stage2_commit", "commit_proposal", "rasterize", "_clone_engine"}
REQUIRED = {"fight_load", "human_act", "menu_cold", "menu_warm", "option_click",
            "target_preview", "area_preview", "movement_preview", "movement_commit",
            "reaction_open", "reaction_answer", "ai_auto_step", "event_poll",
            "character_sheet", "map_editor_load"}
FACTORY_PATHS = ("build_choices", "compile", "stage2", "finalize", "character_sheet")


def error_code(exc):
    diagnostic = getattr(exc, "diagnostic", None)
    return (getattr(exc, "code", None) or getattr(diagnostic, "code", None)
            or (f"OSError:{exc.errno}" if isinstance(exc, OSError) else type(exc).__name__))


@contextmanager
def offline():
    """Deny real sockets, including background embedding/portrait clients."""
    def denied(*a, **kw):
        raise RuntimeError("PERFSUITE1: network access prohibited")
    active = [True]
    def audit(event, args):
        if active[0] and event == "subprocess.Popen":
            command = str(args[:2]).lower()
            if any(word in command for word in ("chromium", "google-chrome", "firefox", "playwright",
                                                 "exact_consumer_harness.py", "run_command6.py")):
                raise RuntimeError("PERFSUITE1: GUI/consumer subprocess prohibited")
    sys.addaudithook(audit)
    with patch.dict(os.environ, {"CF_EMBED_MENU": "0", "TIANXIA_AUTO_TOKEN": "0"}), \
            patch.object(socket.socket, "connect", denied), \
            patch.object(socket.socket, "connect_ex", denied):
        try:
            yield
        finally:
            active[0] = False


def safe_scratch(source: Path | None, scratch: Path) -> None:
    scratch = scratch.resolve()
    live = Path.home() / ".local/state/cultivation-factory"
    if not any(parent == Path("/var/tmp") for parent in scratch.parents):
        raise ValueError("Scratch must be a new directory under /var/tmp")
    if scratch.exists():
        raise ValueError("Scratch already exists; use a new, task-owned directory")
    if source:
        source = source.resolve(strict=True)
        live_checkout = Path.home() / "Projects/CultivationFactory"
        if source == live or live in source.parents or source == live_checkout or live_checkout in source.parents:
            raise ValueError("Live data cannot be a benchmark source")
        if source == scratch or source in scratch.parents or scratch in source.parents:
            raise ValueError("Source and scratch must be disjoint")


def _symbol(key):
    filename, line, name = key
    try:
        filename = str(Path(filename).relative_to(ROOT))
    except ValueError:
        filename = Path(filename).name
    return f"{filename}:{line}:{name}"


def _application(key):
    return str(key[0]).startswith(str(ROOT) + os.sep) and "/tools/perf_suite.py" not in key[0]


def summarize(stats):
    counters = {"application_calls": 0, **{name: 0 for name in sorted(COUNTERS)}}
    entries = []
    for key, (primitive, total, own, cumulative, callers) in stats.items():
        if _application(key):
            counters["application_calls"] += total
            if key[2] in COUNTERS:
                counters[key[2]] += total
        if key[0] == __file__:
            continue
        entries.append({"function": _symbol(key), "calls": total,
                        "self_ms": round(own * 1000, 3), "cumulative_ms": round(cumulative * 1000, 3)})
    return counters, sorted(entries, key=lambda x: -x["cumulative_ms"])[:5]


class Suite:
    def __init__(self, output: Path):
        self.output = output
        self.rows = []

    def save(self):
        self.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.output.parent,
                    prefix=f".{self.output.name}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({"schema": 1, "rows": self.rows}, stream, indent=2)
                stream.write("\n")
            os.replace(temporary, self.output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def measure(self, scenario, path, operation, *, expected=None):
        profiler = cProfile.Profile()
        started = time.perf_counter()
        error = None
        result = None
        response_bytes = 0
        def request():
            nonlocal response_bytes
            value = operation()
            if isinstance(value, dict):
                # Include response encoding, without retaining owner payloads.
                response_bytes = len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())
            return value
        try:
            result = profiler.runcall(request)
            if expected is not None and not expected(result):
                raise AssertionError("Operation did not complete its expected behavior")
        except Exception as exc:
            # Keep a compact error code only: owner payloads must never leak.
            error = error_code(exc)
        elapsed = (time.perf_counter() - started) * 1000
        stats = pstats.Stats(profiler).stats
        counters, top = summarize(stats)
        self.rows.append({"scenario": scenario, "path": path, "status": "ERROR" if error else "PASS",
                          "error": error, "wall_ms": round(elapsed, 3), "counters": counters, "top5": top,
                          "response_bytes": response_bytes})
        if isinstance(result, dict):
            self.rows[-1]["outcome"] = {"status": result.get("status"),
                "blocker_codes": [b.get("code") for b in (result.get("blockers") or []) if isinstance(b, dict)],
                "submission_error_code": (result.get("submission_error") or {}).get("code")}
            if scenario.startswith("factory"):
                # These are the newly generated public fixture's diagnostics,
                # never an existing owner's retained response or sheet.
                diagnostic = result.get("submission_error") or {}
                self.rows[-1]["outcome"]["message"] = str(diagnostic.get("message", ""))[:400]
                self.rows[-1]["outcome"]["detail_keys"] = sorted((diagnostic.get("details") or {}).keys())
        self.rows[-1]["self_top5"] = sorted(
            ({"function": _symbol(key), "calls": value[1], "self_ms": round(value[2] * 1000, 3)}
             for key, value in stats.items() if key[0] != __file__), key=lambda e: -e["self_ms"])[:5]
        self.save()
        print(f"{scenario}/{path}: {error or 'PASS'} {elapsed:.1f} ms", flush=True)
        if error:
            return None, stats
        return result, stats

    def missing(self, scenario, path, reason):
        self.rows.append({"scenario": scenario, "path": path, "status": "UNAVAILABLE",
                          "error": reason, "wall_ms": None, "counters": {}, "top5": []})
        self.save()


def services(data):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    combat = CombatService(ROOT, data)
    return combat, TabletopService(combat, data)


def copy_fight(source, target, mid):
    encoded = "m1_" + base64.urlsafe_b64encode(mid.encode()).decode().rstrip("=")
    origin = source / "Combat/Matches" / encoded
    shutil.copytree(origin, target / "Combat/Matches" / encoded,
                    ignore=shutil.ignore_patterns("*.lock"))
    metadata = json.loads((origin / "FactoryIntegration.json").read_text())
    # Metadata layouts differ by save generation. Recursively find only IDs of
    # installations actually present, rather than copying the full character library.
    def strings(value):
        if isinstance(value, str):
            yield value.removeprefix("actor:factory.")
        elif isinstance(value, dict):
            for k, v in value.items():
                yield from strings(k)
                yield from strings(v)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
    installed = {p.name for p in (source / "portable_characters").iterdir() if p.is_dir()}
    for pid in set(strings(metadata)) & installed:
        for folder in ("portable_characters", "character_sheets", "tabletop_buttons"):
            src = source / folder / pid
            if src.is_dir():
                shutil.copytree(src, target / folder / pid, dirs_exist_ok=True)
            elif src.with_suffix(".json").is_file():
                destination = target / folder
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src.with_suffix(".json"), destination / (pid + ".json"))
    if (source / "combat_maps").exists():
        shutil.copytree(source / "combat_maps", target / "combat_maps", dirs_exist_ok=True)


def deferred_area_choice(data, mid, root):
    """Open the real deferred square choice on a prepared disposable fork."""
    combat, table = services(data)
    answers = []
    for _ in range(20):
        response = table.act(mid, root["candidate_id"], root["decision_id"], root["state_version"], 0,
                             answers, defer_menu=True)
        if response["status"] != "REACTION_REQUIRED":
            raise ValueError("Deferred area did not open a square choice")
        prompt = response["reaction"]
        choice = prompt.get("choice") or {}
        if choice.get("map_pick", {}).get("areas"):
            return choice
        answer = {**prompt["context"], "selection": "DECLINE"}
        if choice:
            count = max(1, int(choice.get("minimum", 1)))
            answer.update(selection="USE", option_ids=[o["id"] for o in choice.get("options", [])[:count]])
        answers.append(answer)
    raise ValueError("Deferred area exceeded twenty bounded choices")


def fight_paths(suite, scenario, data, mid):
    combat, table = services(data)
    suite.measure(scenario, "fight_load", lambda: table.state(mid, include_menu=False), expected=lambda r: bool(r))
    # New services empty their menu/session caches; module/file-system caches
    # are process-warm. This is request-cold, not a machine reboot benchmark.
    combat, table = services(data)
    state, _ = suite.measure(scenario, "menu_cold", lambda: table.state(mid, fog=True), expected=lambda r: bool(r.get("menu")))
    if state is None:
        return
    suite.measure(scenario, "menu_warm", lambda: table.state(mid, fog=True), expected=lambda r: bool(r.get("menu")))
    menu = state["menu"]
    session = combat._load_session(mid)
    candidates = [c.model_dump(mode="json") for c in combat._legal_candidates(session)]
    native_area = any(c.get("area") for c in candidates)
    area_root = next((c for c in candidates if c.get("metadata", {}).get("placement_picker") and
                      (session.engine.action_catalog[c["source_definition_id"]].parameters.get("typed") or {}).get("area")), None)
    choice = None
    if not native_area and area_root:
        with tempfile.TemporaryDirectory(prefix="area-", dir=data.parent) as folder:
            clone = Path(folder) / "data"
            shutil.copytree(data, clone, ignore=shutil.ignore_patterns("*.lock"))
            choice, _ = suite.measure(scenario, "area_picker_open", lambda: deferred_area_choice(clone, mid, area_root),
                                      expected=lambda r: bool(r.get("map_pick", {}).get("areas")))
    client, _ = suite.measure(scenario, "client_process", lambda: client_click(
        menu, state["presentation"].get("actors", []), choice))
    if client is not None:
        suite.rows.pop()  # Process launch cost is not the player's click cost.
        for name in sorted(set(client) | {"option_click", "target_preview", "area_preview"}):
            if name not in client:
                suite.missing(scenario, name, "No matching multi-option picker in this saved state")
                continue
            metrics = client[name]
            suite.rows.append({"scenario": scenario, "path": name, "status": "PASS", "error": None,
                               **metrics, "boundary": "Node production picker/hover CPU; DOM stub, no paint or network"})
        suite.save()
    suite.measure(scenario, "event_poll", lambda: table.events(mid, state["last_sequence"]), expected=lambda r: "last_sequence" in r)
    aid = menu["actor_id"]
    pid = aid.removeprefix("actor:factory.")
    suite.measure(scenario, "character_sheet", lambda: table.sheet(pid), expected=lambda r: bool(r))
    maps = combat.tabletop_maps.list()
    if maps:
        map_id = maps[0]["map_id"]
        suite.measure(scenario, "map_editor_load", lambda: combat.tabletop_maps.get(map_id), expected=lambda r: "cells" in r)
    else:
        suite.missing(scenario, "map_editor_load", "No editor map")
    moves = [c for c in candidates if c["kind"] == "MOVE" and c.get("destination") and c.get("canonical_path")]
    move = min(moves, key=lambda c: (bool(c.get("metadata", {}).get("reaction_exposure")),
                                   len(c["canonical_path"]), c["candidate_id"]), default=None)
    if move and menu.get("manual"):
        route = move["canonical_path"]
        mode = move.get("metadata", {}).get("movement_mode", "walk")
        quote, _ = suite.measure(scenario, "movement_preview", lambda: table.preview_move_path(
            mid, menu["decision_id"], menu["state_version"], aid, route, mode), expected=lambda r: r["status"] == "ROUTE_PREVIEW")
        if quote:
            c = quote["candidate"]
            suite.measure(scenario, "movement_commit", lambda: table.commit_move_path(
                mid, c["candidate_id"], c["decision_id"], c["state_version"], aid, route,
                movement_mode=mode, defer_menu=True), expected=lambda r: r["status"] == "COMMITTED")
    else:
        suite.missing(scenario, "movement_preview", "No manual movement in this saved state")
        suite.missing(scenario, "movement_commit", "No manual movement in this saved state")
    current = table.state(mid)
    m = current.get("menu") or {}
    if m.get("manual"):
        suite.measure(scenario, "human_act", lambda: table.act(mid, m["end_turn"], m["decision_id"],
            m["state_version"], current["last_sequence"], defer_menu=True), expected=lambda r: r["status"] == "COMMITTED")
    else:
        suite.missing(scenario, "human_act", "Current actor is not manual")
    # Choose the real local AI policy through the public controller API. No
    # model driver is installed; this does not imitate a model-seat network call.
    next_actor = combat.decision(mid)["context"]["active_actor_id"]
    combat.set_controller_mode(mid, actor_id=next_actor, controller_mode="LOCAL_AUTO")
    suite.measure(scenario, "ai_auto_step", lambda: table.auto_step(mid, 0, defer_menu=True),
                  expected=lambda r: r["status"] in {"COMMITTED", "REACTION_REQUIRED"})


def client_click(menu, actors, map_choice=None):
    """Run production JS option/target picker code in Node; no GUI/paint claim."""
    result = subprocess.run(["node", str(Path(__file__).with_name("perf_suite_client.mjs"))],
                            input=json.dumps({"menu": menu, "actors": actors, "map_choice": map_choice}),
                            text=True, capture_output=True, check=True, timeout=60)
    return json.loads(result.stdout)


def reaction_paths(suite, data):
    # Existing published fixture: a player-owned guard asks before an OA.
    from tests.test_reaction_ask import _fight, MOVER, GUARD, _gap, _cells
    combat, table, mid = _fight(data)
    mover, guard = "actor:factory." + MOVER, "actor:factory." + GUARD
    for _ in range(40):
        ctx = combat.decision(mid)["context"]
        engine = combat._load_session(mid).engine
        where = {a: (v.position.x, v.position.y) for a, v in engine.state.actors.items()}
        moves = [c for c in ctx["legal_candidates"] if c["kind"] == "MOVE" and c.get("destination")]
        end = next(c for c in ctx["legal_candidates"] if c["kind"] == "END_TURN")
        send = lambda c, answers=(): table.act(mid, c["candidate_id"], ctx["decision_id"], ctx["state_version"], 0, list(answers), defer_menu=True)
        if ctx["active_actor_id"] != mover or not moves:
            send(end)
        elif _gap(where[mover], where[guard]) > 1:
            closer = min(moves, key=lambda c: (_gap(_cells(c["destination"]), where[guard]), c["candidate_id"]))
            send(closer if _gap(_cells(closer["destination"]), where[guard]) < _gap(where[mover], where[guard]) else end)
        else:
            away = [c for c in moves if _gap(_cells(c["destination"]), where[guard]) >= 3]
            if not away:
                send(end)
                continue
            chosen = max(away, key=lambda c: (_gap(_cells(c["destination"]), where[guard]), c["candidate_id"]))
            result, _ = suite.measure("reaction_fixture", "reaction_open", lambda: send(chosen), expected=lambda r: r["status"] == "REACTION_REQUIRED")
            if result:
                answer = {**result["reaction"]["context"], "selection": "USE"}
                suite.measure("reaction_fixture", "reaction_answer", lambda: send(chosen, [answer]), expected=lambda r: r["status"] == "COMMITTED")
            return
    suite.missing("reaction_fixture", "reaction_open", "No opportunity reached in 40 bounded steps")
    suite.missing("reaction_fixture", "reaction_answer", "No opportunity reached")


def stage2_summary(suite, stats, scenario="factory", *, complete=True):
    """Attribute exact direct-call edges inside compile's Stage 2 span.

    cProfile caller-edge totals give Stage 2's five direct callees, rather than
    incorrectly labelling the entire compile profile as Stage 2. The elapsed
    value is nested cumulative time and must not be added to compile's time.
    """
    roots = {key for key in stats if key[2] == "_stage2_commit"}
    entries = []
    calls = 0
    elapsed = 0
    for key in roots:
        calls += stats[key][1]
        elapsed += stats[key][3] * 1000
    for key, values in stats.items():
        edges = [value for caller, value in values[4].items() if caller in roots]
        if edges:
            entries.append({"function": _symbol(key), "calls": sum(e[1] for e in edges),
                            "cumulative_ms": round(sum(e[3] for e in edges) * 1000, 3)})
    status = "PASS" if calls and complete else "PARTIAL" if calls else "UNAVAILABLE"
    error = (None if status == "PASS" else "Compile did not complete; Stage 2 counts are partial"
             if calls else "Compile did not enter Stage 2")
    suite.rows.append({"scenario": scenario, "path": FACTORY_PATHS[2], "status": status,
                       "error": error, "wall_ms": round(elapsed, 3),
                       "counters": {"_stage2_commit": calls, "direct_calls": sum(e["calls"] for e in entries)},
                       "top5": sorted(entries, key=lambda e: -e["cumulative_ms"])[:5], "nested_in": "compile"})
    suite.save()


def factory_paths(suite, data, source=None):
    from app.core import Database, Settings
    from catalog.service import CatalogService
    from character_builder.service import CharacterBuilderService
    from character_creation.service import CharacterCreationExecutionService
    from character_creation.creative_controller.route_persistence import DETERMINISTIC_CREATIVE_CONTROLLER
    from character_creation.production_release import CharacterProductionReleaseAdapter
    from character_sheet import CharacterSheetService
    from factory_authoring import FactoryAuthoringWorkspaceService, FinalCharacterWorkflowService
    from gm_export import GMCharacterExportService
    from portable_character import PortableCharacterPackageService
    from project_store.service import ProjectStore
    from projector.service import ProjectionService
    from security.integrity import IntegrityService, KEY_FILENAME, KEY_METADATA_FILENAME
    from security.local_identity import BoundPrincipalProvider, ProcessPrincipalProvider
    from stage1.service import Stage1ClipboardService
    from stage2 import Stage2AdvancementService
    from vendor_adapter.service import FactoryAdapter
    from tests.test_dcc_linear_s4 import _GoldenFirstProvider
    from tests.rec1_p1cr4_real_acceptance import PINNED_FACTORY, _build_project
    scenario = "factory_snapshot" if source else "factory"
    if source:
        database = source / "foundry.sqlite3"
        wal = database.with_name(database.name + "-wal")
        if wal.exists() and wal.stat().st_size:
            raise ValueError("Factory source must be a quiescent SQLite snapshot without a WAL")
        if shutil.disk_usage(data.parent).free < 2 * 1024**3:
            raise OSError("At least 2 GiB free is required for Factory scratch writes")
        data.mkdir(parents=True)
        # Refuse a full fallback copy of a large snapshot. FICLONE is atomic and leaves the
        # supplied snapshot unopened; all SQLite writes target this clone.
        subprocess.run(["cp", "--reflink=always", "--", str(database), str(data / database.name)], check=True)
    settings = Settings.from_env(ROOT, data)
    if source:
        settings.security_dir.mkdir(parents=True, exist_ok=True)
        for name in (KEY_FILENAME, KEY_METADATA_FILENAME):
            paired = source / "security" / name
            if paired.is_file():
                shutil.copy2(paired, settings.security_dir / name)
    db = Database(settings)
    db.migrate()
    configured = FactoryAdapter(db).configure(PINNED_FACTORY)
    CatalogService(db).rebuild_core(Path(configured["factory_root"]))
    # Compose only the creation pipeline, as provider_free_guided_probe does.
    # create_app processes deletion queues and starts inventory background work;
    # those are unrelated to a benchmark and must not run on a copied database.
    principal = ProcessPrincipalProvider().current_principal()
    bound = BoundPrincipalProvider(principal)
    integrity = IntegrityService.for_database(db)
    workflow = FinalCharacterWorkflowService(db, principal_provider=bound, integrity=integrity)
    sheets = CharacterSheetService(db)
    service = CharacterCreationExecutionService(
        db, stage1=Stage1ClipboardService(db), provider=_GoldenFirstProvider(),
        project_store=ProjectStore(db, principal_provider=bound, integrity=integrity),
        stage2=Stage2AdvancementService(db, principal_provider=bound), character_sheets=sheets,
        gm_exports=GMCharacterExportService(db), portable_characters=PortableCharacterPackageService(db),
        factory_authoring=FactoryAuthoringWorkspaceService(db, principal_provider=bound, integrity=integrity,
                                                         final_character_workflow=workflow),
        projections=ProjectionService(db), production_release=CharacterProductionReleaseAdapter(db),
        owner_principal=principal.principal_id)
    builder = CharacterBuilderService(db)
    # This local adapter supplies the fixture's fixed semantic seed through the
    # public builder argument. Core classes/methods are never replaced. The seed
    # keeps constructed recipes independent of random project/run identifiers.
    recipe_builder = SimpleNamespace(options=builder.options,
        create_project=lambda **kwargs: builder.create_project(autogen_seed="PERFSUITE1_CL20_V1", **kwargs))
    created, _ = suite.measure(scenario, FACTORY_PATHS[0], lambda: _build_project(
        recipe_builder, source_reference="PERFSUITE1 provider-free recipe"), expected=lambda r: bool(r.get("project")))
    if created is None:
        return
    # Use the current guided provider-free recipe (provider_free_guided_probe),
    # which answers training/title/Forge choices from their actual step menus.
    # The older Manual Chat response fixture lacks the current training fields.
    compiled, stats = suite.measure(scenario, FACTORY_PATHS[1], lambda: service.start(
        created["project"]["project_id"], execution_mode="STANDARD_API", idempotency_key="perfsuite1",
        controller_route=DETERMINISTIC_CREATIVE_CONTROLLER),
        expected=lambda r: r["status"] == "READY_FOR_REVIEW" and not r.get("blockers"))
    stage2_summary(suite, stats, scenario, complete=compiled is not None)
    if compiled:
        finalized, _ = suite.measure(scenario, FACTORY_PATHS[3], lambda: service.finalize(compiled["run_id"]),
                                     expected=lambda r: r["status"] == "CLEAN_AND_FINALIZED")
        if finalized:
            suite.measure(scenario, FACTORY_PATHS[4], lambda: sheets.sheet(
                created["project"]["project_id"]), expected=lambda r: bool(r))
    else:
        suite.missing(scenario, FACTORY_PATHS[3], "Compile failed")


def violations(rows, budgets):
    problems = []
    actual = {r["scenario"] + "/" + r["path"]: r for r in rows}
    for key, limits in budgets.items():
        row = actual.get(key)
        if not row or row["status"] != "PASS":
            problems.append(f"{key}: missing or unsuccessful measurement")
            continue
        for name, limit in limits.items():
            value = row["counters"].get(name)
            if value is None or value > limit:
                problems.append(f"{key}: {name}={value} > budget {limit}")
    for key, row in actual.items():
        if row["status"] != "PASS":
            problems.append(f"{key}: {row['status']} ({row.get('error')})")
        elif key not in budgets:
            problems.append(f"{key}: no reviewed budget")
    return problems


def baseline_budgets(rows):
    # Explicit calibration only. CI never learns a new budget automatically.
    return {r["scenario"] + "/" + r["path"]:
            {name: (0 if name == "transport_calls" else value + max(2, (value + 3) // 4))
             for name, value in r["counters"].items()}
            for r in rows if r["status"] == "PASS"}


def load_budgets(path=BUDGET_FILE, *, source=False, factory=True):
    budgets = json.loads(path.read_text())
    scenarios = ({"owner", "other1", "reaction_fixture", "factory_snapshot"} if source
                 else {"small", "reaction_fixture", "factory"})
    if not factory:
        scenarios -= {"factory", "factory_snapshot"}
    return {key: limits for key, limits in budgets.items() if key.split("/", 1)[0] in scenarios}


@contextmanager
def owned_scratch(scratch):
    """Delete only the new directory we own, even after a failed operation."""
    scratch.mkdir(parents=True)
    try:
        with tempfile.TemporaryDirectory(prefix="data-", dir=scratch) as disposable:
            yield Path(disposable)
    finally:
        shutil.rmtree(scratch)


def report(rows, budgets):
    """Rank measured paths, with all count budgets and five profile entries."""
    problems = violations(rows, budgets)
    lines = ["PARTIAL" if problems else "PASS", "", "PERFSUITE1 offline performance budget suite", "",
             "Profiled wall times are diagnostic single samples, not latency gates or percentiles. "
             "Service-cold means new request caches in a process with warm imports and OS caches. "
             "JavaScript rows measure production picker/hover CPU against counted DOM/board stubs; "
             "their top entries are work counters, not sampled CPU times. Browser paint requires the opt-in lead check.", "",
             "| Rank | Scenario / path | Profiled ms | Primary work / budget | Root-cause pointer |",
             "|---:|---|---:|---|---|"]
    ordered = sorted(rows, key=lambda r: -(r.get("wall_ms") or 0))
    for rank, row in enumerate(ordered, 1):
        key = row["scenario"] + "/" + row["path"]
        counter = "application_calls" if "application_calls" in row["counters"] else max(
            row["counters"], key=row["counters"].get, default="")
        actual = row["counters"].get(counter, "unmeasured")
        limit = budgets.get(key, {}).get(counter, "unbudgeted")
        leaf = (row.get("self_top5") or row.get("top5") or [{}])[0]
        pointer = row.get("error") or leaf.get("function", "No profile")
        ms = row.get("wall_ms")
        lines.append(f"| {rank} | {key} | {ms if ms is not None else 'unavailable'} | "
                     f"{counter}: {actual} / {limit} | {pointer.replace('|', '/')} |")
    lines.extend(["", "All named integer call/access limits are in tools/perf_suite_budgets.json. "
                  "Budgets use 25% baseline headroom with a minimum two-call margin, and zero transport calls. "
                  "Stage 2 is nested inside compile and its time is not additive.", "",
                  "Five largest cumulative profile entries per path:"])
    for row in ordered:
        lines.extend(["", row["scenario"] + "/" + row["path"] + ":"])
        for entry in row.get("top5", []):
            timing = (f"{entry['cumulative_ms']} ms cumulative" if 'cumulative_ms' in entry
                      else "deterministic work count; CPU time not sampled")
            lines.append(f"- `{entry['function']}`: {entry['calls']} calls; {timing}")
    if problems:
        lines.extend(["", "Unresolved measurements/budgets:", "", *[f"- {problem}" for problem in problems]])
    return "\n".join(lines) + "\n"


def run(output, scratch, source=None, matches=(), factory=True, only_factory=False):
    if source and not only_factory and len(matches) != 2:
        raise ValueError("Supply exactly two match IDs for the saved-fight benchmark")
    safe_scratch(source, scratch)
    output = output.resolve()
    if scratch.resolve() in output.parents or (source and source.resolve() in output.parents):
        raise ValueError("Evidence output must be outside source and disposable scratch")
    suite = Suite(output)
    with owned_scratch(scratch) as data, offline(), \
            patch.dict(os.environ, {"TMPDIR": str(scratch),
                                    "TIANXIA_FOUNDRY_SECURITY_DIR": str(scratch / "security")}), \
            patch.object(tempfile, "tempdir", str(scratch)):
        if source and not only_factory:
            for index, mid in enumerate(matches):
                label = "owner" if index == 0 else f"other{index}"
                target = data / label
                try:
                    copy_fight(source, target, mid)
                    fight_paths(suite, label, target, mid)
                except Exception as exc:
                    suite.missing(label, "scenario", error_code(exc))
        elif not only_factory:
            from tests.test_tabletop_hunt6 import table_fight
            target = data / "small"
            combat, table, mid = table_fight(target, ["DARK_BASE_DARKNESS"], ask=False, ally_talents=[])
            fight_paths(suite, "small", target, mid)
        if not only_factory:
            try:
                reaction_paths(suite, data / "reaction")
            except Exception as exc:
                suite.missing("reaction_fixture", "setup", error_code(exc))
        if factory:
            try:
                factory_paths(suite, data / "factory", source)
            except Exception as exc:
                suite.missing("factory_snapshot" if source else "factory", "setup", error_code(exc))
    return suite.rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--only-factory", action="store_true", help="Focused Factory compile/Stage 2/finalize profile")
    parser.add_argument("--match-id", action="append", default=[], help="Repeat twice with --source; IDs stay outside source control")
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--budgets", type=Path, default=BUDGET_FILE)
    parser.add_argument("--report", type=Path, help="Write a ranked Markdown report")
    parser.add_argument("--calibrate", action="store_true", help="Explicitly write candidate budgets for review")
    args = parser.parse_args()
    if args.source and not args.only_factory and len(args.match_id) != 2:
        parser.error("--source requires exactly two --match-id arguments")
    rows = run(args.output, args.scratch, args.source, matches=args.match_id, only_factory=args.only_factory)
    if args.calibrate:
        budgets = baseline_budgets(rows)
        args.budgets.write_text(json.dumps(budgets, indent=2, sort_keys=True) + "\n")
        if args.report:
            args.report.write_text(report(rows, budgets))
        return int(any(r["status"] != "PASS" for r in rows))
    budgets = load_budgets(args.budgets, source=bool(args.source))
    if args.only_factory:
        budgets = {key: value for key, value in budgets.items() if key.startswith("factory")}
    if args.report:
        args.report.write_text(report(rows, budgets))
    problems = violations(rows, budgets)
    for problem in problems:
        print(problem)
    return bool(problems)


if __name__ == "__main__":
    raise SystemExit(main())
