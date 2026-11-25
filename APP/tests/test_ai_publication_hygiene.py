"""Publication hygiene: AI bench and MASTERMIND code/tests carry no private pipeline paths or host names.

The forbidden fragments are assembled at runtime so this file never contains them literally.
Offline; reads source text only.
"""
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
FORBIDDEN = ("/var/tmp/" + "auto-audit", "auto" + "-audit/", "swarm" + "lord", "heavy" + "q", "sweep" + "run",
             "d1-" + "fights", "platform" + ".node(")
SCANNED = [APP / "tools" / "ai_bench.py",
           APP / "tests" / "ai_mastermind_bench_support.py", APP / "tests" / "test_ai_bench_smoke.py",
           APP / "tests" / "test_ai_tiers_bench.py", APP / "tests" / "test_ai_tiers_bench_cap.py",
           APP / "tests" / "test_ai_tiers_bench_heldout.py", APP / "tests" / "test_ai_mastermind_timing.py",
           APP / "tests" / "test_ai_mastermind_prone_profile.py", APP / "tests" / "test_ai_publication_hygiene.py",
           *sorted((APP / "tests").glob("test_ai_mastermind*.py")), *sorted((APP / "combat").glob("ai_*.py")),
           *sorted((APP / "combat").glob("gate4_*.py")), APP / "combat" / "flight_decision.py"]


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: p.name)
def test_no_private_pipeline_paths_or_host_names(path):
    text = path.read_text(encoding="utf-8")
    hits = [fragment for fragment in FORBIDDEN if fragment in text]
    assert not hits, f"{path.name} contains private material: {hits}"


def test_bench_output_has_no_hard_coded_default(monkeypatch):
    import importlib
    monkeypatch.delenv("CF_AI_BENCH_OUT", raising=False)
    module = importlib.import_module("tools.ai_bench")
    with pytest.raises(SystemExit):
        module.main(["--seeds", "1"])


def test_time_scale_is_a_setting_not_a_host_rule(monkeypatch):
    from tools import ai_bench
    monkeypatch.delenv("CF_AI_TIME_SCALE", raising=False)
    assert ai_bench.time_scale() == 1.0
    monkeypatch.setenv("CF_AI_TIME_SCALE", "1.5")
    assert ai_bench.time_scale() == 1.5
