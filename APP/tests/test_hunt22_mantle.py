"""Cold Star Mantle is an optional, bearer-owned saved-table damage bonus."""
import pytest

from combat.canonical import canonical_sha256
from tests.test_c2_review import table_fixture, until_turn, action, send, auto_send, reload
from tests.test_riders_c2 import _sheet, ME, ATK, ALLY, ROOT
from combat.ext.stars import MANTLE_TURN


@pytest.mark.parametrize("accept", [False, True])
def test_manual_mantle_bearer_chooses_on_own_turn(tmp_path, accept):
    combat, table, mid = mantle_table(tmp_path)
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Cold Star Mantle", ALLY))["status"] == "COMMITTED"
    assert reload(tmp_path, mid).state.actors[ALLY].conditions
    until_turn(table, mid, ALLY)
    # Cast on an ally: the bearer, rather than the caster, owns the choice.
    cid = action(table, mid, "Starbolt", ATK)
    result = send(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["reaction"] == "Cold Star Mantle"
    assert prompt["context"]["reactor_id"] == ALLY
    before = reload(tmp_path, mid)
    assert MANTLE_TURN not in before.state.actors[ALLY].turn_flags
    answer = {**prompt["context"], "selection": "DECLINE"}
    if accept:
        answer.update(selection="USE", option_ids=[prompt["choice"]["options"][0]["id"]])
    result = send(table, mid, cid, [answer])
    assert result["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert (MANTLE_TURN in engine.state.actors[ALLY].turn_flags) == accept
    damage = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == ALLY][-1]
    # Printed Starbolt includes this fixture's +2 Path modifier; Mantle adds PB 4.
    assert damage.payload["modifier"] == 2 + (4 if accept else 0)


def mantle_table(tmp_path, *, miss=False, reactive=False, legacy=False, weapon=False, abort=False, spend_first=False):
    def configure(bundles):
        for bundle in bundles:
            bundle["actor_template"]["maximum_hp"] = 500
            bundle["actor_template"]["armor_class"] = 1000 if miss and bundle["actor_id"] == ATK else 0
            for a in bundle["action_catalog"]:
                if spend_first and bundle["actor_id"] == ALLY and a["display_name"] == "Starbolt":
                    # Test-only economy permits two damage packets in one turn;
                    # the production Starbolt rule and engine are unchanged.
                    a["economy"] = "BONUS_ACTION"
                typed = a.get("parameters", {}).get("typed", {})
                numbers = typed.get("numbers")
                if numbers:
                    numbers["attack_bonus"] = 100
                if legacy and typed.get("source") == "tianxia.talent.stars.cold_star_mantle":
                    typed["effects"] = [{"type": "hunt22_legacy_mantle"}]
                if weapon and bundle["actor_id"] == ALLY and typed.get("weapon"):
                    typed["weapon"].update(damage_type="COLD", damage_types=["COLD"])
            if legacy:
                for r in bundle.get("typed_reactions", []):
                    r["ask"] = False  # No unrelated Ask-me ownership marker.
                for r in bundle.get("typed_passives", []):
                    r.pop("choice_owner", None)
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    bearer = _sheet(["STARS_BASE_STARBOLT"], weapon="tianxia.mortal.weapon.fu" if weapon else None)
    if reactive:
        bearer["path_and_subpath"]["path_feature_record_ids"] = [
            "tianxia.subpath.qi.mirror_cultivator.feature.reflective_skin"]
        bearer["ability_scores_and_statistics"]["primary_resource"] = {"name": "Qi", "maximum": 30}
    enemy = _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"])
    if abort:
        from tests.test_hunt22_pursuer import PURSUER
        enemy["path_and_subpath"]["path_feature_record_ids"] = [PURSUER]
        enemy["ability_scores_and_statistics"]["primary_resource"] = {"name": "Resonance", "maximum": 30}
    return table_fixture(tmp_path, {
        ME: _sheet(["tianxia.talent.stars.cold_star_mantle"], weapon=None),
        ALLY: bearer,
        ATK: enemy,
    }, {ME: (3, 6), ALLY: (3, 7), ATK: (4, 7) if reactive or weapon else (8, 6)}, seed="H22-MANTLE", configure=configure)


@pytest.fixture
def legacy_mantle_effect():
    """Generate the old persisted payload through an ordinary table transaction.

    Test-only effect registration, not a replacement of any engine/plugin code.
    """
    from combat import ext
    from combat.ext.stars import MANTLE

    @ext.effect("hunt22_legacy_mantle")
    def grant(ctx, eff):
        from combat.typed_executor import effect_expiry
        ctx.engine._apply_condition(ctx.target, MANTLE, ctx.source, ctx.actor.entity_id,
                                    expires_on=effect_expiry(ctx, {}, ctx.target, condition=True),
                                    data={"label": "Cold Star Mantle", "pb": 4})
    try:
        yield
    finally:
        ext.effects().pop("hunt22_legacy_mantle", None)


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("accept", [False, True])
def test_manual_mantle_bearer_chooses_during_enemy_turn(tmp_path, auto, accept):
    combat, table, mid = mantle_table(tmp_path, reactive=True)
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Cold Star Mantle", ALLY))["status"] == "COMMITTED"
    reload(tmp_path, mid)
    until_turn(table, mid, ATK)
    cid = action(table, mid, "Fu (Short Axe) attack", ALLY)
    answers, mantle_prompts = [], []
    for _ in range(16):
        r = auto_send(combat, table, mid, cid, answers) if auto else send(table, mid, cid, answers)
        if r["status"] == "COMMITTED":
            break
        p = r["reaction"]
        answer = {**p["context"], "selection": "DECLINE"}
        if p["reaction"] == "Reflective Skin":
            answer["selection"] = "USE"
        elif p["reaction"] == "Cold Star Mantle":
            mantle_prompts.append(p)
            assert p["context"]["reactor_id"] == ALLY
            assert "Reflective Skin" in p["moment"]
            if accept:
                answer.update(selection="USE", option_ids=[p["choice"]["options"][0]["id"]])
        answers.append(answer)
    else:
        pytest.fail("unending reaction prompts")
    assert mantle_prompts
    engine = reload(tmp_path, mid)
    assert (MANTLE_TURN in engine.state.actors[ALLY].turn_flags) == accept


@pytest.mark.parametrize("miss", [False, True])
def test_ai_mantle_bearer_is_automatic_and_miss_preserves_allowance(tmp_path, miss):
    combat, table, mid = mantle_table(tmp_path, miss=miss)
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Cold Star Mantle", ALLY))["status"] == "COMMITTED"
    reload(tmp_path, mid)
    until_turn(table, mid, ALLY)
    result = auto_send(combat, table, mid, action(table, mid, "Starbolt", ATK))
    assert result["status"] == "COMMITTED"
    assert (MANTLE_TURN in reload(tmp_path, mid).state.actors[ALLY].turn_flags) == (not miss)


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("accept", [False, True])
def test_legacy_mantle_without_other_choice_marker(tmp_path, legacy_mantle_effect, auto, accept):
    from combat.ext.stars import MANTLE
    combat, table, mid = mantle_table(tmp_path, reactive=True, legacy=True)
    assert ALLY not in combat._load_session(mid).engine.typed_ask_reactors
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Cold Star Mantle", ALLY))["status"] == "COMMITTED"
    until_turn(table, mid, ATK)
    engine = reload(tmp_path, mid)
    bearer = engine.state.actors[ALLY]
    assert next(c for c in bearer.conditions.values() if c.condition_id == MANTLE).data == {"label": "Cold Star Mantle", "pb": 4}
    assert not any(r.get("ask") for r in engine.typed_reaction_rows[ALLY])
    assert not any(r.get("choice_owner") for r in engine.typed_passive_rows.get(ALLY, []))
    assert not any(c.data.get("choice_owner") for c in bearer.conditions.values())
    cid = action(table, mid, "Fu (Short Axe) attack", ALLY)
    run = lambda answers: auto_send(combat, table, mid, cid, answers) if auto else send(table, mid, cid, answers)
    result = run([])
    assert result["status"] == "REACTION_REQUIRED"
    p = result["reaction"]
    assert p["reaction"] == "Cold Star Mantle"
    assert p["context"]["reactor_id"] == ALLY
    answer = {**p["context"], "selection": "DECLINE"}
    if accept:
        answer.update(selection="USE", option_ids=[p["choice"]["options"][0]["id"]])
    assert run([answer])["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert (MANTLE_TURN in engine.state.actors[ALLY].turn_flags) == accept
    assert not next(c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id == MANTLE).data.get("choice_owner")


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("outcome", ["hit", "miss", "abort"])
def test_weapon_mantle_is_deferred_without_prompt_or_spending(tmp_path, auto, outcome):
    combat, table, mid = mantle_table(tmp_path, weapon=True, miss=outcome == "miss", abort=outcome == "abort")
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Cold Star Mantle", ALLY))["status"] == "COMMITTED"
    until_turn(table, mid, ALLY)
    before = reload(tmp_path, mid).state.event_sequence
    cid = action(table, mid, "Fu (Short Axe) attack", ATK)
    answers = []
    for _ in range(10):
        result = auto_send(combat, table, mid, cid, answers) if auto else send(table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            break
        p = result["reaction"]
        assert p["reaction"] != "Cold Star Mantle"
        assert "Turn the Pursuer" in p["reaction"]
        option = next(o for o in p["choice"]["options"] if o["id"] == "cell:5,7")
        answers.append({**p["context"], "selection": "USE", "option_ids": [option["id"]]})
    else:
        pytest.fail("weapon action did not commit")
    engine = reload(tmp_path, mid)
    assert MANTLE_TURN not in engine.state.actors[ALLY].turn_flags
    events = [e for e in engine.events if e.sequence > before]
    attacks = [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ALLY]
    if outcome == "abort":
        assert not attacks
    else:
        assert attacks and attacks[-1].payload["provisional_hit"] == (outcome == "hit")
    damage = [e for e in events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == ALLY]
    assert bool(damage) == (outcome == "hit")
    if damage:
        assert damage[0].payload["modifier"] == 2  # Weapon ability only; GM bonus is not automated.
    note = next(e.payload["rider"] for e in events if e.event_type == "GM_RIDER" and "GM applies" in str(e.payload))
    assert engine.state.actors[ALLY].display_name in note
    assert engine.state.actors[ATK].display_name in note
    assert "Fu (Short Axe) attack" in note and "add 4" in note
    assert "shares the once-per-turn allowance with automated damage" in note
    assert "GM must track" in note


@pytest.mark.parametrize("auto", [False, True])
def test_spent_mantle_weapon_reminder_is_suppressed_after_reload(tmp_path, auto):
    combat, table, mid = mantle_table(tmp_path, weapon=True, spend_first=True)
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Cold Star Mantle", ALLY))["status"] == "COMMITTED"
    until_turn(table, mid, ALLY)
    cid = action(table, mid, "Starbolt", ATK)
    result = send(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["reaction"] == "Cold Star Mantle"
    answer = {**prompt["context"], "selection": "USE",
              "option_ids": [prompt["choice"]["options"][0]["id"]]}
    assert send(table, mid, cid, [answer])["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    spent = engine.state.actors[ALLY].turn_flags[MANTLE_TURN]
    damage = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == ALLY][-1]
    assert damage.payload["modifier"] == 6  # Starbolt's +2 Path modifier plus Mantle's PB 4.
    before = engine.state.event_sequence
    # Use new service instances so the weapon path consumes the persisted flag.
    combat = type(combat)(ROOT, tmp_path)
    table = type(table)(combat, tmp_path)
    cid = action(table, mid, "Fu (Short Axe) attack", ATK)
    result = auto_send(combat, table, mid, cid) if auto else send(table, mid, cid)
    assert result["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].turn_flags[MANTLE_TURN] == spent
    events = [e for e in engine.events if e.sequence > before]
    assert not any(e.event_type == "GM_RIDER" and "Cold Star Mantle" in str(e.payload) for e in events)
    damage = [e for e in events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == ALLY]
    assert damage and damage[0].payload["modifier"] == 2
