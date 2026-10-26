"""The opening of a fight (who rolled initiative, round 1, the first turn) reaches the table's log.

Hunt 73 finding 1 / MMX24: the genesis block -- the match record, the initiative rolls, the first
round and the first turn -- is written once into ``GenesisState.json`` and never into the journal, and
the log streamed the genesis only for a continued fight. A brand new fight therefore answered
``GET /events?after=0`` with nothing at all while ``CombatService.replay()`` held the whole opening,
so the player's log opened at the first commit and the fight appeared to begin mid-way.
"""
import json
import re
import zipfile

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import Settings
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop import HIDDEN_LOG_EVENT_TYPES
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_auto_docket import DARK, QI, _sheet
from tests.test_carry import KIT

ME, ALLY, FOE, EAST = ["actor:factory.mmx24" + n for n in ("you", "ally", "foe", "east")]
NAMES = {ME: "River Warden", ALLY: "Guarding Friend", FOE: "Visiting Fighter", EAST: "Eastward Rogue"}


def opening_fight(tmp_path):
    """A brand new 2v2 on a real table, before anything has been committed to it."""
    ids = [ME, ALLY, FOE, EAST]
    bundles = []
    for aid in ids:
        document = sheet(["TAL_WATER_COURT_OF_THE_ENDLESS_TIDE"], cl=20, kit={"starting_kit": KIT})
        document["identity"]["display_name"] = NAMES[aid]
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 200
        document["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
        bundles.append(compile_character(document, actor_id=aid, reaction_plan={"ask": aid == ME}))
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids,
        {ME: "team:factory", ALLY: "team:factory", FOE: "team:opponents", EAST: "team:opponents"},
        {ME: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 6}, EAST: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME, ALLY], [FOE, EAST],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed="MMX24-OPENING",
        display_name="MMX24 opening log regression", maximum_rounds=6)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def test_events_after_zero_shows_the_opening_of_a_new_fight(tmp_path):
    combat, table, mid = opening_fight(tmp_path)

    # Before anything is committed the log used to be empty: the whole opening lives in the genesis.
    assert not (table._match_dir(mid) / "Journal.ndjson").is_file() or not [
        line for line in (table._match_dir(mid) / "Journal.ndjson").read_text(encoding="utf-8").splitlines() if line.strip()]

    served = table.events(mid, 0)
    rows = served["events"]
    assert rows, "a brand new fight must show its opening, not an empty log"

    # Every fighter rolled, round 1 began and the first turn started.
    rolled = [row for row in rows if row["event_type"] == "INITIATIVE_ROLLED"]
    assert len(rolled) == 4
    assert {row["summary"].split(" rolled initiative")[0] for row in rolled} == set(NAMES.values())
    assert [row["event_type"] for row in rows if row["event_type"] in ("ROUND_STARTED", "TURN_STARTED")] == [
        "ROUND_STARTED", "TURN_STARTED"]
    assert "Round 1 started." in [row["summary"] for row in rows]
    assert any(row["summary"].startswith("Turn started: ") for row in rows)

    # The opening reads as plain sentences a player who knows only basic D&D can follow: the fighters'
    # own names, no internal ids, no record names, no engine jargon.
    for row in rows:
        assert not re.search(r"actor:factory|condition:typed|action:[a-z]|MATCH_CREATED|INITIATIVE_ROLLED", row["summary"])
    for row in rolled:
        assert re.fullmatch(rf"{re.escape(NAMES[[aid for aid in NAMES if NAMES[aid] == row['summary'].split(' rolled')[0]][0]])}"
                            r" rolled initiative: .+\.", row["summary"])

    # The fight's own bookkeeping stays out of the log. What a fighter paid, and what the GM still
    # has to apply by hand, are not bookkeeping: the table shows both, so the opening keeps them too.
    assert HIDDEN_LOG_EVENT_TYPES == {"REACTION_WINDOW_OPENED", "INTENT_ACCEPTED", "TURN_ENDED", "MATCH_CREATED"}
    assert not {"RESOURCE_SPENT", "GM_RIDER"} & HIDDEN_LOG_EVENT_TYPES
    assert not [row for row in rows if row["event_type"] in HIDDEN_LOG_EVENT_TYPES]
    # ...while the record itself is untouched: the replay still holds every event, bookkeeping included.
    replayed = {event["event_type"] for event in combat.replay(mid)["events"]}
    assert "MATCH_CREATED" in replayed and "INITIATIVE_ROLLED" in replayed

    # The cursor covers the opening, so the next poll neither repeats it nor skips past it.
    sequences = [row["event_sequence"] for row in rows]
    assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)
    assert served["last_sequence"] >= max(sequences)
    assert served["last_sequence"] == max(event["sequence"] for event in combat.replay(mid)["events"])
    assert table.events(mid, served["last_sequence"])["events"] == []


