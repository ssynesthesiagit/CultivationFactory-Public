"""Printed kind switches through table transactions, persisted reloads and AI turns."""
import copy
import json
from types import SimpleNamespace

import pytest

from combat.canonical import canonical_sha256
from combat.ext import creature_kinds
from tests import test_riders_c7 as body, test_riders_c8 as spirit
from tests.thrum_grave_support import TG  # moved here by 18faa4ab (was spirit.TG)
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import reload

CHALLENGE = "GUARDIAN_BASE_CHALLENGE_PRACTICE"
TRACE = "TAL_UNMAKING_BLACK_TRACE"
UNBODY = "TAL_UNMAKING_UNBODY_THE_FALSE_VESSEL"
BREAKING = "tianxia.subpath.body.stone_fist.feature.breaking_fist"
RADIANT = "tianxia.subpath.body.goruden.feature.radiant_fist"
SPORE = spirit.MW + "spore_murmur"
DRAIN = spirit.SW + "soul_drain_and_death_custody"
DRUM = TG + "burial_drum"
BELL = spirit.EX + "purification_bell"
SEAL = spirit.EX + "seal_of_binding"


def setup(mid, kind=None, *, family=None, free_strike=False, setup_heal=False):
    def prepare(bundles):
        owner, foe, second = bundles
        if family == "spirit":
            owner.clear()
            owner.update(spirit.bundle([mid], actor_id=OWNER, dc=50, cl=17))
        elif family == "body":
            owner.clear()
            owner.update(body.bundle([mid], actor_id=OWNER, dc=50, cl=17))
        owner["actor_template"]["maximum_hp"] = 500
        foe["actor_template"]["creature_types"] = [kind] if kind else []
        foe["actor_template"]["saving_throws"].update(CHA=10, CON=-10)
        # Keep the transaction's hit deterministic apart from the normal natural-1 rule.
        for action in owner["action_catalog"]:
            if free_strike and action["display_name"].startswith("Unarmed Strike"):
                action["economy"] = "NONE"  # Test-only repeated hits in the same turn.
                # NONE is not a primary activation without an explicit declaration (combat/primary_intents.py, ad49b65f).
                action["parameters"] = {**(action.get("parameters") or {}), "free_primary": True}
            if action.get("attack_bonus") is not None:
                action["attack_bonus"] = 100
            numbers = (action.get("parameters") or {}).get("typed", {}).get("numbers")
            if numbers is not None:
                numbers["attack_bonus"] = 100
        if setup_heal:
            # Test-only wound and healing action; the Drum is the unchanged printed action.
            source = next(a for a in owner["action_catalog"] if a["display_name"] == "Burial Drum")
            extra = copy.deepcopy(source)
            extra.update(source_definition_id="test:a11.heal", display_name="Test wound and heal", economy="NONE", costs=[], target_kind="ANY_CREATURE", range_ft=30)
            extra["parameters"]["free_primary"] = True  # Declared free activation (combat/primary_intents.py).
            extra["parameters"]["typed"].update(range={"kind": "feet", "feet": 30}, area=None, riders=[], effects=[
                {"type": "damage", "flat": 20, "damage_types": ["force"], "applies_to": "target"},
                {"type": "healing", "flat": 10, "applies_to": "target"}])
            owner["action_catalog"].append(extra)
            owner["actor_template"]["action_ids"].append(extra["source_definition_id"])
        for b in bundles:
            b.pop("bundle_sha256", None)
            b["bundle_sha256"] = canonical_sha256(b)
    return prepare


def commit_with_choices(combat, table, mid, send, cid, *, auto=False, pick=None):
    if auto:
        force_ai_candidate(combat, mid, OWNER, cid)
    answers, prompts = [], []
    for _ in range(20):
        result = send(cid, answers, auto=auto)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        prompts.append(p)
        answer = {**p["context"], "selection": "DECLINE"}
        if p.get("choice"):
            options = p["choice"]["options"]
            selected = next((o["id"] for o in options if pick and pick in (o.get("label") or o["id"])), None)
            preferred = p["choice"].get("preferred") or [options[0]["id"]]
            maximum = p["choice"].get("maximum_selections", 1)
            answer.update(selection="USE", option_ids=[selected] if selected else preferred[:maximum])
        answers.append(answer)
    raise AssertionError("too many choices")


