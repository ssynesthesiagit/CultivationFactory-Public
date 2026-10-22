"""Dao fidelity: public source data, offline providers and real table commits."""
import pytest

from agent_seats import choices
from agent_seats.dao import dao_view
from agent_seats.protocol import dao_line, build_prompt as protocol_prompt
from combat.gate4_models import LocalControllerPolicy
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_policy import PolicyLibrary, POLICY_FILENAMES
from factory_authoring.sphere_dao import character_dao, controller_policy
from tests.h1_support import ROOT
from tests.test_seat_choices_budget import long_menu, assert_turn_costs
from tests.test_agent_seats import runner_for, raw_state
from tests.test_hunt5_player_choices import fixture, PLAYER
from tests.test_seat_choices import configure
from tests.test_seat_reaction_fallbacks import RECORDED, recorded_frame
from tools.summarize_dao import dao_fidelity, summarize


def real_daos():
    library = PolicyLibrary(ROOT)
    result = [dao_view(library.for_actor(actor)[0], ROOT) for actor in POLICY_FILENAMES]
    for spheres in ({"tianxia.sphere.air": 42, "tianxia.sphere.berserker": 12},
                    {"tianxia.sphere.life": 5, "tianxia.sphere.guardian": 3},
                    {"tianxia.sphere.death": 5}):
        profile = character_dao(spheres)
        policy = LocalControllerPolicy.model_validate(controller_policy(profile, "own"))
        result.append(dao_view(policy, ROOT, profile))
    return result


@pytest.mark.parametrize("dao", real_daos(), ids=lambda d: d["temperament"]["fighting"][:25])
@pytest.mark.parametrize("budget", [800, 700, 600])
@pytest.mark.parametrize("kind", ["TURN", "REACTION"])
@pytest.mark.parametrize("repair", [None, "invalid"])
def test_real_dao_retained_in_all_frames(monkeypatch, dao, budget, kind, repair):
    monkeypatch.setattr(choices, "PROMPT_BYTES", budget)
    view, legal = long_menu()
    view["dao"] = dao
    view["last_seen"] = [{"name": "Private foe", "position": {"x": 98, "y": 99}}]
    if kind == "TURN":
        options = choices.turn_options(view, legal, "edict", list(legal), limit=3)
    else:
        legal = {"ability": "Guard", "affected": "Death fighter", "trigger": "Enemy fighter attacks Death fighter.",
                 "summary": "Reduce the triggering damage by 2 until this attack ends.",
                 "spend_options": [0], "choice": {"minimum": 1, "maximum": 1, "allow_decline": True,
                 "options": [{"id": "x", "label": "Guard (Reaction, 1 Stamina)",
                              "description": "Reduce damage by 2."}]}}
        options = choices.reaction_options(legal, {"selection": "USE", "option_ids": ["x"], "spend": 0})
    prompt, offered = choices.build_prompt(view, options, kind, legal, repair)
    assert dao_line(view) in prompt
    assert len(prompt.encode()) <= budget
    assert offered["A"] == options[0].answer
    assert len(offered) >= 2
    assert "Private foe" not in prompt and "98" not in prompt and "99" not in prompt
    assert "combat_policy_weights" not in prompt and "source_doctrine" not in prompt
    if kind == "TURN":
        assert_turn_costs(prompt, offered, legal)
    else:
        assert legal["summary"] in prompt
        assert "Reaction, 1 Stamina" in prompt and "Enemy fighter attacks" in prompt


def test_protocol_choices_uses_same_dao_for_initial_and_repair():
    view, legal = long_menu()
    view["dao"] = real_daos()[0]
    for repair in (None, "invalid"):
        prompt = protocol_prompt(view, legal, "edict", "", "TURN", repair=repair,
                                 prompt_profile="choices", ranked_keys=list(legal))
        assert dao_line(view) in prompt and len(prompt.encode()) <= 800


def test_minimum_reaction_frame_never_drops_dao(monkeypatch):
    view, _ = long_menu()
    view["dao"] = real_daos()[1]
    legal = {"ability": "Guard", "affected": "you", "trigger": "A visible enemy attacks you.",
             "summary": "Reduce damage by 2.", "spend_options": [0]}
    options = choices.reaction_options(legal, {"selection": "USE", "option_ids": [], "spend": 0})
    monkeypatch.setattr(choices, "PROMPT_BYTES", 300)
    for repair in (None, "invalid"):
        prompt, offered = choices.build_prompt(view, options, "REACTION", legal, repair)
        assert dao_line(view) in prompt and len(prompt.encode()) <= 300
        assert "Fighter:" not in prompt and len(offered) == 2


def test_source_projection_never_invents_missing_names_or_tenets():
    daos = real_daos()
    assert all(d["name"] == "Unnamed Dao" for d in daos[:5])
    assert "destruction as a precise answer" in daos[0]["tenets"][0]
    assert daos[-1]["name"] == "Death"
    assert daos[-1]["temperament"]["fighting"] == ", ".join(character_dao({"tianxia.sphere.death": 5})["dao_verbs"])
    fallback = dao_view(PolicyLibrary(ROOT).fallback(), ROOT)
    assert fallback["tenets"] == [] and fallback["name"] == "Unnamed Dao"
    assert "generic combatant" in dao_line({"dao": fallback})


