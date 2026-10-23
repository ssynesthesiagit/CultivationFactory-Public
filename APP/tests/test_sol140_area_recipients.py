"""Harmful area scopes agree before reactions, on commit, and after reload."""
import pytest

from combat.area_recipients import scoped_area
from combat.factory_compiler import _aimed_area
from combat.gate5_service import CombatService
from combat.typed_executor import _area_targets
from tests.h1_support import ROOT
from tests.test_area_shapes import _Actor, _Engine
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, table_fight


@pytest.mark.parametrize("scope,text,expected", [
    (None, "", {"enemy"}),
    ("enemies_in_area", "", {"enemy"}),
    ("creatures_in_area", "Creatures in the area take damage.", {"enemy"}),
    ("creatures_in_area", "All creatures in the area, including you, take damage.", {"enemy", "ally", "user"}),
])
def test_generic_harmful_area_guard_and_explicit_exception(scope, text, expected):
    effects = [{"type": "damage", "flat": 4, **({"applies_to": scope} if scope else {})}]
    mechanic = {"area": {"shape": "sphere", "size_ft": 15}, "effects": effects,
                "description": text}
    area = scoped_area(_aimed_area(mechanic), effects, text)
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 3, 5), _Actor("enemy", "b", 4, 4)
    assert {a.entity_id for a in _area_targets(_Engine([user, ally, enemy]), user, user.position, area)} == expected


def test_explicit_area_scope_alias_is_not_treated_as_all():
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 3, 5), _Actor("enemy", "b", 4, 4)
    area = {"shape": "sphere", "size_ft": 15, "recipients": "enemies_in_area"}
    assert _area_targets(_Engine([user, ally, enemy]), user, user.position, area) == [enemy]


def test_benefits_and_explicit_self_drawbacks_keep_their_scope():
    area = {"shape": "sphere", "size_ft": 15}
    assert scoped_area(area, [{"type": "healing", "flat": 4}]) == area
    assert scoped_area(area, [{"type": "damage", "flat": 4, "applies_to": "self"}]) == area


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("save", [False, True])
@pytest.mark.parametrize("scope,expected", [(None, {"enemy"}),
    ("enemies_in_area", {"enemy"}), ("creatures_in_area", {"enemy", "ally", "user"})])
def test_mixed_extension_roster_and_harmful_reaction_scope(legacy, save, scope, expected):
    from types import SimpleNamespace
    from combat.typed_executor import _declared_subjects
    from combat.typed_reactions import _incoming_is_adverse
    user, ally, enemy = _Actor("user", "a", 3, 4), _Actor("ally", "a", 3, 5), _Actor("enemy", "b", 4, 4)
    harm = {"type": "damage", "flat": 4, **({"applies_to": scope} if scope else {})}
    if save:
        harm = {"type": "save", **({"applies_to": scope} if scope else {}),
                "on_fail": [{"type": "damage", "flat": 4,
                             "applies_to": "creatures_in_area" if scope else "target"}],
                "on_success": []}
    if scope == "creatures_in_area":
        harm["recipient_text"] = "Each creature in the area is affected."
    effects = [harm, {"type": "practice_protection"}]
    area = {"shape": "sphere", "size_ft": 15}
    if legacy:
        area.update(recipients="all" if scope == "creatures_in_area" else "hostile", exclude_self=True)
    area = scoped_area(area, effects)
    typed = {"area": area, "effects": effects}
    targets = _area_targets(_Engine([user, ally, enemy]), user, user.position, area)
    assert targets == [user, ally, enemy]
    ctx = SimpleNamespace(actor=user, target=None, targets=targets, typed=typed)
    assert {a.entity_id for a in _declared_subjects(ctx, harm, harmful=True)} == expected
    assert {a.entity_id for a in targets if _incoming_is_adverse(user, a, typed)} == expected


