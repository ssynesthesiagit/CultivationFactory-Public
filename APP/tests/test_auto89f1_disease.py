"""AUTO89f1 -- the four AUTO89 review findings, fixed and proved at the table.

AUTO89 automated the Court of the Crawling Fever's "Resistance to Poison and Necrotic damage caused by Disease
talents" with a ``damage_defenses`` subscriber in ``combat/ext/disease.py`` and cleared the printed GM rider on
strength of it. The independent review found the row keyed to the *attacker's character build* rather than to the
ability that dealt the damage, granted to every same-team creature in the aura rather than to the allies the maker
chooses, and proved none of it at service level. This file is the regression net for the fixes:

1. the resistance follows the damage's own provenance (``combat.pending_damage.current`` plus the ability's
   compiled ``sphere``), so a Disease cultivator's unrelated Poison or Death damage lands in full;
2. "You and allies you choose gain ..." is a real, answered, persisted choice: a manual or Ask-me maker is asked
   (with what it gives, who it reaches, how long it lasts and what it costs), an AI maker answers automatically,
   and the answer survives the table's commit and reload;
3. the numbers are asserted through the engine's own damage commit (``combat.typed_reactions.defend``) and through
   real Hit Points lost in a real fight, for a chosen ally, an unchosen ally and a chosen ally out of reach;
4. Spreading Infection's "You choose whether this talent can affect your allies" is answered by the player through
   the real table prompt, and the printed Reaction and 2 CP are really spent (or really not, when declined).

Every fight here is a real ``CombatService`` + ``TabletopService`` match from real compiled Factory sheets, and the
Court is raised through the table's own menu -- never by poking the engine.
"""

from __future__ import annotations

import json

from combat.ext import disease
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

SOW = "DISEASE_BASE_SOW_THE_FEVER_SEED"
COURT = "tianxia.talent.disease.court_of_the_crawling_fever"
SPREADING = "tianxia.talent.disease.spreading_infection"
SOUL_ARMOR = "tianxia.path.spirit_awakening.feature.soul_armor"  # a passive printed Resistance to Psychic damage
WITHERING = "TAL_DEATH_WITHERING_HAND"  # Death: Necrotic damage only, no Disease in its provenance
COURT_CHOICE = "choice:needle.disease_court_allies"
CRAWLING_KEY = disease.CRAWLING
SPREADING_CHOICE = "choice:needle.disease_spreading"

WARDEN, ALLY, OUTSIDER, FOE, MARK = ("actor:factory.f1-" + n for n in ("warden", "ally", "outsider", "foe", "mark"))
TEAMS = {WARDEN: "team:factory", ALLY: "team:factory", OUTSIDER: "team:factory",
         FOE: "team:pestilence", MARK: "team:pestilence"}
# ALLY and OUTSIDER both start inside the Warden's 30-foot aura (10 and 25 feet away), and the Foe is close
# enough for the Warden's ranged Sow the Fever Seed.
PLACES = {WARDEN: {"x": 2, "y": 6}, ALLY: {"x": 4, "y": 6}, OUTSIDER: {"x": 7, "y": 6},
          FOE: {"x": 6, "y": 6}, MARK: {"x": 6, "y": 8}}
FAR = {WARDEN: {"x": 2, "y": 6}, ALLY: {"x": 14, "y": 6}, OUTSIDER: {"x": 15, "y": 6},
       FOE: {"x": 17, "y": 6}, MARK: {"x": 17, "y": 8}}
# The Foe bears the fever, so for Spreading Infection the Foe sits between one ally and one enemy.
NEARBY = {WARDEN: {"x": 2, "y": 6}, ALLY: {"x": 4, "y": 6}, OUTSIDER: {"x": 7, "y": 6},
          FOE: {"x": 5, "y": 6}, MARK: {"x": 6, "y": 6}}
SEED = "AUTO89F1-COURT"


def _mechanics():
    from combat import factory_compiler

    return json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())["mechanics"]


