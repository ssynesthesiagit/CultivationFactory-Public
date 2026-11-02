"""Static Guard's "no Opportunity Attacks" ends at the end of the turn it was used in (hunt HUNT103, lane UEOT).

Six abilities printed "until the end of the current/this turn" but were typed with the
``until_end_of_turn`` duration kind, which for a creature outside the user's side expires at
the end of the holder's NEXT turn -- a full round too long. The printed text wins: the rows now
carry the explicit ``END_OF_CURRENT_TURN`` expiry, so Static Guard's rider ends at the end of the
turn it was used in (the attacker's turn it fired on), not after the attacker's next turn."""
import json

import pytest
from combat import typed_executor
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, OWNER, FOE


def test_static_guard_no_opportunity_attacks_ends_at_the_turn_it_was_used(tmp_path):
    """**Trigger:** a creature within 5 feet hits you with a melee attack. **If you are Charged:**
    the attacker makes a Constitution saving throw; on a success it cannot take Opportunity Attacks
    against you until the end of the current turn. That is the turn the Reaction was used on -- the
    attacker's own turn -- not the attacker's next turn."""
    combat, table, mid, send, commit = fixture(
        tmp_path, ["TAL_LIGHTNING_STATIC_GUARD"], owner_ac=0, owner_dc=1,
        foe_talents=["tianxia.path.body_refining.feature.iron_fist"], foe_score=50)
    # Charge the owner (a bonus action) so Static Guard's "If you are Charged"
    # gate opens; then the foe's Iron Fist hits the owner and the defender's
    # Static Guard Reaction is answered USE -- the printed trigger, through the
    # service's own execute_intent path.
    commit(candidate(table, mid, "Gather Charge: Charge Yourself"))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Iron Fist", OWNER)
    result = send(cid)
    answers = []
    # The reviewed Iron Fist change asks its manual attacker for a damage
    # type before the defender's Static Guard; retain both answers on this action.
    while (result["status"] == "REACTION_REQUIRED"
           and result["reaction"]["context"]["reaction_source_id"] == "choice:needle.iron_fist_damage_type"):
        prompt = result["reaction"]
        answers.append({**prompt["context"], "selection": "USE",
                        "option_ids": [prompt["choice"]["options"][0]["id"]]})
        result = send(cid, answers)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert "STATIC_GUARD" in prompt["context"]["reaction_source_id"]
    result = send(cid, [*answers, {**prompt["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED", result
    # The Reaction's own Constitution save rolled, and the committed fight
    # survives a cold reload.
    session = combat._load_session(mid)
    engine = session.engine
    assert any(e.event_type == "SAVE_ROLLED"
               and e.payload.get("reason") == "SAVE:TAL_LIGHTNING_STATIC_GUARD:CON"
               for e in engine.events)
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"

    # Static Guard's rider -- "the attacker cannot take Opportunity Attacks against
    # you until the end of the current turn" -- is the row the typed data now pins
    # to the current turn. Apply that row to the attacker through the engine's own
    # executor, from the compiled authority the service runs. (The Reaction context's
    # "attacker" subject is a separate open defect -- see the lane report -- so the
    # rider is applied to the attacker directly here; the expiry under test is the
    # rider's own.)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    authority = json.loads((ROOT / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())
    static_guard = authority["mechanics"]["TAL_LIGHTNING_STATIC_GUARD"]
    def find_reaction_denied(node):
        if isinstance(node, dict):
            if node.get("type") == "reaction_denied" and "Opportunity Attacks" in str(node.get("on") or ""):
                yield node
            for value in node.values():
                yield from find_reaction_denied(value)
        elif isinstance(node, list):
            for value in node:
                yield from find_reaction_denied(value)

    def _is_end_turn(candidate):
        return getattr(candidate.kind, "value", candidate.kind) == "END_TURN"

    rider = next(find_reaction_denied(static_guard))
    action = next(iter(engine.action_catalog.values()))
    step = next(c for c in engine.legal_candidates() if _is_end_turn(c))
    intent = ActionIntent(intent_id="intent:ueot-rider", actor_id=engine.state.current_actor_id,
                          decision_id=step.decision_id, candidate_id=step.candidate_id,
                          state_version=engine.state.state_version, target_ids=[foe.entity_id])
    typed_executor.run_effects(
        typed_executor.Context(engine, owner, action, intent, static_guard, [foe], foe), [rider])

    def no_opportunity(engine_):
        return [c for c in engine_.state.actors[FOE].conditions.values()
                if c.condition_id == "condition:typed.no_opportunity_attacks"]

    guard, = no_opportunity(engine)
    assert guard.expires_on == "END_OF_CURRENT_TURN", guard.expires_on

    def end_turn(engine_):
        turn = next(c for c in engine_.legal_candidates() if _is_end_turn(c))
        return engine_.execute_intent(ActionIntent(
            intent_id=f"intent:ueot-end-{engine_.state.state_version}",
            actor_id=engine_.state.current_actor_id,
            decision_id=turn.decision_id, candidate_id=turn.candidate_id,
            state_version=engine_.state.state_version))

    # It ends at the end of the turn it was used in -- the engine's own
    # end-of-turn boundary, through execute_intent -- and does not last
    # until after the attacker's next turn.
    end_turn(engine)
    assert not no_opportunity(engine), "the denial must end at the end of the turn it was used in"
    for _ in range(len(engine.state.actors) * 2):
        actor = engine.state.current_actor_id
        end_turn(engine)
        assert not no_opportunity(engine), "the denial must not survive to the attacker's next turn"
        if actor == FOE:
            break


@pytest.mark.parametrize("mechanic,evidence", [
    ("TAL_LIGHTNING_STATIC_GUARD", "Opportunity Attacks against you until the end of the current turn"),
    ("TAL_LIGHTNING_CHARGED_NEEDLE", "cannot regain CP until the end of the current turn"),
    ("TAL_EARTH_EARTHBIND_LINE", "Speed is reduced by 10 feet until the end of the turn"),
    ("tianxia.talent.space.spatial_domain", "Speed becomes 0 until the end of the current turn"),
    ("tianxia.talent.space.spatial_domain", "Speed is reduced by 10 feet until the end of the current turn"),
    ("tianxia.talent.puppetry.knot_the_knee", "Speed is reduced by 10 feet until the end of the current turn"),
    ("TAL_AXES_ARMOR_JOINT_HOOK", "your next attack roll against the target gains a +2 bonus"),
])
def test_printed_current_turn_rows_carry_the_explicit_expiry(mechanic, evidence):
    """Every row that prints "the current/this turn" and is typed ``until_end_of_turn`` carries the
    explicit end-of-current-turn expiry, so the typed duration no longer contradicts its text."""
    authority = json.loads((ROOT / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())
    matching, carried = [], []

    def walk(node):
        if isinstance(node, dict):
            if (node.get("duration") == "until_end_of_turn"
                    and evidence in str(node.get("evidence") or "")):
                matching.append(node)
                if node.get("expires_on") == "END_OF_CURRENT_TURN":
                    carried.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(authority["mechanics"][mechanic])
    assert matching, f"{mechanic}: no until_end_of_turn row prints {evidence!r}"
    assert len(carried) == len(matching), (
        f"{mechanic}: {len(matching) - len(carried)} of {len(matching)} row(s) printing "
        f"{evidence!r} are still typed until_end_of_turn without expires_on END_OF_CURRENT_TURN")
