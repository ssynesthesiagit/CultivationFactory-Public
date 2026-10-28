"""The acquisition-contract repair target must refuse huge spaces without building them.

On 2026-09-04 a real CL15 run reached the automatic Local-AI correction with 6
legal ordinary Talents at each of 15 levels.  The target materialized
``list(itertools.product(...))`` over that space -- 6**15 times 6 free-pair
choices, about 2.8 trillion tuples -- and the kernel killed the Factory at
16.5 GB resident.  These tests pin the arithmetic pre-check and prove the
bounded path still yields exactly the options the old enumeration produced.
"""

from __future__ import annotations

import itertools
import resource
import time
from copy import deepcopy
from typing import Any

import pytest

import character_creation.service as cc
from app.core import sha256_json

TARGET = cc.CharacterCreationExecutionService._provider_acquisition_contract_repair_target


def _diagnostic() -> dict[str, Any]:
    return {"code": "CG1_PREFERRED_RESPONSE_ACQUISITION_INVALID", "details": {"index": 0}}


def _run() -> dict[str, Any]:
    return {"request": {"request_sha256": "a" * 64}}


def _prior() -> str:
    return '{"request_sha256": "' + "a" * 64 + '", "selection_intent": {}}'


def _payload(*, pair_count: int, pairs: int, per_cl: list[int]) -> dict[str, Any]:
    presented_pairs = [{"sphere_id": f"S{i}", "talent_id": f"FREE-{i}"} for i in range(pairs)]
    by_cl = {
        str(cl): [f"TAL-{cl}-{i}" for i in range(count)]
        for cl, count in enumerate(per_cl, start=1)
    }
    return {
        "response_contract": {
            "expected_acquisition_counts": {
                "sphere_free_talent_pairs": pair_count,
                "ordinary_talent_ids": len(per_cl),
            },
            "presented_legal_first_cycle_pairs": presented_pairs,
            "presented_legal_ordinary_talent_ids_by_cl": by_cl,
        }
    }


def _old_algorithm(payload: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    """The enumeration the target performed before the pre-check, for a small space."""
    contract = payload["response_contract"]
    expected = contract["expected_acquisition_counts"]
    pair_count = expected["sphere_free_talent_pairs"]
    ordinary_count = expected["ordinary_talent_ids"]
    presented_pairs = contract["presented_legal_first_cycle_pairs"]
    by_cl = contract["presented_legal_ordinary_talent_ids_by_cl"]
    ordinary_choices = [by_cl[str(cl)] for cl in range(1, ordinary_count + 1)]
    pair_products = itertools.combinations(presented_pairs, pair_count) if pair_count else [()]
    ordinary_rows = list(itertools.product(*ordinary_choices) if ordinary_choices else [()])
    options: dict[str, dict[str, Any]] = {}
    for pair_tuple in pair_products:
        free_ids = {row["talent_id"] for row in pair_tuple}
        for ordinary_tuple in ordinary_rows:
            if len(set(ordinary_tuple)) != len(ordinary_tuple) or any(v in free_ids for v in ordinary_tuple):
                continue
            mapping = {
                "sphere_free_talent_pairs": [deepcopy(row) for row in pair_tuple],
                "ordinary_talent_ids": list(ordinary_tuple),
            }
            options["acq_" + sha256_json(mapping)[:20]] = mapping
            if len(options) > 256:
                return None
    return options or None


def test_the_crash_shaped_space_is_refused_quickly_and_cheaply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc, "_provider_payload", lambda run, **kw: _payload(pair_count=1, pairs=6, per_cl=[6] * 15))
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    start = time.perf_counter()
    result = TARGET(_diagnostic(), run=_run(), prior_response=_prior())
    elapsed = time.perf_counter() - start
    after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    assert result is None
    assert elapsed < 1.0
    # ru_maxrss is in kilobytes on Linux; the old code grew by gigabytes here.
    assert after - before < 64 * 1024


@pytest.mark.parametrize(
    "shape",
    [
        dict(pair_count=1, pairs=3, per_cl=[2, 2, 2]),
        dict(pair_count=0, pairs=0, per_cl=[3, 3]),
        dict(pair_count=2, pairs=4, per_cl=[2, 3]),
        dict(pair_count=1, pairs=2, per_cl=[4, 4, 3]),
    ],
)
def test_small_spaces_produce_exactly_the_previous_options(monkeypatch: pytest.MonkeyPatch, shape) -> None:
    payload = _payload(**shape)
    monkeypatch.setattr(cc, "_provider_payload", lambda run, **kw: payload)
    result = TARGET(_diagnostic(), run=_run(), prior_response=_prior())
    expected = _old_algorithm(payload)
    if expected is None:
        assert result is None
        return
    assert result is not None
    assert result["options"] == expected
    assert result["option_ids"] == sorted(expected)
    assert result["response_schema"]["properties"]["option_id"]["enum"] == sorted(expected)


def test_a_space_just_over_the_ceiling_is_refused_and_just_under_is_enumerated(monkeypatch: pytest.MonkeyPatch) -> None:
    # 7 * 7 * 7 * 7 * 7 * 3 = 50,421 > 50,000 -> refused up front.
    over = _payload(pair_count=0, pairs=0, per_cl=[7, 7, 7, 7, 7, 3])
    monkeypatch.setattr(cc, "_provider_payload", lambda run, **kw: over)
    assert TARGET(_diagnostic(), run=_run(), prior_response=_prior()) is None

    # 4 * 4 * 4 = 64 <= 50,000 -> enumerated; 64 distinct-valued tuples but the
    # duplicate filter leaves 4 * 3 * 2 = 24 legal options.
    under = _payload(pair_count=0, pairs=0, per_cl=[4, 4, 4])
    for cl in ("1", "2", "3"):
        under["response_contract"]["presented_legal_ordinary_talent_ids_by_cl"][cl] = ["A", "B", "C", "D"]
    monkeypatch.setattr(cc, "_provider_payload", lambda run, **kw: under)
    result = TARGET(_diagnostic(), run=_run(), prior_response=_prior())
    assert result is not None
    assert len(result["options"]) == 24
