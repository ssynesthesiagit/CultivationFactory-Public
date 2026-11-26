"""MMX71r review: a reroll/rewrite prompt must describe the roll it is actually about.

The pre-merge review of the DS12 #1 prompt fix (bd2fd617) found three defects in one sentence: it read
the roll out of the journal instead of carrying it, called every outcome a failure, and called the
rolling creature the creature that was hit. None of them is observable in a hand-built prompt dict,
so these tests use the real paths.

* Finding 1 is driven through the whole table (``TabletopService`` over a real saved fight): two saves
  in a row, the second one on offer for a reroll, then the answer is committed and the fight is
  reloaded from disk with a fresh ``CombatService``.
* Findings 2 and 3 use a real compiled character in a real engine and the real consent hook
  (``ext.d20_rewrite._consent``), then build the prompt exactly as the service does -- the trigger
  transport, ``build_reaction_context`` and ``build_decision_text`` -- so the text is the one a
  player is shown. (Both abilities are ones this review found the wording wrong for: Invoke the
  Omen / Sever One Thread rewrite any roll, Empty Cup rewrites a foe's attack.)
"""
import json
import zipfile

import pytest

from combat.decision_text import build_decision_text
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate4_context import build_reaction_context
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.prepared_actions import SOURCE
from combat.reaction_trigger import contextual_request
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import FOE, ME, attack, duel, force_save, give
from tests.test_factory_combat_compiler import SHEET
from tests.test_factory_live_match import ROOT
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install

BROKEN_GOURD = "TAL_DRUNKEN_STYLE_BROKEN_GOURD_RECOVERY"
SEVER = "tianxia.tradition.spirit.fate_reader.feature.sever_one_thread"
# The Empty Cup Stance talent compiles nothing on its own; the ability is this Drunken Fist feature.
EMPTY_CUP = "tianxia.subpath.body.drunken_fist.feature.empty_cup"
# Flowing River's Flowing Response is what makes this fighter an Ask me reactor at the table; a rewrite
# ability is a passive row and never makes a character askable by itself.
ASKABLE_SPHERE, ASKABLE_TALENT = "tianxia.sphere.flowing_river", "TAL_FLOWING_RIVER_FLOWING_RESPONSE"
HOLD = "system:combat.hold_position"
PLAYER = "3b1f7c52-0d6e-4a48-9b7a-2f5d81c04e19"
RIVAL = "9a4e2d61-7c38-4f05-b1d2-6e0a93b57c48"


# ------------------------------------------------------------------------------ the real table (finding 1)
def _sheet(*, spheres=(), talents=(), features=(), primary=None, maximum=40):
    """The shared owner sheet, with exactly the ability this case needs and nothing else."""
    sheet = json.loads(json.dumps(SHEET))
    block = sheet["spheres_and_talents"]
    block["sphere_record_ids"] = [*block["sphere_record_ids"], ASKABLE_SPHERE, *spheres]
    block["learned_talent_record_ids"] = [*block["learned_talent_record_ids"], ASKABLE_TALENT, *talents]
    if primary:
        sheet["ability_scores_and_statistics"]["primary_resource"] = json.dumps({"name": primary, "maximum": maximum})
    if features:
        sheet["path_and_subpath"] = {"path_feature_record_ids": [*features]}
    return sheet


