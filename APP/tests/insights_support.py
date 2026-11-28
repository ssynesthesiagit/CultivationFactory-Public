"""Shared Insight fixtures for test_auto_insights and test_a2_group_insights6."""

import copy

from combat.gate5_service import FACTORY_ACTOR_PREFIX
from tests.test_factory_combat_compiler import SHEET

OWNER = FACTORY_ACTOR_PREFIX + "insight-owner"


def _sheet(insights=()):
    """Finalized statistics stay identical; Insight ownership has its own surface."""
    sheet = copy.deepcopy(SHEET)
    sheet["spheres_and_talents"] = {
        "sphere_record_ids": [],
        "learned_talent_record_ids": [],
        "cultivation_insight_record_ids": list(insights),
    }
    sheet["equipment"] = []
    return sheet


def _boundary(bundle, insight):
    """The compiled automation boundary the sheet library shows for one owned Insight."""
    return next(row for row in (bundle.get("diagnostics") or {}).get("insights") or [] if row["id"] == insight)
