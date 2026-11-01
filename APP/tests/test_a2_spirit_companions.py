"""A2 Spirit Companions (lane SOL206): second-pass rows through the real table, disk reload and mechanical replay.

Shared Breath Guardian (Insight, owner text in authority/typed_mechanics/rules_text.json): "Reaction. Trigger: A spirit
joined to you ... and within 30 feet would take damage. Transfer half of the triggering damage to yourself ... You receive
the smaller half, rounded down; the spirit receives the remainder." The Insight is owned through the sheet's real Insight
field; the damage comes from an ordinary bow attack chosen on the table.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r1i_service_support import force_ai_candidate
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import ALLY, LEFT, PROJECTS, RIGHT

BREATH = "insight.shared-breath-guardian"
BOND = ["tianxia.talent.spirit_companions.battle_manifestation", "tianxia.talent.spirit_companions.covenant_spirit"]
BOW = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian", "quantity": 1}]}}


def _fight(tmp_path, *, insight_on=("left",), bond_on=("left",), ask=True, modes=None, extra_talents=()):
    """table_fight's yard, with the Insight on the sheet's own cultivation_insight_record_ids field."""
    for name in ("left", "ally", "right"):
        document = sheet([*(BOND if name in bond_on else []), *(extra_talents if name == "left" else [])],
                         cl=15, kit=BOW if name == "right" else None)
        if name in insight_on:
            document.setdefault("spheres_and_talents", {}).setdefault("cultivation_insight_record_ids", []).append(BREATH)
        document["identity"]["display_name"] = name.title()
        folder = tmp_path / "portable_characters" / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    if ask:
        from combat.tabletop import ButtonStore
        for name in ("left", "ally"):
            ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PROJECTS[name], {"mode": "ask"}, {"opportunity_attack"})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Breath yard", "width_squares": 12, "height_squares": 8,
                              "walls": [], "starts": {"team1": [[3, 4], [3, 5]], "team2": [[9, 4]]}})  # out of reach: the move draws no Opportunity Attack
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"], PROJECTS["ally"]], opponent_actor_ids=[RIGHT],
                                     control_modes=modes or {a: "MANUAL" for a in (LEFT, ALLY, RIGHT)},
                                     arena_id="battlefield:map.breath-yard", match_seed="A2-BREATH")["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    commit(cast_sender(combat, table, mid, "Move", at=(7, 4)))
    return combat, table, mid


def _spirit(engine, owner=LEFT):
    return next(a for a in engine.state.actors.values()
                if a.summon and a.summon.get("group") == "bonded_spirit" and a.owner_id == owner)


def _shoot(combat, table, mid, target_id, *, auto=False):
    send = cast_sender(combat, table, mid, "Gong Jian", target=target_id)
    if auto:
        engine = combat._load_session(mid).engine
        action = next(c for c in engine.legal_candidates() if "Gong Jian" in c.display_name and target_id in c.target_ids)
        force_ai_candidate(combat, mid, RIGHT, action.candidate_id)
        return lambda answers=(): table.auto_step(mid, 0, list(answers))
    return send


def _hp(engine, *ids):
    return {i: engine.state.actors[i].current_hp for i in ids}


def _reload(tmp_path, mid):
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"
    return fresh


@pytest.mark.parametrize("answer", ["USE", "DECLINE"])
def test_owner_takes_the_smaller_half_of_damage_to_its_spirit_after_a_table_prompt(tmp_path, monkeypatch, answer):
    combat, table, mid = _fight(tmp_path)
    spirit = _spirit(combat._load_session(mid).engine)
    before = _hp(combat._load_session(mid).engine, LEFT, spirit.entity_id)
    fixed_dice(monkeypatch, [19] * 100)
    send = _shoot(combat, table, mid, spirit.entity_id)
    result = send()
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["reaction"] == "Shared Breath Guardian"
    result = send([{**prompt["context"], "selection": answer}])
    assert result["status"] == "COMMITTED", result
    fresh = _reload(tmp_path, mid)
    after = _hp(fresh.engine, LEFT, spirit.entity_id)
    owner_lost, spirit_lost = before[LEFT] - after[LEFT], before[spirit.entity_id] - after[spirit.entity_id]
    total = owner_lost + spirit_lost
    assert total > 1
    if answer == "USE":
        assert owner_lost == total // 2 and spirit_lost == total - total // 2
        assert fresh.engine.state.actors[LEFT].reaction_available is False
        notes = [e for e in fresh.engine.events if e.source_definition_id == BREATH]
        assert notes and any("in place of" in json.dumps(e.payload) for e in notes)
    else:
        assert owner_lost == 0 and spirit_lost == total
        assert fresh.engine.state.actors[LEFT].reaction_available is True


def test_the_built_in_ai_shares_to_improve_its_spirits_remaining_hp_fraction(tmp_path, monkeypatch):
    combat, table, mid = _fight(tmp_path, ask=False)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    session = combat._load_session(mid)
    spirit = _spirit(session.engine)
    before = _hp(session.engine, LEFT, spirit.entity_id)
    fixed_dice(monkeypatch, [19] * 100)
    assert _shoot(combat, table, mid, spirit.entity_id)()["status"] == "COMMITTED"
    fresh = _reload(tmp_path, mid)
    after = _hp(fresh.engine, LEFT, spirit.entity_id)
    owner_lost, spirit_lost = before[LEFT] - after[LEFT], before[spirit.entity_id] - after[spirit.entity_id]
    total = owner_lost + spirit_lost
    # The AI's rule (damage_sharing._worth): a free share is taken when the taker stays standing and either keeps the
    # target up or improves the spirit's remaining HP fraction while the owner stays standing.
    assert total < before[spirit.entity_id]  # this case does not establish lethal unshared damage
    assert after[LEFT] > 0
    assert owner_lost == total // 2 > 0


@pytest.mark.parametrize("defense", [None, "damage_resistance", "damage_immunity"], ids=["ordinary", "resistant", "immune"])
def test_original_attack_reduction_precedes_the_split_and_recipient_defenses(tmp_path, monkeypatch, defense):
    from combat.ext.next_attack_damage import CONDITION

    combat, table, mid = _fight(tmp_path)
    spirit_id = _spirit(combat._load_session(mid).engine).entity_id
    def setup(engine):
        engine._apply_condition(engine.state.actors[RIGHT], CONDITION, "TAL_IRON_FIST_BELL_RINGING_BODY_SHOT", LEFT,
                                expires_on=None, data={"amount": 8, "label": "Next attack deals 8 less damage"})
        if defense:
            engine._add_modifier(engine.state.actors[spirit_id], "test:a2.spirit_defense", defense, "SET",
                                 "PIERCING", "ALL", expires_on=None)
    _next_foe_turn_after(combat, table, mid, monkeypatch, setup)
    before = _hp(combat._load_session(mid).engine, LEFT, spirit_id)
    fixed_dice(monkeypatch, [19] * 100)
    send = _shoot(combat, table, mid, spirit_id)
    assert _use(send, send())["status"] == "COMMITTED"
    fresh = _reload(tmp_path, mid)
    attack_damage = next(e.payload["combined_total"] for e in reversed(fresh.engine.events)
                         if e.event_type == "DAMAGE_ROLLED" and spirit_id in e.target_ids)
    printed, owner_lost, spirit_lost = _split(fresh, before, spirit_id)
    assert attack_damage > 8
    assert printed == attack_damage - 8
    assert owner_lost == printed // 2
    rest = printed - printed // 2
    assert spirit_lost == (0 if defense == "damage_immunity" else rest // 2 if defense == "damage_resistance" else rest)
    assert not any(c.condition_id == CONDITION for c in fresh.engine.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize("transfer", ["oath", "community"])
def test_existing_nonrecursive_transfers_into_a_spirit_do_not_offer_another_share(tmp_path, monkeypatch, transfer):
    from combat.ext.damage_sharing import OATH
    from combat.typed_executor import mark_condition_id

    talent = "tianxia.talent.protection.community"
    combat, table, mid = _fight(tmp_path, extra_talents=[talent] if transfer == "community" else [])
    spirit_id = _spirit(combat._load_session(mid).engine).entity_id
    def setup(engine):
        for actor_id in (ALLY, spirit_id):
            condition = OATH if transfer == "oath" else mark_condition_id("Aegis", LEFT)
            data = {"share": {"owner": LEFT}} if transfer == "oath" else {
                "mark": "Aegis", "aegis_talent": "PROTECTION_BASE_ARMORED_AEGIS"}
            engine._apply_condition(engine.state.actors[actor_id], condition, "test:a2.transfer", LEFT,
                                    expires_on=None, data=data)
        # Only the spirit and ally are linked. Wounding the ally makes the existing AI offer worthwhile.
        engine._commit_damage(engine.state.actors[ALLY], engine.state.actors[ALLY].current_hp - 10,
                              "FORCE", "test:a2.wound", RIGHT, None, reaction_depth=3)
    _next_foe_turn_after(combat, table, mid, monkeypatch, setup)
    before = _hp(combat._load_session(mid).engine, LEFT, ALLY, spirit_id)
    fixed_dice(monkeypatch, [19] * 100)
    send = _shoot(combat, table, mid, ALLY)
    answers, prompts = [], []
    for _ in range(20):
        result = send(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        use = prompt["reaction"] == "Community" or "damage_sharing:mutual_defense" in prompt["context"]["reaction_source_id"]
        answer = {**prompt["context"], "selection": "USE" if use else "DECLINE"}
        if prompt.get("choice"):
            answer["option_ids"] = [spirit_id] if use else []
        answers.append(answer)
    else:
        raise AssertionError("too many transfer prompts")
    assert not any(p["reaction"] == "Shared Breath Guardian" for p in prompts), prompts
    fresh = _reload(tmp_path, mid)
    after = _hp(fresh.engine, LEFT, ALLY, spirit_id)
    assert after[LEFT] == before[LEFT]
    raw = next(e.payload["combined_total"] for e in reversed(fresh.engine.events)
               if e.event_type == "DAMAGE_ROLLED" and ALLY in e.target_ids)
    assert before[spirit_id] - after[spirit_id] == raw // 2 > 0
    assert before[ALLY] - after[ALLY] == raw - raw // 2
    if transfer == "oath":
        assert not fresh.engine.state.actors[spirit_id].reaction_available
    assert fresh.engine.state.actors[LEFT].reaction_available
    assert not any(e.source_definition_id == BREATH for e in fresh.engine.events)


@pytest.mark.parametrize("answer", ["USE", "DECLINE"])
def test_owner_originated_damage_still_offers_the_legal_spirit_reaction(tmp_path, monkeypatch, answer):
    gap = "TAL_VOID_COLLAPSING_GAP"
    combat, table, mid = _fight(tmp_path, extra_talents=[gap])
    spirit_id = _spirit(combat._load_session(mid).engine).entity_id
    while table.state(mid)["menu"]["actor_id"] != LEFT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    before = _hp(combat._load_session(mid).engine, LEFT, spirit_id)
    spirit = combat._load_session(mid).engine.state.actors[spirit_id]
    fixed_dice(monkeypatch, [1] * 100)
    send = cast_sender(combat, table, mid, "Collapsing Gap", at=(spirit.position.x, spirit.position.y))
    answers, breath_prompts = [], []
    for _ in range(20):
        result = send(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        reply = {**prompt["context"], "selection": "DECLINE"}
        if prompt["context"]["reaction_source_id"] == "choice:needle.area_recipients":
            reply.update(selection="USE", option_ids=[spirit_id])
        elif prompt["reaction"] == "Shared Breath Guardian":
            breath_prompts.append(prompt)
            assert "Collapsing Gap" in json.dumps(prompt) and "Left" in json.dumps(prompt)
            assert spirit.display_name in json.dumps(prompt)
            reply["selection"] = answer
        elif prompt.get("choice") and not prompt["choice"].get("allow_decline"):
            choice = prompt["choice"]
            options = choice.get("preferred") or [o["id"] for o in choice["options"]]
            reply.update(selection="USE", option_ids=options[:int(choice.get("minimum") or 1)])
        answers.append(reply)
    else:
        raise AssertionError("too many area/reaction prompts")
    assert len(breath_prompts) == 1, breath_prompts
    fresh = _reload(tmp_path, mid)
    after = _hp(fresh.engine, LEFT, spirit_id)
    raw = next(e.payload["rolled_or_pending_damage"] for e in reversed(fresh.engine.events)
               if e.event_type == "DAMAGE_COMMITTED" and spirit_id in e.target_ids)
    assert raw > 1
    assert before[LEFT] - after[LEFT] == (raw // 2 if answer == "USE" else 0)
    assert before[spirit_id] - after[spirit_id] == (raw - raw // 2 if answer == "USE" else raw)
    assert fresh.engine.state.actors[LEFT].reaction_available == (answer == "DECLINE")


def test_transfer_scope_does_not_suppress_a_fresh_nested_damage_packet(tmp_path, monkeypatch):
    from combat.ext.damage_transfer_scope import nonrecursive_transfer

    combat, table, mid = _fight(tmp_path)
    spirit_id = _spirit(combat._load_session(mid).engine).entity_id
    before = _hp(combat._load_session(mid).engine, LEFT, spirit_id)
    def fresh_damage(engine):
        spirit = engine.state.actors[spirit_id]
        bow = next(a for a in engine.action_catalog.values() if a.owner_id == RIGHT and "Gong Jian" in a.display_name)
        # A fresh packet during a recipient's defense evaluation has its own
        # context and no transfer flag, even when it hits that same recipient.
        with nonrecursive_transfer(engine, spirit):
            engine._commit_damage(spirit, 20, "PIERCING", bow.source_definition_id, RIGHT,
                                  engine._active_intent, reaction_depth=0)
    on_hold(monkeypatch, fresh_damage)
    send = cast_sender(combat, table, mid, "Hold position")
    assert _use(send, send())["status"] == "COMMITTED"
    fresh = _reload(tmp_path, mid)
    after = _hp(fresh.engine, LEFT, spirit_id)
    assert before[LEFT] - after[LEFT] == before[spirit_id] - after[spirit_id] == 10


def test_fresh_damage_during_a_transfer_commit_gets_its_own_defense_and_reaction(tmp_path, monkeypatch):
    from combat.ext.damage_sharing import OATH
    from combat.ext.damage_transfer_scope import NONRECURSIVE_TRANSFER
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.pending_damage import current

    combat, table, mid = _fight(tmp_path)
    spirit_id = _spirit(combat._load_session(mid).engine).entity_id
    def setup(engine):
        for actor_id in (ALLY, spirit_id):
            engine._apply_condition(engine.state.actors[actor_id], OATH, "test:a2.transfer", LEFT,
                                    expires_on=None, data={"share": {"owner": LEFT}})
        engine._commit_damage(engine.state.actors[ALLY], engine.state.actors[ALLY].current_hp - 10,
                              "FORCE", "test:a2.wound", RIGHT, None, reaction_depth=3)
    _next_foe_turn_after(combat, table, mid, monkeypatch, setup)
    before = _hp(combat._load_session(mid).engine, LEFT, ALLY, spirit_id)
    original = Gate4ControllerEngine._append_event
    def fresh_packet(engine, event_type, *args, **kwargs):
        result = original(engine, event_type, *args, **kwargs)
        packet = current(engine)
        if event_type == "DAMAGE_COMMITTED" and spirit_id in (kwargs.get("target_ids") or ()) \
                and packet is not None and NONRECURSIVE_TRANSFER in packet.source_flags:
            # Synthetic fresh damage in the real receipt callback, while the
            # transferred share's actor flags are still installed. It is not
            # itself a transfer, even though it hits the same creature.
            engine._commit_damage(engine.state.actors[spirit_id], 20, "PIERCING", packet.source_id,
                                  RIGHT, None, reaction_depth=3)
        return result
    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", fresh_packet)
    fixed_dice(monkeypatch, [19] * 100)
    send = _shoot(combat, table, mid, ALLY)
    answers, prompts = [], []
    for _ in range(20):
        result = send(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        answers.append({**prompt["context"], "selection": "USE"})
    else:
        raise AssertionError("too many transfer/fresh-damage prompts")
    fresh = _reload(tmp_path, mid)
    after = _hp(fresh.engine, LEFT, ALLY, spirit_id)
    assert any(p["reaction"] == "Shared Breath Guardian" for p in prompts), prompts
    assert before[LEFT] - after[LEFT] == 10
    assert before[ALLY] - after[ALLY] == 5
    assert before[spirit_id] - after[spirit_id] == 15  # 5 transferred + 10 fresh, with 10 taken by owner


def test_the_insight_on_another_cultivator_does_not_answer_lefts_spirit(tmp_path, monkeypatch):
    # The Insight is on the ally, the spirit belongs to Left: "a spirit joined to you" only.
    combat, table, mid = _fight(tmp_path, insight_on=("ally",))
    spirit = _spirit(combat._load_session(mid).engine)
    fixed_dice(monkeypatch, [19] * 100)
    assert _shoot(combat, table, mid, spirit.entity_id)()["status"] == "COMMITTED"
    fresh = _reload(tmp_path, mid)
    assert not [e for e in fresh.engine.events if e.source_definition_id == BREATH]
    assert fresh.engine.state.actors[ALLY].reaction_available is True


def test_damage_to_an_ordinary_ally_is_not_shared(tmp_path, monkeypatch):
    combat, table, mid = _fight(tmp_path, insight_on=("left", "ally"))
    fixed_dice(monkeypatch, [19] * 100)
    assert _shoot(combat, table, mid, ALLY)()["status"] == "COMMITTED"
    fresh = _reload(tmp_path, mid)
    assert not [e for e in fresh.engine.events if e.source_definition_id == BREATH]
    assert fresh.engine.state.actors[LEFT].reaction_available is True


# ------------------------------------------------------------------------------------------------ A2SPIRIT review fixes
import re  # noqa: E402

from tests.test_tabletop_hunt6 import on_hold  # noqa: E402


def _next_foe_turn_after(combat, table, mid, monkeypatch, callback):
    """A synthetic setup inside the foe's accepted Hold Position, then the foe's next turn (where it shoots)."""
    on_hold(monkeypatch, callback)
    commit(cast_sender(combat, table, mid, "Hold position"))
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"


def _split(fresh, before, spirit_id):
    note = next(e for e in fresh.engine.events if e.source_definition_id == BREATH and "in place of" in json.dumps(e.payload))
    printed = int(re.search(r"of the (\d+)", json.dumps(note.payload)).group(1))
    after = _hp(fresh.engine, LEFT, spirit_id)
    return printed, before[LEFT] - after[LEFT], before[spirit_id] - after[spirit_id]


def _use(send, result):
    assert result["status"] == "REACTION_REQUIRED" and result["reaction"]["reaction"] == "Shared Breath Guardian", result
    return send([{**result["reaction"]["context"], "selection": "USE"}])


@pytest.mark.parametrize("defense,spirit_share", [("damage_resistance", lambda rest: rest // 2), ("damage_immunity", lambda rest: 0)],
                         ids=["resistant-spirit", "immune-spirit"])
def test_the_split_happens_before_the_spirits_own_defenses(tmp_path, monkeypatch, defense, spirit_share):
    combat, table, mid = _fight(tmp_path)
    spirit_id = _spirit(combat._load_session(mid).engine).entity_id
    _next_foe_turn_after(combat, table, mid, monkeypatch, lambda engine: engine._add_modifier(
        engine.state.actors[spirit_id], "test:a2.spirit_defense", defense, "SET", "PIERCING", "ALL", expires_on=None))
    before = _hp(combat._load_session(mid).engine, LEFT, spirit_id)
    fixed_dice(monkeypatch, [19] * 100)
    send = _shoot(combat, table, mid, spirit_id)
    assert _use(send, send())["status"] == "COMMITTED"
    fresh = _reload(tmp_path, mid)
    printed, owner_lost, spirit_lost = _split(fresh, before, spirit_id)
    assert owner_lost == printed // 2                       # the owner's half, through the owner's own (absent) defenses
    assert spirit_lost == spirit_share(printed - printed // 2)  # the spirit's half, through the spirit's own defense


@pytest.mark.parametrize("auto_attacker", [False, True], ids=["manual-attack", "ai-attack"])
def test_a_low_hp_ask_me_owner_is_still_offered_the_share_with_the_real_trigger(tmp_path, monkeypatch, auto_attacker):
    combat, table, mid = _fight(tmp_path)
    spirit_id = _spirit(combat._load_session(mid).engine).entity_id
    _next_foe_turn_after(combat, table, mid, monkeypatch, lambda engine: engine._commit_damage(
        engine.state.actors[LEFT], engine.state.actors[LEFT].current_hp - 2, "FORCE", "test:a2.wound", RIGHT, None, reaction_depth=3))
    loaded = combat._load_session(mid).engine
    assert loaded.state.actors[LEFT].current_hp == 2
    before = _hp(loaded, LEFT, spirit_id)
    fixed_dice(monkeypatch, [19] * 100)
    send = _shoot(combat, table, mid, spirit_id, auto=auto_attacker)
    result = send()
    assert result["status"] == "REACTION_REQUIRED", result  # the AI's "it would fall" preference does not hide a player's choice
    prompt = result["reaction"]
    assert prompt["reaction"] == "Shared Breath Guardian"
    text = json.dumps(prompt)
    spirit_name = loaded.state.actors[spirit_id].display_name
    assert spirit_name in text and "Gong Jian" in text, text      # the creature actually hit, by the action that hit it
    assert re.search(r"Take \d+ of it yourself", text), text       # the transfer, said plainly
    assert _use(send, result)["status"] == "COMMITTED"
    fresh = _reload(tmp_path, mid)
    printed, owner_lost, _spirit_lost = _split(fresh, before, spirit_id)
    assert owner_lost == min(2, printed // 2)