def _disease_bases():
    sphere = _mechanics()[SOW]["sphere_id"]
    return [k for k, m in _mechanics().items() if m.get("sphere_id") == sphere and m.get("kind") == "base_ability"]


def _bundle(mids, actor_id, name, *, no_base=False, attack_bonus=None, armor_class=None, con_score=None):
    doc = sheet(list(mids), cl=12, dc=16)
    doc["identity"]["display_name"] = name
    stats = doc["ability_scores_and_statistics"]
    if con_score is not None:
        con = next(a for a in stats["abilities"] if a["ability"] == "CON")
        con.update(score=con_score, modifier=(con_score - 10) // 2)
    stats["hit_points"] = {"maximum": 200}
    stats["primary_resource"]["maximum"] = 40
    if attack_bonus is not None:
        stats["technique_attack_bonus"] = attack_bonus
    if armor_class is not None:
        stats["armor_class"]["base_value"] = armor_class
    if no_base:
        doc.get("spheres_and_talents", {}).pop("automatic_sphere_component_record_ids", None)
    return compile_character(doc, actor_id=actor_id)


def _roster(*, wither=False, spreading=False, foe_disease=False, ask_me=False):
    warden = _bundle([*_disease_bases(), SOW, COURT, *( [WITHERING] if wither else [] ),
                      *( [SPREADING] if spreading else [] )], WARDEN, "Fever Warden", attack_bonus=100)
    if ask_me:  # the sheet's Reactions setting "Ask me": the player answers this character's own prompts
        warden["reaction_plan"] = {**warden["reaction_plan"], "mode": "ask", "ask": True}
    return [
        warden,
        _bundle([SOUL_ARMOR], ALLY, "Fever Ally", no_base=True, armor_class=2),
        _bundle([], OUTSIDER, "Second Ally", no_base=True, armor_class=2),
        _bundle([*_disease_bases(), SOW, COURT] if foe_disease else [*_disease_bases(), SOW],
                FOE, "Bloat", attack_bonus=100),
        _bundle([], MARK, "Wasting Hand", no_base=True, armor_class=2),
    ]


def _start(root, bundles, *, positions=None, maker_mode="MANUAL"):
    combat = CombatService(ROOT, root)
    table = TabletopService(combat, root)
    mid = combat._finish_factory_match(
        bundles, list(TEAMS), TEAMS, positions or PLACES,
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [WARDEN], [FOE, MARK], control_modes={WARDEN: maker_mode, **{a: "MANUAL" for a in (ALLY, OUTSIDER, FOE, MARK)}},
        match_seed=SEED, display_name="AUTO89f1 Court", maximum_rounds=20)["match_id"]
    return combat, table, mid


def _fight(root, **kw):
    positions = kw.pop("positions", None)
    maker_mode = kw.pop("maker_mode", "MANUAL")
    return _start(root, _roster(**kw), positions=positions, maker_mode=maker_mode)


# -------------------------------------------------------------------------------------------------------- table helpers
def _options(prompt):
    return [row["id"] for row in (prompt.get("choice") or {}).get("options") or []]


def _labels(prompt):
    return [row["label"] for row in (prompt.get("choice") or {}).get("options") or []]


def _answer_to(prompt, choose):
    picked = choose(prompt)
    return {**prompt["context"], "selection": "DECLINE" if picked is None else "USE", "option_ids": list(picked or [])}


def _step(table, mid, state, candidate_id, answer):
    """Commit one table action, answering whatever it asks with ``answer(prompt) -> option ids or None``."""
    menu = state["menu"]
    answers, prompts = [], []
    for _ in range(14):
        result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        answers.append(_answer_to(prompt, answer))
    raise AssertionError("one action asked more questions than it can")


def _end_turn(table, mid, state, answer=lambda prompt: None):
    menu = state["menu"]
    return _step(table, mid, state, menu["end_turn"], answer)


def _turn_of(table, mid, actor, answer=lambda prompt: None, limit=12):
    for _ in range(limit):
        state = table.state(mid)
        if state["menu"]["actor_id"] == actor:
            return state
        _end_turn(table, mid, state, answer)
    raise AssertionError(f"{actor} never came up")


def _use(table, mid, label, answer=lambda prompt: None, state=None):
    """Commit the menu entry whose label contains ``label``."""
    state = state or table.state(mid)
    group = next((g for g in state["menu"]["actions"] if label in g["label"]), None)
    assert group is not None, (label, [g["label"] for g in state["menu"]["actions"]])
    return _step(table, mid, state, group["options"][0]["candidate_id"], answer)


def _raise_court(table, mid, *, choose, state=None):
    """The maker raises the Court through the table's own menu. ``choose`` picks the allies (None declines)."""

    def answer(prompt):
        return choose(_options(prompt)) if prompt["context"]["reaction_source_id"] == COURT_CHOICE else None

    return [p for p in _use(table, mid, "Court of the Crawling Fever", answer, state)
            if p["context"]["reaction_source_id"] == COURT_CHOICE]


def _session(combat, mid):
    """A fresh service reading the committed fight back off disk -- the persistence half of the change."""
    return CombatService(ROOT, combat.userdata_root)._load_session(mid)


def _engine(combat, mid):
    return _session(combat, mid).engine


def _court_zone(engine):
    zone = next((z for z in disease._zones_of(engine, disease.CRAWLING) if z.owner_id == WARDEN), None)
    assert zone is not None, "the Court of the Crawling Fever was never raised"
    return zone


def _chosen(engine):
    return (_court_zone(engine).trigger_profile or {}).get(disease.COURT_ALLIES) or []


def _defend(engine, target, amount, damage_type, source_id, source_actor):
    """The engine's own damage commit, on a real reloaded fight: what a Factory fighter actually takes."""
    from combat import typed_reactions

    return typed_reactions.defend(engine, engine.state.actors[target], amount, damage_type, source_id, source_actor)


def _own_action(engine, actor_id, endswith):
    """The creature's own compiled catalog action id (actor-qualified, not a bare mechanic id)."""
    return next(a for a in engine.state.actors[actor_id].action_ids if a.endswith(endswith))


# -------------------------------------------------------------------------------------------------------- finding 2: the printed ally choice
def test_the_court_asks_its_maker_which_allies_join_in_plain_words_and_persists_the_answer(tmp_path):
    """"You and allies you choose gain: ..." is asked of the maker when the aura is raised, names what each ally
    gets and what it costs, and the answer is stored on the aura so it survives a commit and a reload."""
    combat, table, mid = _fight(tmp_path)
    asked = _raise_court(table, mid, state=_turn_of(table, mid, WARDEN),
                         choose=lambda options: [o for o in options if o == ALLY])
    assert len(asked) == 1, asked
    prompt = asked[0]
    assert prompt["reaction"] == "Court of the Crawling Fever", prompt  # the question names the ability
    assert _options(prompt) == [ALLY, OUTSIDER], prompt["choice"]  # both allies in the aura are offered, named
    assert all("joins your Court" in text for text in _labels(prompt)), _labels(prompt)
    assert all("Fever Ally" in text or "Second Ally" in text for text in _labels(prompt)), _labels(prompt)
    said = json.dumps(prompt)  # the question the player is shown
    assert "Advantage on saving throws against Disease" in said, said
    # the printed scope is "caused by Disease talents" (not "your Disease talents"): combat/ext/disease.py
    # caused_by_disease accepts any Disease caster's packet, so the question must not narrow it.
    assert "Resistance to Poison and Necrotic damage caused by Disease talents" in said, said
    assert "your Disease talents" not in said, said
    assert "An ally you leave out gains none of them" in said, said
    # the printed immunity to the maker's own Veil and Cloud damage is not implemented, so it is disclosed as a
    # table call rather than promised as automation.
    assert "does not work that immunity out for you" in said, said
    for text in (prompt["moment"], *_labels(prompt)):  # no internal ids or code names in what is read out
        assert "disease_court_allies" not in text and "trigger_profile" not in text, text
    assert prompt["cost"] == "7 Qi", prompt  # the printed price of raising the Court
    assert "up to 1 minute" in prompt["limits"], prompt

    engine = _engine(combat, mid)
    assert _chosen(engine) == [ALLY], _court_zone(engine).trigger_profile
    assert disease.court_covers(engine, engine.state.actors[WARDEN]) is True
    assert disease.court_covers(engine, engine.state.actors[ALLY]) is True
    assert disease.court_covers(engine, engine.state.actors[OUTSIDER]) is False  # offered, not chosen
    # the answer is in the fight's own record, so a saved fight replays the Court with the same beneficiaries
    assert any(e.event_type == "ZONE_CREATED"
               and (e.payload or {}).get("zone", {}).get("trigger_profile", {}).get(disease.COURT_ALLIES) == [ALLY]
               for e in engine.events), [e.event_type for e in engine.events]
    assert _session(combat, mid).verify()["status"] == "PASS"


def test_a_maker_who_chooses_no_ally_leaves_its_own_court_to_itself(tmp_path):
    """The printed choice is optional: declining keeps every ally out, and the maker keeps all four benefits."""
    combat, table, mid = _fight(tmp_path)
    asked = _raise_court(table, mid, state=_turn_of(table, mid, WARDEN), choose=lambda options: None)
    assert len(asked) == 1 and (asked[0].get("choice") or {}).get("allow_decline") is True, asked
    engine = _engine(combat, mid)
    assert _chosen(engine) == [], _court_zone(engine).trigger_profile
    assert disease.court_covers(engine, engine.state.actors[WARDEN]) is True
    assert disease.court_covers(engine, engine.state.actors[ALLY]) is False
    assert disease._sheltered(engine, engine.state.actors[ALLY]) is False  # no Advantage on saves against Disease
    assert disease._sheltered(engine, engine.state.actors[WARDEN]) is True


def test_a_maker_with_nobody_to_answer_takes_every_ally_in_reach(tmp_path):
    """The AI's answer to the printed choice, on the real engine: ``rider_choices.pick`` is documented to answer
    automatically when no player is there, so an AI maker's Court takes every ally standing in it -- which is what
    the old unchosen behaviour gave, so an AI fight replays as before."""
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate4_engine import Gate4ControllerEngine

    bundles = [b for b in (_bundle([*_disease_bases(), SOW, COURT], WARDEN, "Fever Warden"),
                           _bundle([SOUL_ARMOR], ALLY, "Fever Ally", no_base=True, armor_class=2),
                           _bundle([], OUTSIDER, "Second Ally", no_base=True, armor_class=2),
                           _bundle([], FOE, "Bloat", no_base=True),
                           _bundle([], MARK, "Wasting Hand", no_base=True))]
    engine = Gate4ControllerEngine(ROOT, match_seed=SEED, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": list(TEAMS), "team_by_actor": TEAMS,
                                                 "starting_positions": PLACES,
                                                 "arena_id": "battlefield:map.builtin-sect-trial-platform"})
    engine.state.current_slot_index = engine.state.initiative_order.index(WARDEN)
    engine.state.current_actor_id = WARDEN
    engine._system_start_turn()
    warden = engine.state.actors[WARDEN]
    warden.action_available = warden.bonus_action_available = warden.reaction_available = True
    warden.resources["resource:core.qi"] = 30
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Court of the Crawling Fever"
                     and c.actor_id == WARDEN)
    assert getattr(engine, "_gate4_reaction_provider", None) is None, "this fight must have nobody to ask"
    engine.execute_intent(ActionIntent(intent_id="auto-court", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=WARDEN, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    zone = next(z for z in disease._zones_of(engine, CRAWLING_KEY) if z.owner_id == WARDEN)
    assert (zone.trigger_profile or {}).get(disease.COURT_ALLIES) == [ALLY, OUTSIDER], zone.trigger_profile
    assert disease.court_covers(engine, engine.state.actors[ALLY]) is True


def test_an_ask_me_maker_is_still_asked_for_its_court_allies(tmp_path):
    """Ask me: the maker's own choice is the player's, so the table stops and asks."""
    combat, table, mid = _fight(tmp_path, ask_me=True)
    asked = _raise_court(table, mid, state=_turn_of(table, mid, WARDEN),
                         choose=lambda options: [o for o in options if o == ALLY])
    assert len(asked) == 1, asked
    assert _options(asked[0]) == [ALLY, OUTSIDER], asked[0]["choice"]
    engine = _engine(combat, mid)
    assert _chosen(engine) == [ALLY], _court_zone(engine).trigger_profile


def test_a_maker_with_no_ally_in_reach_is_asked_nothing_and_stores_an_empty_answer(tmp_path):
    """Inert when the aura is empty: no prompt, an empty stored answer, no stray state."""
    combat, table, mid = _fight(tmp_path, positions=FAR)
    asked = _raise_court(table, mid, state=_turn_of(table, mid, WARDEN), choose=lambda options: None)
    assert asked == [], asked
    engine = _engine(combat, mid)
    assert _chosen(engine) == [], _court_zone(engine).trigger_profile
    assert disease.court_covers(engine, engine.state.actors[WARDEN]) is True
    assert disease.court_covers(engine, engine.state.actors[ALLY]) is False


# -------------------------------------------------------------------------------------------------------- finding 1: the damage's own source
def test_the_resistance_follows_the_damage_source_not_the_caster_who_dealt_it(tmp_path):
    """The printed words are "caused by Disease talents". A Disease *and* Death cultivator's Death Withering Hand
    is not one, so its Necrotic damage lands in full on the very ally the Court was raised for, while the same
    caster's Sow the Fever Seed is halved. The old row keyed off the caster's build and halved both."""
    combat, table, mid = _fight(tmp_path, wither=True)
    _raise_court(table, mid, state=_turn_of(table, mid, WARDEN), choose=lambda options: [o for o in options if o == ALLY])
    engine = _engine(combat, mid)
    sow = _own_action(engine, WARDEN, SOW)
    withering = _own_action(engine, WARDEN, WITHERING)
    assert withering in engine.state.actors[WARDEN].action_ids

    assert _defend(engine, ALLY, 12, "NECROTIC", sow, WARDEN) == 6      # Disease talent -> Resistance
    assert _defend(engine, ALLY, 12, "POISON", sow, WARDEN) == 6
    assert _defend(engine, ALLY, 12, "NECROTIC", withering, WARDEN) == 12  # Death talent, same caster -> full
    assert _defend(engine, WARDEN, 12, "NECROTIC", sow, WARDEN) == 6      # the maker is its own beneficiary
    assert _defend(engine, WARDEN, 12, "NECROTIC", withering, WARDEN) == 12
    # Psychic is not one of the two printed damage types (the Ally's own printed Soul Armor halves it)
    assert _defend(engine, ALLY, 12, "PSYCHIC", sow, WARDEN) == 6


def test_an_ally_outside_the_aura_or_left_unchosen_takes_the_full_disease_damage(tmp_path):
    """Both halves of the printed scope: the aura's reach, and the maker's choice."""
    combat, table, mid = _fight(tmp_path)
    _raise_court(table, mid, state=_turn_of(table, mid, WARDEN), choose=lambda options: [o for o in options if o == ALLY])
    engine = _engine(combat, mid)
    sow = _own_action(engine, WARDEN, SOW)

    assert _defend(engine, ALLY, 12, "NECROTIC", sow, WARDEN) == 6       # chosen and standing in the aura
    assert _defend(engine, OUTSIDER, 12, "NECROTIC", sow, WARDEN) == 12  # in the aura, never chosen
    # a chosen ally that has walked out of the 30-foot aura is no longer covered
    from combat.gate2_runtime_models import Position

    engine.state.actors[OUTSIDER].position = Position(x=18, y=6)
    assert _defend(engine, OUTSIDER, 12, "NECROTIC", sow, WARDEN) == 12


def test_the_resistance_is_off_without_the_court(tmp_path):
    """Inert for everyone else: no Court, nothing."""
    combat, table, mid = _fight(tmp_path, wither=True)
    engine = _engine(combat, mid)  # the Court is never raised in this fight
    sow = _own_action(engine, WARDEN, SOW)
    withering = _own_action(engine, WARDEN, WITHERING)
    assert not any(z.owner_id == WARDEN for z in disease._zones_of(engine, disease.CRAWLING))
    assert _defend(engine, ALLY, 12, "NECROTIC", sow, WARDEN) == 12
    assert _defend(engine, WARDEN, 12, "POISON", sow, WARDEN) == 12
    assert _defend(engine, ALLY, 12, "NECROTIC", withering, WARDEN) == 12


# -------------------------------------------------------------------------------------------------------- finding 3: real Hit Points, real service
def _fight_with_court(root, *, choose_ally):
    combat, table, mid = _fight(root)
    asked = _raise_court(table, mid, state=_turn_of(table, mid, WARDEN),
                         choose=(lambda options: [o for o in options if o == ALLY]) if choose_ally else (lambda options: None))
    assert len(asked) == 1, asked
    engine = _engine(combat, mid)
    assert _chosen(engine) == ([ALLY] if choose_ally else []), _court_zone(engine).trigger_profile
    return combat, mid, engine


def test_a_chosen_ally_loses_half_of_real_disease_damage_in_a_real_fight(tmp_path):
    """The numbers above, as Hit Points and as recorded events. The enemy Foe is also a Disease cultivator: it
    commits a real Necrotic damage packet under its own compiled Sow the Fever Seed (the same ``_commit_damage``
    the typed executor deals through), and the Ally the Warden chose takes half what the packet carried, while the
    Second Ally standing in the same aura but never chosen takes all of it."""
    combat, mid, engine = _fight_with_court(tmp_path / "covered", choose_ally=True)
    sow = _own_action(engine, FOE, SOW)
    assert sow in engine.state.actors[FOE].action_ids
    for victim, expected_factor in ((ALLY, 0.5), (OUTSIDER, 1.0)):
        start = len(engine.events)
        engine._commit_damage(engine.state.actors[victim], 14, "NECROTIC", sow, FOE, None, reaction_depth=0)
        hit = next(e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED" and victim in e.target_ids)
        assert hit.payload["damage_type"] == "NECROTIC", hit.payload
        assert hit.payload["hp_damage"] == int(14 * expected_factor), (victim, hit.payload)
        assert engine.state.actors[victim].maximum_hp - engine.state.actors[victim].current_hp ==             sum(int(e.payload["hp_damage"]) for e in engine.events[start:]
                if e.event_type == "DAMAGE_COMMITTED" and victim in e.target_ids), victim


def test_the_court_maker_and_its_chosen_ally_take_half_of_the_same_real_packet(tmp_path):
    """The maker itself is "You ... gain", so it is halved too -- asserted on Hit Points, not on rows."""
    combat, mid, engine = _fight_with_court(tmp_path, choose_ally=True)
    sow = _own_action(engine, FOE, SOW)
    for victim in (WARDEN, ALLY):
        before = engine.state.actors[victim].current_hp
        engine._commit_damage(engine.state.actors[victim], 14, "NECROTIC", sow, FOE, None, reaction_depth=0)
        assert before - engine.state.actors[victim].current_hp == 7, (victim, before, engine.state.actors[victim].current_hp)


# -------------------------------------------------------------------------------------------------------- finding 3: Spreading Infection's choice
def _sow(combat, table, mid, state, *, on=None):
    """The Warden's own Sow the Fever Seed, taken from the engine's own legal candidates (the table's attack list
    is the action menu, not the attacks) and committed through ``TabletopService.act``."""
    engine = _engine(combat, mid)
    target = on or FOE
    strike = next(c for c in engine.legal_candidates()
                  if c.source_definition_id.endswith(SOW) and c.actor_id == WARDEN and target in c.target_ids)
    _step(table, mid, state, strike.candidate_id, lambda prompt: None)
    return engine, strike


def _spreading_fight(tmp_path):
    """The Warden Sows the Fever Seed at the Foe, which stands beside one ally and one enemy."""
    combat, table, mid = _start(tmp_path, _roster(spreading=True), positions=NEARBY)
    _sow(combat, table, mid, _turn_of(table, mid, WARDEN), on=FOE)
    engine = _engine(combat, mid)
    bearer = engine.state.actors[FOE]
    assert disease.tokens(engine, engine.state.actors[WARDEN], bearer) >= 1, "the Foe bears no Contagion Token"
    # the bearer stands beside one ally (Fever Ally) and one enemy (Wasting Hand), both inside 10 feet
    assert engine.grid.distance_ft(bearer.position, engine.state.actors[ALLY].position) <= 10
    assert engine.grid.distance_ft(bearer.position, engine.state.actors[MARK].position) <= 10
    return combat, table, mid


def _spreading_prompt(table, mid, choose, limit=14):
    """End turns until the Foe's turn start raises Spreading Infection's question, and answer it with ``choose``."""
    def answer(prompt):
        return choose(prompt) if prompt["context"]["reaction_source_id"] == SPREADING_CHOICE else None

    for _ in range(limit):
        prompts = _end_turn(table, mid, table.state(mid), answer)
        asked = [p for p in prompts if p["context"]["reaction_source_id"] == SPREADING_CHOICE]
        if asked:
            return asked
    raise AssertionError("Spreading Infection never asked")


def test_spreading_infection_really_asks_whether_your_allies_may_be_affected_and_spends_its_price(tmp_path):
    """"You choose whether this talent can affect your allies": the bearer is offered the ally as well as the
    enemy, the labels say which is which and what the choice costs, and answering spends the Reaction and 2 CP."""
    combat, table, mid = _spreading_fight(tmp_path)
    from combat.ext.rider_support import cp_pool

    engine = _engine(combat, mid)
    pool = cp_pool(engine.state.actors[WARDEN])
    before = engine.state.actors[WARDEN].resources[pool]
    assert engine.state.actors[WARDEN].reaction_available is True
    asked = _spreading_prompt(table, mid, lambda prompt: [o for o in _options(prompt) if o == ALLY])
    labels = _labels(asked[0])
    assert sum("an ally" in text for text in labels) >= 1, labels
    assert sum("an enemy" in text for text in labels) >= 1, labels
    assert any("Reaction" in text and "2 CP" in text for text in labels), labels
    assert _options(asked[0]) and ALLY in _options(asked[0]), _options(asked[0])
    assert asked[0]["context"]["reactor_id"] == WARDEN, asked[0]["context"]
    engine = _engine(combat, mid)
    warden = engine.state.actors[WARDEN]
    assert warden.reaction_available is False, "the printed Reaction was not spent"
    assert warden.resources[pool] == before - 2, warden.resources[pool]  # the printed 2 CP
    assert _session(combat, mid).verify()["status"] == "PASS"


def test_the_warden_passing_spreading_infection_keeps_its_reaction_and_its_cp(tmp_path):
    """Passing the printed choice costs nothing."""
    combat, table, mid = _spreading_fight(tmp_path)
    from combat.ext.rider_support import cp_pool

    engine = _engine(combat, mid)
    pool = cp_pool(engine.state.actors[WARDEN])
    before = engine.state.actors[WARDEN].resources[pool]
    asked = _spreading_prompt(table, mid, lambda prompt: None)
    assert _options(asked[0]), asked[0]["choice"]
    engine = _engine(combat, mid)
    warden = engine.state.actors[WARDEN]
    assert warden.reaction_available is True, "a passed choice still spent the Reaction"
    assert warden.resources[pool] == before, warden.resources[pool]
