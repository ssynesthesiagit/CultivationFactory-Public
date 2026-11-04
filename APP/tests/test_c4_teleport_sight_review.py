"""Reaction steps offer only visible cells through real table transactions."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext.teleport_steps import destinations
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE
from tests.test_r1i_round3 import reload
from tests.test_c4_path_step_review import TALENTS, scenario
from tests.test_c4_protection_review import inherited_prompt_loader


def obscured_miss(kind):
    """Deliver a persisted zone/condition before the compiled reaction checkpoint."""
    def prepare(bundles):
        scenario("Qi", 3, True)(bundles)
        base_kind, _, sense = kind.partition("__")
        if sense:
            owner = bundles[0]
            owner["senses"] = {"rows": [{"sense": sense, "range_ft": 20, "when": "always"}]}
            owner.pop("bundle_sha256", None)
            owner["bundle_sha256"] = canonical_sha256(owner)
        foe = bundles[1]
        for action in foe["action_catalog"]:
            if not action["display_name"].startswith("Void Needle"):
                continue
            typed = action["parameters"]["typed"]
            if base_kind == "blinded":
                typed["effects"].insert(0, {"type": "condition", "condition": "blinded",
                    "applies_to": "target", "expires_on": "UNTIL_REMOVED"})
            elif base_kind != "clear":
                typed["zone_spec"] = {"name": "Darkness" if base_kind != "heavy" else "Heavy fog",
                    "shape": "sphere", "size_ft": 60 if base_kind == "all_dark" else 5,
                    "centered_on_self": True, "duration": {"kind": "minutes", "amount": 1},
                    "obscured": "heavy", "visual": {"darkness": base_kind != "heavy"}}
                # Reviewed area occlusion leaves pockets behind pillars. This
                # synthetic whole-map darkness must spread around corners.
                if base_kind == 'all_dark':
                    typed['zone_spec']['spreads'] = True
                typed["effects"].insert(0, {"type": "zone"})
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)
    return prepare


@pytest.mark.parametrize("kind", ["clear", "darkness", "heavy", "all_dark", "blinded",
    "blinded__blindsight", "darkness__darkvision", "all_dark__blindsight"])
@pytest.mark.parametrize("mode", ["manual", "ai_attacker", "ai_both"])
def test_reaction_step_visible_destinations_pause_commit_reload(tmp_path, monkeypatch, kind, mode):
    # This test exercises the reaction to a rolled AC miss, after passing the
    # owner's new concealment check. A concealment miss has no attack d20.
    from combat import ext
    from tests.h1_support import script
    def pass_concealment(engine, attacker, defender, intent, context):
        from combat.targeting import concealment_percent
        script(engine, [100, 2, 2] if concealment_percent(engine, attacker, defender) else [2, 2])
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'before_attack', [*ext._HOOKS.get('before_attack', []), pass_concealment])
    combat, table, mid, send, commit = fixture(tmp_path, TALENTS, owner_ac=500,
        foe_talents=["TAL_VOID_VOID_NEEDLE"], seed="C4-SIGHT",
        bundle_transform=obscured_miss(kind), wide=kind.startswith("all_dark"))
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    if mode == "ai_both":
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    cid = candidate(table, mid, "Void Needle", OWNER)
    auto = mode != "manual"
    if auto:
        force_ai_candidate(combat, mid, FOE, cid)
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    answers, prompts, picked = [], [], None
    for _ in range(4):
        result = send(cid, answers, auto=auto)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        prompts.append(p)
        assert reload(tmp_path, mid).state.model_dump(mode="json") == before
        assert send(cid, answers, auto=auto)["reaction"] == p
        answer = {**p["context"], "selection": "USE"}
        if p.get("choice"):
            assert p["context"]["reaction_source_id"] == "choice:needle.reaction_teleport"
            assert kind not in ("all_dark", "blinded")
            offered = [o["id"] for o in p["choice"]["options"]]
            if kind in ("darkness", "heavy"):
                # The actual pre-attack zone is a five-foot sphere at 4,6.
                assert not {"cell:4,5", "cell:5,6", "cell:4,7"} & set(offered)
            picked = p["choice"]["preferred"][0]
            answer["option_ids"] = [picked]
        answers.append(answer)
    else:
        pytest.fail("reaction did not commit")
    engine = reload(tmp_path, mid)
    bearer = engine.state.actors[OWNER]
    moved = bearer.position.model_dump(mode="json") != before["actors"][OWNER]["position"]
    assert moved == (kind not in ("all_dark", "blinded"))
    assert len(prompts) == (0 if mode == "ai_both" else 1 if not moved else 2)
    assert bearer.resources["resource:core.qi"] == 2
    assert not bearer.reaction_available
    if picked:
        assert picked == f"cell:{bearer.position.x},{bearer.position.y}"
    if kind.startswith("blinded"):
        assert any(c.condition_id == "condition:typed.blinded" for c in bearer.conditions.values())
        if kind == "blinded":
            assert destinations(engine, bearer, 20) == []
        else:
            assert destinations(engine, bearer, 20)
    elif kind != "clear":
        assert any(e.event_type == "ZONE_CREATED" for e in engine.events)
        if moved and "__" not in kind:
            assert not any((bearer.position.x, bearer.position.y) in {(c.x, c.y) for c in z.affected_cells}
                           for z in engine.state.zones.values())
