"""MMX102 regressions (round 24, 42e43e14): player-owned summons, rider damage naming,
and Ask-me prompts that name a creature.

1. A player-owned summoned companion acts per its printed default or the player's command:
   a commanded Bone Guard is offered its printed "Bone Strike" on its own turn, and an
   uncommanded one takes the printed Dodge default. AI-owned summons are untouched.
2. A rider's damage is logged under the rider that dealt it, not the parent ability.
3. An Ask-me prompt names the creature it is about instead of leaving the field blank.
"""
from __future__ import annotations

import json
import zipfile

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.history_feed import format_history_feed
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

BONE = "tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"
OWNER = FACTORY_ACTOR_PREFIX + "mmx102-owner"
FOE = FACTORY_ACTOR_PREFIX + "mmx102-foe"


def _portable(tmp_path, actor_id, doc):
    folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))


def _docs(owner_talents, foe_talents=()):
    docs = [sheet(owner_talents, cl=10, primary="Stamina"),
            sheet(list(foe_talents), cl=10, dc=50, score=14)]
    for actor_id, doc in zip((OWNER, FOE), docs):
        doc["identity"]["display_name"] = actor_id.rsplit("-", 1)[-1].title()
        doc["identity"]["proficiency_bonus"] = 3
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
    return docs


def _fight(tmp_path, control, *, owner_talents=(BONE,), foe_talents=(), gap=2):
    docs = _docs(list(owner_talents), foe_talents)
    for actor_id, doc in zip((OWNER, FOE), docs):
        _portable(tmp_path, actor_id, doc)
    bundles = [compile_character(doc, actor_id=actor_id,
                                 reaction_plan={"ask": True} if actor_id == OWNER else None)
               for actor_id, doc in zip((OWNER, FOE), docs)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    # The owner's companion starts within its own printed 5 ft reach of the foe.
    arena = combat.tabletop_maps.save({"display_name": "MMX102 table", "width_squares": 20,
                                       "height_squares": 12, "walls": [],
                                       "starts": {"team1": [[3, 6]], "team2": [[3 + gap, 6]]}})
    mid = combat._finish_factory_match(
        bundles, [OWNER, FOE], {OWNER: "team:a", FOE: "team:b"},
        {OWNER: {"x": 3, "y": 6}, FOE: {"x": 3 + gap, "y": 6}},
        combat.factory_arenas()["battlefield:map." + arena["map_id"]], [OWNER], [FOE],
        control_modes={OWNER: control, FOE: "LOCAL_AUTO"},
        match_seed="MMX102", display_name="MMX102 regression", maximum_rounds=6)["match_id"]
    return combat, table, mid


def _answer(prompt):
    answer = {**prompt["context"], "selection": "DECLINE"}
    choice = prompt.get("choice")
    if choice and not choice.get("allow_decline"):
        answer.update(selection="USE",
                      option_ids=(choice.get("preferred") or [choice["options"][0]["id"]])[:1])
    return answer


def _commit(table, mid, candidate_id):
    answers = []
    for _ in range(16):
        menu = table.state(mid)["menu"]
        result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, list(answers))
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append(_answer(result["reaction"]))
    raise AssertionError("too many prompts")


def _press(actions, prefix):
    for group in actions or []:
        for option in group.get("options") or []:
            if str(option.get("label") or group.get("label") or "").startswith(prefix):
                return option["candidate_id"]
    return None


def _advance(table, mid):
    """One table step: a human's menu submits end turn, an auto actor's menu is driven."""
    menu = table.state(mid)["menu"]
    if menu.get("manual"):
        return _commit(table, mid, menu["end_turn"])
    result = table.auto_step(mid, 0)
    for _ in range(16):
        if result.get("status") != "REACTION_REQUIRED":
            return result
        result = table.act(mid, None, None, None, 0, [_answer(result["reaction"])])
    return result


def _kinds(table, mid):
    """Event kind names from the table feed, whichever key the projection uses."""
    return {str(e.get("event_type") or e.get("type") or e.get("kind") or "") for e in table.events(mid, 0)["events"]}


def _summaries(table, mid):
    return [str(e.get("summary") or "") for e in table.events(mid, 0)["events"]]


# --------------------------------------------------------------------------- 1. player-owned summons

