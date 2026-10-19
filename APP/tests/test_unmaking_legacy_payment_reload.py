"""The saved-fight regressions the AUTO84r2 and AUTO84r3 reviews asked for, on a save the old code really wrote.

Checklist 7 asks that anything stored in fight state survives a table commit and a reload. An earlier lane's
test said "commit and reload" but only JSON-round-tripped one actor and put it back into the same engine,
which cannot see a journal or a recovery failure. The next round used the real table, but installed the
pre-change condition shape in memory on a fight it had already reloaded, so the legacy second payment never
crossed persistence -- and the module's own docstring then claimed two committed payments with a reload
between them, which no test did.

So the legacy shape is not installed by a test at all. It lives in
``tests/fixtures/auto84_legacy_price_save``: a whole table, committed by the real service, written by the
version of ``combat/ext/maximum_hp_riders.max_hp_loss`` from before the running total existed
(``87d57c26``; see that directory's README.md). Each test copies it, so the fight it opens is a legacy save
in the only sense that matters -- one the old code wrote and the journal still replays -- and not a modern
save with its condition edited.

The price is the Fifth Ruin Form upkeep, "reduce your current and maximum HP by 10 until you finish a Long
Rest". It is offered again at the end of every one of its user's turns, so the same key can be paid a second
time on the reload through a real ``TabletopService.act`` (as a menu button, or as an answer to the price
the form asks mid-action -- whichever the table routes it to).

What the legacy shape must survive: the stored ``amount`` is everything paid so far, with no running total and
that payment already taken off the maximum. Reading only the total restores the earlier reduction instead of
stacking onto it, so two 10s on a base of 250 would leave the maximum at 240, not 230.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from combat.ext.maximum_hp_riders import LOST
from combat.factory_compiler import compile_character
from combat.gate3_reducer import canonical_state_document
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

FIXTURE = Path(__file__).with_name("fixtures") / "auto84_legacy_price_save"
OWNER, ALLY, FOE = [FACTORY_ACTOR_PREFIX + "auto84r3f1-" + name for name in ("owner", "ally", "foe")]
MATCH_ID = json.loads(next((FIXTURE / "Combat" / "Matches").glob("m1_*/Manifest.json")).read_text())["match_id"]
FORM = "TAL_UNMAKING_FIFTH_RUIN_FORM_DOMAIN_OF_COLLAPSE"
WITH_STRAIN = ("TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_LAST_INCH_CONTROL")
FORM_NAME = "Fifth Ruin Form: Domain of Collapse"
PRICE = "Lose 10 of your current and maximum Hit Points"
BASE_MAXIMUM, BASE_CURRENT = 250, 250


def legacy_save(tmp_path):
    """A writable copy of the committed legacy fixture. Copied so the test can commit to it."""
    root = tmp_path / "legacy_save"
    shutil.copytree(FIXTURE, root)
    for lock in root.rglob(".*.lock"):                 # transient writer locks, not part of the save
        lock.unlink()
    # Inspection locks an existing writer-lock file without changing its bytes.
    # Recreate that empty transport file on the disposable copy, never the fixture.
    for match in (root / "Combat" / "Matches").glob("m1_*"):
        (match / ".writer.lock").touch()
    return root


def held_price(owner):
    return next(condition for condition in owner.conditions.values()
                if condition.condition_id.startswith(LOST))


def continued_legacy_save(tmp_path):
    """Rebind a copied legacy save through the public compatibility API.

    P15 changed the policy bundle. Preserve every byte of the old match while
    testing the legacy payment shape in the continuation the service creates.
    """
    import hashlib

    root = legacy_save(tmp_path)
    service = CombatService(ROOT, root)
    original = service._match_dir(MATCH_ID)
    inventory = lambda: {p.relative_to(original).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in original.rglob('*') if p.is_file() and not p.name.endswith('.lock')}
    before = inventory()
    report = service.saved_fight_compatibility(MATCH_ID)
    result = service.continue_saved_fight(MATCH_ID, token=report['token'], mode=report['mode'])
    assert result['original_preserved'] and inventory() == before
    return root, result['match_id']


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


def test_the_legacy_save_reloads_and_replays_under_this_code(tmp_path):
    """The fixture is a real save, so a service that only reads what the table wrote has to recover it whole."""
    root, match_id = continued_legacy_save(tmp_path)
    session = CombatService(ROOT, root)._load_session(match_id)
    assert session.mechanical.replay()["state"] == canonical_state_document(session.engine.state), \
        "the legacy journal still replays to the saved state under this code"
    owner = session.engine.state.actors[OWNER]
    held = held_price(owner)
    assert "lost" not in held.data and int(held.data["amount"]) == 10, \
        f"and it really is the old shape -- everything paid so far, stored as amount: {held.data}"
    assert (owner.maximum_hp, owner.current_hp) == (BASE_MAXIMUM - 10, BASE_CURRENT - 10), \
        "with that one payment already off the maximum and off current"


def test_paying_the_price_again_on_the_legacy_save_commits_stacks_and_survives_another_reload(tmp_path):
    """The regression the AUTO84r3 review asked to be real: a legacy payment, then a payment committed at the table,
    then a fresh service reading only the journal."""
    root, match_id = continued_legacy_save(tmp_path)
    opening = CombatService(ROOT, root)._load_session(match_id)
    assert opening.mechanical.replay()["state"] == canonical_state_document(opening.engine.state), \
        "the legacy save this starts from is one the journal still replays to"
    answer = pay_once(TabletopService(CombatService(ROOT, root), root), match_id)
    assert answer["status"] == "COMMITTED", answer                         # a committed table action, not an in-memory call

    fresh = CombatService(ROOT, root)                                      # reads only what the table wrote
    session = fresh._load_session(match_id)
    assert session.mechanical.replay()["state"] == canonical_state_document(session.engine.state), \
        "and the journal it wrote replays to the state it saved"
    owner = session.engine.state.actors[OWNER]
    held = held_price(owner)
    assert owner.maximum_hp == BASE_MAXIMUM - 20, \
        f"the legacy payment is still on the maximum, not restored (got {owner.maximum_hp}, wanted {BASE_MAXIMUM - 20})"
    assert owner.current_hp == BASE_CURRENT - 20, "and both payments came out of current Hit Points, ten each"
    assert int(held.data["lost"]) == 20 and int(held.data["amount"]) == 10, \
        f"integers and strings only, so a save keeps them: {held.data}"
    assert isinstance(held.data["lost"], int) and isinstance(held.data["amount"], int) \
        and isinstance(held.data["label"], str), "no floats and no objects survive a reload"


def test_two_prices_committed_at_the_table_across_a_reload_stack_the_same_way(tmp_path):
    """The same check on a save of today's own making, so the legacy fixture above is not the only thing holding it up."""
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