@pytest.mark.parametrize("label,wanted", [("Mindless", "mindless"), ("Animated", "animated"),
    ("Possessed", "unclean"), ("Possessing Entities", "unclean"), ("Fiendish", "fiend"),
    ("Puppet Bodies", "puppet body"), ("Daemonic-tagged", "daemonic"), ("Spirit-Beasts", "spirit beast"),
    ("Animated Constructs", "construct"), ("Undead Spirit", "unclean")])
def test_explicit_backlog_vocabulary_and_plural_labels(label, wanted):
    assert creature_kinds.matches(SimpleNamespace(creature_types=[label]), wanted)


def test_no_inferred_kind_from_name_immunity_or_animation():
    actor = SimpleNamespace(creature_types=[], display_name="Mindless possessed construct", intelligence=0)
    assert not creature_kinds.matches(actor, ["mindless", "possessed", "construct"])
    actor.creature_types = ["Animated"]
    assert not creature_kinds.matches(actor, ["construct", "temporary body"])


@pytest.mark.parametrize("include", [False, True])
def test_reviewed_menu_overflow_is_opt_in_and_preserves_existing_action_indices(include):
    from combat import factory_compiler
    from tests.h1_support import sheet
    document = json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())
    options = document["mechanics"][TRACE]["options"]
    for option in options:
        option.pop("include_in_menu", None)
    extra = copy.deepcopy(options[0])
    extra.update(label="Test eighth printed branch", include_in_menu=include)
    options.append(extra)
    b = factory_compiler.compile_character(sheet([TRACE]), actor_id=OWNER, typed_authority=document)
    ids = {a["source_definition_id"] for a in b["action_catalog"] if TRACE in a["source_definition_id"]}
    assert all(any(a.endswith(f"#opt{n}") for a in ids) for n in range(6))
    assert not any(a.endswith("#opt6") for a in ids)
    assert any(a.endswith("#opt7") for a in ids) is include


@pytest.mark.parametrize("auto", [False, True])
def test_challenge_cannot_target_a_labelled_mindless_creature_after_reload(tmp_path, auto):
    combat, table, mid, send, _ = fixture(tmp_path, [CHALLENGE], bundle_transform=setup(CHALLENGE, "Mindless"))
    assert not [o for g in table.state(mid)["menu"]["actions"] if g["label"] == "Challenge"
                for o in g["options"] if FOE in o.get("target_ids", [])]
    cid = candidate(table, mid, "Challenge", SECOND)
    commit_with_choices(combat, table, mid, send, cid, auto=auto)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id.endswith(".challenged") for c in engine.state.actors[FOE].conditions.values())
    assert any(c.condition_id.endswith(".challenged") for c in engine.state.actors[SECOND].conditions.values())
    assert creature_kinds.matches(engine.state.actors[FOE], "mindless")


@pytest.mark.parametrize("mid,label,kind", [(UNBODY, "Unbody the False Vessel", "Temporary Body"), (SEAL, "Seal of Binding", "Possessed")])
@pytest.mark.parametrize("auto", [False, True])
def test_printed_non_summon_kinds_are_offered_committed_and_persisted(tmp_path, mid, label, kind, auto):
    combat, table, match, send, _ = fixture(tmp_path, [mid], bundle_transform=setup(mid, kind, family="spirit" if mid == SEAL else None))
    cid = candidate(table, match, label, FOE)
    assert not [o for g in table.state(match)["menu"]["actions"] if label in g["label"]
                for o in g["options"] if SECOND in o.get("target_ids", [])]
    commit_with_choices(combat, table, match, send, cid, auto=auto)
    after = reload(tmp_path, match)
    assert creature_kinds.matches(after.state.actors[FOE], kind)
    if mid == UNBODY:
        assert after.state.actors[FOE].current_hp < 500
    else:
        assert any(c.condition_id.endswith(".binding_seal") for c in after.state.actors[FOE].conditions.values())


