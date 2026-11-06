"""Resonance Breaker from real Silence-Breaking Note and explicit Music Checks."""
import pytest

from combat.ext import resonance_breaker as plug
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, act, action_sender, fight, reload, resolve, turn

NOTE = "tianxia.talent.music.silence_breaking_note"


def fresh(c, mid):
    e = reload(c, mid)
    s = c._load_session(mid)
    assert s.verify()["status"] == "PASS"
    assert s.mechanical.replay()["status"] == "PASS"
    return e


def fixture(tmp_path, *, owns=True, dc=1, sphere="tianxia.sphere.sound", ai=False, check_name="Music Check", purpose="identify", extra_witness=False, disrupted=False):
    def sheet(doc, aid):
        if aid == LEFT:
            doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [plug.FEATURE] if owns else []
    def bundle(b):
        if b["actor_id"] == RIGHT:
            a = next(a for a in b["action_catalog"] if a["display_name"] == "Cause")
            a["parameters"]["typed"]["sphere"] = sphere
            a["concentration"] = True
            a["parameters"]["typed"]["duration"] = {"kind": "until_removed", "concentration": True}
    return fight(tmp_path, [NOTE], spheres=["tianxia.sphere.music"], sheet_edit=sheet, bundle_edit=bundle,
        cause=[{"type": "condition", "condition": "silenced", "applies_to": "target", "duration": {"kind": "until_removed"}}],
        cause_target="ANY_CREATURE", prepare_target="ANY_CREATURE", cause_save_dc=dc, ally=True,
        extra_witness=extra_witness, witness_position={"x": 2, "y": 5}, reaction_ask=not ai,
        prepare=[{"type": "contest_against", "actor_check": {"kind": "cultivation", "name": check_name,
            "effect_sphere": sphere, **({"purpose": purpose} if purpose is not None else {}), "effect_owner_id": RIGHT,
            **({"disrupted_actor_id": RIGHT} if disrupted else {})},
            "target_check": {"kind": "dc", "dc": dc}, "on_success": [], "on_fail": []}],
        extra_actions=[("Spend Focus", {"effects": [{"type": "spend_resource", "resource_id": plug.FOCUS, "flat": 1, "applies_to": "self"}]}),
            ("Damage", {"target_kind": "ANY_CREATURE", "effects": [
                {"type": "damage", "flat": 1, "applies_to": "target", "damage_types": ["force"]}]}),
            ("ReSilence", {"target_kind": "ANY_CREATURE", "sphere": sphere, "effects": [
                {"type": "condition", "condition": "silenced", "applies_to": "target", "duration": {"kind": "until_removed"}}]})])


def entries(e):
    return [ev for ev in e.events if ev.event_type == "PASSIVE_TRIGGERED" and ev.source_definition_id == plug.FEATURE]


@pytest.mark.parametrize("choice", ["cp", "focus", "ally:" + ALLY, "concentration"])
def test_real_music_check_offers_all_four_benefits_and_cold_reload(tmp_path, choice):
    c, t, mid = fixture(tmp_path)
    resolve(lambda a: act(t, mid, "Spend Focus", a))
    turn(t, mid, RIGHT)
    resolve(lambda a: act(t, mid, "Cause", a, target_id=ALLY))
    turn(t, mid, LEFT)
    before = fresh(c, mid).state.actors[LEFT].resources["resource:core.qi"]
    _, prompts = resolve(lambda a: act(t, mid, "Silence-Breaking Note", a, target_id=ALLY), {plug.CHOICE: [choice]})
    e = fresh(c, mid)
    q = next(p for p in prompts if p["context"]["reaction_source_id"] == plug.CHOICE)
    assert {o["id"] for o in q["choice"]["options"]} == {"cp", "focus", "ally:" + LEFT, "ally:" + ALLY, "concentration"}
    assert "Silence-Breaking Note" in str(q) and "Resonance Breaker" in str(q)
    assert e.state.actors[LEFT].resources["resource:core.qi"] == before - 5 + (choice == "cp")
    assert e.state.actors[LEFT].resources[plug.FOCUS] == int(choice == "focus")
    assert e.state.actors[ALLY].temporary_hp == (4 if choice.startswith("ally:") else 0)
    modes = [r for r in e.state.actors[RIGHT].conditions.values() if r.source_definition_id == plug.FEATURE]
    assert len(modes) == int(choice == "concentration")
    if modes:
        assert modes[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
        assert modes[0].data["rule"] == {"concentration_mode": "DISADVANTAGE", "next": True}
    assert len(entries(e)) == 1
    # Another qualifying successful check after a cold reload cannot repeat it.
    _, again = resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    assert not again and len(entries(fresh(c, mid))) == 1
    if choice == "concentration":
        resolve(lambda a: act(t, mid, "Damage", a, target_id=RIGHT))
        landed = fresh(c, mid)
        saves = [r for r in landed.rolls if r.actor_id == RIGHT and "concentration" in r.reason.lower()]
        assert saves and saves[-1].mode == "DISADVANTAGE"
        assert not any(r.source_definition_id == plug.FEATURE for r in landed.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("purpose", ["identify", "suppress", "disrupt"])
def test_all_printed_check_operations_and_ai_own_choice(tmp_path, ai, purpose):
    c, t, mid = fixture(tmp_path, ai=ai, purpose=purpose)
    resolve(lambda a: act(t, mid, "Spend Focus", a))
    _, prompts = resolve(action_sender(c, t, mid, "Prepare", target_id=RIGHT, ai=ai), {plug.CHOICE: ["focus"]})
    assert bool(prompts) != ai
    assert fresh(c, mid).state.actors[LEFT].resources[plug.FOCUS] == 1
    assert len(entries(fresh(c, mid))) == 1


@pytest.mark.parametrize("kwargs", [{"owns": False}, {"dc": 100}, {"sphere": "tianxia.sphere.force"},
                                    {"check_name": "Other Check"}, {"purpose": "ordinary_attack"}, {"purpose": None}])
def test_other_characters_failures_and_unqualified_checks_are_inert(tmp_path, kwargs):
    c, t, mid = fixture(tmp_path, **kwargs)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT))
    assert not prompts and not entries(fresh(c, mid))


