"""Maximum-HP upkeep payments stack across real table commits and cold reload.

The retained regression pays Fifth Ruin Form upkeep twice through the table,
with a fresh service between payments. Historical engine continuation and
legacy-save replay are no longer requirements; current gameplay persistence is.
"""

from __future__ import annotations

import json
import zipfile

from combat.ext.maximum_hp_riders import LOST
from combat.factory_compiler import compile_character
from combat.gate3_reducer import canonical_state_document
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER, ALLY, FOE = [FACTORY_ACTOR_PREFIX + "auto84r3f1-" + name for name in ("owner", "ally", "foe")]
FORM = "TAL_UNMAKING_FIFTH_RUIN_FORM_DOMAIN_OF_COLLAPSE"
WITH_STRAIN = ("TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_LAST_INCH_CONTROL")
FORM_NAME = "Fifth Ruin Form: Domain of Collapse"
PRICE = "Lose 10 of your current and maximum Hit Points"
BASE_MAXIMUM, BASE_CURRENT = 250, 250


def held_price(owner):
    return next(condition for condition in owner.conditions.values()
                if condition.condition_id.startswith(LOST))


def price_option(prompt):
    """The id of the printed upkeep price in a question the table asked, or None when it asked something else."""
    return next((row["id"] for row in (prompt.get("choice") or {}).get("options") or []
                 if str(row.get("label") or "").startswith(PRICE)), None)


def pay_once(table_service, match_id):
    """Press the printed upkeep price the next time the table routes it to us, and return that committed answer.

    The price reaches the table either as its own menu button or as a question asked part-way through the turn that
    ends the form's upkeep; both are real ``TabletopService.act`` calls and both commit through the journal. Choosing
    it can raise one more question of its own before the turn commits, so the answer that counts is the first
    COMMITTED one after the price has been chosen -- not the answer that carried the click.
    """
    form_taken, paid, answer = False, False, None
    for _ in range(200):
        state = table_service.state(match_id)
        pending = state.get("pending_action")
        if pending:                                     # a question is outstanding; nothing else can be asked until it is
            prompt, request = pending.get("reaction") or {}, pending["request"]
            option = None if paid else price_option(prompt)      # one press buys one payment, not two
            paid = paid or option is not None
            reply = {**prompt["context"], "selection": "USE", "option_ids": [option]} if option is not None \
                else {**prompt["context"], "selection": "DECLINE"}
            # the table keeps every answer given for one pending action and insists they arrive in order
            answer = table_service.act(match_id, request["candidate_id"], request["decision_id"],
                                       request["state_version"], request["after"],
                                       reactions=[*(pending.get("reactions") or []), reply])
            if paid and answer["status"] == "COMMITTED":
                return answer
            continue
        menu = state.get("menu")
        if not menu:                                   # nobody is deciding yet; poll the table again
            continue
        if menu["actor_id"] == OWNER:
            taking = next((row["candidate_id"] for group in menu.get("actions") or [] for row in group.get("options") or []
                           if row.get("label") == FORM_NAME), None)
            if taking is not None and not form_taken:
                form_taken = True
                table_service.act(match_id, taking, menu["decision_id"], menu["state_version"], state["last_sequence"])
                continue                                # re-read; activating the form is what puts the price up
            for group in menu.get("actions") or [] if not paid else ():
                for row in group.get("options") or []:
                    if str(row.get("label") or "").startswith(PRICE):   # one press buys one payment, not two
                        paid = True
                        answer = table_service.act(match_id, row["candidate_id"], menu["decision_id"],
                                                   menu["state_version"], state["last_sequence"])
                        if answer["status"] == "COMMITTED":
                            return answer
        table_service.act(match_id, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    raise AssertionError(f"the printed upkeep price was never offered again (last answer: {str(answer)[:200]})")


def modern_table(tmp_path):
    """A real persisted table of today's own making, for the same check without the legacy save."""
    docs = [sheet([FORM, *WITH_STRAIN], cl=15), sheet([]), sheet([])]
    for doc in docs:
        doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 60
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = BASE_MAXIMUM
    bundles = []
    for actor, doc in zip((OWNER, ALLY, FOE), docs):
        folder = tmp_path / "portable_characters" / actor.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=actor, reaction_plan={"ask": True}))
    combat = CombatService(ROOT, tmp_path)
    match_id = combat._finish_factory_match(
        bundles, [OWNER, ALLY, FOE],
        {OWNER: "team:factory", ALLY: "team:factory", FOE: "team:opponents"},
        {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER, ALLY], [FOE],
        control_modes={actor: "MANUAL" for actor in (OWNER, ALLY, FOE)},
        match_seed="auto84r3f1", display_name="AUTO84r3f1 maximum Hit Point prices", maximum_rounds=12)["match_id"]
    return combat, TabletopService(combat, tmp_path), match_id


def test_two_prices_committed_at_the_table_across_a_reload_stack_the_same_way(tmp_path):
    """Two real upkeep choices stack, with a fresh service and replay after each payment."""
    root = tmp_path / "modern"
    root.mkdir()
    combat, table_service, match_id = modern_table(root)
    first = pay_once(table_service, match_id)
    assert first["status"] == "COMMITTED", first

    fresh = CombatService(ROOT, combat.userdata_root)                      # a fresh service: it reads only what the table wrote
    session = fresh._load_session(match_id)
    assert session.mechanical.replay()["state"] == canonical_state_document(session.engine.state)
    paid_once = held_price(session.engine.state.actors[OWNER])
    assert int(paid_once.data["lost"]) == 10, "the first committed price survived the reload"

    second = pay_once(TabletopService(fresh, combat.userdata_root), match_id)
    assert second["status"] == "COMMITTED", second
    reloaded = CombatService(ROOT, combat.userdata_root)._load_session(match_id)
    assert reloaded.mechanical.replay()["state"] == canonical_state_document(reloaded.engine.state)
    owner = reloaded.engine.state.actors[OWNER]
    assert owner.maximum_hp == BASE_MAXIMUM - 20, "two committed payments of ten, stacked, not twenty or ten"
    assert int(held_price(owner).data["lost"]) == 20
