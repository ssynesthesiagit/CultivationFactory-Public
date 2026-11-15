"""Concurrent JSON publishers must not share a temporary file or lose profile edits."""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from combat import gate5_service
from combat.gate5_service import CombatService, VISUAL_PROFILE_SCHEMA


def test_atomic_json_uses_a_distinct_temporary_file_for_each_thread(tmp_path, monkeypatch):
    barrier = threading.Barrier(2)
    real_fsync = os.fsync

    def flush_together(fd):
        real_fsync(fd)
        barrier.wait(timeout=5)

    monkeypatch.setattr(gate5_service.os, 'fsync', flush_together)
    target = tmp_path / 'Profile.json'
    values = [{'writer': 'first'}, {'writer': 'second', 'larger': [1, 2, 3]}]
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(gate5_service._atomic_json, target, value) for value in values]
        for future in futures:
            future.result(timeout=5)
    assert json.loads(target.read_text()) in values
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize('failure', ['flush', 'replace'])
def test_atomic_json_failure_preserves_destination_and_removes_temporary(tmp_path, monkeypatch, failure):
    target = tmp_path / 'Profile.json'
    before = b'{"before":true}\n'
    target.write_bytes(before)

    def refuse(*args):
        raise OSError('injected write failure')

    monkeypatch.setattr(gate5_service.os, 'fsync' if failure == 'flush' else 'replace', refuse)
    with pytest.raises(OSError, match='injected write failure'):
        gate5_service._atomic_json(target, {'after': True})
    assert target.read_bytes() == before
    assert list(tmp_path.iterdir()) == [target]


def test_concurrent_visual_resets_preserve_both_token_edits(tmp_path, monkeypatch):
    service = object.__new__(CombatService)
    service.visual_profile_path = tmp_path / 'Profile.json'
    service.visual_profile_path.write_text(json.dumps({
        'schema': VISUAL_PROFILE_SCHEMA, 'tokens': {'first': {}, 'second': {}}, 'background': None,
    }))
    # The manifest is a presentation read after the transaction, not part of this mutation contract.
    monkeypatch.setattr(service, '_effective_visual_manifest', lambda: service._read_visual_profile())
    real_read = service._read_visual_profile
    first_read = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_read = threading.Event()
    local = threading.local()

    def read():
        document = real_read()
        if getattr(local, 'actor', None) == 'first' and not first_read.is_set():
            first_read.set()
            assert release_first.wait(timeout=5)
        elif getattr(local, 'actor', None) == 'second':
            second_read.set()
        return document

    def reset(actor):
        local.actor = actor
        if actor == 'second':
            second_started.set()
        return service.reset_visual_upload(kind='token', actor_id=actor)

    monkeypatch.setattr(service, '_read_visual_profile', read)
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(reset, 'first')
        assert first_read.wait(timeout=5)
        second = workers.submit(reset, 'second')
        assert second_started.wait(timeout=5)
        try:
            assert not second_read.wait(timeout=0.1), 'a second editor read an uncommitted profile'
        finally:
            release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert real_read()['tokens'] == {}
