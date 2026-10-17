"""F4: real table choices and persisted status text identify the seal and deadline."""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import ability_lockout
from tests import test_riders_c2 as C2
from tests.test_c14_review_save_choice import table_fixture
from tests.test_c5_review import _act
from tests.test_riders_c14 import ROOT


def pill(table, mid):
    return next(row for actor in table.state(mid)["presentation"]["actors"]
                for row in actor["conditions"] if row["condition_id"] == ability_lockout.LOCKOUT)


@pytest.mark.parametrize("source_mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("save", ["CON", "WIS"])
def test_seal_selection_and_status_text_survive_table_reload(tmp_path, source_mode, save):
    combat, mid = table_fixture(tmp_path, ask=True, target_talents=[
        "TAL_ALCHEMY_CALMING_HEART_PILL", "TAL_ALCHEMY_MERIDIAN_SEALING_PILL"])
    # The fixture uses both named abilities through normal table transactions,
    # before the Pressure Point expires, so the seal must ask which to restrict.
    combat.set_controller_mode(mid, actor_id=C2.ME, controller_mode=source_mode)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    answers, prompts = [], []
    menu = table.state(mid)["menu"]
    candidate = next(c for c in combat.decision(mid)["context"]["legal_candidates"]
                     if c["display_name"] == "Fu (Short Axe) attack")
    for _ in range(12):
        before = combat._load_session(mid).engine.state.model_dump(mode="json")
        result = (table.act(mid, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)
                  if source_mode == "MANUAL" else table.auto_step(mid, 0, answers))
        if result["status"] == "COMMITTED":
            if prompts:
                break
            continue  # AI may make a setting choice before attacking.
        assert result["status"] == "REACTION_REQUIRED", result
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        prompts.append(prompt)
        options = prompt["choice"]["options"]
        if prompt["context"]["reaction_source_id"].endswith("ability_lockout"):
            assert prompt["context"]["reactor_id"] == C2.ME
            assert prompt["reaction"] == "Technique-Closing Point"
            assert "Technique-Closing Point" in prompt["moment"]
            assert "Fu (Short Axe) attack" in prompt["moment"]
            assert combat._load_session(mid).engine.state.actors[C2.ATK].display_name in prompt["moment"]
            assert "no extra action or resource" in prompt["moment"]
            selected = next(o["id"] for o in options if "Calming Heart Pill" in o["label"])
        else:
            selected = save
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [selected]})
        combat = CombatService(ROOT, tmp_path)  # pending choices also survive reopen
        table = TabletopService(combat, tmp_path)
    else:
        pytest.fail("seal transaction did not finish")
    assert any(p["context"]["reaction_source_id"].endswith("ability_lockout") for p in prompts) == (source_mode == "MANUAL")
    resumed = CombatService(ROOT, tmp_path)
    session = resumed._load_session(mid)
    owner = session.engine.state.actors[C2.ME]
    target = session.engine.state.actors[C2.ATK]
    record = ability_lockout.records(target)[0]
    until = (f"until the start of {owner.display_name}'s next turn" if save == "CON" else
             f"until the end of {target.display_name}'s next turn")
    row = pill(TabletopService(resumed, tmp_path), mid)
    assert row["source_ability"] == "Technique-Closing Point"
    assert "Technique-Closing Point" in record.data["label"] and until in record.data["label"]
    assert row["display_name"] == record.data["label"]
    chosen_name = "Calming Heart Pill" if source_mode == "MANUAL" else "Meridian-Sealing Pill"
    assert chosen_name in row["detail"] and until in row["detail"]
    assert "Fu (Short Axe) attack" not in record.data["label"]
    assert record.data["mode"] == ("watch" if save == "CON" else "barred")
    assert session.mechanical.verify()["status"] == "PASS"
    resumed.set_controller_mode(mid, actor_id=C2.ME, controller_mode="MANUAL")
    table = TabletopService(resumed, tmp_path)
    _act(resumed, table, mid, "End turn")
    if save == "WIS":
        refreshed = pill(table, mid)
        assert f"until the end of {target.display_name}'s turn" in refreshed["rule_text"]
        assert until not in refreshed["rule_text"]  # stored 'next' label is not stale UI
        assert until not in refreshed["display_name"]
        assert f"until the end of {target.display_name}'s turn" in refreshed["display_name"]
    _act(resumed, table, mid, "End turn")
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not ability_lockout.records(session.engine.state.actors[C2.ATK])
    assert session.mechanical.verify()["status"] == "PASS"


@pytest.mark.parametrize("expiry,anchor,edge,next_turn", [
    ("START_OF_SOURCE_NEXT_TURN", "source", "start", True),
    ("END_OF_SOURCE_TURN_AT:{next}", "source", "end", True),
    ("END_OF_SOURCE_TURN_AT:{now}", "source", "end", False),
    ("END_OF_HOLDER_NEXT_TURN", "holder", "end", True),
    ("START_OF_TURN_AT:{holder}:{next}", "holder", "start", True),
    ("END_OF_TURN_AT:{holder}:{now}", "holder", "end", False),
    ("END_OF_SOURCE_TURN_AT:{future}", "source", "end", False),
    ("START_OF_TURN_AT:{holder}:{future}", "holder", "start", False),
])
def test_old_saved_lockout_deadlines_at_actual_table_boundary(tmp_path, monkeypatch, expiry, anchor, edge, next_turn):
    combat, mid = table_fixture(tmp_path)
    session = combat._load_session(mid)
    source, holder = session.engine.state.actors[C2.ME], session.engine.state.actors[C2.ATK]
    source.display_name, holder.display_name = "Seal user", "Defender"
    actor = source if anchor == "source" else holder
    token = expiry.format(holder=holder.entity_id, now=actor.turns_started, next=actor.turns_started + 1,
                          future=actor.turns_started + 3)
    action = next(a for a in session.engine.action_catalog.values() if a.display_name == "Calming Heart Pill")
    # Historical records have only the original presentation fields. Project the
    # actual table API without migrating or adding any new required saved fields.
    session.engine._apply_condition(holder, ability_lockout.LOCKOUT, action.source_definition_id,
                                    source.entity_id, expires_on=token, data={
        "ability": ability_lockout.key_of(action), "name": action.display_name, "mode": "barred",
        "source": action.source_definition_id, "label": "Old seal: cannot use Calming Heart Pill"})
    table = TabletopService(combat, tmp_path)
    monkeypatch.setattr(combat, "_load_session", lambda match_id: session)
    turn = f"turn {actor.turns_started + 3}" if "{future}" in expiry else "next turn" if next_turn else "turn"
    expected = f"until the {edge} of {actor.display_name}'s {turn}"
    row = pill(table, mid)
    assert expected in row["rule_text"] and expected in row["display_name"]
