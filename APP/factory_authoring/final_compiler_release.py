"""Additive release of the rulebook-aligned final compiler (compiler v2).

The pinned HF05ZVK Factory tree is never modified: Command 5 and the compiler
selection authority keep using it unchanged.  The final-character materializer
instead runs a derived copy of that tree in which only
``05_COMPILER/compile_character.py`` is replaced by the repository-owned
``final_compiler/compile_character_v2.py``.  Base tree, v2 source and derived
tree are each verified against fixed pins before use.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from app.core import FoundryError, sha256_json

RELEASE_ID = "final-compiler-v2"
BASE_FACTORY_BUNDLE = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
BASE_FACTORY_DIR = "HF05ZVK_R1H_Phase2I_HF2"
BASE_FACTORY_ROOT_SHA256 = "224ff86eda3e0bbef07e5cedd5a9bd236479640e14ecdd21ffa0d76ec5363e7c"
COMPILER_RELATIVE_PATH = "05_COMPILER/compile_character.py"
SOURCE_PATH = Path(__file__).resolve().parent / "final_compiler" / "compile_character_v2.py"
# Fixed pins for the released v2 source and the derived dependency tree.
COMPILER_SHA256 = "c161536a623ef19dd1c8a5fd9ea8ca3ad141a3651e9b6ea06a5b967465a59de2"
FACTORY_ROOT_SHA256 = "f1ec2160f6e14873e112c2cfa4d5f617f5002c1edce3ed8306b44ca8931ad759"


def _invalid(message: str, **details: object) -> FoundryError:
    return FoundryError("FINAL_COMPILER_RELEASE_INVALID", message, details=details or None, status_code=503)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(131072), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    """Hash every regular dependency file by relative POSIX path (bytecode excluded)."""

    root = Path(root)
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise _invalid("The compiler dependency tree contains a symlink.", path=str(path))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            files[path.relative_to(root).as_posix()] = _file_sha256(path)
    return sha256_json(files)


def base_root(state_root: Path) -> Path:
    return Path(state_root) / "vendor" / "extracted" / BASE_FACTORY_BUNDLE / BASE_FACTORY_DIR


def release_root(state_root: Path) -> Path:
    return Path(state_root) / "vendor" / "releases" / RELEASE_ID / COMPILER_SHA256 / BASE_FACTORY_DIR


def release_compiler(state_root: Path) -> Path:
    return release_root(state_root) / COMPILER_RELATIVE_PATH


def verified_source() -> Path:
    if SOURCE_PATH.is_symlink() or not SOURCE_PATH.is_file() or _file_sha256(SOURCE_PATH) != COMPILER_SHA256:
        raise _invalid("The repository compiler v2 source does not match its release pin.")
    return SOURCE_PATH


def ensure_release(state_root: Path) -> Path:
    """Publish (or re-verify) the derived v2 tree and return its compiler path."""

    source = verified_source()
    target = release_root(state_root)
    if target.exists():
        if target.is_symlink() or tree_sha256(target) != FACTORY_ROOT_SHA256:
            raise _invalid("The published compiler v2 tree does not match its release pin.", root=str(target))
        return target / COMPILER_RELATIVE_PATH
    base = base_root(state_root)
    if base.is_symlink() or not base.is_dir() or tree_sha256(base) != BASE_FACTORY_ROOT_SHA256:
        raise _invalid("The pinned base Factory tree is missing or changed.", root=str(base))
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".compiler-v2-", dir=target.parent))
    try:
        staged = staging / BASE_FACTORY_DIR
        shutil.copytree(base, staged, symlinks=False, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(source, staged / COMPILER_RELATIVE_PATH)
        if tree_sha256(staged) != FACTORY_ROOT_SHA256:
            raise _invalid("The derived compiler v2 tree does not match its release pin.")
        os.rename(staged, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return target / COMPILER_RELATIVE_PATH
