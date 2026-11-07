"""Zero-Hit-Point replacers: one resolves per lethal hit, each limited per scene, after earlier reduction."""
from combat import typed_reactions
from combat.factory_compiler import compile_character
from tests.test_auto_bodya import AN, BODY_REFINING_SHEET, ME, _engine

PATH = "tianxia.path.body_refining.feature."
STAMINA = "resource:core.stamina"


def _owner(*features):
    sheet = {**BODY_REFINING_SHEET, "path_and_subpath": {"path_feature_record_ids": [PATH + "iron_fist", *features]}}
    engine = _engine(compile_character(sheet, actor_id=ME))
    me = engine.state.actors[ME]
    me.resources[STAMINA], me.current_hp = 10, 20
    return engine, me


def _lethal(engine, me, source=None):
    pending = typed_reactions.on_damage(engine, me, 999, 0, source_definition_id=source, source_actor_id=AN)
    engine._commit_damage(me, pending, "FORCE", "reaction:test.lethal", AN, None, reaction_depth=0)


def test_blood_pump_works_once_per_scene():
    engine, me = _owner(PATH + "blood_pump")
    _lethal(engine, me)
    assert me.current_hp == 1 and me.resources[STAMINA] == 4
    me.current_hp, me.resources[STAMINA] = 20, 10
    _lethal(engine, me)
    assert me.current_hp <= 0 and me.resources[STAMINA] == 10


def test_only_one_replacer_resolves_for_a_lethal_hit():
    engine, me = _owner(PATH + "blood_pump", "tianxia.subpath.body.iron_shirt.feature.invincible_iron")
    rows = typed_reactions._generic_rows(engine, ME, "drop_to_zero")
    assert len(rows) == 2
    _lethal(engine, me)
    resolved = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and (e.payload or {}).get("kind") == "drop_to_zero"]
    assert me.current_hp == 1 and len(resolved) == 1


def test_several_replacers_let_the_player_choose_which_one_resolves(monkeypatch):
    # Regression (SYS2 review finding 2): with Blood Pump and Invincible Iron both available, the first replacer in catalog order
    # fired with no choice. The printed "If several are available, choose one" is now a prompt; the player's pick decides which
    # replacer's outcome lands. Blood Pump leaves the owner at 1 HP; Invincible Iron leaves 11 HP on this sheet.
    from combat.ext import needle
    asked, prompts, attack_names = [], [], []
    for pick, expected_hp in ((0, 1), (1, 11)):
        def choose(engine, intent, checkpoint, chooser, choice_id, options, _pick=pick, **kwargs):
            if choice_id == "choice:typed.zero_hp_replacer":
                asked.append(list(options))
                # Finding 4: the prompt names the creature that would drop and every replacer on offer, not just the labels.
                prompts.append((kwargs.get("prompt") or "", dict(kwargs.get("labels") or {})))
                return [options[_pick]]
            return [options[0]]

        monkeypatch.setattr(needle, "ask", choose)
        engine, me = _owner(PATH + "blood_pump", "tianxia.subpath.body.iron_shirt.feature.invincible_iron")
        # Checklist 9 (SYS2 review finding 1): the lethal hit comes from a real attack of Ancestor's; its name must be in the prompt.
        attack = next(key for key, action in engine.action_catalog.items() if action.owner_id == AN)
        attack_names.append(engine.action_catalog[attack].display_name)
        _lethal(engine, me, attack)
        assert me.current_hp == expected_hp, f"pick {pick} should land {expected_hp} HP"
    assert [len(options) for options in asked] == [2, 2]
    for (prompt, labels), attack_name in zip(prompts, attack_names):
        assert attack_name and f" with {attack_name}" in prompt, prompt
        assert "Several features" in prompt and "Choose one" in prompt
        assert "would drop to 0 Hit Points" in prompt and "from " in prompt, prompt  # names the creature and the attack
        assert labels and all(name in prompt for name in labels.values()), (prompt, labels)
