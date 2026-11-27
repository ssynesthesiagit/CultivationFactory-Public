"""AUTO89 (Disease Sphere): the printed effects this lane automated, at the table and in the authority.

Before this lane the Disease sphere's authority carried twenty mechanics with GM riders -- text the table printed for a
human to resolve. Seven of them are FULL here, so no GM line remains for them:

* Enlarged Quarantine Veil / Narrow Quarantine -- the printed radii ride the typed modifier's ``area_size_ft`` /
  ``area_size_ft_by_cl`` and its "no longer requires Concentration ... until the end of your next turn" duration.
* Plague Cloud -- the "At Core Formation ... half the Hit Points" cap runs in combat/ext/disease.py
  (tests/test_disease_plague_cloud.py drives that at the table); the cloud's look is printed description.
* Infection of the Cultivation Breath -- the table has no CP cost reductions, so "cannot reduce CP costs below printed
  values" holds with nothing left to resolve.
* Court of the Crawling Fever -- "Resistance to Poison and Necrotic damage caused by Disease talents" now resolves.
* Spreading Infection -- "You choose whether this talent can affect your allies" is the player's menu, labelled.
"""

from __future__ import annotations

import json

from combat.ext import disease
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

SOW = "DISEASE_BASE_SOW_THE_FEVER_SEED"
VEIL = "DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL"
ENLARGED = "tianxia.talent.disease.enlarged_quarantine_veil"
NARROW = "tianxia.talent.disease.narrow_quarantine"
CLOUD = "tianxia.talent.disease.plague_cloud"
BREATH = "tianxia.talent.disease.infection_of_the_cultivation_breath"
COURT = "tianxia.talent.disease.court_of_the_crawling_fever"
CLEAN = "tianxia.talent.disease.clean_carrier_method"
SPREADING = "tianxia.talent.disease.spreading_infection"
DEATH_HAND = "TAL_DEATH_WITHERING_HAND"  # another creature's Necrotic ability, for the "caused by Disease" scope
NO_BASE_ABILITIES = "automatic_sphere_component_record_ids"

AUTOMATED = [ENLARGED, NARROW, CLOUD, BREATH, COURT, SPREADING]
SEED = "AUTO89-DISEASE-1-1"

MAKER, ALLY, FOE, MARK = ("actor:factory.a89-" + name for name in ("maker", "ally", "foe", "mark"))
TEAMS = {MAKER: "team:factory", ALLY: "team:factory", FOE: "team:pestilence", MARK: "team:pestilence"}
PLACES = {MAKER: {"x": 2, "y": 6}, ALLY: {"x": 3, "y": 6}, FOE: {"x": 12, "y": 6}, MARK: {"x": 13, "y": 6}}


def mechanics():
    from combat import factory_compiler

    return json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())["mechanics"]


def _hp(doc, hp=200):
    doc["ability_scores_and_statistics"]["hit_points"] = {"maximum": hp}
    return doc


def _sheet(mids, actor_id, *, cl=12, dc=50, no_base=False):
    doc = _hp(sheet(list(mids), cl=cl, dc=dc))
    if no_base:
        doc.get("spheres_and_talents", {}).pop(NO_BASE_ABILITIES, None)
    return compile_character(doc, actor_id=actor_id)


def _disease_bases():
    mechs = mechanics()
    sphere = mechs[SOW]["sphere_id"]
    return [k for k, m in mechs.items() if m.get("sphere_id") == sphere and m.get("kind") == "base_ability"]


# -------------------------------------------------------------------------------------------------------- authority: no GM line remains
def test_automated_disease_mechanics_are_full_with_no_gm_riders():
    """Every effect this lane automated resolves in the engine, so the table no longer prints a GM line for it."""
    mechs = mechanics()
    for mid in AUTOMATED:
        row = mechs[mid]
        assert row.get("riders") == [], (mid, row.get("riders"))
        assert row.get("coverage") == "FULL", (mid, row.get("coverage"))
        assert row.get("effects") or row.get("modifier") or row.get("options"), mid


def test_enlarged_veil_carries_its_printed_radius_per_realm_and_narrow_quarantine_its_short_veil():
    """Both printed geometry lines ride typed modifier data the compiler already applies, per Realm."""
    mechs = mechanics()
    enlarged = mechs[ENLARGED]["modifier"]
    assert enlarged["area_size_ft"] == 15, enlarged
    assert [list(row) for row in enlarged["area_size_ft_by_cl"]] == [[1, 9, 15], [10, 14, 20], [15, 20, 30]], enlarged
    narrow = mechs[NARROW]["modifier"]
    assert narrow["area_size_ft"] == 5, narrow
    # "the veil no longer requires Concentration, but it lasts only until the end of your next turn"
    assert narrow["duration"]["kind"] == "until_end_of_your_next_turn", narrow
    assert narrow["duration"]["concentration"] is False, narrow