def test_commanded_player_summon_is_offered_its_printed_attack(tmp_path):
    """Human control: a companion the player commands may use its stat block."""
    combat, table, mid = _fight(tmp_path, "MANUAL")
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        _advance(table, mid)
    menu = table.state(mid)["menu"]
    _commit(table, mid, _press(menu["actions"], "Bone Guard Manifestation"))
    menu = table.state(mid)["menu"]
    _commit(table, mid, _press(menu["actions"], "Command Bone Guard"))
    assert "SUMMONS_COMMANDED" in _kinds(table, mid), "the command must be recorded"

    for _ in range(6):
        menu = table.state(mid).get("menu")
        if menu and "bone_guard" in (menu.get("actor_id") or ""):
            break
        _advance(table, mid)
    else:  # pragma: no cover - defensive
        raise AssertionError("the companion never took its own turn")
    labels = [str(group.get("label")) for group in menu.get("actions") or []]
    assert "Bone Strike" in labels, \
        f"a commanded player companion must be offered its printed attack, got {labels}"


def test_auto_controlled_player_summon_uses_its_printed_attack(tmp_path):
    """Ask-me/auto: the companion acts on its own, and attacks rather than only dodging."""
    combat, table, mid = _fight(tmp_path, "MANUAL")
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        _advance(table, mid)
    menu = table.state(mid)["menu"]
    _commit(table, mid, _press(menu["actions"], "Bone Guard Manifestation"))
    menu = table.state(mid)["menu"]
    _commit(table, mid, _press(menu["actions"], "Command Bone Guard"))

    # A companion inherits its summoner's control mode, so hand the owner to the built-in AI.
    path = combat._metadata_path(mid)
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["participant_control_modes"][OWNER] = "LOCAL_AUTO"
    path.write_text(json.dumps(meta), encoding="utf-8")
    table = TabletopService(combat, tmp_path)

    for _ in range(10):
        if any("Bone Strike" in s for s in _summaries(table, mid)):
            break
        if not table.state(mid).get("menu"):
            break
        _advance(table, mid)
    summaries = _summaries(table, mid)
    assert any("Bone Strike" in s for s in summaries), \
        f"an auto-controlled commanded companion must strike, saw {summaries[-6:]}"


def test_uncommanded_player_summon_takes_its_printed_dodge_default(tmp_path):
    """Printed for every bonus-action summon: "without a command, it takes Dodge"."""
    combat, table, mid = _fight(tmp_path, "MANUAL")
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        _advance(table, mid)
    menu = table.state(mid)["menu"]
    _commit(table, mid, _press(menu["actions"], "Bone Guard Manifestation"))
    # No Command: the companion's own turn must pass by itself with the printed default.
    for _ in range(8):
        if "COMPANION_DEFAULT_APPLIED" in _kinds(table, mid):
            break
        _advance(table, mid)
    kinds, summaries = _kinds(table, mid), _summaries(table, mid)
    assert "COMPANION_DEFAULT_APPLIED" in kinds, "an uncommanded companion takes the printed Dodge default"
    assert "SUMMONS_COMMANDED" not in kinds, "this fight never commands the companion"
    assert any("Dodge" in s for s in summaries), "the default is the printed Dodge action"


# --------------------------------------------------------------------------- 2. rider damage naming

def test_rider_damage_is_logged_under_the_rider_that_dealt_it():
    """The shape from the round-24 playtest: the roll names the rider, the commit named the parent."""
    parent = "talent:thunder.lightning_lash"
    events = [
        {"event_type": "DAMAGE_ROLLED", "source_definition_id": parent, "actor_id": "A",
         "target_ids": ["B"], "payload": {"roll_id": "r1", "expression": "4d8+3", "total": 25}},
        {"event_type": "DAMAGE_COMMITTED", "source_definition_id": parent, "actor_id": "A",
         "target_ids": ["B"], "payload": {"rolled_or_pending_damage": 25, "reduced_to": 25,
                                          "hp_damage": 25, "damage_type": "THUNDER", "remaining_hp": 30}},
        {"event_type": "DAMAGE_ROLLED", "source_definition_id": parent, "actor_id": "A",
         "target_ids": ["B"], "payload": {"roll_id": "r2", "expression": "2d8", "total": 11,
                                          "damage_label": "Crackling Arrow"}},
        {"event_type": "DAMAGE_COMMITTED", "source_definition_id": parent, "actor_id": "A",
         "target_ids": ["B"], "payload": {"rolled_or_pending_damage": 11, "reduced_to": 11,
                                          "hp_damage": 11, "damage_type": "LIGHTNING", "remaining_hp": 0}},
    ]
    rows = format_history_feed(events, [], pre_state=None, post_state={},
                               actor_names={"A": "Xiahou Zhen", "B": "Peng Xilan"},
                               definition_names={parent: "Lightning Lash: Charge + Spark-Instrument Method"})
    committed = [row["summary"] for row in rows if row.get("event_type") == "DAMAGE_COMMITTED"]
    assert committed[0].startswith("Xiahou Zhen — Lightning Lash: Charge + Spark-Instrument Method"), \
        "the ability's own damage keeps the ability's name"
    assert committed[1].startswith("Xiahou Zhen — Crackling Arrow"), \
        f"a rider's damage must be logged under the rider, got {committed[1]}"


