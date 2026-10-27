"""Grow's production preview and submission must agree on used level choices.

Only synthetic sealed packages, persisted table records and offline Node UI
stubs are used; no browser, history access or live model server is needed.
"""
from copy import deepcopy
import hashlib
import json
import shutil
import subprocess

import pytest

from combat.tabletop import TabletopError
from tests.test_grow1_abilities import PID, ROOT, growth_service, installed_sheet
from tests.test_grow1_respec_review import seal


def assert_production_preview(payload, *, consumed):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the offline production UI regression")
    script = """
      const assert = require('node:assert/strict');
      const fs = require('node:fs');
      const source = fs.readFileSync(process.argv[1], 'utf8');
      // The full local planning database need not fit Linux\'s per-argument limit.
      const data = JSON.parse(fs.readFileSync(0, "utf8"));
      const consumed = JSON.parse(process.argv[2]);
      const handlers = {};
      let rendered = [];
      const root = {
        addEventListener: (kind, fn) => handlers[kind] = fn,
        replaceChildren: (...nodes) => rendered = nodes,
      };
      const text = node => node == null ? '' : typeof node === 'object'
        ? (node.children || []).map(text).join('') : String(node);
      (async () => {
        const grow = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
        grow.initGrow({
          h: (tag, attrs, ...children) => ({tag, attrs, children}),
          $: id => id === 'grow-root' ? root : null,
          fetchJson: async () => data, projectId: () => 'synthetic',
        });
        await grow.loadGrow();
        handlers.input({target: {
          id: 'grow-ability-WIS', dataset: {growAbility: 'WIS'}, value: '2',
        }});
        const output = rendered.map(text).join('');
        assert.ok(output.includes('Wisdom 12→14'), output);
        assert.equal(output.includes('Level increase legal:'), !consumed, output);
        assert.equal(output.includes('needs an unused opportunity'), consumed, output);
      })().catch(error => {console.error(error); process.exitCode = 1});
    """
    result = subprocess.run(
        [node, "-e", script, str(ROOT / "static/tabletop/grow.js"), json.dumps(consumed)],
        input=json.dumps(payload), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "kind,target_cl,table_gm,consumed",
    [
        ("ability_score_change", 4, None, True),
        ("cultivation_insight_acquisition", 4, None, True),
        ("ability_score_change", 8, None, False),
        ("talent_acquisition", 4, None, False),
        (None, None, False, True),
        (None, None, True, False),
        (None, None, None, False),
    ],
    ids=["sealed-asi", "sealed-insight", "other-cl", "other-kind",
         "table-level", "table-gm-grant", "unused"],
)
def test_current_level_preview_matches_submission_after_cold_reload(
    tmp_path, kind, target_cl, table_gm, consumed,
):
    base = installed_sheet()  # Current CL4, WIS12: a +2 is below the cap.
    if kind:
        base["advancement_history"] = {"canonical_allocations": [
            {"target_cl": target_cl, "advancement_kind": kind},
        ]}
    package = seal(tmp_path, base)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    if table_gm is not None:
        growth_service(tmp_path).buttons.save_advancement(PID, {"abilities": [
            {"reason": "level_increase", "cl": 4, "changes": {"CON": 2}, "gm": table_gm},
        ]})

    service = growth_service(tmp_path)
    before = deepcopy(service.buttons.get(PID).get("advancement"))
    payload = service.advancement(PID)
    # Execute the full production module with the actual service response, not
    # a separately assembled approximation of the preview's inputs.
    assert_production_preview(payload, consumed=consumed)
    assert (4 in payload["ability_panel"]["level_increase"]["recorded_cls"]) == consumed
    entry = {"reason": "level_increase", "cl": 4, "changes": {"WIS": 2}}
    if consumed:
        with pytest.raises(TabletopError, match="already recorded at CL 4") as error:
            service.add_ability(PID, entry)
        assert error.value.status_code == 409
        assert growth_service(tmp_path).buttons.get(PID).get("advancement") == before
    else:
        service.add_ability(PID, entry)
        recorded = growth_service(tmp_path).buttons.get(PID)["advancement"]["abilities"][-1]
        assert recorded["changes"] == {"WIS": 2}
        assert recorded["gm"] is False
    assert hashlib.sha256(package.read_bytes()).hexdigest() == digest
