"""Real table-action transport shared by R10 consent and lifetime regressions."""
from contextlib import contextmanager
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import script


@contextmanager
def table_probe_copy(combat, userdata):
    """An isolated, disposable saved-fight probe for hidden-menu comparisons.

    Alchemy and Steal Momentum tests compare an uncommitted menu against later
    hidden movement. The real Table preserves pending choices, so the first
    probe uses a small userdata copy and never abandons the real fight's prompt.
    """
    from pathlib import Path
    from shutil import copytree
    from tempfile import TemporaryDirectory
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    with TemporaryDirectory(prefix='table-probe-', dir=userdata.parent) as scratch:
        copied = Path(scratch) / 'userdata'
        copytree(userdata, copied)
        service = CombatService(combat.source_root, copied)
        yield service, TabletopService(service, copied), copied


def fixed_dice(monkeypatch, values):
    original = Gate4ControllerEngine.execute_intent
    def execute(engine, *args, **kwargs):
        script(engine, values)
        return original(engine, *args, **kwargs)
    monkeypatch.setattr(Gate4ControllerEngine, "execute_intent", execute)


def cast_sender(combat, table, mid, name, *, at=None, target=None, contains=""):
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    candidates = [c for c in engine.legal_candidates() if name in c.display_name and contains in c.display_name
                  and (at is None or c.destination and (c.destination.x, c.destination.y) == at)
                  and (target is None or target in c.target_ids)]
    assert candidates, (name, contains, at, target)
    c = min(candidates, key=lambda c: len(c.display_name))
    return lambda answers=(): table.act(mid, c.candidate_id, c.decision_id, c.state_version, state["last_sequence"], list(answers))


def answer(prompt, option=None, use=True):
    return {**prompt["context"], "selection": "USE" if use else "DECLINE",
            "option_ids": [option or prompt["choice"]["options"][0]["id"]] if use else []}


def commit(send, selections=None):
    answers = []
    prompts = []
    for _ in range(20):
        result = send(answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        option, use = selections(prompt) if selections else (None, False)
        answers.append(answer(prompt, option, use))
    raise AssertionError("too many prompts")