def _feed_by_sequence(rows):
    """Feed rows carry the sequence of the event they describe, so a claim about "the rider that
    rolled it" can be checked against the event itself and never against a matching amount."""
    return {row.get("event_sequence"): row for row in rows}


def _dealt_by(summary: str) -> str:
    """The "<actor> — <dealt by> dealt <n> ..." name a commit line reports."""
    return str(summary).split(" — ", 1)[-1].rsplit(" dealt ", 1)[0]


def test_a_consumed_rider_roll_cannot_rename_a_later_ordinary_hit():
    """A rider whose commit already carried its own name must not stay queued for the next hit.

    The review's counterexample: rider roll 7 -> explicitly attributed rider commit 7 -> an
    ordinary bare commit followed by an ordinary roll/commit of the same 7 against the same
    target, all without an action boundary. The bare commit independently detects an unconsumed
    roll; the ordinary packet must also keep the ability's own name.
    """
    parent = "talent:thunder.lightning_lash"
    rider = "passive:TAL_VOID_NULLIFYING_STRIKE"
    events = [
        {"sequence": 1, "event_type": "DAMAGE_ROLLED", "source_definition_id": parent, "actor_id": "A", "target_ids": ["B"],
         "payload": {"roll_id": "r1", "expression": "2d8", "total": 7,
                     "damage_label": "Crackling Arrow", "display_source_id": rider}},
        {"sequence": 2, "event_type": "DAMAGE_COMMITTED", "source_definition_id": parent, "actor_id": "A", "target_ids": ["B"],
         "payload": {"rolled_or_pending_damage": 7, "reduced_to": 7, "hp_damage": 7,
                     "damage_type": "LIGHTNING", "remaining_hp": 40, "display_source_id": rider}},
        # No action boundary and no new roll: consumption must protect this bare commit too.
        {"sequence": 3, "event_type": "DAMAGE_COMMITTED", "source_definition_id": parent, "actor_id": "A", "target_ids": ["B"],
         "payload": {"rolled_or_pending_damage": 7, "hp_damage": 7, "damage_type": "LIGHTNING"}},
        {"sequence": 4, "event_type": "DAMAGE_ROLLED", "source_definition_id": parent, "actor_id": "A", "target_ids": ["B"],
         "payload": {"roll_id": "r2", "expression": "2d8", "total": 7}},
        {"sequence": 5, "event_type": "DAMAGE_COMMITTED", "source_definition_id": parent, "actor_id": "A", "target_ids": ["B"],
         "payload": {"rolled_or_pending_damage": 7, "reduced_to": 7, "hp_damage": 7,
                     "damage_type": "LIGHTNING", "remaining_hp": 33}},
    ]
    rows = _feed_by_sequence(format_history_feed(
        events, [], pre_state=None, post_state={},
        actor_names={"A": "Xiahou Zhen", "B": "Peng Xilan"},
        definition_names={parent: "Lightning Lash: Charge + Spark-Instrument Method",
                          rider: "Nullifying Strike"}))
    for index, event in enumerate(events):
        if event["event_type"] != "DAMAGE_COMMITTED":
            continue
        dealt = _dealt_by(rows[event["sequence"]]["summary"]) if event.get("sequence") in rows else None
        if event["payload"].get("display_source_id"):
            assert dealt == "Nullifying Strike", \
                f"a commit that names its own rider must report that rider, got {dealt!r}"
        else:
            assert dealt == "Lightning Lash: Charge + Spark-Instrument Method", \
                (f"commit {index} is the ability's own damage and must not be renamed by an "
                 f"earlier rider, got {dealt!r}")


