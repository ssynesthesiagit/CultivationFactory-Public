"""Normal-run authority dependency recording; no changes to queue admission.

Loaded by tests/conftest.py before application imports. Writes one trace next to
--basetemp, or to --record-impact-dir. Collection, fixture and cross-file caches
can carry computed values without another boundary call. Therefore a multi-file
process conservatively shares its dependency union across its files; separate
file runs retain narrow traces. This deliberately trades false positives for
safety rather than claiming an unobserved cached value is independent.

Raw reads and subprocesses are session-wide wildcards (children are not traced).
Background threads share the subscriber. The runner may supply RECORD_IMPACT_REV
(a full 40-character lowercase commit SHA) and RECORD_IMPACT_CLEAN=1 after
checking the checkout. Without both, traces are diagnostic only. Incomplete,
failed or dirty runs are also diagnostic only: selectors must select their files. No test names,
ability IDs, curated reader tables, AST import guesses or selection caps.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

import pytest

from authority_records import boundary_read, inside_boundary_read, recording, source_paths
APP = Path(__file__).resolve().parents[1]
TRACE_SCHEMA = "record-impact.trace.v1"

_ACTIVE = None
_AUDIT_INSTALLED = False
_AUDIT_PAUSED = False
_CONFIGURED = False
_SOURCE_FILES = set()
_TYPED_INPUTS = str(APP / "authority" / "typed_mechanics") + "/"


def _audit(event, args):
    recorder = _ACTIVE
    if recorder is None or _AUDIT_PAUSED:
        return
    if event in {"subprocess.Popen", "os.fork", "os.posix_spawn"}:
        recorder.record("*", "*")
    elif event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        # Audit every open without invoking Path.resolve/Path.stat in application
        # code. realpath still follows aliases so raw reads cannot evade tracing.
        path = os.path.realpath(os.fsdecode(args[0])).replace("\\", "/")
        if (path in _SOURCE_FILES or path.startswith(_TYPED_INPUTS)
                or path.endswith("/authority/Tianxia_Typed_Mechanics_Authority_R1.json")
                or path.endswith("/authority/typed_mechanics/rules_text.json")
                or path.endswith("/authority/typed_mechanics/player_text.json")):
            if not inside_boundary_read():
                recorder.record("*", "*")


class TraceRecorder:
    def __init__(self):
        self.dependencies = set()
        self.files = {}
        self.run_sha = ""
        self.clean = False
        self.incomplete = False

    def record(self, record_id, aspect):
        self.dependencies.add((record_id, aspect))

    def document(self, complete):
        dependencies = [{"record_id": str(rid), "aspect": str(aspect)}
                        for rid, aspect in sorted(self.dependencies, key=lambda item: (str(item[0]), str(item[1])))]
        return {"schema": TRACE_SCHEMA, "run_sha": self.run_sha,
                "complete": bool(complete and self.clean and not self.incomplete),
                "files": [{"test_file": file, "source_sha256": digest,
                           "dependencies": dependencies}
                          for file, digest in sorted(self.files.items())]}


def install():
    """Install once before application imports; audit hooks cannot be removed."""
    global _ACTIVE, _AUDIT_INSTALLED, _SUBSCRIPTION
    if _ACTIVE is None:
        _ACTIVE = TraceRecorder()
        _SUBSCRIPTION = recording(_ACTIVE.record)
        _SUBSCRIPTION.__enter__()
    if not _AUDIT_INSTALLED:
        sys.addaudithook(_audit)
        _AUDIT_INSTALLED = True
        # Prime the EXISTING parse cache once, solely to classify raw source IO
        # before collection imports can fill downstream caches. No dependencies
        # are claimed for this recorder-internal index operation.
        from combat.authority_cache import read_authority
        try:
            with boundary_read():
                data, _ = read_authority(APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json")
            _SOURCE_FILES.update(str((APP.parent / path).resolve()) for path in source_paths(data))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            _ACTIVE.record("*", "*")


def pytest_addoption(parser):
    parser.addoption("--record-impact-dir", type=Path, default=None,
                     help="Write record-impact.trace.v1 JSON here (default beside basetemp)")


def pytest_configure(config):
    global _CONFIGURED
    install()
    # Repeated in-process sessions inherit unobservable computed caches. Node
    # selections and collect-only runs likewise do not cover a complete file.
    if _CONFIGURED or config.option.collectonly or any("::" in arg for arg in config.args):
        _ACTIVE.incomplete = True
    _CONFIGURED = True
    # Identity is attested by the outer runner, never discovered by pytest.
    revision = os.environ.get("RECORD_IMPACT_REV", "")
    _ACTIVE.run_sha = revision if re.fullmatch(r"[0-9a-f]{40}", revision) else ""
    _ACTIVE.clean = bool(_ACTIVE.run_sha and os.environ.get("RECORD_IMPACT_CLEAN") == "1")


def pytest_collection_finish(session):
    for item in session.items:
        path = Path(item.path).resolve()
        try:
            file = path.relative_to(APP).as_posix()
        except ValueError:
            _ACTIVE.record("*", "*")
            continue
        _ACTIVE.files[file] = hashlib.sha256(path.read_bytes()).hexdigest()


def pytest_deselected(items):
    _ACTIVE.incomplete = True


def pytest_runtest_logreport(report):
    if report.skipped or report.failed:
        _ACTIVE.incomplete = True


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    if _ACTIVE is None:
        return
    config = session.config
    directory = config.getoption("--record-impact-dir")
    if directory is None:
        basetemp = config.getoption("basetemp")
        if basetemp is None:
            # pytest's own temporary root; no repository writes.
            basetemp = config._tmp_path_factory.getbasetemp()
        base = Path(basetemp)
        directory = base.parent / (base.name + "-record-impact")
    path = directory / f"trace-{uuid.uuid4().hex}.json"
    # Diagnostic only: an unwritable trace directory must never fail the test session.
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_ACTIVE.document(exitstatus == 0), sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
    except OSError as exc:
        print(f"record-impact: trace not written ({exc})", file=sys.stderr)
