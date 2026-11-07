"""The shared public option fixture must feed the compiler's printed heading too.

Public exports redact printed prose (category headings included) while keeping
typed effects. `test_option_tooltips` and `test_option_tooltips_printed` run
their real sheet, table and Node assertions under the shared fixture
`tests.option_tooltip_support.synthetic_option_rules`, which supplies stable
synthetic prose to both the tooltip projection and the printed-rules reader the
compiler uses for heading tags. If that fixture stopped supplying the heading,
the public copy would lose `Shape Darkness: Numbing Darkness` from the sheet and
the table menu. This pins the shared fixture itself, not production combat code.

The fixture is the shared support module, not another test file: importing test
functions from a neighbouring module breaks whenever that module renames or
removes them, and pytest then collects those tests twice.
"""
import json
import subprocess

from combat.gate5_service import CombatService
from combat.status_text import printed_rules
from combat.tabletop_service import TabletopService
from tests.option_tooltip_support import ROOT, option_match, rows, synthetic_option_rules

DARKNESS = "Shape Darkness: Numbing Darkness"


def labels(rows_):
    return [row["label"] for row in rows_]


def test_shape_darkness_survives_redacted_printed_input_on_sheet_table_and_node(tmp_path, monkeypatch):
    # The public copy replaces this talent's printed prose with redacted text;
    # the fixture supplies the heading the compiler reads for shape selectors.
    with synthetic_option_rules(tmp_path, monkeypatch):
        assert "### Numbing Darkness - Darkness" in printed_rules()["TAL_DARK_NUMBING_DARKNESS"]
        parts = option_match(tmp_path)
        assert DARKNESS in labels(parts["buttons"]), labels(parts["buttons"])
        assert DARKNESS in labels(parts["state"]["menu"]["actions"])

        # The same menu after a cold reload keeps the option.
        resumed = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(parts["mid"])
        assert DARKNESS in labels(resumed["menu"]["actions"])

        # The Node sheet/table builders render the rows the fixture compiled.
        payload = rows()
        assert DARKNESS in labels(payload)
        rows_file = tmp_path / "sol155-rows.json"
        rows_file.write_text(json.dumps(payload))
        subprocess.run(["node", "tests/option_tooltips.test.mjs", str(rows_file)], cwd=ROOT, check=True)

    # The fixture is scoped to its with-block: the real printed text returns and
    # the synthetic prose never leaks into another test.
    assert "Synthetic reference prose" not in printed_rules()["TAL_DARK_NUMBING_DARKNESS"]