def test_a_roll_whose_commit_was_never_recorded_cannot_reach_the_next_action():
    """A roll left uncommitted is dropped at the next action, not held for a same-amount hit."""
    parent = "talent:thunder.lightning_lash"
    rider = "passive:TAL_VOID_NULLIFYING_STRIKE"
    events = [
        {"sequence": 6, "event_type": "DAMAGE_ROLLED", "source_definition_id": parent, "actor_id": "A", "target_ids": ["B"],
         "payload": {"roll_id": "r1", "expression": "2d8", "total": 7,
                     "damage_label": "Crackling Arrow", "display_source_id": rider}},
        # The commit this roll belonged to was never recorded (an older or truncated record).
        {"sequence": 7, "event_type": "INTENT_ACCEPTED", "source_definition_id": "action:other", "actor_id": "A",
         "target_ids": ["B"], "payload": {}},
        {"sequence": 8, "event_type": "ATTACK_DECLARED", "source_definition_id": parent, "actor_id": "A", "target_ids": ["B"],
         "payload": {}},
        {"sequence": 9, "event_type": "DAMAGE_ROLLED", "source_definition_id": parent, "actor_id": "A", "target_ids": ["B"],
         "payload": {"roll_id": "r2", "expression": "2d8", "total": 7}},
        {"sequence": 10, "event_type": "DAMAGE_COMMITTED", "source_definition_id": parent, "actor_id": "A", "target_ids": ["B"],
         "payload": {"rolled_or_pending_damage": 7, "reduced_to": 7, "hp_damage": 7,
                     "damage_type": "LIGHTNING", "remaining_hp": 33}},
    ]
    rows = _feed_by_sequence(format_history_feed(
        events, [], pre_state=None, post_state={},
        actor_names={"A": "Xiahou Zhen", "B": "Peng Xilan"},
        definition_names={parent: "Lightning Lash: Charge + Spark-Instrument Method",
                          rider: "Nullifying Strike"}))
    final = next(row for row in rows.values() if row["event_type"] == "DAMAGE_COMMITTED")
    assert _dealt_by(final["summary"]) == "Lightning Lash: Charge + Spark-Instrument Method", \
        f"an uncommitted roll must not rename this hit, got {_dealt_by(final['summary'])!r}"


def test_halved_rider_packet_is_consumed_before_same_action_damage():
    """Successful-save damage changes 8 to 4, then another source deals 8 without a boundary."""
    events = [
        {"sequence": 1, "event_type": "DAMAGE_ROLLED", "source_definition_id": "action:parent", "actor_id": "A", "target_ids": ["B"],
         "payload": {"expression": "2d8", "total": 8, "damage_label": "Rider", "display_source_id": "passive:rider"}},
        {"sequence": 2, "event_type": "DAMAGE_COMMITTED", "source_definition_id": "action:parent", "actor_id": "A", "target_ids": ["B"],
         "payload": {"rolled_or_pending_damage": 4, "hp_damage": 4, "display_source_id": "passive:rider"}},
        # Same-source bare commit independently proves consumption despite the transformation.
        {"sequence": 3, "event_type": "DAMAGE_COMMITTED", "source_definition_id": "action:parent", "actor_id": "A", "target_ids": ["B"],
         "payload": {"rolled_or_pending_damage": 8, "hp_damage": 8}},
        {"sequence": 4, "event_type": "DAMAGE_ROLLED", "source_definition_id": "action:other", "actor_id": "A", "target_ids": ["B"],
         "payload": {"expression": "2d8", "total": 8}},
        {"sequence": 5, "event_type": "DAMAGE_COMMITTED", "source_definition_id": "action:other", "actor_id": "A", "target_ids": ["B"],
         "payload": {"rolled_or_pending_damage": 8, "hp_damage": 8}},
    ]
    rows = _feed_by_sequence(format_history_feed(events, [], pre_state=None, post_state={},
        actor_names={"A": "Shooter", "B": "Foe"}, definition_names={"action:parent": "Parent", "action:other": "Other", "passive:rider": "Rider"}))
    assert _dealt_by(rows[2]["summary"]) == "Rider"
    assert _dealt_by(rows[3]["summary"]) == "Parent"
    assert _dealt_by(rows[5]["summary"]) == "Other"