def _table(tmp_path, monkeypatch, sheet, force):
    """A real table that pauses for a rewrite consent, and the prompt the player is shown.

    ``force`` runs inside the table's own commit (a synthetic Ready) and makes the roll under test
    through the engine's own save code, so the consent that pauses the fight is production's.
    """
    for side, character in ((PLAYER, sheet), (RIVAL, _sheet())):
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(character))
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(PLAYER, {"mode": "ask"}, set())
    install(monkeypatch, "prepare_options", lambda *a: [{"option_id": "save", "source_id": "test:save", "label": "Save on hold",
                                                          "trigger": "HOLD_POSITION_COMMITTED"}])
    install(monkeypatch, "prepared_trigger", lambda *a: True)
    install(monkeypatch, "prepared_action", lambda engine, actor, option, event, intent: force(engine, actor) or True)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "H1 yard", "width_squares": 12, "height_squares": 8, "walls": [],
                               "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    modes = {FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in (PLAYER, RIVAL)}
    mid = combat.create_factory_match(project_ids=[PLAYER], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + RIVAL],
                                      control_modes=modes, arena_id="battlefield:map.h1-yard", match_seed="H1-TABLE")["match_id"]
    table = TabletopService(combat, tmp_path)
    state = table.state(mid)
    assert state["menu"].get("actions"), "the player's turn never opened: " + str(state["menu"])[:200]
    actor_id = state["menu"]["actor_id"]
    assert act(table, mid, SOURCE)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    held = act(table, mid, HOLD)
    assert held["status"] == "REACTION_REQUIRED"
    menu = held["state"]["menu"]
    candidate = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD)
    answers = [{**held["reaction"]["context"], "selection": "USE"}]
    asked = table.act(mid, candidate, menu["decision_id"], menu["state_version"], held["state"]["last_sequence"], answers)
    assert asked["status"] == "REACTION_REQUIRED", f"the table never asked about the roll: {asked['status']}"
    return combat, table, mid, actor_id, asked, answers