@pytest.mark.parametrize("auto", [False, True])
def test_black_trace_crack_adds_pb_only_to_construct_damage(tmp_path, auto):
    outcomes = []
    for kind in ["Construct", None]:
        folder = tmp_path / (kind or "ordinary")
        combat, table, match, send, _ = fixture(folder, [TRACE], bundle_transform=setup(TRACE, kind))
        cid = candidate(table, match, "Black Trace: Crack", FOE)
        commit_with_choices(combat, table, match, send, cid, auto=auto)
        after = reload(folder, match)
        assert after.state.actors[FOE].current_hp < 500
        outcomes.append(after.state.actors[FOE].current_hp)
    assert outcomes[1] - outcomes[0] == 4


@pytest.mark.parametrize("mid,label,kind", [(BREAKING, "Unarmed Strike", "Construct"), (RADIANT, "Unarmed Strike", "Daemonic-tagged")])
@pytest.mark.parametrize("auto", [False, True])
def test_unarmed_kind_bonus_matches_print_and_survives_table_reload(tmp_path, mid, label, kind, auto):
    outcomes = []
    for target_kind in [kind, None]:
        folder = tmp_path / (target_kind or "ordinary")
        combat, table, match, send, _ = fixture(folder, [mid], bundle_transform=setup(mid, target_kind, family="body"))
        cid = candidate(table, match, label, FOE)
        commit_with_choices(combat, table, match, send, cid, auto=auto, pick="Extra Radiant Damage")
        after = reload(folder, match)
        assert after.state.actors[FOE].current_hp < 500
        outcomes.append(after.state.actors[FOE].current_hp)
        if mid == BREAKING and target_kind:
            assert after.state.actors[OWNER].turn_flags["creature_kind_once:" + BREAKING] == f"{after.state.round_number}:{OWNER}"
            assert type(after.state.actors[OWNER].turn_flags["creature_kind_once:" + BREAKING]) is str
    assert outcomes[1] - outcomes[0] == 6


@pytest.mark.parametrize("auto", [False, True])
def test_soul_drain_uses_higher_charisma_for_possessed_creature_after_reload(tmp_path, auto):
    combat, table, match, send, _ = fixture(tmp_path, [DRAIN], bundle_transform=setup(DRAIN, "Possessed", family="spirit"))
    cid = candidate(table, match, "Soul Drain", FOE)
    commit_with_choices(combat, table, match, send, cid, auto=auto)
    engine = reload(tmp_path, match)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert any(e.payload["reason"].endswith(":CHA") for e in saves)


@pytest.mark.parametrize("auto", [False, True])
def test_purification_bell_filters_ordinary_creatures_from_choice_and_damage(tmp_path, auto):
    combat, table, match, send, _ = fixture(tmp_path, [BELL], bundle_transform=setup(BELL, "Possessing Entity", family="spirit"))
    cid = candidate(table, match, "Purification Bell")
    prompts = commit_with_choices(combat, table, match, send, cid, auto=auto)
    for p in prompts:
        if p.get("choice") and any(o["id"] == FOE for o in p["choice"]["options"]):
            assert not any(o["id"] == SECOND for o in p["choice"]["options"])
    engine = reload(tmp_path, match)
    assert engine.state.actors[FOE].current_hp < 500
    assert engine.state.actors[SECOND].current_hp == 500


@pytest.mark.parametrize("kind", ["Mindless", None])
@pytest.mark.parametrize("auto", [False, True])
def test_spore_murmur_prompt_omits_mental_options_only_for_mindless(tmp_path, kind, auto):
    combat, table, match, send, _ = fixture(tmp_path, [SPORE], bundle_transform=setup(SPORE, kind, family="spirit"))
    prompts = commit_with_choices(combat, table, match, send, candidate(table, match, "Spore Murmur: Psychic", FOE), auto=auto)
    if not auto:
        options = next(p["choice"]["options"] for p in prompts if p.get("choice") and any(o["id"] == "heavy_cap" for o in p["choice"]["options"]))
        assert ({"false_forest", "drowsing_root"} <= {o["id"] for o in options}) is (kind is None)
    assert reload(tmp_path, match).state.actors[FOE].current_hp < 500