def test_spirit_path_effects_qualify_without_inventing_a_sphere(tmp_path):
    c, t, mid = fixture(tmp_path, sphere="tianxia.path.spirit_awakening.feature.spiritual_exorcism")
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT), {plug.CHOICE: ["cp"]})
    assert len(entries(fresh(c, mid))) == 1


def test_decline_preserves_scene_use_and_concentration_penalty_expires(tmp_path):
    c, t, mid = fixture(tmp_path)
    resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT), {plug.CHOICE: []})
    assert not fresh(c, mid).state.actors[LEFT].turn_flags.get(plug.USED)
    turn(t, mid, RIGHT)
    resolve(lambda a: act(t, mid, "Cause", a, target_id=ALLY))
    turn(t, mid, LEFT)
    resolve(lambda a: act(t, mid, "Silence-Breaking Note", a, target_id=ALLY), {plug.CHOICE: ["concentration"]})
    assert any(r.source_definition_id == plug.FEATURE for r in fresh(c, mid).state.actors[RIGHT].conditions.values())
    turn(t, mid, RIGHT)
    turn(t, mid, LEFT)
    assert not any(r.source_definition_id == plug.FEATURE for r in fresh(c, mid).state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize("purpose", ["identify", "suppress", "disrupt"])
def test_effect_owner_alone_does_not_establish_a_disrupted_creature(tmp_path, purpose):
    c, t, mid = fixture(tmp_path, purpose=purpose)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT), {plug.CHOICE: ["ally:" + LEFT]})
    q = next(p for p in prompts if p["context"]["reaction_source_id"] == plug.CHOICE)
    assert "concentration" not in {o["id"] for o in q["choice"]["options"]}
    e = fresh(c, mid)
    assert e.state.actors[LEFT].temporary_hp == 4
    assert not any(r.source_definition_id == plug.FEATURE for r in e.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize("relation", ["ALLY", "ENEMY", "NEUTRAL"])
def test_authoritative_relations_keep_self_and_cross_team_allies_only(tmp_path, relation):
    c, t, mid = fixture(tmp_path, extra_witness=True)
    # Both changes are ordinary evented GM service commands and survive reload.
    for other, value in [(RIGHT, "ALLY"), (ALLY, relation)]:
        state = fresh(c, mid).state
        c.change_relations(mid, change={"kind": "ACTOR_RELATION", "subject": LEFT,
            "other": other, "relation": value}, expected_state_version=state.state_version)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a, target_id=ALLY if relation != "ALLY" else RIGHT),
                         {plug.CHOICE: ["ally:" + RIGHT]})
    q = next(p for p in prompts if p["context"]["reaction_source_id"] == plug.CHOICE)
    pool = {o["id"] for o in q["choice"]["options"] if o["id"].startswith("ally:")}
    assert pool == {"ally:" + LEFT, "ally:" + RIGHT} | ({"ally:" + ALLY} if relation == "ALLY" else set())
    assert fresh(c, mid).state.actors[RIGHT].temporary_hp == 4


def test_identification_with_explicit_subject_still_does_not_disrupt(tmp_path):
    c, t, mid = fixture(tmp_path, disrupted=True)
    _, prompts = resolve(lambda a: act(t, mid, "Prepare", a, target_id=RIGHT), {plug.CHOICE: ["cp"]})
    q = next(p for p in prompts if p["context"]["reaction_source_id"] == plug.CHOICE)
    assert "concentration" not in {o["id"] for o in q["choice"]["options"]}
    assert len(entries(fresh(c, mid))) == 1
