"""F2: Opening Phrase consumption with real earlier event hooks and saved table transactions."""
import pytest

from combat.factory_compiler import compile_character
from combat.gate2_engine import SYSTEM_CONCENTRATION
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_persistence import Gate4Persistence
from combat.gate4_policy import PolicyLibrary
from combat import ext
from combat.ext import music
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

SINGER, OWNER, ATTACKER = [f"actor:factory.f2_{name}" for name in ("singer", "owner", "attacker")]


@pytest.fixture(autouse=True)
def module_order(monkeypatch):
    # Other test modules may eagerly import Music. Exercise the normal alphabetical plug-in load order,
    # using the real callbacks, and restore the registry afterwards.
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", sorted(ext._HOOKS["event"], key=lambda fn: fn.__module__))


def submit(session, name, target=None, at=None):
    candidates = [c for c in session.engine.legal_candidates()
                  if (c.display_name == name or c.display_name.startswith(name + " at "))
                  and (target is None or target in c.target_ids)
                  and (at is None or c.destination and (c.destination.x, c.destination.y) == at)]
    assert candidates, (name, sorted({c.display_name for c in session.engine.legal_candidates()}))
    c = candidates[0]
    intent = ActionIntent(intent_id=f"f2-{c.state_version}-{name}", decision_id=c.decision_id,
                          candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
                          target_ids=c.target_ids, destination=c.destination)
    before = len(session.engine.events)
    session.submit_intent(intent, primary_decision_record=None, reaction_provider=None)
    return session.engine.events[before:]


def fixture(tmp_path, interaction, attack_count=1):
    mids = (["FORMATIONS_BASE_SET_ARRAY", "tianxia.talent.formations.elemental_killing_array"]
            if interaction == "formation" else ["TAL_MONKEY_STYLE_THOUSAND_MONKEY_UPRISING"])
    singer = compile_character(sheet([music.KEEP, music.OPENING, music.M + "captivating_melody"], cl=20), actor_id=SINGER)
    owner = compile_character(sheet(mids, cl=20, kit={"starting_kit": KIT}), actor_id=OWNER)
    attacker = compile_character(sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], cl=20,
                                       kit={"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "quantity": 1}]}}),
                                 actor_id=ATTACKER)
    for bundle, initiative in ((owner, 300), (singer, 200), (attacker, 100)):
        bundle["actor_template"].update(maximum_hp=5000, armor_class=0, initiative_bonus=initiative)
        bundle["actor_template"]["saving_throws"].update(CON=100, WIS=100)
        for action in bundle["action_catalog"]:
            if bundle is attacker and action["display_name"] == "Fu (Short Axe) thrown":
                # Keep this repeat-attack fixture on melee: throwing leaves the
                # held axe on the map, so a second attack would require recovery.
                # The real local controller still chooses its move and attack.
                action["parameters"]["player_only"] = True
            typed = action["parameters"].get("typed")
            if typed:
                typed["numbers"]["attack_bonus"] = 100
                if bundle is attacker:
                    for effect in typed.get("effects") or []:
                        if effect.get("type") == "attack":
                            effect["count"] = attack_count
    if interaction == "monkey":
        singer["actor_template"]["saving_throws"]["CON"] = -100
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C14-F2-interactions", typed_bundles=(singer, owner, attacker), roster_setup={
        "primary_actor_ids": [OWNER, SINGER, ATTACKER],
        "team_by_actor": {OWNER: "team:b", SINGER: "team:a", ATTACKER: "team:b"},
        "starting_positions": {OWNER: {"x": 3, "y": 6}, SINGER: {"x": 4, "y": 6},
                               ATTACKER: {"x": 4, "y": 7}}})
    assert session.engine.state.current_actor_id == OWNER
    if interaction == "formation":
        submit(session, "Next Killing Line: Blood or Poison")
        submit(session, "Combat Array: Killing Line (Fire)", at=(3, 6))
    else:
        submit(session, "Thousand-Monkey Uprising")
    submit(session, "End turn")
    submit(session, "Keep the Measure")
    submit(session, "End turn")
    submit(session, "End turn")
    if interaction == "formation":
        submit(session, "Pulse: Killing Line", target=SINGER)
        assert any(c.condition_id.endswith(".formation_weak_con")
                   for c in session.engine.state.actors[SINGER].conditions.values())
    submit(session, "End turn")
    submit(session, "Captivating Melody", target=OWNER)
    submit(session, "Opening Phrase: Concentration Save", target=SINGER)
    submit(session, "End turn")
    assert session.mechanical.verify()["status"] == "PASS"
    return persistence, persistence.load_match(session.match_id)


