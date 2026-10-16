"""Source pin and native delivery gap for Barrier Ward; no invented HP rules.

The table fixture compiles source IDs through the normal compiler. It does not
certify character-builder acquisition. The strict xfail is a tracked delivery
requirement, not evidence that the complete ability is automated.
"""
import hashlib

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_auto_protection_wards import ROOT, printed, record, table_fixture
from tests.test_r1i_round3 import reload


ROW = "PROTECTION_BASE_BARRIER_WARD"
PIN = "c1f7e6ab5ad4b8f73eb8c0208563990401e32a88ee3710cb4d2672fd7e282666"


class MissingBarrierWard(AssertionError):
    """Only the known native delivery gap may be an expected failure."""


def labels(table, mid):
    return [option["label"] for group in table.state(mid)["menu"]["actions"]
            for option in group["options"]]


def cold_table(tmp_path, mid):
    reload(tmp_path, mid)
    return TabletopService(CombatService(ROOT, tmp_path), tmp_path)


def test_barrier_ward_source_pin():
    assert hashlib.sha256(printed(ROW).encode()).hexdigest() == PIN
    assert record(ROW)["source"]["text_sha256"] == PIN
    assert "learn this Ward talent automatically" in printed(ROW)


def test_nonowner_has_no_barrier_ward_before_and_after_reload(tmp_path):
    combat, table, mid = table_fixture(tmp_path, [])
    assert not any("Barrier" in label for label in labels(table, mid))
    table = cold_table(tmp_path, mid)
    assert not any("Barrier" in label for label in labels(table, mid))


@pytest.mark.xfail(strict=True, raises=MissingBarrierWard,
                   reason="Barrier Ward has no native action provider; starting HP/defenses need a source ruling")
def test_barrier_ward_is_reachable_at_native_table_after_reload(tmp_path):
    combat, table, mid = table_fixture(tmp_path, [ROW])
    table = cold_table(tmp_path, mid)
    if not any(label.startswith("Ward: Barrier") for label in labels(table, mid)):
        raise MissingBarrierWard("Owning the exact source row does not offer Barrier Ward at the table")