def test_breaking_fist_cannot_add_bonus_again_after_saved_same_turn_reload(tmp_path):
    damage = []
    for kind in ["Construct", None]:
        folder = tmp_path / (kind or "ordinary")
        combat, table, match, send, _ = fixture(folder, [BREAKING], bundle_transform=setup(BREAKING, kind, family="body", free_strike=True))
        hp = []
        for _ in range(2):
            commit_with_choices(combat, table, match, send, candidate(table, match, "Unarmed Strike", FOE))
            hp.append(reload(folder, match).state.actors[FOE].current_hp)
        damage.append([500 - hp[0], hp[0] - hp[1]])
    assert damage[0][0] - damage[1][0] == 6
    assert damage[0][1] == damage[1][1]


def test_breaking_fist_legacy_used_turn_continues_commits_and_renews(tmp_path, monkeypatch):
    from combat import ext
    from combat.gate5_service import CombatService
    from tests.persistence_support import inventory
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT

    key = "creature_kind_once:" + BREAKING
    outcomes = []
    for kind in ["Construct", None]:
        folder = tmp_path / (kind or "ordinary")

        def prepare(bundles):
            setup(BREAKING, kind, family="body", free_strike=True)(bundles)
            # A test-only free counter exercises renewed eligibility before
            # the owner's next turn can clear its turn flags.
            bundles[0]["typed_reactions"].append({
                "block": "generic", "kind": "attacked", "feature_id": "test:a11.legacy_counter",
                "name": "Test unarmed counter", "ask": True, "free": True, "costs": [],
                "range_ft": 5, "numbers": {}, "effects": [
                    {"type": "attack", "attack_kind": "unarmed", "strike_with": "unarmed"}]})
            for b in bundles[1:]:
                aid = b["actor_id"]
                b.clear()
                b.update(body.bundle([], actor_id=aid, cl=17))
                b["actor_template"].update(maximum_hp=500, creature_types=[kind] if kind else [])
            for b in bundles:
                b.pop("bundle_sha256", None)
                b["bundle_sha256"] = canonical_sha256(b)

        combat, table, match, send, _ = fixture(folder, [BREAKING], bundle_transform=prepare,
            positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 3, "y": 7}})

        def legacy_landed(ctx, target, hit_kind):
            # Reproduce the prior persisted representation through the actual
            # hit/commit path. Only this plug-in hook changes during capture;
            # no engine classes, journals or hashes are patched.
            for target_id, pending_key, _ in ctx.damage_cache.pop("_unarmed_kind_pending", []):
                if target_id == getattr(target, "entity_id", None):
                    ctx.actor.turn_flags[pending_key] = 1

        with monkeypatch.context() as capture:
            capture.setitem(ext._HOOKS, "after_hit", [
                legacy_landed if callback is creature_kinds.unarmed_kind_landed else callback
                for callback in ext._HOOKS["after_hit"]])
            commit_with_choices(combat, table, match, send, candidate(table, match, "Unarmed Strike", FOE))
        prior = reload(folder, match)
        if kind:
            assert type(prior.state.actors[OWNER].turn_flags[key]) is int
            assert prior.state.actors[OWNER].turn_flags[key] == 1
        source = combat._load_session(match).store.match_dir
        original = inventory(source)
        # This prior numeric turn-flag shape still fits the data schema. A fresh
        # service can continue the same match without a compatibility approval.
        combat = CombatService(ROOT, folder)
        table = TabletopService(combat, folder)

        def send(cid, answers=(), auto=False):
            menu = table.state(match)["menu"]
            return table.act(match, cid, menu["decision_id"], menu["state_version"], 0, list(answers))

        resumed = reload(folder, match)
        assert inventory(source) == original
        assert resumed.state.current_actor_id == OWNER
        assert resumed.state.actors[FOE].current_hp == prior.state.actors[FOE].current_hp
        if kind:
            assert type(resumed.state.actors[OWNER].turn_flags[key]) is int
        damage = [500 - resumed.state.actors[FOE].current_hp]
        for _ in range(2):
            before = reload(folder, match)
            commit_with_choices(combat, table, match, send, candidate(table, match, "Unarmed Strike", FOE))
            after = reload(folder, match)
            hits = [e for e in after.events if e.sequence > before.state.event_sequence
                    and e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]
            assert len(hits) == 1 and hits[0].payload["provisional_hit"]
            damage.append(before.state.actors[FOE].current_hp - after.state.actors[FOE].current_hp)
            if kind:
                assert after.state.actors[OWNER].turn_flags[key] == f"{after.state.round_number}:{OWNER}"
                assert type(after.state.actors[OWNER].turn_flags[key]) is str
        commit_with_choices(combat, table, match, send, table.state(match)["menu"]["end_turn"])
        active = table.state(match)["menu"]["actor_id"]
        assert active in (FOE, SECOND)
        before = reload(folder, match)
        commit_with_choices(combat, table, match, send, candidate(table, match, "Unarmed Strike", OWNER))
        after = reload(folder, match)
        hits = [e for e in after.events if e.sequence > before.state.event_sequence
                and e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]
        assert len(hits) == 1 and hits[0].payload["provisional_hit"]
        damage.append(before.state.actors[active].current_hp - after.state.actors[active].current_hp)
        if kind:
            assert after.state.actors[OWNER].turn_flags[key] == f"{after.state.round_number}:{active}"
        outcomes.append(damage)
    assert [a - b for a, b in zip(*outcomes)] == [6, 0, 0, 6]


