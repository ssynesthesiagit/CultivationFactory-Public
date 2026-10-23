"""SOL124f1: real paid Sword attacks, AI-turn reactions and saved table deadlines."""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests import test_ocf8_sword_core as S

PROJECTS = ["f100000a", "f100000b", "f100000c"]
IDS = ["actor:factory." + p for p in PROJECTS]


def fixture(tmp_path, seed, *, two_owners, owner_first=True, extra_reaction=False):
    projects = PROJECTS if two_owners else [PROJECTS[0], PROJECTS[2]]
    bundles = []
    for project in projects:
        target = project == PROJECTS[2]
        S._table_sheet(tmp_path, project=project, hp=800,
                       cl=20 if target else 15 if extra_reaction else 5 if project == PROJECTS[0] else 10,
                       talents=(S.TRAINING, S.LIFE_SEVERING, "TAL_GUARDIAN_ADAMANT_GUARDIAN_INCARNATION")
                       if extra_reaction else (S.TRAINING, S.LIFE_SEVERING),
                       spheres=() if target else (S.SWORD_SPHERE,),
                       path_features=(S.IMMORTAL_BODY,) if target else ())
        with zipfile.ZipFile(tmp_path / "portable_characters" / project / "current.zip") as z:
            doc = json.loads(z.read("Tianxia_Owner_Character_Sheet_v1.json"))
        doc["identity"]["proficiency_bonus"] = 3 if project == PROJECTS[0] else 4
        doc["ability_scores_and_statistics"]["initiative"] = {
            "bonus": 0 if target else (100 if project == PROJECTS[0] else 50) if two_owners
            else 100 if owner_first else -100}
        with zipfile.ZipFile(tmp_path / "portable_characters" / project / "current.zip", "w") as z:
            z.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundles.append(compile_character(doc, actor_id="actor:factory." + project, reaction_plan={"ask": True}))
        ButtonStore(tmp_path / "tabletop_buttons").save_reactions(project, {"mode": "ask"}, set())
    combat = CombatService(S.ROOT, tmp_path)
    arena = combat.tabletop_maps.save({"display_name": "Sword review yard", "width_squares": 12,
        "height_squares": 10, "walls": [], "starts": {"team1": [[4, 3], [4, 4]], "team2": [[3, 3]]}})
    ids = ["actor:factory." + p for p in projects]
    owners, target = ids[:-1], ids[-1]
    mid = combat._finish_factory_match(bundles, ids,
        {aid: "team:opponents" if aid == target else "team:factory" for aid in ids},
        dict(zip(ids, [{"x": 4, "y": 3}, {"x": 4, "y": 4}, {"x": 3, "y": 3}] if two_owners
                 else [{"x": 4, "y": 3}, {"x": 3, "y": 3}])),
        combat.factory_arenas()["battlefield:map." + arena["map_id"]], owners, [target],
        control_modes={aid: "LOCAL_AUTO" if aid == target else "MANUAL" for aid in ids},
        match_seed=seed, maximum_rounds=6, display_name=seed)["match_id"]
    production = combat.controller

    class WaitingAI:
        """Keep the target adjacent until the test's explicit movement trigger."""

        def choose_primary_action(self, context):
            end = next((c for c in context.legal_candidates if c.kind == "END_TURN"), None)
            if end is None:
                return production.choose_primary_action(context)
            return ManualControllerAdapter(lambda _: (end.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(production, name)

    combat.controller = WaitingAI()
    return combat, TabletopService(combat, tmp_path), mid, owners, target


def reload(combat, tmp_path, mid):
    saved = combat._load_session(mid)
    fresh = CombatService(S.ROOT, tmp_path)._load_session(mid)
    assert saved.engine.state.model_dump(mode="json") == fresh.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"
    return fresh.engine


def reductions(engine, target):
    return {mid: m for mid, m in engine.state.actors[target].modifiers.items()
            if m.target_field == "healing_reduction"}


def advance(table, mid, state, *, want="Broken concentration", asked=None):
    if state["menu"].get("manual"):
        return S._press(table, mid, state["menu"], state, want=want, asked=asked)
    answers = []
    for _ in range(12):
        response = table.auto_step(mid, state["last_sequence"], answers)
        if response["status"] != "REACTION_REQUIRED":
            assert response["status"] == "COMMITTED", response
            return response
        prompt = response["reaction"]
        if asked is not None:
            asked.append(prompt)
        options = (prompt.get("choice") or {}).get("options") or []
        picked = next((o for o in options if want in o["label"]), options[0] if options else None)
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [picked["id"]] if picked else []})
    raise AssertionError("unbounded reaction prompts")