def test_damage_attribution_does_not_cross_sources_or_guess_ambiguous_rolls():
    """Equal amounts are not packet identity, including multiple rolls under one source."""
    events = [
        {"sequence": 1, "event_type": "DAMAGE_ROLLED", "source_definition_id": "action:parent", "actor_id": "A", "target_ids": ["B"],
         "payload": {"expression": "2d8", "total": 8, "damage_label": "Rider"}},
        {"sequence": 2, "event_type": "DAMAGE_COMMITTED", "source_definition_id": "action:other", "actor_id": "A", "target_ids": ["B"],
         "payload": {"rolled_or_pending_damage": 8, "hp_damage": 8}},
        {"sequence": 3, "event_type": "DAMAGE_ROLLED", "source_definition_id": "action:parent", "actor_id": "A", "target_ids": ["B"],
         "payload": {"expression": "2d8", "total": 8}},
        {"sequence": 4, "event_type": "DAMAGE_COMMITTED", "source_definition_id": "action:parent", "actor_id": "A", "target_ids": ["B"],
         "payload": {"rolled_or_pending_damage": 8, "hp_damage": 8}},
    ]
    rows = _feed_by_sequence(format_history_feed(events, [], pre_state=None, post_state={},
        actor_names={"A": "Shooter", "B": "Foe"}, definition_names={"action:parent": "Parent", "action:other": "Other"}))
    assert _dealt_by(rows[2]["summary"]) == "Other"
    assert _dealt_by(rows[4]["summary"]) == "Parent"


def _packet_names(events):
    """For each DAMAGE_COMMITTED, the rider names its own damage packet could legitimately use.

    A packet is the damage rolled for one target since the previous commit against that target, so
    names are bound to the event, never to a matching amount elsewhere in the feed.
    """
    seen: dict[tuple, list[str]] = {}
    by_commit = {}
    for event in events:
        key = (event.get("actor_id"), tuple(event.get("target_ids") or ()))
        payload = event.get("payload") or {}
        if event["event_type"] == "DAMAGE_ROLLED":
            seen.setdefault(key, [])
            if payload.get("damage_label"):
                seen[key].append(str(payload["damage_label"]))
        elif event["event_type"] == "DAMAGE_COMMITTED":
            names = list(seen.pop(key, []))
            if payload.get("display_name"):
                names.append(str(payload["display_name"]))
            by_commit[event.get("sequence")] = names
    return by_commit


def test_every_named_rider_roll_is_logged_under_that_rider(tmp_path, monkeypatch):
    """Service level, checked event by event: no commit is named by a rider that did not deal it.

    The fixture really produces both shapes -- a rider commit that carries its own attribution and
    the ability's own unattributed commit -- so the assertions below cannot pass by skipping.
    """
    from combat.gate4_engine import Gate4ControllerEngine
    from tests.test_p4_void_needle import cast

    monkeypatch.setattr(Gate4ControllerEngine, "_attack_mode", lambda *a, **k: "ADVANTAGE")
    boundary, _ = cast(tmp_path, monkeypatch, "Empty Vitality", "Hollowed", ruin=True,
                       extra=("TAL_FENCING_CHEST_STRIKE",))
    events, feed = boundary["events"], boundary["feed"]
    fresh = CombatService(ROOT, tmp_path)
    match, = fresh.list_matches()
    _, definitions = TabletopService(fresh, tmp_path)._names_for(match["match_id"])
    definitions.update({"passive:TAL_IRON_FIST_BREAKING_KNUCKLE": "Breaking Knuckle",
                        "passive:TAL_VOID_NULLIFYING_STRIKE": "Nullifying Strike"})
    rows = _feed_by_sequence(feed)
    packet = _packet_names(events)
    # Every rider name the fight recorded, so "some rider's name was used" is detectable at all.
    riders = {name for names in packet.values() for name in names}
    assert riders, "the fixture must record at least one rider's name"

    attributed = unattributed = 0
    for event in events:
        if event["event_type"] != "DAMAGE_COMMITTED":
            continue
        row = rows.get(event.get("sequence"))
        if row is None:
            continue
        sequence = event.get("sequence")
        payload = event.get("payload") or {}
        dealt = _dealt_by(row["summary"])
        if dealt in riders:
            assert dealt in packet[sequence], (
                f"commit {sequence} is named {dealt!r}, a rider that belongs to another damage "
                f"packet (this one rolled {packet[sequence]!r})")
        if payload.get("display_name") or payload.get("display_source_id"):
            attributed += 1
            expected = payload.get("display_name") or definitions[payload["display_source_id"]]
            assert dealt == expected, (
                f"commit {sequence} explicitly names {expected!r} but the log names {dealt!r}")
        else:
            unattributed += 1
            assert dealt not in riders, (
                f"commit {sequence} is the ability's own damage but is named {dealt!r}, a rider "
                f"that did not deal it")
    assert attributed, "the fixture must produce a rider commit that carries its own attribution"
    assert unattributed, "the fixture must produce the ability's own unattributed commit"




