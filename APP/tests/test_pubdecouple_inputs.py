"""Explicit negative-control files work without access to repository history."""
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

APP = Path(__file__).resolve().parents[1]
SOURCES = {'c4': 'tests/test_riders_c4.py', 'c5': 'tests/test_riders_c5.py', 'c8': 'tests/test_riders_c8.py', 'c9': 'tests/test_riders_c9.py', 'c10': 'tests/test_riders_c10.py', 'c11': 'tests/test_riders_c11.py', 'c12': 'tests/test_riders_c12.py', 'c13': 'tests/test_riders_c13.py', 'c14': 'tests/test_riders_c14.py', 'c15': 'tests/test_riders_c15.py', 'lane13': 'tests/test_riders_lane13.py', 'lane14': 'tests/test_riders_lane14.py'}


def helper(module, name, **namespace):
    # Load the real helper body without collecting an entire combat test module.
    node = next(n for n in ast.parse((APP / SOURCES[module]).read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    scope = {"os": os, "Path": Path, "json": json, **namespace}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(APP / SOURCES[module]), "exec"), scope)
    return scope[name]


@pytest.mark.parametrize("lane", ["c4", "c5", "c11", "c12", "c13", "c14", "c15", "lane14"])
def test_fixture_reads_explicit_authority_and_restores_default(tmp_path, monkeypatch, lane):
    key = ("R14" if lane == "lane14" else lane.upper()) + "_OLD_AUTHORITY_FILE"
    default = tmp_path / "current.json"
    supplied = tmp_path / "supplied.json"
    supplied.write_text('{"mechanics":{"sentinel":{}}}')
    compiler = SimpleNamespace(TYPED_AUTHORITY=default)
    fixture = helper(lane, "base_typing", compiler=compiler)
    monkeypatch.delenv(key, raising=False)
    ordinary = fixture()
    next(ordinary)
    assert compiler.TYPED_AUTHORITY == default
    ordinary.close()
    monkeypatch.setenv(key, str(supplied))
    control = fixture()
    next(control)
    assert json.loads(compiler.TYPED_AUTHORITY.read_text()) == {"mechanics": {"sentinel": {}}}
    control.close()
    assert compiler.TYPED_AUTHORITY == default


@pytest.mark.parametrize("lane,key", [("c8", "C8"), ("c9", "C9"), ("c10", "C10"), ("lane13", "R13")])
def test_authority_loader_uses_current_or_supplied_file(tmp_path, monkeypatch, lane, key):
    authority = tmp_path / "authority"
    authority.mkdir()
    (authority / "Tianxia_Typed_Mechanics_Authority_R1.json").write_text('{"mechanics":{"current":{}}}')
    supplied = tmp_path / "supplied.json"
    supplied.write_text('{"mechanics":{"prior":{}}}')
    env = key + "_OLD_AUTHORITY_FILE"
    monkeypatch.delenv(env, raising=False)
    monkeypatch.delenv("R13_AUTHORITY", raising=False)
    ordinary = helper(lane, "authority", ROOT=tmp_path, OLD=False)
    assert ordinary() == {"mechanics": {"current": {}}}
    monkeypatch.setenv(env, str(supplied))
    control = helper(lane, "authority", ROOT=tmp_path, OLD=True)
    assert control() == {"mechanics": {"prior": {}}}
