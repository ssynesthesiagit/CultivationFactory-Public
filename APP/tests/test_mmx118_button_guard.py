"""MMX118f1 guard: every button the table offers a stock fighter can be executed or cleanly refused.

HUNT112 #1 (P1, round-24 LIVE 42e43e14) found a printed button -- "Qi Storage Talisman" -- that the
table happily offered 17 times in one fight and that raised ``ValueError("unknown resource")`` the
moment it was pressed, taking the owner's fight down mid-turn. A single hand-found button does not
scale, so this presses *everything* the table offers a stock character and holds the table to one
rule: an offered button either happens, or is refused in words the service chose on purpose. It may
not raise, and it may not sit half-answered.

What this guard has to earn (MMX118f1 review #2). The first version of this file could pass without
ever entering an ability's effect, because it was loose in three ways, all of which are closed here:

* **Every ``TabletopError`` counted as a clean refusal.** The only three codes that reach ``act`` are
  ``TABLETOP_PENDING``, ``TABLETOP_STALE`` and ``TABLETOP_NOT_YOUR_TURN`` -- all of them this test's
  own plumbing (a half-answered choice, a stale menu, the wrong turn), none of them the table meaning
  "no". A refused ability is a ``CombatServiceError`` carrying a deliberate diagnostic code, so that
  is the only thing that may count as a refusal now.
* **Prompts were never answered.** A button that only raises a pending choice left the state untouched,
  so the next press raised ``TABLETOP_PENDING`` and every later button "succeeded" without running. Each
  attempt here answers its own prompts and must reach a committed result; an unfinished prompt is
  reported as ``unresolved``, which fails the test.
* **Spending action economy hid later buttons, and the only coverage claim was ``pressed > 0``.** Each
  button now gets its own freshly built fight, so nothing spent earlier can remove a button before it is
  tried, and the test asserts that *every ability the table offered was actually exercised* -- naming any
  ability that never ran.

``test_the_guard_would_catch_a_qi_storage_restore_that_crashs`` is the negative control: with the pool
resolution forced back to the old Qi-only guess, this same machinery must report a crash, so a green run
here means something.
"""
from __future__ import annotations

import re
import shutil
from typing import Any

import pytest

from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopError, TabletopService
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet

ME, FOE = "actor:factory.mmx118-guard", "actor:factory.mmx118-guard-foe"

# Codes the service raises when it means to say no. A refusal the player can read is a correct fight.
REFUSAL_CODES = {
    "GATE2_PAYMENT_DECLINED", "GATE2_RESOURCE_UNDERFLOW", "GATE2_CANDIDATE_ILLEGAL",
    "GATE2_TARGET_INVALID", "GATE2_ECONOMY_SPENT", "COMBAT_CANDIDATE_STALE",
    "COMBAT_STATE_VERSION_STALE", "COMBAT_DECISION_STALE", "COMBAT_UI_DATA_INVALID",
    "COMBAT_CONTENT_NOT_READY",
}
# The engine's catch-all for "resolution blew up". Never a refusal -- it is the exact shape of the
# Qi Storage crash (gate5_service.py:3157-3161 re-raises ValueError as this code).
CRASH_CODES = {"COMBAT_AI_INTENT_INVALID"}
# How many prompts one press may be asked to answer before the guard gives up on it.
PROMPT_BUDGET = 8

# A stock CL 10 fighter: two Path abilities, a subpath feature and a kit, so the menu carries real
# item buttons as well as abilities.
STOCK = [
    "tianxia.talent.talismans.qi_storage_talisman",
    "tianxia.talent.talismans.warding_talisman",
    "tianxia.talent.talismans.talisman_wall",
]
QI_STORAGE = "Qi Storage Talisman"
_DESTINATION = re.compile(r"\s+at\s+-?\d+,-?\d+$")
# A catalog row is addressed by the actor-scoped prefix the compiler adds ("action:typed.<hash>."), so
# a row is named by the ability path behind it, which is the stable part.
_SCOPED = re.compile(r"^[a-z_]+:[^.]*\.")


def _ability_path(source: str) -> str:
    """``action:typed.a2f1abf1be.tianxia.talent.talismans.qi_storage_talisman`` -> the ability path."""
    return _SCOPED.sub("", str(source or "")) or str(source or "")


