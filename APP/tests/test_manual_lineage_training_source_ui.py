from __future__ import annotations

import re
import subprocess
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "static/app.js"
INDEX_HTML = ROOT / "static/index.html"
STYLES = ROOT / "static/styles.css"


def _ids(html: str) -> list[str]:
    class IdParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.values: list[str] = []

        def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.values.extend(value for key, value in attrs if key == "id" and value)

    parser = IdParser()
    parser.feed(html)
    return parser.values


def test_manual_lineage_resolver_is_exact_error_gated_and_accessible() -> None:
    javascript = APP_JS.read_text(encoding="utf-8")
    html = INDEX_HTML.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    subprocess.run(["node", "--check", str(APP_JS)], check=True)
    identifiers = _ids(html)
    assert not [value for value, count in Counter(identifiers).items() if count > 1]
    for expected in (
        'id="guidedManualLineageResolver"',
        'id="guidedManualLineageRoutes"',
        'id="guidedManualLineageOwnerForm"',
        'id="guidedManualLineageTrainingTypes"',
        'id="guidedManualLineageTargetOptions"',
        'id="guidedManualLineagePrepare"',
        'id="guidedManualLineagePreview"',
        'id="guidedManualLineageApprovalConfirm"',
        'id="guidedManualLineageApprove"',
        'id="guidedManualLineageAdvanced"',
    ):
        assert expected in html
    assert 'role="list" aria-label="Manual Lineage resolution routes"' in html
    assert 'type="search"' in html
    assert 'Target IDs are never entered manually.' in html
    assert 'id="guidedBuildButtonReason"' in html
    assert 'aria-describedby="guidedBuildButtonReason"' in html

    assert 'diagnostic?.code === "FINAL_CHARACTER_BOUNDED_CHOICE_REQUIRED"' in javascript
    assert 'diagnostic?.details?.slot_id === "manual_lineage_training_source"' in javascript
    assert 'if (!networkFailure && isManualLineageBoundedChoiceDiagnostic(diagnostic)) openManualLineageResolver(diagnostic);' in javascript
    assert 'const routes = Array.isArray(contract?.resolution_routes) ? contract.resolution_routes : [];' in javascript
    assert 'for (const route of routes)' in javascript
    assert 'card.dataset.selected = "false";' in javascript
    assert 'route.actionable_now === false' in javascript
    assert 'route.availability_status || "Proposal required"' in javascript
    assert 'route.availability_status || "requires_explicit_ai_proposal"' in javascript
    assert 'Unavailable — no authenticated project-locked source is available.' in javascript
    assert 'route?.route_id === "owner_supplied_custom_training_source"' in javascript
    assert "approve.disabled = !manualLineageResolver.challenge || !confirm?.checked" in javascript
    assert 'state === "prepared"' in javascript
    assert 'Approval prepared' in javascript
    assert 'Exact approval prepared. Review the source and hashes, then explicitly approve; nothing was sealed by this step.' in javascript
    assert 'setManualLineageStatus("The exact source is sealed.' in javascript
    assert 'reason.textContent = !editable' in javascript
    assert 'reason.textContent = !editable\n      ? PLANNING_FREEZE_MESSAGE\n      : !valid' in javascript
    assert 'blockers[0]?.message' in javascript
    assert 'fieldId: "sheetMethodRouteChoice", message: "Choose how this character learned the selected Method."' in javascript
    assert 'Ready — all required planning choices are complete.' in javascript

    resolver = re.search(
        r"function initManualLineageResolver\(\) \{.*?^\}\n\ninitManualLineageResolver\(\);",
        javascript,
        re.MULTILINE | re.DOTALL,
    )
    assert resolver is not None
    resolver_source = resolver.group(0)
    assert "/manual-lineage-training-source/challenge" in resolver_source
    assert "/manual-lineage-training-source/approve" in resolver_source
    assert "selected_ai_custom_training_source" not in resolver_source
    assert "provider" not in resolver_source.casefold()
    assert "seal_custom_training_source" not in resolver_source
    assert "guidedManualLineageApprovalConfirm" in resolver_source
    assert "challenge_id: challenge.challenge_id" in resolver_source
    assert "nonce: challenge.nonce" in resolver_source

    assert ".manual-lineage-route-grid" in styles
    assert ".manual-lineage-confirmation" in styles
    assert "@media (max-width: 860px)" in styles
    assert "@media (max-width: 560px)" in styles
