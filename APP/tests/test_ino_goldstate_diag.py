"""Lead diagnostic (Ino 2026-11-23, GOLDSTATEPROSE1): which mechanical-state value differs on the scrambled copy.
Fails on purpose: line 1 (kept by the public report, 300 chars) has per-top-level-key hashes; the rest is every path."""
import copy

from combat.canonical import canonical_sha256
from combat.gate3_scripted import execute_persistent_script
from tests.test_combat_gate3_persistence import SCRIPT_PATH, ROOT


def test_ino_goldstate_diag(tmp_path):
    session, _ = execute_persistent_script(ROOT, tmp_path / "UserData", SCRIPT_PATH)
    state = copy.deepcopy(session.replay()["state"])
    state.pop("observations")
    top = ";".join(f"{k}={canonical_sha256(state[k])[:5]}" for k in sorted(state))
    lines = []

    def walk(v, path, depth):
        lines.append(f"{path or '/'} {canonical_sha256(v)[:8]}")
        if depth >= 6:
            return
        if isinstance(v, dict):
            for k in sorted(v):
                walk(v[k], f"{path}/{k}", depth + 1)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]", depth + 1)

    walk(state, "", 0)
    assert False, f"GSD{len(state)} {canonical_sha256(state)[:6]} {top}\nGSDFULL\n" + "\n".join(lines)