def test_breaking_fist_miss_preserves_bonus_through_table_commit_reload(tmp_path):
    outcomes = []
    for kind in ["Construct", None]:
        folder = tmp_path / (kind or "ordinary")

        def prepare(bundles):
            setup(BREAKING, kind, family="body", free_strike=True)(bundles)
            owner = bundles[0]
            strike = next(a for a in owner["action_catalog"] if a["display_name"].startswith("Unarmed Strike"))
            miss = copy.deepcopy(strike)
            miss.update(source_definition_id="test:a11.miss", display_name="Test missed unarmed strike", attack_bonus=-100)
            miss["parameters"]["typed"]["numbers"]["attack_bonus"] = -100
            owner["action_catalog"].append(miss)
            owner["actor_template"]["action_ids"].append(miss["source_definition_id"])
            owner.pop("bundle_sha256")
            owner["bundle_sha256"] = canonical_sha256(owner)

        combat, table, match, send, _ = fixture(folder, [BREAKING], bundle_transform=prepare)
        commit_with_choices(combat, table, match, send, candidate(table, match, "Test missed unarmed strike", FOE))
        after_miss = reload(folder, match)
        assert after_miss.state.actors[FOE].current_hp == 500
        assert "creature_kind_once:" + BREAKING not in after_miss.state.actors[OWNER].turn_flags
        assert any(e.event_type == "ATTACK_ROLLED" and not e.payload["provisional_hit"] for e in after_miss.events)
        commit_with_choices(combat, table, match, send, candidate(table, match, "Unarmed Strike", FOE))
        outcomes.append(reload(folder, match).state.actors[FOE].current_hp)
    assert outcomes[1] - outcomes[0] == 6