def test_the_opening_survives_a_reload_and_keeps_its_cursor_after_a_commit(tmp_path):
    combat, table, mid = opening_fight(tmp_path)
    before = table.events(mid, 0)

    # A fresh service pair reads the same fight from disk and still opens on the same log.
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert fresh.events(mid, 0) == before

    # After the first turn the feed is the opening followed by the turn, with nothing repeated.
    after_sequence = before["last_sequence"]
    view = table.state(mid)
    committed = table.act(mid, view["menu"]["end_turn"], view["menu"]["decision_id"], view["menu"]["state_version"],
                         view["last_sequence"])
    assert committed["status"] == "COMMITTED"
    tail = fresh.events(mid, after_sequence)["events"]
    assert tail
    assert all(row["event_sequence"] > after_sequence for row in tail)
    whole = fresh.events(mid, 0)["events"]
    sequences = [row["event_sequence"] for row in whole]
    assert sequences == sorted(sequences), "the feed must stay in order once the journal joins the opening"
    assert len(set(sequences)) == len(sequences), "the opening must not be re-sent once the journal streams"
    assert sequences[: len(before["events"])] == [row["event_sequence"] for row in before["events"]]


# ----------------------------------------------------------------- pre-fight casts
NIGHT_SIGHT = "tianxia.talent.stars.night_sight_meridian"  # 1 Qi, an hour, no Concentration
KARMIC_SIGHT = "tianxia.talent.karma.karmic_sight"  # 1 Qi, Concentration, ten minutes
BUFF_TALENTS = [*DARK, "TAL_DARK_DARKVISION", "TAL_DARK_CLEARSIGHT", NIGHT_SIGHT, KARMIC_SIGHT]
BUFF_SPHERES = ["tianxia.sphere.dark", "tianxia.sphere.stars", "tianxia.sphere.karma"]


def _pick(bundle, name):
    return next(option["action_id"] for option in bundle["prefight"]["options"] if option["name"] == name)


def prefight_fight(data_dir, preflight):
    """A new fight whose fighters cast buffs before it begins: ``preflight(me, foe)`` sets each side's picks.

    ``preflight`` is handed the two compiled bundles, so a test can also make a cast impossible.
    """
    bundles = []
    for aid in (ME, FOE):
        document = _sheet(BUFF_TALENTS, spheres=BUFF_SPHERES)
        document["identity"]["display_name"] = NAMES[aid]
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 200
        document["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
        bundles.append(compile_character(document, actor_id=aid, reaction_plan={"ask": aid == ME}))
    preflight(bundles[0], bundles[1])
    combat = CombatService(ROOT, data_dir)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "SUGGESTED"}, match_seed="MMX24-PREFLIGHT",
        display_name="MMX24 pre-fight opening regression", maximum_rounds=6)["match_id"]
    return combat, TabletopService(combat, data_dir), mid


def cast_both_before_the_fight(me, foe):
    """Both fighters cast the two buffs they can pay for."""
    for bundle in (me, foe):
        bundle["prefight"] = {**bundle["prefight"], "picks": [_pick(bundle, "Night-Sight Meridian"),
                                                              _pick(bundle, "Karmic Sight")], "chosen": True}


def cast_one_the_second_cannot_pay(me, foe):
    """The first fighter casts as normal; the second's saved picks no longer match its starting pool."""
    cast_both_before_the_fight(me, foe)
    foe["actor_template"]["resources"] = [
        {**row, "initial": 0} if row["resource_id"] == QI else row
        for row in foe["actor_template"]["resources"]
    ]


