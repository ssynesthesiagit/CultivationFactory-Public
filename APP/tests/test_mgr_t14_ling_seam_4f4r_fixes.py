"""Regression tests for the Sol review 4F4R findings on the ling-seam Thousand-Fold Steel Body branch."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEYOND = 'tianxia.subpath.body.thousand_fold_steel_body.feature.body_beyond_the_hammer'


def test_body_beyond_the_hammer_grants_no_damage_threshold_bypass():
    # Review finding 1: the printed text makes unarmed strikes adamantine only for rules that recognize that
    # material; it never says an Unarmed Strike ignores an object's Damage Threshold.
    rows = json.loads((ROOT / 'combat/rules/feature_blocks.d/riders_c7.json').read_text(encoding='utf-8'))['features']
    row = rows[BEYOND]
    assert 'ignore_threshold' not in row
    assert 'Damage Threshold' not in row['why'] or 'no Damage Threshold bypass' in row['why']


def test_native_acquisition_helpers_do_not_accept_schema_failure_or_no_browser_states():
    # Review finding 2: the native acquisition helpers must require READY_FOR_REVIEW. They may not accept
    # NEEDS_REVIEW, pin a known schema-failure diagnostic as a pass, or force the browser off.
    for name in ('test_body_modes_native.py', 'test_mgr_t14_thousand_fold_steel_body_floor58.py'):
        source = (ROOT / 'tests' / name).read_text(encoding='utf-8')
        assert 'NEEDS_REVIEW' not in source, name
        assert 'GM_VIEW_MODEL_PINNED_SCHEMA_ERROR' not in source, name
        assert 'NO_BROWSER_ALLOWED' not in source, name
        assert "status']=='READY_FOR_REVIEW'" in source or "status'] == 'READY_FOR_REVIEW'" in source, name
