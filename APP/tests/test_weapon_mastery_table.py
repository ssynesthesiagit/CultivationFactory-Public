"""Weapon mastery limits through table commits and persisted replay."""

import json

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_factory_combat_compiler import ACTOR, SHEET, _weapons_of

COMBO = "TAL_DUAL_WIELDING_COMBO_MANEUVERS"
NICK_WEAPONS = ["tianxia.mortal.weapon.bi_shou", "tianxia.mortal.weapon.hu_die_dao", "tianxia.mortal.weapon.zi_wu"]
CLEAVE_FLAG = "typed_once_turn:cleave"


def _owner(items, *, talents=(), spheres=(), features=(), ask=False):
    """The test fighter (STR 18) with ``items``; ``ask`` sets its reactions to Ask me."""
    abilities = [{"ability": a, "modifier": m, "score": 10 + 2 * m}
                 for a, m in (("STR", 4), ("DEX", 2), ("CON", 4), ("INT", 0), ("WIS", 0), ("CHA", 0))]
    owned = SHEET["spheres_and_talents"]
    owner_sheet = {**SHEET, "equipment": [{"starting_kit": {"items": [{"item_id": item} for item in items]}}],
                   "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"], "abilities": json.dumps(abilities)},
                   "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"], "path_feature_record_ids": list(features)},
                   "spheres_and_talents": {**owned, "sphere_record_ids": [*owned["sphere_record_ids"], *spheres],
                                           "learned_talent_record_ids": [*owned["learned_talent_record_ids"], *talents]}}
    return compile_character(owner_sheet, actor_id=ACTOR, granted_spheres=["tianxia.sphere.weapons"],
                             reaction_plan={"ask": True} if ask else None)


def _foe(actor_id, hp=None):
    foe_sheet = sheet([])
    if hp is not None:
        foe_sheet["ability_scores_and_statistics"] = {**foe_sheet["ability_scores_and_statistics"], "hit_points": {"maximum": hp}}
    return compile_character(foe_sheet, actor_id=actor_id)


def _end_turns_until_owner(table, match_id):
    for _ in range(8):
        state = table.state(match_id)
        if state["menu"]["actor_id"] == ACTOR:
            return state
        menu = state["menu"]
        response = table.act(match_id, menu["end_turn"], menu["decision_id"], menu["state_version"],
                             state["last_sequence"], [])
        assert response["status"] == "COMMITTED"
    raise AssertionError("the owner's turn never came")