# --------------------------------------------------------------------------- 3. Ask-me prompts

R1I_OWNER, R1I_FOE = FACTORY_ACTOR_PREFIX + "r1i-owner", FACTORY_ACTOR_PREFIX + "r1i-foe"


def test_spinning_shot_target_choice_stays_unresolved_at_the_table(tmp_path, monkeypatch):
    """Real ask transport -> table.act -> final builder -> answer -> commit and reload."""
    from tests.test_c10_review_fixup import make_table, end_until_hero, act, reload_check

    combat, table, match = make_table(tmp_path, ["TAL_BARRAGE_SPINNING_SHOT"],
        "tianxia.sphere.barrage", "MANUAL", foes=3, body=True)
    end_until_hero(table, match)
    prompts = act(combat, table, match, "MANUAL", monkeypatch,
                  "Barrage: Gong Jian (Bow and Arrow) + Spinning Shot")
    assert prompts, "Spinning Shot must actually ask for its next target"
    for prompt in prompts:
        assert prompt["reaction"] == "Spinning Shot"
        assert prompt["affected"] == ""
        assert prompt["by"] == ""
        assert " uses " not in prompt["trigger"]
    engine = reload_check(combat, match)
    attacks = [e for e in engine.events if e.event_type == "ATTACK_ROLLED"]
    assert len(attacks) == 2 and len({e.target_ids[0] for e in attacks}) == 2


def _ask_me_table(tmp_path, talents=("tianxia.talent.blood.bloodletting_strike",)):
    """A real table and a real saved fight whose owner is set to Ask me."""
    from tests.r1i_service_support import fixture as r1i_fixture

    return r1i_fixture(tmp_path, list(talents), owner_dc=50)


def test_ask_me_prompt_names_the_creature_the_packet_recorded(tmp_path):
    """Table level: the prompt a real Ask-me pause shows names the creature it is about.

    Reaches the final presentation path -- table.act -> _reaction_prompt -> build_decision_text --
    on a real service, a real session and the real roster, and then the prompt is answered back.
    """
    from tests.r10_fixup_support import answer, cast_sender

    combat, table, match, _send, _commit = _ask_me_table(tmp_path)
    send = cast_sender(combat, table, match, "Blood Thread", target=R1I_FOE)
    result = send()
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    roster = {actor.entity_id: actor.display_name
              for actor in combat._load_session(match).engine.state.actors.values()}
    assert prompt["affected"] == roster[R1I_FOE], (
        f"the prompt must name the creature the action targeted, got {prompt['affected']!r}")
    for field in ("affected", "trigger_actor", "by"):
        assert prompt.get(field, "") in {"", *roster.values()}, (
            f"{field}={prompt.get(field)!r} is not a creature the table knows")
    committed = send([answer(prompt, "bloodletting")])
    assert committed["status"] == "COMMITTED", committed


