"""Failure-path regressions: synthetic captures, no fights or nested pytest runs."""
import hashlib
import importlib
import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest
from _pytest._code import ExceptionInfo
from _pytest.assertion import util

from tests.replay_assertions import assert_replay_equal


def _forbid_rich_diff(*args, **kwargs):
    pytest.fail('large replay operands reached pytest rich comparison')


@pytest.mark.parametrize('module_name,function_name', [
    ('test_a2_glass_stock', 'test_six_stock_captures_equal_main'),
    ('test_a2_qisub6r3_stock', 'test_six_stock_ai_captures_match_reviewed_parent'),
    ('test_wall_height_replays', 'test_six_full_stock_ai_captures_stay_identical'),
])
def test_large_failed_stock_guard_renders_within_five_seconds(
        tmp_path, monkeypatch, record_property, module_name, function_name):
    """Exercise each real guard and pytest failure rendering on >5 MB captures."""
    module = importlib.import_module('tests.' + module_name)
    monkeypatch.setattr(module, 'replay_base_or_skip', lambda: 'synthetic-base')
    monkeypatch.setenv('CF_STOCK_EVIDENCE', str(tmp_path / 'evidence'))
    monkeypatch.delenv('WALLHEIGHT_REPLAY_EVIDENCE', raising=False)
    prefix = 'x' * (5 * 1024 * 1024)
    captures = [dict(state={'terminal_result': 'done'}, steps=1, events=[],
                     payload=prefix + suffix) for suffix in ('a', 'b')]
    responses = iter(json.dumps(capture) for capture in captures)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout=next(responses), stderr=''))
    # Fail fast if the original bug returns; do not spend 40 minutes diffing.
    monkeypatch.setattr(util, '_compare_eq_iterable', _forbid_rich_diff)
    started = time.monotonic()
    with pytest.raises(AssertionError) as caught:
        getattr(module, function_name)(tmp_path, 'synthetic-seed')
    rendered = str(ExceptionInfo.from_exception(caught.value).getrepr(style='short'))
    elapsed = time.monotonic() - started
    record_property('failure_render_seconds', elapsed)
    assert elapsed < 5, f'failure rendering took {elapsed:.3f}s'
    message = str(caught.value)
    assert len(message) < 3000
    assert len(rendered) < 12000
    assert 'base_sha256' in message and 'head_sha256' in message
    assert 'first_difference' in message and 'byte_offset' in message
    for capture in captures:
        encoded = module._bytes_of(capture).encode()
        assert hashlib.sha256(encoded).hexdigest() in message


@pytest.mark.parametrize('left,right', [(b'', b'x'), ('abc', 'abcd'),
                                       ({'nested': [1]}, {'nested': [2]})])
def test_compact_comparison_keeps_verdict_and_hashes(monkeypatch, left, right):
    monkeypatch.setattr(util, '_compare_eq_iterable', _forbid_rich_diff)
    with pytest.raises(AssertionError) as caught:
        assert_replay_equal(left, right, {'large_context': 'y' * (5 * 1024 * 1024)})
    assert len(str(caught.value)) < 3000
    assert 'first_difference' in str(caught.value)
    assert_replay_equal(left, left)
    # Native equality, including numeric equality, remains the verdict.
    assert_replay_equal({'n': 1}, {'n': True})


def test_replay_scripts_compile_without_running_captures():
    """Standalone evidence scripts are opt-in; verify their edited syntax only."""
    root = Path(__file__).parent
    for name in ('cw2r1_replay_compare.py', 'hunt29_replay_compare.py',
                 'hunt31_replay_compare.py', 'prompt_ui_replay.py'):
        compile((root / name).read_text(), str(root / name), 'exec')