def test_two_sword_owners_keep_the_first_reduction_and_heal_after_reload(tmp_path):
    combat, table, mid, owners, target = fixture(tmp_path, "F1-TWO", two_owners=True)
    struck, retained, pb = [], None, None
    for _ in range(70):
        state = table.state(mid)
        actor = state["menu"]["actor_id"]
        if actor in owners and actor not in struck:
            state, option = S._configure_sword_strike(combat, table, mid, state, target)
            if option:
                asked = []
                S._press(table, mid, state["menu"], state, candidate=option[1],
                         want="Broken concentration" if not struck else "Halved healing", asked=asked)
                assert any(p["reaction"] == "Life-Severing Sword" for p in asked)
                engine = reload(combat, tmp_path, mid)
                mods = reductions(engine, target)
                if not struck:
                    assert len(mods) == 1
                    retained = next(iter(mods))
                    pb = int(mods[retained].value.split(":")[1])
                else:
                    assert retained in mods, "second owner's choice removed the first owner's reduction"
                    assert sorted(m.value for m in mods.values()) == ["half", f"minus:{pb}"]
                    assert mods[retained].source_actor_id == struck[0]
                    other_pb = 3 if actor == IDS[0] else 4
                    assert pb != other_pb
                    # A real 20-HP Immortal Body grant occurs at the target's
                    # next start, before either swordsman's next start.
                    before = engine.state.actors[target].current_hp
                    break
                struck.append(actor)
                continue
        advance(table, mid, state)
    else:
        pytest.fail("both owners did not strike before their effects expired")
    for _ in range(20):
        state = table.state(mid)
        if state["menu"]["actor_id"] == target:
            engine = reload(combat, tmp_path, mid)
            assert retained in reductions(engine, target)
            assert engine.state.actors[target].current_hp == before + (20 - pb) // 2
            return
        advance(table, mid, state)
    pytest.fail("target's regeneration turn was not reached")


@pytest.mark.parametrize("owner_first", [True, False])
def test_manual_opportunity_choice_on_ai_turn_expires_at_swordsmans_next_start(tmp_path, owner_first):
    # Production deterministic dice: these seeds hit on both the marking strike
    # and the Opportunity Attack, so the regression reaches the paid choice.
    seed = f"F1-OFF-{int(owner_first)}-C"
    combat, table, mid, owners, target = fixture(tmp_path, seed, two_owners=False, owner_first=owner_first)
    owner = owners[0]
    production = combat.controller
    # Supported AI primary-action transport; production reaction decisions are
    # unchanged. Move out of the Jian's reach once, then end the AI turn.
    class MovingAI:
        def choose_primary_action(self, context):
            candidates = list(context.legal_candidates)
            moves = [c for c in candidates if c.kind == "MOVE" and c.destination]
            selected = max(moves, key=lambda c: abs(c.destination.x - 4) + abs(c.destination.y - 3), default=None)
            actor = next(a for a in context.actors if a.entity_id == context.active_actor_id)
            if actor.position.x != 3 or actor.position.y != 3 or selected is None:
                selected = next(c for c in candidates if c.kind == "END_TURN")
            return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(production, name)

    configured = False
    for _ in range(40):
        state = table.state(mid)
        if state["menu"]["actor_id"] == owner:
            state, option = S._configure_sword_strike(combat, table, mid, state, target)
            if option:
                # Place this swordsman's Intent using the real paid ranged hit.
                S._press(table, mid, state["menu"], state, candidate=option[1], want="Broken concentration")
                # The compiled Opportunity Attack asks for its paid-hit rider
                # inside the reaction, rather than using a weapon setting.
                configured = True
                order = combat._load_session(mid).engine.state.initiative_order
                assert (order.index(owner) < order.index(target)) == owner_first
                combat.controller = MovingAI()
                break
        advance(table, mid, state)
    assert configured
    prompts = []
    for _ in range(20):
        state = table.state(mid)
        advance(table, mid, state, want="Halved healing", asked=prompts)
        if any(any("Halved healing" in o["label"] for o in (p.get("choice") or {}).get("options", []))
               for p in prompts):
            assert state["menu"]["actor_id"] == target and not state["menu"]["manual"]
            assert any(p["reaction"] == "Opportunity Attack" for p in prompts)
            engine = reload(combat, tmp_path, mid)
            half = next(m for m in reductions(engine, target).values() if m.value == "half")
            assert half.expires_on != "START_OF_SOURCE_NEXT_TURN"
            deadline = engine.state.actors[owner].turns_started + 1
            break
        if not state["menu"]["manual"]:
            events = combat._load_session(mid).engine.events
            attacks = [e.payload for e in events if e.event_type == "ATTACK_ROLLED"
                       and e.source_definition_id.endswith(".opportunity_attack")]
            pytest.fail(f"AI movement did not deliver the extra choice: {attacks}; prompts={prompts}")
    else:
        pytest.fail("manual swordsman's AI-turn extra choice never occurred")
    for _ in range(20):
        engine = combat._load_session(mid).engine
        if engine.state.actors[owner].turns_started == deadline:
            engine = reload(combat, tmp_path, mid)
            assert engine.state.current_actor_id == owner
            assert not any(m.value == "half" for m in reductions(engine, target).values())
            return
        assert any(m.value == "half" for m in reductions(engine, target).values())
        advance(table, mid, table.state(mid))
    pytest.fail("swordsman's next start was not reached")