def test_ask_me_prompt_does_not_name_an_option_the_player_has_not_chosen(tmp_path):
    """The review's counterexample, through the real presentation builder.

    An arc offers several creatures as options and records its centre separately. The prompt must
    report the recorded centre, never whichever option happens to read longest, and never a
    creature that the question merely mentions.
    """
    combat, table, match, _send, _commit = _ask_me_table(tmp_path)
    engine = combat._load_session(match).engine
    roster = {actor.entity_id: actor.display_name for actor in engine.state.actors.values()}
    # The question's own words mention Second, but the packet acted on Foe.
    context = {
        "reactor_id": R1I_OWNER,
        "reaction_source_id": "choice:needle.arc",
        "checkpoint": "NEEDLE:arc:1:4",
        "extension_choice": {"option_ids": [R1I_FOE, FACTORY_ACTOR_PREFIX + "r1i-second"],
                             "minimum_selections": 0, "maximum_selections": 1, "allow_decline": True},
        "recent_events": [],
        "choice_trigger": {"prompt": "Lightning Arc: Second is closest, but arc to which creature?",
                           "labels": {R1I_FOE: roster[R1I_FOE],
                                      FACTORY_ACTOR_PREFIX + "r1i-second": roster[FACTORY_ACTOR_PREFIX + "r1i-second"]},
                           "name": "Lightning Arc", "feature_id": "lightning_arc",
                           "target_id": R1I_FOE},
    }
    prompt = table._reaction_prompt(match, context, engine=engine)
    assert prompt["affected"] == roster[R1I_FOE], (
        f"the prompt must name the recorded target, got {prompt['affected']!r}")
    # The site may repeat its own wording, but nothing may be appended that says the arc lands on
    # an option the player has not chosen.
    narrative = " ".join(str(prompt.get(field) or "") for field in ("moment", "trigger", "by"))
    other = roster[FACTORY_ACTOR_PREFIX + "r1i-second"]
    assert f"on {other}" not in narrative and f"to {other}" not in narrative, \
        f"an unselected option was written into the prompt as the target: {narrative!r}"


def test_ask_me_prompt_ignores_a_roster_name_inside_an_ability_name(tmp_path):
    """A creature called Guard is not affected by a question about "Guard-Cutting Parry"."""
    from types import SimpleNamespace

    table = TabletopService.__new__(TabletopService)
    table._names_for = lambda _: ({"actor:me": "Lu Bo", "actor:guard": "Guard"},
                                  {"reaction:typed.parry": "Guard-Cutting Parry"})
    prompt = table._reaction_prompt_fields("unused", {
        "reactor_id": "actor:me",
        "reaction_source_id": "reaction:typed.parry",
        "checkpoint": "TYPED:INCOMING_DAMAGE",
        "recent_events": [],
        "choice_trigger": {"prompt": "Guard-Cutting Parry against this attack.", "action_name": "Guard-Cutting Parry"},
    })
    assert prompt["affected"] == "", (
        f"an ability name is not a creature, got {prompt['affected']!r}")


def test_ask_me_prompt_names_the_target_the_packet_supplied(tmp_path):
    """The original defect: a packet that records its target must not leave the field blank."""
    table = TabletopService.__new__(TabletopService)
    table._names_for = lambda _: ({"actor:me": "Lu Bo", "actor:foe": "Tang Zhenfeng"},
                                  {"reaction:typed.parry": "Guard-Cutting Parry"})
    prompt = table._reaction_prompt_fields("unused", {
        "reactor_id": "actor:me",
        "reaction_source_id": "reaction:typed.parry",
        "checkpoint": "TYPED:INCOMING_DAMAGE",
        "recent_events": [],
        "choice_trigger": {"prompt": "Guard-Cutting Parry against Tang Zhenfeng's attack.",
                           "target_id": "actor:foe"},
    })
    assert prompt["affected"] == "Tang Zhenfeng", \
        f"the recorded target must be reported, got {prompt['affected']!r}"


def test_ask_me_prompt_leaves_unknown_provenance_unknown(tmp_path):
    """A question that names no creature still names none (gilded-context guard)."""
    table = TabletopService.__new__(TabletopService)
    from combat.tabletop_service import TabletopService as TS
    original = TS._names_for
    TS._names_for = lambda self, _: ({"actor:me": "Guard Owner", "actor:foe": "Old Attacker"},
                                     {"old:attack": "Old Attack"})
    try:
        prompt = table._reaction_prompt_fields("unused", {
            "reactor_id": "actor:me",
            "reaction_source_id": "reaction:typed.parry",
            "attacking_actor_id": "actor:foe",
            "recent_events": [{"actor_id": "actor:foe", "source_definition_id": "old:attack"}],
            "choice_trigger": {"prompt": "Choose dice against this damage."},
        })
    finally:
        TS._names_for = original
    assert prompt.get("affected", "") == ""
    assert "Old" not in prompt["moment"]