def test_action_family_diversity_before_near_duplicate_targets(monkeypatch):
    view, legal = long_menu()
    legal["same"] = dict(legal["edict"], targets=["ally"])
    options = choices.turn_options(view, legal, "edict", ["same", "gaze", "command"])
    assert options[0].answer["plan"][0] == "edict"
    assert options[1].answer["plan"][0] == "gaze"
    for budget in (800, 600):
        monkeypatch.setattr(choices, "PROMPT_BYTES", budget)
        prompt, offered = choices.build_prompt(view, options, "TURN", legal)
        assert offered["A"]["plan"][0] == "edict"
        # Even at the minimum menu, ending versus acting is a different choice.
        assert any(answer["plan"][0] != "edict" for answer in offered.values())


def test_saved_portable_policy_still_carries_source_dao_without_owner_sheet():
    profile = character_dao({"tianxia.sphere.death": 5})
    policy = LocalControllerPolicy.model_validate(controller_policy(profile, "portable"))
    dao = dao_view(policy, ROOT)
    assert dao["name"] == "Death"
    assert dao["temperament"]["fighting"] == profile["posture"]["natural"]["meaning"]
    assert dao["tenets"] == []  # No sheet-dependent tenets are fabricated.


@pytest.mark.parametrize("dao", real_daos()[-3:], ids=lambda d: d["name"])
@pytest.mark.parametrize("repair", [None, "invalid"])
@pytest.mark.parametrize("budget", [800, 760])
def test_long_recorded_reaction_keeps_source_dao_and_all_mechanics(monkeypatch, dao, repair, budget):
    monkeypatch.setattr(choices, "PROMPT_BYTES", budget)
    view, legal, builtin = recorded_frame(RECORDED[1])
    view["dao"] = dao
    prompt, offered = choices.build_prompt(view, choices.reaction_options(legal, builtin), "REACTION", legal, repair)
    assert "Dao: " + dao["name"] + ": " in prompt
    assert dao["temperament"]["verbs"][0] in prompt
    assert " ".join(legal["summary"].split()) in prompt
    assert all(row["label"] in prompt for row in legal["choice"]["options"])
    assert offered["A"] == builtin and len(offered) == 2
    assert len(prompt.encode()) <= budget


def test_real_table_dao_policy_pick_offered_after_repair_and_reload(tmp_path):
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    combat.controller = LocalDeterministicController()
    before = table.state(mid)
    menu = before["menu"]
    table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], before["last_sequence"], [])
    prompts = []
    def fake(config, prompt, png):
        prompts.append(prompt)
        assert "Dao: Air:" in prompt
        assert len(prompt.encode()) <= 800 and png is None
        return ("invalid" if len(prompts) == 1 else "A"), None
    runner, _ = runner_for(tmp_path, table, fake, timeout=10)
    configure(runner)
    runner.set_seat(mid, PLAYER, "MODEL", "fake")
    state = raw_state(runner, mid)
    session = combat._load_session(mid)
    view, known = runner.own_view(mid, state, PLAYER, session)
    assert view["dao"]["combat_policy_weights"] == combat.policies.for_actor(PLAYER)[0].weights
    keys, scores = [], {}
    options = runner._menu(state, known)
    builtin, _ = runner._builtin(mid, session, known, options, view["visible_cells"], keys, scores)
    legal = {k: v["description"] for k, v in options.items()}
    shortlist = choices.turn_options(view, legal, builtin, keys, scores)
    _, offered = choices.build_prompt(view, shortlist, "TURN", legal)
    # The owner's tactical-move requirement can remove a whole expensive
    # built-in alternative at 800 bytes; Dao and its ranking still survive.
    assert any(any(legal[k]["action"] == "Move" for k in a["plan"]) for a in offered.values())
    expected_first = offered["A"]["plan"][0]
    assert runner.drive(mid, max_steps=1) == 1
    assert len(prompts) == 2 and "Invalid reply" in prompts[1]
    row = runner.decisions(mid)[0]
    assert not row["fallback"] and row["chosen"][0] == expected_first
    assert row["built_in_pick"] == builtin
    assert row["dao_policy_top2"] == list(dict.fromkeys([builtin, *keys]))[:2]
    assert len(row["dao_policy_top2"]) == 2
    assert dao_fidelity([row])["overall"]["top2_measured"] == 1
    saved = type(combat)(ROOT, tmp_path)._load_session(mid)
    assert saved.verify()["status"] == saved.mechanical.replay()["status"] == "PASS"


def test_fidelity_measures_top_two_excludes_fallback_and_marks_old_logs_unknown(tmp_path):
    def decision(chosen, fighter="wall", **extra):
        return dict(actor_id=fighter, kind="TURN", chosen=[chosen, "end"], built_in_pick="guard",
                    fallback=None, latency_ms=1, **extra)
    ds = [decision("guard"), decision("strike", dao_policy_top2=["guard", "strike"]),
          decision("move", dao_policy_top2=["guard", "strike"]), decision("move", "old")]
    fallback = decision("guard"); fallback["fallback"] = "timeout"
    ds += [fallback, {"kind": "STEP"}]
    result = dao_fidelity(ds)
    assert result["overall"] == {"model_decisions": 4, "top1": 1, "top1_rate": .25,
                                 "top2": 2, "top2_measured": 3, "top2_unknown": 1, "top2_rate": 2 / 3}
    assert result["per_fighter"]["old"]["top2_rate"] is None
    row = dict(arm="Qwen9B", seed="fake-1", pair="wall-vs-thunder", decisions=ds[:-1], calls=5)
    summary = summarize([row], tmp_path)
    assert next(a for a in summary["aggregate"] if a["arm"] == "Qwen9B")["dao_fidelity"] == result
    use = {"selection": "USE", "option_ids": ["x"], "spend": 1}
    reaction = dict(actor_id="wall", kind="REACTION", chosen=dict(use, why="source style"),
                    built_in_pick=use, fallback=None)
    assert dao_fidelity([reaction])["overall"]["top1"] == 1