def test_compiled_veil_variants_carry_the_printed_geometry():
    """The compiled action for a character owning Enlarged/Narrow Quarantine really has those areas."""
    bundle = _sheet([*_disease_bases(), SOW, ENLARGED, NARROW], MAKER, cl=15)
    areas = {}
    for action in (bundle.get("action_catalog") or []):
        typed = (action.get("parameters") or {}).get("typed") or {}
        if typed.get("area"):
            areas[action.get("display_name")] = typed["area"]
    assert areas, "no veil variant compiled an area"
    assert any(a.get("size_ft") == 30 for a in areas.values()), areas  # Nascent Soul: 30 feet
    assert any(a.get("size_ft") == 5 for a in areas.values()), areas  # Narrow Quarantine: 5 feet


# -------------------------------------------------------------------------------------------------------- table: the Court's printed resistance
def _fight(tmp_path, mids_by_actor):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [_sheet(mids, aid, **kw) for aid, (mids, kw) in mids_by_actor.items()]
    mid = combat._finish_factory_match(
        bundles, list(TEAMS), TEAMS, PLACES, combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [MAKER], [FOE, MARK], control_modes={aid: "MANUAL" for aid in TEAMS}, match_seed=SEED,
        display_name="AUTO89 disease regression", maximum_rounds=20)["match_id"]
    engine = Gate4ControllerEngine(ROOT, match_seed=SEED, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": list(TEAMS), "team_by_actor": TEAMS,
                                                 "starting_positions": PLACES})
    return combat, table, mid, engine


def _raise_court(table, mid, answer):
    """Raise the Court of the Crawling Fever through the table, answering its "allies you choose" question with
    ``answer(prompt) -> option ids or None``. AUTO89f1: the printed choice is the maker's, so the test now answers
    it (declining leaves the maker the only beneficiary) and asks the real catalog action ids about the damage."""
    state = _turn_of(table, mid, MAKER)
    menu = state["menu"]
    group = next((g for g in menu["actions"] if "Court of the Crawling Fever" in g["label"]), None)
    assert group is not None, [g["label"] for g in menu["actions"]]
    answers, prompts = [], []
    for _ in range(12):
        result = table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        picked = answer(prompt)
        answers.append({**prompt["context"], "selection": "DECLINE" if picked is None else "USE",
                        "option_ids": list(picked or [])})
    raise AssertionError("the Court asked more questions than one action can")


def _choice_options(prompt):
    return [row["id"] for row in (prompt.get("choice") or {}).get("options") or []]


def _court_action(engine):
    """The maker's own compiled catalog action for the Court -- a real action id, not the raw mechanic id, so
    ``combat.typed_reactions._typed`` really resolves its typed row (AUTO89 review finding 3)."""
    return next(a for a in engine.state.actors[MAKER].action_ids if "court_of_the_crawling_fever" in a)


def test_court_resists_poison_and_necrotic_disease_damage_for_the_allies_its_maker_chooses(tmp_path):
    """Court of the Crawling Fever: the maker is asked which allies join, and an ally it chose takes half
    Poison/Necrotic damage from a Disease talent while another creature's own Necrotic ability still lands in
    full."""
    combat, table, mid, _ = _fight(tmp_path, {
        MAKER: ([*_disease_bases(), SOW, COURT], {}),
        ALLY: ([], {"no_base": True}),
        FOE: ([DEATH_HAND], {"no_base": True}),
        MARK: ([], {"no_base": True}),
    })
    prompts = _raise_court(table, mid, lambda prompt: [o for o in _choice_options(prompt) if o == ALLY])
    asked = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.disease_court_allies"]
    assert asked, [p["context"]["reaction_source_id"] for p in prompts]
    assert _choice_options(asked[0]) == [ALLY], asked[0]["choice"]

    engine = CombatService(ROOT, combat.userdata_root)._load_session(mid).engine
    zone = next((z for z in disease._zones_of(engine, disease.CRAWLING)), None)
    assert zone is not None, "the Court aura was never made"
    assert disease._inside(zone, engine.state.actors[ALLY]), "the ally is not standing in the aura"
    assert (zone.trigger_profile or {}).get(disease.COURT_ALLIES) == [ALLY], zone.trigger_profile

    from combat import typed_reactions

    court = _court_action(engine)
    for kind in ("NECROTIC", "POISON"):
        rows = typed_reactions.additional_defenses(engine, engine.state.actors[ALLY], kind, court, MAKER)
        assert any("resistance" in row.get("kind", "resistance") and kind in row.get("damage_types", [])
                   for row in rows), (kind, rows)
    # the maker themself is covered ("You ... gain")
    rows = typed_reactions.additional_defenses(engine, engine.state.actors[MAKER], "NECROTIC", court, MAKER)
    assert rows, "the Court's own maker gained no resistance"
    # another creature's own Necrotic ability is not "caused by Disease talents" (AUTO89f1: the printed
    # qualification is the damaging ability, not the caster's other talents)
    foe_hand = next(a for a in engine.state.actors[FOE].action_ids if a.endswith(DEATH_HAND))
    rows = typed_reactions.additional_defenses(engine, engine.state.actors[ALLY], "NECROTIC", foe_hand, FOE)
    assert not rows, rows
    # Psychic is not one of the printed damage types
    rows = typed_reactions.additional_defenses(engine, engine.state.actors[ALLY], "PSYCHIC", court, MAKER)
    assert not rows, rows