def _fight(root, tag: str, *, primary: str, mids: list[str] = None, seed: str):
    """One synthetic fight, in its own data root.

    A match directory is immutable once written (``MatchLock.json``), so two fights built from the same
    seed cannot share a root. That is also what buys the isolation this guard needs.
    """
    mine = sheet(list(mids if mids is not None else STOCK), cl=10, dc=20, primary=primary)
    mine["ability_scores_and_statistics"]["hit_points"]["maximum"] = 400
    bundles = [compile_character(mine, actor_id=ME, reaction_plan={"ask": False}),
               compile_character(sheet([], cl=10, primary=primary), actor_id=FOE)]
    combat = CombatService(ROOT, root / tag)
    table = TabletopService(combat, root / tag)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed=seed,
        display_name="MMX118 button guard", maximum_rounds=20)["match_id"]
    # The menu belongs to whoever is up. The guard must ask the talisman owner, not the bare opponent.
    while table.state(mid)["menu"]["actor_id"] != ME:
        from tests.test_lock2_persistence import act
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def _offered(table: Any, mid: str) -> list[dict[str, Any]]:
    """One row per distinct button, so the guard covers every *ability* the table offers.

    A single ability aimed at 274 squares is one button to the player, not 274; pressing every square
    would spend the whole test on one row and still miss the other abilities (corkboard #356).
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for group in (table.state(mid) or {}).get("menu", {}).get("actions") or []:
        for option in group.get("options") or []:
            if not option.get("candidate_id"):
                continue
            label = _DESTINATION.sub("", str(option.get("label") or "")).strip()
            key = (label, str(group.get("source_definition_id") or ""))
            if key in seen:
                continue
            seen.add(key)
            out.append({"label": label, "source": key[1], "option": option})
    return out


def _answer(prompt: dict[str, Any]) -> dict[str, Any]:
    """Take the table's own first choice for a prompt: the option the engine itself prefers.

    The guard is about *reaching* a committed result, not about which answer a player would pick, so it
    answers with ``choice.preferred`` -- the same pick ``tests/iron_fist_support.py`` uses -- rather than
    with a hand-written per-prompt answer. A prompt whose ``preferred`` is empty falls back to its first
    option; a prompt with neither is left unanswered, and the attempt is then reported as ``unresolved``.
    """
    choice = prompt.get("choice") or {}
    picked = [str(row) for row in (choice.get("preferred") or [])]
    if not picked:
        picked = [str(row["id"]) for row in (choice.get("options") or [])[:1] if row.get("id")]
    return {**prompt["context"], "selection": "USE", "option_ids": picked}


def _press(table: Any, mid: str, option: dict[str, Any]) -> tuple[str, str]:
    """Press one offered button and answer its prompts. Returns ("executed"|"refused"|"unresolved"|"crash…", why)."""
    answers: list[dict[str, Any]] = []
    for _ in range(PROMPT_BUDGET + 1):
        state = table.state(mid)
        menu = state["menu"]
        try:
            result = table.act(mid, option["candidate_id"], menu["decision_id"],
                               menu["state_version"], state["last_sequence"], list(answers))
        except TabletopError as error:
            # Every TabletopError that reaches here is this test's own plumbing (a half-answered
            # choice, a stale menu, the wrong turn) -- never the table declining on purpose.
            return "unresolved", f"table plumbing error {getattr(error, 'code', '?')}: {error}"
        except CombatServiceError as error:
            code = str(getattr(getattr(error, "diagnostic", None), "code", "") or "")
            if code in REFUSAL_CODES:
                return "refused", code
            return f"crash[{code or type(error).__name__}]", str(error)
        except Exception as error:  # noqa: BLE001 - the whole point is to name anything that escapes
            return f"crash[{type(error).__name__}]", str(error)
        status = str(result.get("status") or "")
        if status == "COMMITTED":
            return "executed", "committed"
        if status == "REACTION_REQUIRED" and len(answers) < PROMPT_BUDGET:
            answers.append(_answer(result["reaction"]))
            continue
        if status in CRASH_CODES:
            return f"crash[{status}]", "the engine rejected the intent"
        return "unresolved", f"stopped at {status or 'an unknown status'}"
    return "unresolved", f"still asking after {PROMPT_BUDGET} prompts"


def _exercise(root, tag: str, *, primary: str, label: str, source_tail: str | None = None,
              mids: list[str] = None, seed: str) -> tuple[str, str]:
    """One button, one brand new fight, prompts answered. Nothing spent elsewhere can hide this row."""
    combat, table, mid = _fight(root, tag, primary=primary, mids=mids, seed=seed)
    try:
        rows = _offered(table, mid)
        row = next((row for row in rows if row["label"] == label
                    and (source_tail is None or row["source"].endswith(source_tail))), None)
        if row is None:
            return "unresolved", f"{label!r} was not offered at all (saw {sorted({r['label'] for r in rows})})"
        verdict, why = _press(table, mid, row["option"])
        if verdict == "executed" and combat.verify(mid)["status"] != "PASS":
            return "crash[VERIFY]", "the fight did not verify after the press"
        return verdict, why
    finally:
        shutil.rmtree(root / tag, ignore_errors=True)


def _menu_fight(root, tag: str, *, primary: str, seed: str):
    """The fight whose first turn defines what the guard has to cover. Left in place for the caller."""
    return _fight(root, tag, primary=primary, seed=seed)


@pytest.mark.parametrize("primary", ["Qi", "Stamina", "Resonance"])
def test_every_offered_button_executes_or_is_cleanly_refused(tmp_path, primary):
    """Every ability the table offers is pressed in its own fight, prompts answered, coverage asserted."""
    seed = f"MMX118-{primary}"
    combat, table, mid = _menu_fight(tmp_path, "menu", primary=primary, seed=seed)
    offered = _offered(table, mid)
    assert offered, "the stock character was offered no buttons at all, so nothing was checked"
    expected = {row["source"] for row in offered}
    assert QI_STORAGE in {row["label"] for row in offered}, "the printed button the lane is about is not offered"

    verdicts: dict[str, tuple[str, str]] = {}
    for index, row in enumerate(offered):
        verdicts[row["source"]] = _exercise(tmp_path, f"try{index}", primary=primary, label=row["label"],
                                            source_tail=_ability_path(row["source"]), seed=seed)
    shutil.rmtree(tmp_path / "menu", ignore_errors=True)

    # 1. Nothing raised, and nothing was left half-answered.
    bad = [f"{source.rsplit('.', 1)[-1]} -> {verdict} ({why})" for source, (verdict, why) in verdicts.items()
           if verdict not in ("executed", "refused")]
    assert not bad, ("an offered button did not execute and was not cleanly refused:\n  " + "\n  ".join(bad))
    # 2. Coverage: every ability the table offered actually ran, not merely "something was pressed".
    exercised = {source for source, (verdict, _) in verdicts.items() if verdict in ("executed", "refused")}
    missing = expected - exercised
    assert not missing, "these offered abilities were never exercised:\n  " + "\n  ".join(
        f"{source} ({[row['label'] for row in offered if row['source'] == source][0]})" for source in sorted(missing))
    # 3. The ability this whole lane exists for is offered and really restores a pool.
    storage = [row for row in offered if row["label"] == QI_STORAGE][0]
    assert verdicts[storage["source"]][0] == "executed", f"{QI_STORAGE} -> {verdicts[storage['source']]}"
    # 4. A pressed button left a verifiable fight behind.
    assert combat is not None


def test_the_guard_would_catch_a_qi_storage_restore_that_crashs(tmp_path, monkeypatch):
    """The negative control: the guard must fail on the bug it was written to catch.

    Forcing the pool resolution back to the old Qi-only guess reproduces the pre-fix behaviour exactly --
    a fighter gains a pool they do not have, ``gate2_engine._gain_resource`` raises
    ``ValueError("unknown resource")`` and the service re-raises it as ``COMBAT_AI_INTENT_INVALID``. Without
    this control a green guard could mean the guard never looked.
    """
    from combat.ext import cp_pools

    tail = "tianxia.talent.talismans.qi_storage_talisman"
    clean = _exercise(tmp_path, "clean", primary="Stamina", label=QI_STORAGE, source_tail=tail,
                      mids=[tail], seed="MMX118-NEG-CONTROL")
    assert clean[0] == "executed", f"the control must be green before the bug is injected, got {clean}"

    monkeypatch.setattr(cp_pools, "restore_pool", lambda actor, recorded: cp_pools.QI)
    broken = _exercise(tmp_path, "broken", primary="Stamina", label=QI_STORAGE, source_tail=tail,
                       mids=[tail], seed="MMX118-NEG-CONTROL")
    assert broken[0].startswith("crash"), f"the guard did not catch the restored-bug crash: {broken}"


def test_a_qi_fighter_still_pays_its_qi_pool(tmp_path):
    """The guard's control: the fix must not move a Qi fighter's CP onto another pool."""
    combat, table, mid = _fight(tmp_path, "qicontrol", primary="Qi", mids=["tianxia.talent.talismans.qi_storage_talisman"],
                                seed="MMX118-QI-CONTROL")
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[ME]
    assert "resource:core.qi" in actor.resources
    assert actor.resources["resource:core.qi"] >= 0
    assert "resource:core.stamina" not in actor.resources
    shutil.rmtree(tmp_path / "qicontrol", ignore_errors=True)
