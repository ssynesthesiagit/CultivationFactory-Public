"""TEMPORARY PERFJUMP1 probe (deleted before commit): counts pricing calls around the profiled test."""
import json
import time

from combat import flight, passage_routes
from tests import test_auto115_guardian_r4 as target

OUT = '/var/tmp/lane/PERFJUMP1/probe.json'


def test_perfjump1_probe(tmp_path, monkeypatch):
    counts = {}

    def count(name, fn):
        def wrapper(*args, **kwargs):
            counts[name] = counts.get(name, 0) + 1
            return fn(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(passage_routes, 'path_cost', count('path_cost', passage_routes.path_cost))
    monkeypatch.setattr(flight, '_jump_quote_cost', count('_jump_quote_cost', flight._jump_quote_cost))
    monkeypatch.setattr(flight, 'jumps', count('jumps', flight.jumps))
    monkeypatch.setattr(flight, 'step_cost', count('step_cost', flight.step_cost))
    monkeypatch.setattr(passage_routes.Resources, 'advance', count('advance', passage_routes.Resources.advance))
    t0 = time.perf_counter()
    target.test_overlapping_allied_auras_use_highest_pb_then_fall_back_after_expiry(tmp_path, True)
    wall = time.perf_counter() - t0
    with open(OUT, 'w') as handle:
        json.dump({'wall_s': round(wall, 2), 'counts': counts}, handle, sort_keys=True)
