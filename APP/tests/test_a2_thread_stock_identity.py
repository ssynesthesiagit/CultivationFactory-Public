"""Current-thread-head stock AI captures against the reviewed lane parent."""
import hashlib
import json
import subprocess
import sys

import pytest

from tests.h1_support import ROOT

APP = ROOT
BASE = "5044b588819f4446ec38a1006b5ea5315da570ac"
SEEDS = ("GATE4-AN-1", "GATE4-LEE", "GATE4-TEST", "LOCK5-A", "LOCK5-B", "LOCK5-C")


@pytest.mark.parametrize("seed", SEEDS)
def test_stock_ai_base_head_capture_identity(tmp_path, seed):
    authority = tmp_path / "base-authority.json"
    authority.write_bytes(subprocess.check_output(
        ["git", "show", f"{BASE}:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"],
        cwd=APP.parent,
    ))

    def capture(label):
        args = [sys.executable, "-m", "tests.sol150_replay_capture", str(tmp_path / label), f"stock:{seed}"]
        if label == "base":
            args.extend((BASE, str(authority)))
        result = subprocess.run(args, cwd=APP, text=True, capture_output=True, timeout=600,
                                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"})
        (tmp_path / f'{label}.stdout.log').write_text(result.stdout)
        (tmp_path / f'{label}.stderr.log').write_text(result.stderr)
        assert result.returncode == 0, result.stdout[-1000:] + result.stderr[-3000:]
        captured = json.loads(result.stdout.splitlines()[-1])
        (tmp_path / f'{label}.json').write_text(json.dumps(captured, sort_keys=True))
        return captured

    before, after = capture("base"), capture("head")
    encoded = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    left, right = encoded(before), encoded(after)
    print(f"{seed}: base={hashlib.sha256(left).hexdigest()} head={hashlib.sha256(right).hexdigest()} "
          f"identical={left == right} decisions={len(before['choices'])}/{len(after['choices'])}")
    evidence = {'seed': seed, 'base_revision': BASE, 'base_sha256': hashlib.sha256(left).hexdigest(),
                'head_sha256': hashlib.sha256(right).hexdigest(), 'identical': left == right,
                'decisions': [len(before['choices']), len(after['choices'])],
                'cold_verify_and_replay': 'PASS'}
    (tmp_path / 'comparison.json').write_text(json.dumps(evidence, indent=2) + '\n')
    assert left == right