def test_court_resistance_leaves_an_ally_its_maker_did_not_choose_alone(tmp_path):
    """"You and allies you choose gain": declining the choice leaves every ally with none of the four benefits."""
    combat, table, mid, _ = _fight(tmp_path, {
        MAKER: ([*_disease_bases(), SOW, COURT], {}),
        ALLY: ([], {"no_base": True}),
        FOE: ([], {"no_base": True}),
        MARK: ([], {"no_base": True}),
    })
    _raise_court(table, mid, lambda prompt: None)
    engine = CombatService(ROOT, combat.userdata_root)._load_session(mid).engine
    zone = next(z for z in disease._zones_of(engine, disease.CRAWLING))
    assert (zone.trigger_profile or {}).get(disease.COURT_ALLIES) == [], zone.trigger_profile
    assert disease.court_covers(engine, engine.state.actors[MAKER]) is True
    assert disease.court_covers(engine, engine.state.actors[ALLY]) is False

    from combat import typed_reactions

    court = _court_action(engine)
    rows = typed_reactions.additional_defenses(engine, engine.state.actors[ALLY], "NECROTIC", court, MAKER)
    assert not rows, rows
    # and the ally keeps no Advantage on saves against Disease either
    assert disease._sheltered(engine, engine.state.actors[ALLY]) is False
    assert disease._sheltered(engine, engine.state.actors[MAKER]) is True


# -------------------------------------------------------------------------------------------------------- menu: the ally choice is the player's
def test_spreading_infection_offers_allies_and_names_them(tmp_path, monkeypatch):
    """Spreading Infection: "You choose whether this talent can affect your allies" is a player menu that
    offers the allies as well as the enemies, with labels that say which is which, instead of a silent
    nearest-hostile pick."""
    combat, table, mid, engine = _fight(tmp_path, {
        MAKER: ([*_disease_bases(), SOW, SPREADING], {}),
        ALLY: ([], {"no_base": True}),
        FOE: ([], {"no_base": True}),
        MARK: ([], {"no_base": True}),
    })
    engine = CombatService(ROOT, combat.userdata_root)._load_session(mid).engine
    maker, bearer = engine.state.actors[MAKER], engine.state.actors[FOE]
    from combat.ext.rider_support import cp_pool

    pool = cp_pool(maker)
    assert pool is not None, "the maker has no CP pool"
    maker.resources[pool] = max(2, int(maker.resources.get(pool, 0)))  # the printed cost is 2 CP
    maker.reaction_available = True
    # the bearer is infected by the maker, and stands next to one ally and one enemy
    disease.add_tokens(engine, maker, bearer, 1, SOW)
    engine.state.actors[ALLY].position = bearer.position
    engine.state.actors[FOE].position = bearer.position
    engine.state.actors[MARK].position = bearer.position

    seen = {}

    def _fake_ask(engine_, intent, cid, actor, kind, options, *, labels=None, **kwargs):
        seen["labels"] = dict(labels or {})
        seen["options"] = list(options)
        return []

    from combat.ext import rider_choices
    original = rider_choices.ask
    rider_choices.ask = _fake_ask
    try:
        disease._spreading(engine, bearer)
    finally:
        rider_choices.ask = original

    offered = list(seen.get("options", []))
    names = list(seen.get("labels", {}).values())
    assert set(offered) >= {ALLY, MARK}, seen  # the ally is offered, not only the enemy
    assert sum("an ally" in text for text in names) == 1, names
    assert sum("an enemy" in text for text in names) == 1, names


# -------------------------------------------------------------------------------------------------------- helpers (a real table, not a stub)
def _turn_of(table, mid, actor):
    import pytest

    for _ in range(2 * len(TEAMS)):
        state = table.state(mid)
        if state["menu"]["actor_id"] == actor:
            return state
        result = table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"],
                           state["last_sequence"], [])
        assert result["status"] in ("COMMITTED", "REACTION_REQUIRED"), result
        while result["status"] == "REACTION_REQUIRED":
            prompt = result["reaction"]
            result = table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"],
                               state["last_sequence"], [{**prompt["context"], "selection": "DECLINE"}])
    pytest.fail(f"{actor} never came up")


def _use(table, mid, state, label):
    menu = state["menu"]
    group = next((g for g in menu["actions"] if label in g["label"]), None)
    assert group is not None, (label, [g["label"] for g in menu["actions"]])
    result = table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                       state["last_sequence"], [])
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        result = table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], [{**prompt["context"], "selection": "DECLINE"}])
    assert result["status"] == "COMMITTED", result
    return result["state"]
