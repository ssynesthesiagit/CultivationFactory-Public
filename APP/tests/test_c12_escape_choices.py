"""Player escape choices use real table transactions, retries and saved reloads."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext import escape_options
from combat.ext.illusion_riders import SUBSTANTIAL
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import resolve, reload

PRISON = "tianxia.talent.stars.constellation_prison"
ABILITY = "choice:needle.escape_ability"
FREE = "choice:needle.escape_free"


def fixed_dice(monkeypatch, check):
    from combat.gate2_rolls import DeterministicRollAuthority
    real = DeterministicRollAuthority.d20

    def dice(roller, **kwargs):
        wanted = (1 if kwargs["reason"].startswith("SAVE:") else check
                  if kwargs["reason"].startswith("CHECK:") else None) if kwargs["actor_id"] == FOE else None
        while True:
            roll = real(roller, **kwargs)
            if wanted is None or roll.natural_result == wanted:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", dice)


def prison_setup(tmp_path, monkeypatch, *, different_modes=False):
    fixed_dice(monkeypatch, 20)

    def prepare(bundles):
        if not different_modes:
            return
        owner, foe = bundles[:2]
        # Test-only modes on a real activated hold: lower-modifier Charisma is
        # still more likely to succeed than Strength with Disadvantage.
        foe["actor_template"]["saving_throws"]["CHA"] = 1
        action = next(a for a in owner["action_catalog"] if a["display_name"] == "Constellation Prison")
        action["parameters"]["typed"]["effects"].append({
            "type": "ongoing", "condition": "c12_choice_modes", "applies_to": "target",
            "rule": {"check_mode": {"STR": "DISADVANTAGE", "CHA": "ADVANTAGE"}},
            "expires_on": "UNTIL_REMOVED"})
        for bundle in (owner, foe):
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid, send, commit = fixture(tmp_path, [PRISON], owner_dc=16, bundle_transform=prepare)
    commit(candidate(table, mid, "Constellation Prison", FOE))
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    assert escape_options.options(reload(tmp_path, mid).state.actors[FOE])
    return combat, table, mid, send, commit


@pytest.mark.parametrize("ability", ["STR", "CHA"])
@pytest.mark.parametrize("mode", ["MANUAL", "SUGGESTED"])
def test_manual_constellation_ability_pause_retry_commit_reload(tmp_path, monkeypatch, ability, mode):
    combat, table, mid, send, commit = prison_setup(tmp_path, monkeypatch)
    if mode != "MANUAL":
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode=mode)
    cid = candidate(table, mid, "Break free")
    before = reload(tmp_path, mid)
    state = before.state.model_dump(mode="json")
    result = send(cid)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == ABILITY
    assert prompt["context"]["reactor_id"] == FOE
    assert {o["id"] for o in prompt["choice"]["options"]} == {"STR", "CHA"}
    assert not prompt["choice"]["allow_decline"]
    assert all(word in str(prompt) for word in ("Constellation Prison", "Break free", "Foe", "Strength", "Charisma"))
    assert send(cid)["reaction"] == prompt
    assert reload(tmp_path, mid).state.model_dump(mode="json") == state
    answer = {**prompt["context"], "selection": "USE", "option_ids": [ability]}
    assert send(cid, [answer])["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    (check,) = [e for e in after.events[len(before.events):] if e.event_type == "CHECK_ROLLED"]
    assert check.payload["ability"] == ability and check.payload["success"]
    assert not escape_options.options(after.state.actors[FOE])
    assert not any(c.source_definition_id == PRISON for c in after.state.actors[FOE].conditions.values())
    assert not after.state.actors[FOE].action_available
    assert after.state.actors[FOE].resources == before.state.actors[FOE].resources


def test_ai_ability_preference_accounts_for_modes_without_prompt(tmp_path, monkeypatch):
    combat, table, mid, send, commit = prison_setup(tmp_path, monkeypatch, different_modes=True)
    cid = candidate(table, mid, "Break free")
    force_ai_candidate(combat, mid, FOE, cid)
    before = len(reload(tmp_path, mid).events)
    assert send(cid, auto=True)["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    (check,) = [e for e in after.events[before:] if e.event_type == "CHECK_ROLLED"]
    assert check.payload["ability"] == "CHA"
    assert check.payload["actor"]["mode"] == "ADVANTAGE"
    assert not escape_options.options(after.state.actors[FOE])


@pytest.mark.parametrize("auto,accept,check", [
    (False, False, 20), (False, True, 1), (False, True, 20),
    (True, True, 1), (True, True, 20),
])
def test_optional_free_study_end_turn_pause_choice_reload(tmp_path, monkeypatch, auto, accept, check):
    fixed_dice(monkeypatch, check)
    combat, table, mid, send, commit = fixture(tmp_path, [SUBSTANTIAL], owner_dc=16,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 8, "y": 6}})
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Create Figment + Substantial Phantasm (3 CP; Grappled)"
               for o in g["options"] if o.get("destination") == {"x": 4, "y": 6})
    resolve(combat, mid, send, cid, {"choice:needle.substantial_phantasm": FOE})
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    before = reload(tmp_path, mid)
    ((key, record),) = escape_options.options(before.state.actors[FOE])
    cid = table.state(mid)["menu"]["end_turn"]
    if auto:
        force_ai_candidate(combat, mid, FOE, cid)
    _, prompts = resolve(combat, mid, send, cid, {FREE: "study"} if accept else {}, auto=auto)
    if not auto:
        (prompt,) = [p for p in prompts if p["context"]["reaction_source_id"] == FREE]
        assert prompt["context"]["reactor_id"] == FOE
        assert prompt["choice"]["allow_decline"]
        assert all(word in str(prompt) for word in ("Substantial Phantasm", "Foe", "end of", "Study", "No Action"))
    else:
        assert not prompts
    after = reload(tmp_path, mid)
    checks = [e for e in after.events[len(before.events):] if e.event_type == "CHECK_ROLLED"]
    assert len(checks) == int(accept)
    if accept:
        assert checks[0].payload["ability"] == "INT"
        assert checks[0].payload["success"] == (check == 20)
    # Inspect the removal's event order before caster-start expiry can hide a
    # failure: successful Study must remove the actual hold immediately.
    hold_removals = [e for e in after.events[len(before.events):] if e.event_type == "CONDITION_REMOVED"
                     and e.source_definition_id == escape_options.SELF_ACTION
                     and e.payload.get("instance_id") in record.data["guards"]]
    assert len(hold_removals) == (len(record.data["guards"]) if accept and check == 20 else 0)
    if accept and check == 20:
        assert hold_removals
        assert min(e.sequence for e in hold_removals) > checks[0].sequence
    if after.state.current_actor_id != OWNER:
        assert (key in after.state.actors[FOE].conditions) == (not accept or check != 20)
        assert all((iid in after.state.actors[FOE].conditions) == (not accept or check != 20)
                   for iid in record.data["guards"])
    assert after.state.actors[FOE].resources == before.state.actors[FOE].resources


def test_unheld_end_turn_has_no_escape_prompt_or_roll(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [])
    before = len(reload(tmp_path, mid).events)
    assert send(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    assert not any(e.event_type == "CHECK_ROLLED" for e in reload(tmp_path, mid).events[before:])