@pytest.mark.parametrize("own_hit", [False, True])
def test_breaking_fist_reactions_use_current_turn_after_table_commit_reload(tmp_path, own_hit):
    outcomes = []
    stamps = []
    for kind in ["Construct", None]:
        folder = tmp_path / (kind or "ordinary")

        def prepare(bundles):
            setup(BREAKING, kind, family="body", free_strike=True)(bundles)
            owner = bundles[0]
            # Test-only two-strike counter: a paid Ask me reaction after an
            # own-turn hit, or a free automatic counter on two different turns.
            owner["typed_reactions"].append({
                "block": "generic", "kind": "attacked", "feature_id": "test:a11.counter",
                "name": "Test unarmed counter", "ask": True, "free": not own_hit, "costs": [],
                "range_ft": 5, "numbers": {}, "effects": [
                    {"type": "attack", "attack_kind": "unarmed", "count": 2, "strike_with": "unarmed"}]})
            for b in bundles[1:]:
                aid = b["actor_id"]
                b.clear()
                b.update(body.bundle([], actor_id=aid, cl=17))
                b["actor_template"].update(maximum_hp=500, creature_types=[kind] if kind else [])
            for b in bundles:
                b.pop("bundle_sha256", None)
                b["bundle_sha256"] = canonical_sha256(b)

        combat, table, match, send, _ = fixture(folder, [BREAKING], bundle_transform=prepare,
            positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 3, "y": 7}})
        damage = []
        if own_hit:
            commit_with_choices(combat, table, match, send, candidate(table, match, "Unarmed Strike", FOE))
            after = reload(folder, match)
            damage.append(500 - after.state.actors[FOE].current_hp)
        commit_with_choices(combat, table, match, send, table.state(match)["menu"]["end_turn"])
        for _ in range(1 if own_hit else 2):
            active = table.state(match)["menu"]["actor_id"]
            assert active in (FOE, SECOND)
            before = reload(folder, match)
            cid = candidate(table, match, "Unarmed Strike", OWNER)
            answers, prompts = [], []
            for _ in range(20):
                result = send(cid, answers)
                if result["status"] == "COMMITTED":
                    break
                assert result["status"] == "REACTION_REQUIRED", result
                p = result["reaction"]
                prompts.append(p)
                answers.append({**p["context"], "selection": "USE" if p["context"]["reaction_source_id"] == "reaction:typed.test:a11.counter" else "DECLINE"})
            else:
                raise AssertionError("too many reaction prompts")
            assert any(p["context"]["reaction_source_id"] == "reaction:typed.test:a11.counter" for p in prompts) is own_hit
            after = reload(folder, match)
            attacks = [e for e in after.events if e.sequence > before.state.event_sequence
                       and e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]
            assert len(attacks) == 2 and all(e.payload["provisional_hit"] for e in attacks)
            damage.append(before.state.actors[active].current_hp - after.state.actors[active].current_hp)
            if kind:
                stamps.append((after.state.actors[OWNER].turn_flags["creature_kind_once:" + BREAKING],
                               f"{after.state.round_number}:{active}"))
            commit_with_choices(combat, table, match, send, table.state(match)["menu"]["end_turn"])
        outcomes.append(damage)
    # Each two-hit reaction gets PB once, independently on each acting creature's
    # turn. Own-turn use, when present, cannot suppress either off-turn bonus.
    assert [a - b for a, b in zip(*outcomes)] == [6] * len(outcomes[0])
    assert all(stored == expected for stored, expected in stamps)


@pytest.mark.parametrize("kind", ["Undead", "Possessed", "Death-sustained", None])
def test_burial_drum_kind_damage_after_aura_commit_and_reload(tmp_path, kind):
    combat, table, match, send, _ = fixture(tmp_path, [DRUM], bundle_transform=setup(DRUM, kind, family="spirit", setup_heal=True))
    commit_with_choices(combat, table, match, send, candidate(table, match, "Burial Drum"))
    assert reload(tmp_path, match).state.actors[FOE].current_hp == 500
    commit_with_choices(combat, table, match, send, candidate(table, match, "Test wound and heal", FOE))
    assert reload(tmp_path, match).state.actors[FOE].current_hp == 480 - (12 if kind else 0)


def test_stock_saved_ai_continuation_is_byte_identical_without_kind_rows(monkeypatch):
    from combat import ext
    from tests.test_hunt32_inert_replay import _capture
    enabled = _capture()
    for point, callbacks in list(ext._HOOKS.items()):
        monkeypatch.setitem(ext._HOOKS, point, [f for f in callbacks if f.__module__ != "combat.ext.creature_kinds"])
    assert _capture() == enabled
