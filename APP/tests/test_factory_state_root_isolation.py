"""The pinned Factory state root is this run's own, not the developer's live one.

MAINREDVENDOR1: the compiler/corpus acceptance tests verified their pinned
Factory dependencies inside the per-user state root
(~/.local/state/cultivation-factory or $CULTIVATION_FACTORY_STATE_ROOT).  That
tree exists only where a live Factory installed the archive, so those tests
failed with "The pinned compiler authority dependency is missing" and
FileNotFoundError vendor/factory_adapter.json on CI and on every machine that
was not the owner's.  conftest now points the state root at the run's own
temporary directory and the factory_state_root fixture extracts the bundled,
hash-verified archive there; these tests hold that property (and the pins of
what was extracted) so it cannot quietly regress to the live tree.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.core import EXPECTED_FACTORY_HASH, sha256_file
import factory_authoring.final_character_materializer as materializer
from factory_authoring import final_compiler_release as compiler_release


def test_state_root_is_the_runs_own_and_not_the_live_factory_state(factory_state_root):
    assert os.environ["CULTIVATION_FACTORY_STATE_ROOT"] == str(factory_state_root)
    # The materializer resolves the state root once at import from that setting;
    # if it were imported first it would keep the live ~/.local/state tree.
    assert materializer.FINAL_CHARACTER_DEFAULT_STATE_ROOT == factory_state_root
    assert factory_state_root != Path.home() / ".local" / "state" / "cultivation-factory"


def test_state_root_holds_the_pinned_factory_archive(factory_state_root):
    vendor = factory_state_root / "vendor"
    adapter = json.loads((vendor / "factory_adapter.json").read_text(encoding="utf-8"))
    assert adapter["factory_zip_hash"] == EXPECTED_FACTORY_HASH
    root = Path(adapter["factory_root"])
    # The extracted dependency tree belongs to this run, inside its own state root.
    assert root.resolve().is_relative_to((vendor / "extracted").resolve())
    assert compiler_release.tree_sha256(root) == compiler_release.BASE_FACTORY_ROOT_SHA256
    corpus = materializer.FINAL_CHARACTER_DEFAULT_CORPUS
    assert corpus.is_relative_to(root)
    assert sha256_file(corpus) == materializer.FINAL_CHARACTER_CORPUS_SHA256
