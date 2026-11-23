"""Lead diagnostic 2 (Ino 2026-11-23, GOLDSTATEPROSE1): the golden-test hashes with the two lock fingerprints left out.
Fails on purpose so the public report (300 chars) keeps the one line; the private run gives the full values."""
import copy

from combat.canonical import canonical_sha256
from combat.gate3_scripted import execute_persistent_script
from tests.test_combat_gate3_persistence import SCRIPT_PATH, ROOT, strip_gate3_fields
from tests.test_gate3_golden_hashes import _historical_events


def test_ino_goldstate_diag2(tmp_path):
    session, _ = execute_persistent_script(ROOT, tmp_path / "UserData", SCRIPT_PATH)
    replay = session.replay()
    events = [strip_gate3_fields(e) for e in replay["events"]]
    state = copy.deepcopy(replay["state"])
    state.pop("observations")
    locks = {k: state.pop(k) for k in ("mechanics_lock_sha256", "universal_defaults_lock_sha256")}
    s1 = canonical_sha256(state)
    no_counter = copy.deepcopy(state)
    no_counter.pop("event_sequence")
    s2 = canonical_sha256(no_counter)
    hist = _historical_events(events)
    e1 = canonical_sha256(hist)
    hist[0]["payload"].pop("targeting_policy")
    e2 = canonical_sha256(hist)
    in_events = sum(1 for e in events if any(v in str(e) for v in locks.values()))
    assert False, (f"GSD2 S={s1} SN={s2} E={e1[:16]} EN={e2[:16]} LK={in_events} "
                   f"L={locks['mechanics_lock_sha256'][:8]},{locks['universal_defaults_lock_sha256'][:8]}")