def _commit(tmp_path, table, mid, asked, answers):
    """Commit the player's Use, then reload the fight from disk.

    A later Ask me ability of the same commit asks as well; the table is answered again (declining
    that one) with every answer so far, because a paused commit is retried as a whole.
    """
    asked = {"reaction": asked["reaction"], "state": asked["state"]}
    selection = "USE"
    for _ in range(6):
        reaction, menu = asked["reaction"], asked["state"]["menu"]
        candidate = next(g["options"][0]["candidate_id"] for g in menu["actions"]
                         if g["source_definition_id"] == HOLD)
        answers = [*answers, {**reaction["context"], "selection": selection}]
        result = table.act(mid, candidate, menu["decision_id"], menu["state_version"], asked["state"]["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return CombatService(ROOT, tmp_path)._load_session(mid)
        asked, selection = result, "DECLINE"
    raise AssertionError("the table never settled: " + str(result["status"]))


def test_the_prompt_names_the_current_save_and_not_an_earlier_one(tmp_path, monkeypatch):
    """Finding 1: two saves in a row; the prompt must describe the second, the one on offer.

    The first save is already in the journal when the second asks for a reroll. Reading the journal
    instead of carrying the roll showed the first save's ability and its DC.
    """
    def force(engine, actor):
        # Outcomes are forced with the DC, not by editing the fighter, so the typed journal still
        # replays to the same post-state. This fighter's Wisdom is +0, so every d20 beats 1; a d20
        # plus the +2 Dexterity is never 60.
        engine._roll_save(actor, "WIS", 1, "typed:some.hazard")        # recorded, and it succeeded
        engine._roll_save(actor, "DEX", 60, "typed:some.hazard")       # recorded, and it failed

    combat, table, mid, actor_id, asked, answers = _table(
        tmp_path, monkeypatch, _sheet(spheres=["tianxia.sphere.drunken_style"], talents=[BROKEN_GOURD]), force)
    me = combat._load_session(mid).engine.state.actors[actor_id]
    said = str(asked["reaction"]["trigger"])
    # The roll this prompt is about: the failed Dexterity save against DC 60 that is on offer.
    assert said == f"{me.display_name} failed a Dexterity saving throw (DC 60) from Hazard."
    # The earlier, successful Wisdom save is in the journal too; it is not this prompt's roll.
    assert "Wisdom" not in said and "actor:" not in said and "typed:" not in said

    # The answer commits and the fight reloads from disk as a faithful, replayable fight.
    loaded = _commit(tmp_path, table, mid, asked, answers)
    assert loaded.engine.state.actors[actor_id].entity_id == actor_id
    assert loaded.mechanical.replay()["status"] == "PASS"


# ------------------------------------------------------------------ the real consent hook and the service's own text
def _prompt_text(engine, requests, reaction_name):
    """The text the table shows for a rewrite consent, built exactly as ``TabletopService._reaction_prompt`` builds it."""
    request = next(r for r in requests if str(r["checkpoint"]).startswith("TYPED:D20_"))
    policies = PolicyLibrary(ROOT)
    policy, _ = policies.for_actor(str(request["reactor_id"]))
    context = build_reaction_context(engine, policy, request).model_dump(mode="json")
    actors = {actor.entity_id: actor.display_name for actor in engine.state.actors.values()}
    prompt = {"reactor": actors[context["reactor_id"]], "reaction": reaction_name,
              "moment": context["checkpoint"], "by": "", "action": ""}
    # The table resolves the triggering source through its real action catalog.
    definitions = {source: action.display_name for source, action in engine.action_catalog.items()}
    return build_decision_text(engine, context, prompt, actors, definitions, {})["trigger"]


def _ask_on(engine, roll):
    """Make ``roll`` with this fighter set to Ask me, and return the consents the real hook asked.

    The roll runs under an active intent because that is where the engine reads a reaction answer
    from (``typed_reactions._consent``): with no intent and no service provider, a consent is simply
    not used, which is the AI path, not the one under test.
    """
    asked = []

    def provider(request):
        # The service enriches the request with the trigger scope while the consent is open
        # (gate5_service's provider), so the roll's metadata is captured here, not reconstructed later.
        asked.append(contextual_request(engine, request))
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE"), None

    engine.typed_ask_reactors = frozenset({ME})
    engine.set_reaction_provider(provider)
    previous = getattr(engine, "_active_intent", None)
    engine._active_intent = ActionIntent(intent_id="i-mmx71r", decision_id="d-mmx71r", candidate_id="c-mmx71r",
                                         state_version=engine.state.state_version, actor_id=ME, target_ids=())
    try:
        roll()
    finally:
        engine._active_intent = previous
    return asked


def test_a_successful_roll_offered_for_rewriting_is_not_called_a_failure():
    """Finding 2: a rewrite that fires on any roll must report the roll's real outcome.

    Sever One Thread offers to rewrite any roll in reach, and the rival's save succeeded. Calling it
    a failed save would tell the player to decline a rewrite worth making.
    """
    engine = duel(SEVER, primary="Resonance")
    give(engine, ME, resonance=30)
    # The rival's Wisdom is +0, so every d20 beats DC 1: the save succeeds, and is still on offer.
    asked = _ask_on(engine, lambda: force_save(engine, FOE, "WIS", dc=1, source_id="typed:some.hazard"))
    assert [r["checkpoint"].split("@")[0] for r in asked] == ["TYPED:D20_REWRITE_ROLL"], asked
    said = _prompt_text(engine, asked, "Sever One Thread")
    assert said == f"{engine.state.actors[FOE].display_name} succeeded at a Wisdom saving throw (DC 1) from Hazard."
    assert "failed" not in said and "actor:" not in said


@pytest.mark.parametrize("source_id, action_name", [
    ("action:an_eui.paired_bi_shou_assault", "Paired Bi Shou Assault"),
    ("action:an_eui.paired_strike", "Paired Strike"),
])
def test_an_enemy_attack_prompt_names_the_attacker_and_who_was_hit(source_id, action_name):
    """Finding 3: the transported target of a rewrite is the roller, so the victim must come from the roll.

    Empty Cup makes the foe reroll an attack that hit the fighter. The prompt used to read as if the
    attacker had been hit by its own attack.
    """
    engine = duel(EMPTY_CUP, primary="Stamina")   # Empty Cup costs Stamina 2
    give(engine, ME, stamina=10)
    assert engine.action_catalog[source_id].display_name == action_name
    # The rival's attack bonus is far above the fighter's Armour Class, so it hits.
    asked = _ask_on(engine, lambda: attack(engine, FOE, ME, bonus=50, source_id=source_id))
    assert "TYPED:D20_REROLL_ATTACK" in [r["checkpoint"].split("@")[0] for r in asked], asked
    said = _prompt_text(engine, asked, "Empty Cup")
    assert said == (f"{engine.state.actors[FOE].display_name}'s attack roll for {action_name} "
                    f"against {engine.state.actors[ME].display_name} hit.")
    assert "was hit" not in said and "missed" not in said
    assert "action:" not in said
