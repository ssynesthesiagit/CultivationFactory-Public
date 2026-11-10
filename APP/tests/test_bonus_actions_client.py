"""Public, offline coverage of bonus-action loading and stranded local choices."""
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def assert_node_success(result):
    output = result.stdout + result.stderr
    # Public CI retains the first assertion line: lead with the Node failure.
    lines = [line.strip() for line in output.splitlines()]
    errors = [line for line in lines if any(word in line for word in
                                           ("error:", "Error:", "AssertionError"))]
    failed = [line for line in lines if "✖" in line or "not ok" in line]
    diagnostic = " | ".join(errors + failed)
    assert result.returncode == 0, diagnostic + "\n" + output


def test_bonus_action_client_regressions():
    result = subprocess.run(
        ["node", "--test", "tests/bonus_actions_client.test.mjs"],
        cwd=ROOT, text=True, capture_output=True, timeout=60,
    )
    assert_node_success(result)


@pytest.mark.parametrize("test_file", [
    "tests/menuspeed7_lazy.test.mjs",
    "tests/option_composition.test.mjs",
    "tests/tabletop_target_selection.test.mjs",
    "tests/optionspeed1_sheet_controller_public.test.mjs",
    "static/tabletop/tabletop.test.mjs",
    "static/tabletop/tabletop_map_pick_hit.test.mjs",
])
def test_existing_chooser_and_draft_regressions(test_file):
    # Report each chooser/lifecycle harness separately, retaining all assertions.
    result = subprocess.run(
        ["node", "--test", test_file],
        cwd=ROOT, text=True, capture_output=True, timeout=120,
    )
    assert_node_success(result)


def test_table_modules_carry_the_deploy_build_stamp(tmp_path):
    # The deploy stamp replaces every per-module version, and the same id travels in the response header.
    from app.static_build import BUILD_HEADER, StaticBuild, compute_build, stamp_source

    app_dir = tmp_path / "APP"
    (app_dir / "app").mkdir(parents=True)
    (app_dir / "app" / "api.py").write_text("x = 1\n")
    table = app_dir / "static" / "tabletop"
    table.mkdir(parents=True)
    (table / "tabletop.js").write_text('import {api} from "./api.js?v=menuspeed6f3";\nimport("./dice3d.js?v=old");\n')
    (table / "tabletop.html").write_text('<script type="module" src="/static/tabletop/tabletop.js?v=charlist1"></script>')
    (table / "api.js").write_text("export const api = 1;\n")

    build = StaticBuild(app_dir, nonce="one").build
    stamped = stamp_source((table / "tabletop.js").read_text(), build, ".js")
    assert f'"./api.js?v={build}"' in stamped and f'"./dice3d.js?v={build}"' in stamped
    assert "menuspeed6f3" not in stamped and "?v=old" not in stamped
    page = stamp_source((table / "tabletop.html").read_text(), build, ".html")
    assert f"tabletop.js?v={build}" in page and "charlist1" not in page

    served = StaticBuild(app_dir, nonce="one").response_for("/static/tabletop/tabletop.js")
    assert served is not None and served.headers[BUILD_HEADER] == build
    assert f'"./api.js?v={build}"' in served.body.decode()
    # Paths outside the table's own directory are not served by this stamp.
    assert StaticBuild(app_dir, nonce="one").response_for("/static/tabletop/../../etc/passwd") is None

    # A restart or any table or server source change is a new build.
    assert compute_build(app_dir, "two") != build
    (table / "api.js").write_text("export const api = 2;\n")
    assert compute_build(app_dir, "one") != build


def test_browser_check_uses_configured_chromium_and_refuses_unported_urls():
    text = (ROOT / "tests" / "test_bonus_actions_browser_optin.py").read_text()
    assert 'os.environ.get("BONUSFIX_CHROMIUM", "/usr/bin/chromium")' in text
    assert "parsed.port not in {None, 8765}" not in text
    assert "parsed.port is not None and parsed.port != 8765" in text