def _commit(table, match_id, suffix, target):
    state = table.state(match_id)
    menu = state["menu"]
    group = next(row for row in menu["actions"] if row["source_definition_id"].endswith(suffix))
    option = next(row for row in group["options"] if target in row["target_ids"])
    return table.act(match_id, option["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], [])


def _grip(table, match_id, weapon, held):
    """Draw/Stow through the legal table action, retaining persisted grip choices."""
    state = table.state(match_id)
    menu = state['menu']
    engine = table.combat._load_session(match_id).engine
    group = next(g for g in menu['actions']
                 if (action := engine.action_catalog.get(g['source_definition_id'])) is not None
                 and (grip := action.parameters.get('equipment_grip'))
                 and grip['weapon'].endswith('.weapon.' + weapon) and bool(grip['held']) == held)
    return _commit(table, match_id, group['source_definition_id'], ACTOR)


def test_nick_extra_attack_shared_across_light_weapons_and_survives_reload(tmp_path):
    bundle, _ = _weapons_of(["tianxia.mortal.weapon.bi_shou", "tianxia.mortal.weapon.hu_die_dao",
                             "tianxia.mortal.weapon.zi_wu"],
                            paths=("tianxia.path.body_refining",), spheres=("tianxia.sphere.weapons",))
    foes = ["actor:factory.nick-foe-one", "actor:factory.nick-foe-two"]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    ids = [ACTOR, *foes]
    bundles = [bundle, *(compile_character(sheet([]), actor_id=foe) for foe in foes)]
    view = combat._finish_factory_match(
        bundles, ids, {ACTOR: "team:a", **{foe: "team:b" for foe in foes}},
        {ACTOR: {"x": 3, "y": 6}, foes[0]: {"x": 4, "y": 6}, foes[1]: {"x": 4, "y": 7}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ACTOR], foes,
        control_modes={actor: "MANUAL" for actor in ids}, match_seed="NICK-SHARED-ONCE",
        display_name="Nick mastery", maximum_rounds=3)
    match_id = view["match_id"]
    for _ in range(8):
        state = table.state(match_id)
        if state["menu"]["actor_id"] == ACTOR:
            break
        menu = state["menu"]
        response = table.act(match_id, menu["end_turn"], menu["decision_id"], menu["state_version"],
                             state["last_sequence"], [])
        assert response["status"] == "COMMITTED"
    assert table.state(match_id)["menu"]["actor_id"] == ACTOR

    assert _commit(table, match_id, ".weapon.bi_shou", foes[0])["status"] == "COMMITTED"
    assert _grip(table, match_id, 'bi_shou', False)['status'] == 'COMMITTED'
    assert _grip(table, match_id, 'hu_die_dao', True)['status'] == 'COMMITTED'
    assert _commit(table, match_id, ".weapon.hu_die_dao#offhand", foes[1])["status"] == "COMMITTED"
    assert _grip(table, match_id, 'hu_die_dao', False)['status'] == 'COMMITTED'
    assert _grip(table, match_id, 'zi_wu', True)['status'] == 'COMMITTED'
    menu = table.state(match_id)["menu"]
    assert not any(row["source_definition_id"].endswith(".weapon.zi_wu#offhand")
                   for row in menu["actions"]), "A second Nick Light extra attack is unavailable this turn"

    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    attacks = [event for event in fresh.engine.events
               if event.event_type == "ATTACK_ROLLED" and event.actor_id == ACTOR]
    assert len(attacks) == 2
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


CLEAVE_FOES = ["actor:factory.cleave-foe-one", "actor:factory.cleave-foe-two", "actor:factory.cleave-foe-three"]


def _cleave_match(tmp_path, *, owner_mode="MANUAL", foe_mode="MANUAL", bundle=None, foe_hp=None, third_at=(5, 6),
                  seed="CLEAVE-CHOICE"):
    bundle = bundle or _weapons_of(["tianxia.mortal.weapon.ji"],
                                   paths=("tianxia.path.body_refining",), spheres=("tianxia.sphere.weapons",))[0]
    foes = CLEAVE_FOES
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    ids = [ACTOR, *foes]
    bundles = [bundle, *(_foe(foe, (foe_hp or {}).get(foe)) for foe in foes)]
    view = combat._finish_factory_match(
        bundles, ids, {ACTOR: "team:a", **{foe: "team:b" for foe in foes}},
        {ACTOR: {"x": 3, "y": 6}, foes[0]: {"x": 4, "y": 6},
         foes[1]: {"x": 4, "y": 7}, foes[2]: {"x": third_at[0], "y": third_at[1]}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ACTOR], foes,
        control_modes={ACTOR: owner_mode, **{foe: foe_mode for foe in foes}},
        match_seed=seed, display_name="Cleave choice", maximum_rounds=3)
    return table, view["match_id"], foes


def _cleave_table(tmp_path, *, owner_mode="MANUAL", **kwargs):
    table, match_id, foes = _cleave_match(tmp_path, owner_mode=owner_mode, **kwargs)
    _end_turns_until_owner(table, match_id)
    return table, match_id, foes


def _followups(session):
    return [event for event in session.engine.events if event.event_type == "ATTACK_ROLLED"
            and event.payload.get("attack_label") == "Cleave follow-up"]


def _cleave_attack(table, match_id, target):
    state = table.state(match_id)
    menu = state["menu"]
    group = next(row for row in menu["actions"] if row["source_definition_id"].endswith("weapon.ji"))
    option = next(row for row in group["options"] if target in row["target_ids"])
    return table.act(match_id, option["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], [])


def _answer_cleave(table, match_id, first, attack_target, selection, target=None):
    prompt = first["reaction"]
    answer = {**prompt["context"], "selection": selection}
    if selection == "USE":
        answer["option_ids"] = [target]
    state = table.state(match_id)
    menu = state["menu"]
    group = next(row for row in menu["actions"] if row["source_definition_id"].endswith("weapon.ji"))
    option = next(row for row in group["options"] if attack_target in row["target_ids"])
    return table.act(match_id, option["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], [answer])


def test_cleave_ask_me_owner_chooses_target_and_survives_reload(tmp_path):
    table, match_id, foes = _cleave_table(tmp_path)
    first = _cleave_attack(table, match_id, foes[0])
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert prompt["reaction"] == "Cleave"
    assert {row["id"] for row in prompt["choice"]["options"]} == set(foes[1:])
    committed = _answer_cleave(table, match_id, first, foes[0], "USE", foes[2])
    assert committed["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    followups = [event for event in fresh.engine.events if event.event_type == "ATTACK_ROLLED"
                 and event.payload.get("attack_label") == "Cleave follow-up"]
    assert len(followups) == 1 and followups[0].target_ids == (foes[2],)
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_cleave_ask_me_owner_can_decline_and_survives_reload(tmp_path):
    table, match_id, foes = _cleave_table(tmp_path)
    first = _cleave_attack(table, match_id, foes[0])
    assert first["status"] == "REACTION_REQUIRED"
    committed = _answer_cleave(table, match_id, first, foes[0], "DECLINE")
    assert committed["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert _followups(fresh) == []
    assert not fresh.engine.state.actors[ACTOR].turn_flags.get(CLEAVE_FLAG), "declining does not use up Cleave"
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_cleave_ai_uses_lowest_hp_eligible_target(tmp_path):
    # foe-two has the lower HP but the later ID, so the HP preference (not the ID tie-break) must pick it.
    table, match_id, foes = _cleave_table(tmp_path, owner_mode="LOCAL_AUTO", foe_hp={CLEAVE_FOES[1]: 40})
    assert foes[1] > foes[2]
    engine = table.combat._load_session(match_id).engine
    chosen = next(candidate for candidate in engine.legal_candidates()
                  if candidate.source_definition_id.endswith("weapon.ji") and foes[0] in candidate.target_ids)
    from combat.gate4_adapters import ManualControllerAdapter
    original = table.combat.controller
    cleave_reactions = []

    class SelectedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (chosen.candidate_id, ())).choose_primary_action(context)

        def choose_reaction(self, context):
            choice = original.choose_reaction(context)
            if context.extension_choice is not None:
                cleave_reactions.append((context, choice))
            return choice

        def __getattr__(self, name):
            return getattr(original, name)

    table.combat.controller = SelectedController()
    try:
        response = table.auto_step(match_id, table.state(match_id)["last_sequence"], [])
    finally:
        table.combat.controller = original
    assert response["status"] == "COMMITTED"
    assert len(cleave_reactions) == 1
    spec, choice = cleave_reactions[0]
    assert set(spec.extension_choice.option_ids) == set(foes[1:])
    assert tuple(spec.extension_choice.preferred_option_ids) == (foes[1],)
    assert choice.decision.option_ids == (foes[1],)
    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    followups = _followups(fresh)
    assert len(followups) == 1
    assert followups[0].target_ids == (foes[1],)
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_cleave_decline_keeps_the_use_for_a_later_hit_in_the_same_turn(tmp_path):
    """Hunt 54 / L47 review: declining Cleave after the first hit must leave it for a later hit that turn, and a use
    after that is the only one."""
    bundle = _owner(["tianxia.mortal.weapon.ji"], features=["tianxia.path.body_refining.feature.extra_attack"])
    table, match_id, foes = _cleave_table(tmp_path, bundle=bundle, seed="CLEAVE-1")
    answers, prompts = [], []
    for _ in range(4):
        state = table.state(match_id)
        menu = state["menu"]
        group = next(row for row in menu["actions"] if row["source_definition_id"].endswith("weapon.ji"))
        option = next(row for row in group["options"] if foes[0] in row["target_ids"])
        response = table.act(match_id, option["candidate_id"], menu["decision_id"], menu["state_version"],
                             state["last_sequence"], answers)
        if response["status"] != "REACTION_REQUIRED":
            break
        prompt = response["reaction"]
        assert prompt["reaction"] == "Cleave"
        prompts.append(prompt)
        answer = {**prompt["context"], "selection": "DECLINE" if len(prompts) == 1 else "USE"}
        if answer["selection"] == "USE":
            answer["option_ids"] = [foes[2]]
        answers.append(answer)
    assert response["status"] == "COMMITTED"
    assert len(prompts) == 2, "the declined Cleave is offered again on the next hit, and only once more after a use"
    assert prompts[0]["context"]["checkpoint"] != prompts[1]["context"]["checkpoint"]

    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    attacks = [event for event in fresh.engine.events if event.event_type == "ATTACK_ROLLED" and event.actor_id == ACTOR]
    followups = _followups(fresh)
    assert len(followups) == 1 and followups[0].target_ids == (foes[2],)
    hits = [event for event in fresh.engine.events if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == ACTOR
            and event.target_ids == (foes[0],)]
    after_use = [event for event in hits if event.sequence > followups[0].sequence]
    assert len(hits) >= 3 and after_use, "a hit after the use (no third prompt) is part of this fixture"
    assert len([event for event in attacks if event.target_ids == (foes[0],)]) == 4
    assert fresh.engine.state.actors[ACTOR].turn_flags.get(CLEAVE_FLAG)
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


class _ForcedFoeController:
    """Test-only stand-in for the AI's primary choices: the first foe walks out of the owner's reach once, every other
    AI turn just ends. Reactions and every other method stay the real controller's."""

    def __init__(self, original, mover):
        self.original, self.mover, self.move_decision = original, mover, None

    def choose_primary_action(self, context):
        candidates = context.legal_candidates
        if context.active_actor_id == self.mover and self.move_decision in (None, context.decision_id):
            self.move_decision = context.decision_id
            pick = next(c for c in candidates if str(c.kind).endswith("MOVE") and c.destination is not None
                        and (c.destination.x, c.destination.y) == (8, 6))
        else:
            pick = next(c for c in candidates if str(c.kind).endswith("END_TURN"))
        return ManualControllerAdapter(lambda _: (pick.candidate_id, ())).choose_primary_action(context)

    def __getattr__(self, name):
        return getattr(self.original, name)


def _ai_turn_cleave(tmp_path, *, ask, cleave_answer=None, cleave_target=None):
    """The owner (manual control) has a reach weapon with Cleave; on an AI foe's turn that foe walks out of its reach and
    provokes an Opportunity Attack that hits, with two other foes within 5 feet of it. Steps the AI turns at the table,
    answering each prompt, until that move is committed (still the foe's turn). Returns the prompts asked."""
    bundle = _owner(["tianxia.mortal.weapon.ji"], ask=ask)
    table, match_id, foes = _cleave_match(tmp_path, foe_mode="LOCAL_AUTO", bundle=bundle, third_at=(5, 7))
    prompts, answers = [], []
    forced = _ForcedFoeController(None, foes[0])
    for _ in range(10):
        state = table.state(match_id)
        assert state["menu"]["actor_id"] != ACTOR, "the foe never walked away"
        original = forced.original = table.combat.controller
        table.combat.controller = forced
        try:
            response = table.auto_step(match_id, state["last_sequence"], answers)
        finally:
            table.combat.controller = original
        if response["status"] == "COMMITTED":
            if forced.move_decision is not None:
                return table, match_id, foes, prompts  # the foe's move, with its Opportunity Attack, is committed
            answers = []
            continue
        assert response["status"] == "REACTION_REQUIRED"
        prompt = response["reaction"]
        prompts.append(prompt)
        if prompt["reaction"] == "Cleave":
            # Nothing is committed while the table waits: a fresh service (a restart) sees the foe where it stood.
            reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
            assert (reloaded.engine.state.actors[foes[0]].position.x, reloaded.engine.state.actors[foes[0]].position.y) == (4, 6)
            assert not any(event.event_type == "ATTACK_ROLLED" for event in reloaded.engine.events)
            table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
            answer = {**prompt["context"], "selection": cleave_answer}
            if cleave_answer == "USE":
                answer["option_ids"] = [cleave_target]
        else:
            answer = {**prompt["context"], "selection": "USE"}
        answers.append(answer)
    raise AssertionError("the foe's move never committed")


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_cleave_on_an_ai_turn_asks_a_manual_ask_me_owner_and_survives_reload(tmp_path, selection):
    table, match_id, foes, prompts = _ai_turn_cleave(tmp_path, ask=True, cleave_answer=selection, cleave_target=CLEAVE_FOES[1])
    assert [prompt["reaction"] for prompt in prompts] == ["Opportunity Attack", "Cleave"]
    cleave = prompts[1]
    assert {row["id"] for row in cleave["choice"]["options"]} == set(foes[1:])
    # Equal HP: the automatic default is foe-three (ID order); a USE below picks foe-two and must be honoured.
    assert cleave["choice"]["preferred"] == [foes[2]] and cleave["choice"]["allow_decline"]
    # The prompt names the ability, the triggering action, the owner making it and the creature hit.
    assert cleave["action"] == "Opportunity Attack" and cleave["trigger_actor"] == "Test Cultivator"
    assert cleave["affected"] == "Factory character" and "once per turn" in cleave["moment"]
    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    followups = _followups(fresh)
    owner = fresh.engine.state.actors[ACTOR]
    if selection == "USE":
        assert len(followups) == 1 and followups[0].target_ids == (foes[1],)
        assert owner.turn_flags.get(CLEAVE_FLAG)
    else:
        assert followups == []
        assert not owner.turn_flags.get(CLEAVE_FLAG)
    assert any(event.event_type == "DAMAGE_COMMITTED" and event.actor_id == ACTOR and event.target_ids == (foes[0],)
               for event in fresh.engine.events), "the Opportunity Attack hit"
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def test_cleave_on_an_ai_turn_is_automatic_for_a_manual_owner_with_auto_reactions(tmp_path):
    """Reactions set to Auto: the Opportunity Attack and its Cleave are decided without a prompt (lowest HP, then ID)."""
    table, match_id, foes, prompts = _ai_turn_cleave(tmp_path, ask=False)
    assert prompts == []
    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    followups = _followups(fresh)
    assert len(followups) == 1 and followups[0].target_ids == (foes[2],)
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"


def _nick_combo_table(tmp_path):
    bundle = _owner(NICK_WEAPONS, talents=[COMBO], spheres=["tianxia.sphere.dual_wielding"])
    nick_extras = {row["source_definition_id"] for row in bundle["action_catalog"]
                   if row["source_definition_id"].endswith("#offhand")
                   or (row["parameters"].get("typed") or {}).get("replaces_attack")}
    combo = next(row["source_definition_id"] for row in bundle["action_catalog"]
                 if ((row["parameters"].get("typed") or {}).get("replaces_attack") or {}).get("source_definition_id", "").endswith("hu_die_dao#offhand")
                 and row["parameters"]["typed"].get("unarmed_option") == "shove_push")
    foes = ["actor:factory.nick-foe-one", "actor:factory.nick-foe-two"]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    ids = [ACTOR, *foes]
    view = combat._finish_factory_match(
        [bundle, *(_foe(foe) for foe in foes)], ids, {ACTOR: "team:a", **{foe: "team:b" for foe in foes}},
        {ACTOR: {"x": 3, "y": 6}, foes[0]: {"x": 4, "y": 6}, foes[1]: {"x": 4, "y": 7}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ACTOR], foes,
        control_modes={actor: "MANUAL" for actor in ids}, match_seed="NICK-COMBO", display_name="Nick combo",
        maximum_rounds=3)
    match_id = view["match_id"]
    _end_turns_until_owner(table, match_id)
    return table, match_id, foes, nick_extras, combo


def _offered(table, match_id, sources):
    return {row["source_definition_id"] for row in table.state(match_id)["menu"]["actions"]} & sources


@pytest.mark.parametrize("first", ["combo", "nick"])
def test_nick_use_is_shared_with_combo_maneuver_replacements_and_survives_reload(tmp_path, first):
    """Hunt 54 / L47 review: a Combo Maneuvers Shove/Grapple made in place of a Nick off-hand attack is that once-per-turn
    extra attack, in either order, after a reload, and it comes back on the owner's next turn."""
    table, match_id, foes, nick_extras, combo = _nick_combo_table(tmp_path)
    assert _commit(table, match_id, ".weapon.bi_shou", foes[0])["status"] == "COMMITTED"
    assert combo not in _offered(table, match_id, nick_extras), 'a replacement inherits its stowed weapon restriction'
    assert _grip(table, match_id, 'bi_shou', False)['status'] == 'COMMITTED'
    assert _grip(table, match_id, 'hu_die_dao', True)['status'] == 'COMMITTED'
    offered = _offered(table, match_id, nick_extras)
    assert combo in offered and any(source.endswith(".weapon.hu_die_dao#offhand") for source in offered)
    used = combo if first == "combo" else next(source for source in offered if source.endswith(".weapon.hu_die_dao#offhand"))
    assert _commit(table, match_id, used, foes[1])["status"] == "COMMITTED"
    assert _grip(table, match_id, 'hu_die_dao', False)['status'] == 'COMMITTED'
    assert _grip(table, match_id, 'zi_wu', True)['status'] == 'COMMITTED'
    assert _offered(table, match_id, nick_extras) == set(), "one Nick extra attack (or its replacement) per turn"

    reloaded = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert _offered(reloaded, match_id, nick_extras) == set()
    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"

    state = reloaded.state(match_id)
    menu = state["menu"]
    assert reloaded.act(match_id, menu["end_turn"], menu["decision_id"], menu["state_version"],
                        state["last_sequence"], [])["status"] == "COMMITTED"
    _end_turns_until_owner(reloaded, match_id)
    assert _grip(reloaded, match_id, 'zi_wu', False)['status'] == 'COMMITTED'
    assert _grip(reloaded, match_id, 'bi_shou', True)['status'] == 'COMMITTED'
    assert _commit(reloaded, match_id, ".weapon.bi_shou", foes[0])["status"] == "COMMITTED"
    assert _grip(reloaded, match_id, 'bi_shou', False)['status'] == 'COMMITTED'
    assert _grip(reloaded, match_id, 'hu_die_dao', True)['status'] == 'COMMITTED'
    assert combo in _offered(reloaded, match_id, nick_extras), "the Nick use returns on the owner's next turn"


def test_followup_target_seam_has_one_owner_per_effect(tmp_path, monkeypatch):
    """The general optional_followup_target seam: the Cleave consumer answers only for Cleave, and a second consumer
    claiming the same effect is an error (rolled back) rather than silently overriding the owner's choice."""
    from combat import ext
    from combat.ext.weapon_mastery import choose_cleave_target

    assert choose_cleave_target(None, {"type": "some_other_followup"}, [], "") is None
    table, match_id, foes = _cleave_table(tmp_path)
    before = table.state(match_id)["last_sequence"]
    ext._load()
    rival = lambda ctx, effect, eligible, preferred: eligible[-1].entity_id  # noqa: E731
    monkeypatch.setitem(ext._HOOKS, "optional_followup_target", [*ext._HOOKS["optional_followup_target"], rival])
    first = _cleave_attack(table, match_id, foes[0])
    assert first["status"] == "REACTION_REQUIRED" and first["reaction"]["reaction"] == "Cleave"
    from combat.gate5_service import CombatServiceError

    with pytest.raises(CombatServiceError) as rejected:
        _answer_cleave(table, match_id, first, foes[0], "USE", foes[1])
    causes, error = [], rejected.value
    while error is not None:
        causes.append(str(error))
        error = error.__cause__ or error.__context__
    assert any("one plug-in must own each optional follow-up target choice" in text for text in causes)
    assert table.state(match_id)["last_sequence"] == before, "the rejected attack committed nothing"
