"""Shared Circuit Memory after Feed: the rider must not claim the automated Concentration path is manual.

Regression for the MGR-T15 close review: the reviewed foundations3 authority kept
"not automated yet" for the Feed-helped save path that this branch automates.
Reads only in-repo authority files (public-safe, no git history).
"""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
MECHANIC = 'foundation.origin_spirit_body_v0_2B.refined_shared_circuit_memory'
REVIEWED = APP / 'authority' / 'typed_mechanics' / 'reviewed_final.d' / 'foundations3.json'
GENERATED = APP / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json'


def _reviewed_riders():
    return json.loads(REVIEWED.read_text(encoding='utf-8'))['mechanics'][MECHANIC]['riders']


def _generated_riders():
    return json.loads(GENERATED.read_text(encoding='utf-8'))['mechanics'][MECHANIC]['riders']


def test_feed_concentration_path_is_not_listed_as_manual():
    for riders in (_reviewed_riders(), _generated_riders()):
        text = ' '.join(riders)
        assert 'not automated yet' not in text
        assert 'Feed on the ally\'s failed Concentration save is automated.' in text


def test_generated_authority_carries_reviewed_rider():
    assert _generated_riders() == _reviewed_riders()
