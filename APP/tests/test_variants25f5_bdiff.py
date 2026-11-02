"""VARIANTS25F5 behaviour diff harness (evidence only). Dumps owner legal candidates + owned catalogue per scenario."""
import json
from pathlib import Path

import pytest

from tests.auto_worker1_support import LEFT as OWNER, fight
from tests.worker2_support import fixture, reload

TREE = "head"
OUT = Path("/var/tmp/auto-audit/fix/VARIANTS25F5-evidence/bdiff")
SPACE, ILLUSION, WRESTLING = "tianxia.sphere.space", "tianxia.sphere.illusion", "tianxia.sphere.wrestling"
FT = "tianxia.talent.formations."
FIGHT = {
    "folded_reach": ("tianxia.talent.space.folded_reach", [SPACE]),
    "substantial_phantasm": ("tianxia.talent.illusion.substantial_phantasm", [ILLUSION]),
    "saint_body_rebuke": ("foundation.ancient_desolate_sacred_body_v0_2C.saint_body_rebuke", []),
    "grandstanding_slam": ("TAL_WRESTLING_GRANDSTANDING_SLAM", [WRESTLING]),
}
FIXTURE = {
    "darkvision_meld": (["TAL_DARK_DARKVISION", "TAL_DARK_PERSISTENT_MELD"], 15),
    "protection": (["PROTECTION_BASE_AEGIS", "PROTECTION_BASE_ARMORED_AEGIS"], 15),
    "pulse_court_sovereign": (["court_of_the_ninefold_array", "sovereign_of_the_world_diagram"], 15),
    "pulse_second": (["sovereign_pulse"], 12),
}


def _dump(engine):
    cat = engine.action_catalog
    legal = []
    for c in engine.legal_candidates():
        if c.actor_id != OWNER:
            continue
        act = cat.get(c.source_definition_id)
        legal.append({"source": c.source_definition_id, "targets": list(c.target_ids),
                      "name": getattr(act, "display_name", None), "destination": str(c.destination),
                      "economy": str(getattr(act, "economy", None)),
                      "costs": sorted(map(str, dict(getattr(act, "costs", None) or ()).items()))})
    legal.sort(key=lambda r: json.dumps(r, sort_keys=True))
    owned = [{"id": k, "name": a.display_name, "economy": str(a.economy),
              "costs": sorted(map(str, dict(a.costs or ()).items())),
              "variant": (lambda v: (v.base_key, sorted(p.axis + "=" + p.label for p in v.choices)) if v else None)(getattr(a, "variant", None))}
             for k, a in cat.items() if a.owner_id == OWNER]
    owned.sort(key=lambda r: json.dumps(r, sort_keys=True))
    return {"legal": legal, "owned": owned}


def _write(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{TREE}.{name}.json").write_text(json.dumps(data, indent=1, sort_keys=True))


@pytest.mark.parametrize("name", list(FIGHT))
def test_bdiff_fight(tmp_path, name):
    talent, spheres = FIGHT[name]
    combat, table, mid = fight(tmp_path, [talent], spheres=spheres)
    _write(name, _dump(reload(tmp_path, mid)))


@pytest.mark.parametrize("name", list(FIXTURE))
def test_bdiff_fixture(tmp_path, name):
    talents, cl = FIXTURE[name]
    combat, table, mid = fixture(tmp_path, talents, cl=cl)
    _write(name, _dump(reload(tmp_path, mid)))
