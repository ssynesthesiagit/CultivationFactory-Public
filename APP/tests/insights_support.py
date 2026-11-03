"""Shared synthetic Insight sheet and boundary helpers for Insight table tests."""
import copy

from combat.gate5_service import FACTORY_ACTOR_PREFIX
from tests.test_factory_combat_compiler import SHEET

OWNER = FACTORY_ACTOR_PREFIX + "insight-owner"


def sheet(insights=()):
    """Finalized statistics stay identical; Insight ownership has its own surface."""
    result = copy.deepcopy(SHEET)
    result["spheres_and_talents"] = {
        "sphere_record_ids": [],
        "learned_talent_record_ids": [],
        "cultivation_insight_record_ids": list(insights),
    }
    result["equipment"] = []
    return result


def boundary(bundle, insight):
    """The compiled automation boundary the sheet library shows for one owned Insight."""
    return next(row for row in (bundle.get("diagnostics") or {}).get("insights") or [] if row["id"] == insight)