def test_a_buff_cast_before_the_fight_still_says_what_it_cost_and_whether_it_worked(tmp_path):
    combat, table, mid = prefight_fight(tmp_path, cast_one_the_second_cannot_pay)

    # The opening is the only place these events are written: no turn has been committed yet.
    genesis = json.loads((table._match_dir(mid) / "GenesisState.json").read_text(encoding="utf-8"))
    assert "MATCH_CREATED" in [event["event_type"] for event in genesis["initial_events"]], \
        "the record is written once, into the opening; the log is what leaves it out"
    assert [event["event_type"] for event in genesis["initial_events"]].count("RESOURCE_SPENT") == 2
    assert [event["event_type"] for event in genesis["initial_events"]].count("GM_RIDER") == 2
    rows = table.events(mid, 0)["events"]
    spent = [row for row in rows if row["event_type"] == "RESOURCE_SPENT"]
    assert [row["summary"] for row in spent] == [
        f"{NAMES[ME]} spent 1 Qi for Prefight; 99 remained.",
        f"{NAMES[ME]} spent 1 Qi for Prefight; 98 remained.",
    ], "a cast announced before the fight has to say what it cost and what is left"

    # The buff that would not take effect says so, for the fighter it concerns, in the same feed and
    # in order right behind the cast that announced it.
    warned = [row for row in rows if row["event_type"] == "GM_RIDER"]
    assert [row["summary"] for row in warned] == [
        f"{NAMES[ME]}'s Night-Sight Meridian on {NAMES[ME]}: additional effect reminder. "
        "Resolve only effects that the recorded outcomes have not already applied. "
        "Rule reminder: Advantage on checks made to identify constellations, "
        "celestial distortions, Star Anchors, or astral signs.",
        f"{NAMES[FOE]}'s Prefight on {NAMES[FOE]}: additional effect reminder. "
        "Resolve only effects that the recorded outcomes have not already applied. "
        "Rule reminder: A buff cast before the fight did not take effect.",
    ]
    assert all("Resolve only effects that the recorded outcomes have not already applied." in row["summary"]
               for row in warned)
    failed = [event for event in genesis["initial_events"] if event.get("payload", {}).get("error_type")]
    assert len(failed) == 1 and failed[0]["payload"]["error_type"] == "CombatGate1Error"
    assert all("CombatGate1Error" not in row["summary"] for row in rows)

    # Both sit between the fighter's cast announcement and the fight's own bookkeeping, which is still
    # left out, and every line reads plainly for someone who knows only basic D&D.
    assert [row["event_type"] for row in rows if row["event_type"] in
            ("PASSIVE_TRIGGERED", "RESOURCE_SPENT", "GM_RIDER", "MATCH_CREATED")][:3] == [
        "PASSIVE_TRIGGERED", "RESOURCE_SPENT", "GM_RIDER"]
    assert not [row for row in rows if row["event_type"] in HIDDEN_LOG_EVENT_TYPES]
    for row in rows:
        assert not re.search(r"actor:factory|condition:typed|action:[a-z]|system:[a-z]|MATCH_CREATED"
                             r"|INITIATIVE_ROLLED|GM_RIDER|RESOURCE_SPENT", row["summary"])

    # The record itself is untouched: the replay still holds every event, bookkeeping included.
    replayed = {event["event_type"] for event in combat.replay(mid)["events"]}
    assert {"MATCH_CREATED", "RESOURCE_SPENT", "GM_RIDER"} <= replayed


def test_the_opening_and_its_cursor_are_served_over_http(tmp_path):
    """The player's route, not the service: GET .../events?after=0 and after=N, on a persisted new fight."""
    combat, table, mid = opening_fight(tmp_path)
    before = table.events(mid, 0)  # the fight on disk is the same one the app will serve

    settings = Settings.from_env(ROOT, tmp_path)
    with TestClient(create_app(settings)) as client:
        headers = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
        served = client.get(f"/api/tabletop/matches/{mid}/events", params={"after": 0}, headers=headers)
        assert served.status_code == 200, served.text
        body = served.json()
        assert [row["summary"] for row in body["events"]] == [row["summary"] for row in before["events"]], \
            "the route must serve the fight's opening, not an empty log"
        assert [row["event_sequence"] for row in body["events"]] == [row["event_sequence"] for row in before["events"]]

        # The opening reads as the fight starting, and the fight's own bookkeeping never reaches the player.
        assert any("rolled initiative" in row["summary"] for row in body["events"])
        assert "Round 1 started." in [row["summary"] for row in body["events"]]
        assert not [row for row in body["events"] if row["event_type"] in HIDDEN_LOG_EVENT_TYPES]
        assert body["dice"], "the initiative dice the opening records must reach the table"
        sequences = [row["event_sequence"] for row in body["events"]]
        assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)

        # A cursor from inside the opening is exclusive: the row it names is not re-sent, and the ones
        # before it are not either.
        middle = sequences[len(sequences) // 2]
        tail_of_opening = client.get(f"/api/tabletop/matches/{mid}/events", params={"after": middle}, headers=headers).json()
        assert tail_of_opening["events"], "an opening cursor inside the block must still return the rest of it"
        assert [row["event_sequence"] for row in tail_of_opening["events"]] == \
            [sequence for sequence in sequences if sequence > middle]

        # Polling with the cursor the route returned yields nothing, and does not rewind it.
        after_cursor = client.get(f"/api/tabletop/matches/{mid}/events",
                                  params={"after": body["last_sequence"]}, headers=headers).json()
        assert after_cursor["events"] == []
        assert after_cursor["last_sequence"] == body["last_sequence"]

        # After a committed turn the tail arrives on the same cursor, and the opening is not re-sent.
        view = client.get(f"/api/tabletop/matches/{mid}/state", headers=headers).json()
        menu = view["menu"]
        committed = client.post(f"/api/tabletop/matches/{mid}/act", headers=headers, json={
            "candidate_id": menu["end_turn"], "decision_id": menu["decision_id"],
            "state_version": menu["state_version"], "after": body["last_sequence"], "reactions": []})
        assert committed.status_code == 200, committed.text
        assert committed.json()["status"] == "COMMITTED"

        tail = client.get(f"/api/tabletop/matches/{mid}/events",
                          params={"after": body["last_sequence"]}, headers=headers).json()
        assert tail["events"], "the committed turn must reach the log"
        assert all(row["event_sequence"] > body["last_sequence"] for row in tail["events"])
        whole = client.get(f"/api/tabletop/matches/{mid}/events", params={"after": 0}, headers=headers).json()
        assert [row["event_sequence"] for row in whole["events"][: len(sequences)]] == sequences
        assert len({row["event_sequence"] for row in whole["events"]}) == len(whole["events"])