def test_two_concentration_saves_in_one_activation_get_the_bonus_only_once(tmp_path):
    # A compiled two-strike fixture proves consumption before the Phrase's natural deadline.
    persistence, session = fixture(tmp_path, "formation", attack_count=2)
    singer = session.engine.state.actors[SINGER]
    events = attack(session, False)
    saves = [e.payload for e in events if e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == SYSTEM_CONCENTRATION]
    assert [p["modifier"] for p in saves] == [singer.saving_throws["CON"] + singer.proficiency_bonus,
                                             singer.saving_throws["CON"]]
    assert [p["mode"] for p in saves] == ["DISADVANTAGE", "NORMAL"]
    assert session.mechanical.verify()["status"] == "PASS"
    session = persistence.load_match(session.match_id)
    assert not any(c.condition_id == music.OPENING_SAVE for c in session.engine.state.actors[SINGER].conditions.values())


def attack(session, ai):
    if not ai:
        return submit(session, "Fu (Short Axe) attack", target=SINGER)
    engine = session.engine
    policy = PolicyLibrary(ROOT).for_actor(ATTACKER)[0]
    # This consumption regression needs two weapon attacks. The generic ranged
    # preference throws the only axe, then cannot repeat without picking it up.
    # Supply a melee preference through the normal policy contract, preserving
    # the real controller, rolls, event hooks and saved decision records.
    melee = next(a.source_definition_id for a in engine.action_catalog.values()
                 if a.owner_id == ATTACKER and a.display_name == "Fu (Short Axe) attack")
    policy = policy.model_copy(update={"preferred_range_bands_ft": ((0, 5),),
                                       "action_priorities": {**policy.action_priorities, melee: 100}})
    before = len(engine.events)
    for _ in range(12):
        choice = LocalDeterministicController().choose_primary_action(build_decision_context(engine, policy, for_ai=True))
        picked = next(c for c in engine.legal_candidates() if c.candidate_id == choice.intent.candidate_id)
        session.submit_intent(choice.intent, primary_decision_record=choice.record, reaction_provider=None)
        if picked.display_name in ("Fu (Short Axe) attack", "Fu (Short Axe) thrown"):
            assert SINGER in picked.target_ids
            return engine.events[before:]
        assert picked.display_name.startswith("Move to ")
    raise AssertionError("AI did not attack")


@pytest.mark.parametrize("interaction", ["formation", "monkey"])
@pytest.mark.parametrize("ai", [False, True], ids=["manual", "automatic-ai"])
def test_opening_phrase_consumed_despite_earlier_hook_events_commit_reload_and_replay(tmp_path, interaction, ai):
    persistence, session = fixture(tmp_path, interaction)
    singer = session.engine.state.actors[SINGER]
    assert any(c.condition_id == music.OPENING_SAVE for c in singer.conditions.values())
    events = attack(session, ai)
    (save,) = [e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == SYSTEM_CONCENTRATION]
    assert save.payload["modifier"] == singer.saving_throws["CON"] + singer.proficiency_bonus
    if interaction == "formation":
        assert save.payload["mode"] == "DISADVANTAGE"
        assert any(e.sequence > save.sequence and e.event_type == "CONDITION_REMOVED"
                   and e.payload["condition_id"].endswith(".formation_weak_con") for e in events)
    else:
        assert save.payload["success"] is False
        assert any(e.sequence > save.sequence and e.event_type == "CONDITION_APPLIED"
                   and "monkey" in e.payload["condition_id"] for e in events)
    assert not any(c.condition_id == music.OPENING_SAVE for c in singer.conditions.values())
    assert session.mechanical.verify()["status"] == "PASS"
    session = persistence.load_match(session.match_id)
    assert not any(c.condition_id == music.OPENING_SAVE for c in session.engine.state.actors[SINGER].conditions.values())
    submit(session, "End turn")
    submit(session, "End turn")
    if interaction == "monkey":  # the first failed save ended the Melody; concentrate again, without another Phrase
        submit(session, "Captivating Melody", target=OWNER)
    submit(session, "End turn")
    events = attack(session, ai)
    (save,) = [e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == SYSTEM_CONCENTRATION]
    assert save.payload["modifier"] == session.engine.state.actors[SINGER].saving_throws["CON"]
    assert session.mechanical.verify()["status"] == "PASS"