@pytest.mark.parametrize("attack", [False, True], ids=["damage", "attack"])
def test_mixed_extension_without_recipient_token_commits_benefits_and_replays(tmp_path, monkeypatch, attack):
    from combat import ext
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from combat.area_safety import harmful_recipients
    from combat.typed_executor import Context
    from tests.test_lock_choices import install
    from tests.test_lock2_persistence import act
    source = "test:mixed-protection"
    harm = {"type": "attack", "attack_kind": "cultivation_ranged", "count": 1,
            "on_hit": [{"type": "damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["radiant"]}],
            "on_miss": []} if attack else {"type": "damage", "flat": 4, "damage_types": ["radiant"]}
    def compile_action(info):
        if info["actor_id"] != LEFT:
            return []
        return [ActionDefinition(source_definition_id=source, display_name="Practice protective flare",
            owner_id=LEFT, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF", radius_ft=15,
            parameters={"typed": {"numbers": {**info["numbers"], "attack_bonus": 99},
                "area": {"shape": "sphere", "size_ft": 15, "centered_on_self": True},
                "effects": [harm, {"type": "practice_protection"}]}})]
    def protect(ctx, row):
        for subject in ctx.targets:
            if subject.team_id == ctx.actor.team_id:
                ctx.engine._grant_temp_hp(subject, 7, ctx.source, ctx.actor.entity_id)
    install(monkeypatch, "compile_actions", compile_action)
    monkeypatch.setitem(ext.effects(), "practice_protection", protect)
    combat, table, mid = table_fight(tmp_path, [], ally_talents=[])
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[LEFT]
    action = next(a for a in engine.action_catalog.values() if a.source_definition_id == source)
    targets = _area_targets(engine, actor, actor.position, action.parameters["typed"]["area"], typed=action.parameters["typed"])
    ctx = Context(engine, actor, action, None, action.parameters["typed"], targets, None)
    assert harmful_recipients(ctx, ctx.typed["effects"]) == {RIGHT}
    before = {who: a.current_hp for who, a in engine.state.actors.items()}
    assert act(table, mid, source)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    if attack:
        rolls = [e for e in loaded.engine.events if e.event_type == "ATTACK_ROLLED" and e.source_definition_id == source]
        assert len(rolls) == 1 and set(rolls[0].target_ids) == {RIGHT}
    for who in (LEFT, ALLY):
        assert loaded.engine.state.actors[who].current_hp == before[who]
        assert loaded.engine.state.actors[who].temporary_hp == 7
    if attack:
        assert loaded.engine.state.actors[RIGHT].current_hp <= before[RIGHT]  # a natural 1 may miss
    else:
        assert loaded.engine.state.actors[RIGHT].current_hp == before[RIGHT] - 4
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_legacy_effect_roster_cannot_bypass_harmful_area_self_guard():
    from types import SimpleNamespace
    from combat.typed_executor import _declared_subjects
    user, enemy = _Actor("user", "a", 3, 4), _Actor("enemy", "b", 4, 4)
    ctx = SimpleNamespace(actor=user, target=None, targets=[user, enemy],
                          typed={"area": {"shape": "sphere", "size_ft": 15}})
    assert _declared_subjects(ctx, {"type": "damage"}, harmful=True) == [enemy]
    assert _declared_subjects(ctx, {"type": "damage", "applies_to": "self"}, harmful=True) == [user]
    ctx.typed["area"]["include_self"] = True
    assert _declared_subjects(ctx, {"type": "damage"}, harmful=True) == [enemy]
    # A legacy bundle has printed provenance but no compiled policy fields.
    ctx.typed["area"].pop("include_self")
    explicit = {"type": "damage", "evidence": "All creatures in the area, including you, take damage."}
    ctx.typed["effects"] = [explicit]
    assert _declared_subjects(ctx, explicit, harmful=True) == [user, enemy]


@pytest.mark.parametrize("forged", [False, True], ids=["judgment-ray", "iron-fist-rising-knee-burst"])
def test_real_area_obeys_printed_or_forged_scope_and_replays(tmp_path, monkeypatch, forged):
    from tests import test_tabletop_hunt6 as fixtures
    talent = "TAL_IRON_FIST_RISING_KNEE" if forged else "RADIANCE_TAL_JUDGMENT_RAY"
    if forged:
        original = fixtures.sheet
        def character(*args, **kwargs):
            document = original(*args, **kwargs)
            document["forged_techniques"] = [{
                "technique_id": "forged:test.rising-knee-burst", "name": "Iron Fist Rising Knee Burst",
                "primary_sphere_effect": {"talent_id": talent}, "base_form": {"form_id": "burst"},
                "augments": [], "drawbacks": [], "cp_cost": {"final": 1}, "action_type": "action"}]
            return document
        monkeypatch.setattr(fixtures, "sheet", character)
    combat, table, mid = table_fight(tmp_path, [talent], ally_talents=[], cl=10)
    label = "Iron Fist Rising Knee Burst" if forged else "Judgment Ray"
    destination = {"x": 3, "y": 4} if forged else {"x": 4, "y": 4}
    from tests.test_friendly_fire_area_table import _commit_area_action
    result, option = _commit_area_action(table, mid, label, destination)
    if forged:
        assert "Left" not in option.get("label", "").split("Hits allies too:")[-1]
    answers = []
    for _ in range(16):
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
        state = table.state(mid)
        menu = state["menu"]
        result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    sources = {key for key, action in loaded.engine.action_catalog.items() if label in action.display_name}
    relevant = [e for e in loaded.engine.events if e.source_definition_id in sources]
    saves = [e.actor_id for e in relevant if e.event_type == "SAVE_ROLLED"]
    assert RIGHT in saves
    assert LEFT not in saves
    if forged:
        assert loaded.engine.state.actors[LEFT].current_hp == 60
        assert ALLY not in saves
    else:
        assert loaded.engine.state.actors[LEFT].current_hp == 60
        assert not any("dawnmark" in c.condition_id for c in loaded.engine.state.actors[LEFT].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"
