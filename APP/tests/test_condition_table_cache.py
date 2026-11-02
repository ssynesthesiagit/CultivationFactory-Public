"""The condition reading table is cached per rules object (2026-10-06: the sheet rebuilt it once per attack button).
The cache must equal a fresh build, hand out independent copies, and rebuild when the rules change."""
from combat import condition_text


def test_cached_table_equals_a_fresh_build():
    assert condition_text.all_conditions() == condition_text._all_conditions()


def test_callers_get_independent_copies():
    first = condition_text.all_conditions()
    key = next(iter(first))
    first[key]["reading"] = "mutated by a caller"
    first.pop(key)
    second = condition_text.all_conditions()
    assert key in second and second[key]["reading"] != "mutated by a caller"


def test_a_new_rules_object_rebuilds_the_table(monkeypatch):
    real = condition_text.rules()
    condition_text.all_conditions()
    changed = {**real, "conditions": {**(real.get("conditions") or {}), "zz_cache_probe": {"_rule": "Probe rule text."}}}
    monkeypatch.setattr(condition_text, "rules", lambda: changed)
    assert "zz_cache_probe" in condition_text.all_conditions()
    monkeypatch.setattr(condition_text, "rules", lambda: real)
    assert "zz_cache_probe" not in condition_text.all_conditions()


def test_overlapping_rules_snapshots_each_get_their_own_table(monkeypatch):
    """Two requests holding different rules snapshots each see their own table, even when the other request replaces the
    cache after the first one has stored its table but before it has handed it back (the race SHEET1r1 found).

    Phases are enforced, never timed out silently: worker A builds and stores its table, then pauses at its first step
    after storing -- re-reading the shared dict (the unlocked cache, 2711356f) or copying the table it kept (the fixed
    cache). Worker B starts only once A is paused, answers fully under the other snapshot, and then releases A. Every
    wait is asserted, both workers must finish, and worker exceptions fail the test. Fails on 2711356f; passes now."""
    import copy
    import threading
    real = condition_text.rules()
    other = {**real, "conditions": {**(real.get("conditions") or {}), "zz_other_snapshot": {"_rule": "Other."}}}
    local = threading.local()
    monkeypatch.setattr(condition_text, "rules", lambda: getattr(local, "src", real))
    a_paused, b_done = threading.Event(), threading.Event()
    waits = []

    def pause_a():
        if getattr(local, "name", "") == "A" and not a_paused.is_set():
            a_paused.set()
            waits.append(b_done.wait(timeout=10))

    class PausingCache(dict):
        def __getitem__(self, key):
            if key == "table":  # the unlocked cache read its answer back from the shared dict after storing it
                pause_a()
            return super().__getitem__(key)

    real_deepcopy = copy.deepcopy

    def pausing_deepcopy(value, *args, **kwargs):  # the fixed cache copies the table it kept under the lock
        pause_a()
        return real_deepcopy(value, *args, **kwargs)

    monkeypatch.setattr(condition_text, "_ALL_CONDITIONS", PausingCache())
    monkeypatch.setattr(copy, "deepcopy", pausing_deepcopy)
    results, errors = {}, []

    def worker(name, src):
        try:
            local.name, local.src = name, src
            if name == "B":
                waits.append(a_paused.wait(timeout=10))
            results[name] = "zz_other_snapshot" in condition_text.all_conditions()
        except Exception as error:  # surface worker failures in the test, not just in a thread's stderr
            errors.append(error)
        finally:
            if name == "B":
                b_done.set()

    threads = [threading.Thread(target=worker, args=("A", real)), threading.Thread(target=worker, args=("B", other))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors, errors
    assert waits == [True, True], "a phase was skipped: A never paused after storing, or B never finished"
    assert results == {"A": False, "B": True}


def test_sheet_reuses_the_table_until_the_rules_change(monkeypatch):
    """Building many attack descriptions builds the table once; a changed rules object rebuilds it once."""
    from combat.ext import attack_modifiers
    real = condition_text.rules()
    condition_text._ALL_CONDITIONS.clear()
    for _ in range(5):
        attack_modifiers.description([{"effects": [{"type": "condition", "condition": "frightened"}]}])
    assert condition_text._ALL_CONDITIONS["builds"] == 1
    changed = {**real}
    monkeypatch.setattr(condition_text, "rules", lambda: changed)
    for _ in range(5):
        attack_modifiers.description([{"effects": [{"type": "condition", "condition": "frightened"}]}])
    assert condition_text._ALL_CONDITIONS["builds"] == 2
