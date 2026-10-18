"""Circuit Scholar insight tests."""
import pytest
import hashlib
from factory_authoring.insight_sources import INSIGHT_KIND

CIRCUIT_SCHOLAR = "insight.circuit-scholar"
KIT = {"items": [{"item_id": "tianxia.mortal.armor.lacquered_lamellar", "name": "Lacquered Lamellar", "quantity": 1}]}
LEFT = "actor:factory.left"


def make_typed_authority():
    text = """**Prerequisite:** Qiweaving sphere

**Ability Increase (Level Selection):** Increase your Intelligence, Charisma, or Wisdom score by 1, to the maximum allowed by your current Realm.

When you make an Intelligence check to identify a spell, sphere technique, talisman effect, or Active Qi Pattern, add your Proficiency Bonus if you are not already proficient.

If you are proficient, add double your Proficiency Bonus."""
    text_sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
    record_sha = "f9787a23b67437ce465846b16cb0e01883f048d747b83010c560288497aa7408"

    return {
        "mechanics": {
            CIRCUIT_SCHOLAR: {
                "id": CIRCUIT_SCHOLAR,
                "name": "Circuit Scholar",
                "kind": INSIGHT_KIND,
                "typing_status": "reviewed_final",
                "source": {
                    "record_id": "sphere-compendium.qiweaving.circuit-scholar",
                    "text_sha256": text_sha,
                    "record_sha256": record_sha,
                },
                "insight_selectable": True,
                "insight_reviewed_text_sha256": text_sha,
                "text_sha256": text_sha,
                "ability_options": ["Intelligence", "Charisma", "Wisdom"],
            }
        }
    }


def _compile_character(insights, **kw):
    from tests.h1_support import sheet
    from combat.factory_compiler import compile_character
    doc = sheet(list(insights), cl=4, dc=100, kit={"items": KIT["items"]}, score=14)
    doc.setdefault("spheres_and_talents", {})
    doc["spheres_and_talents"]["cultivation_insight_record_ids"] = [i for i in insights if i.startswith("insight.")]
    doc["identity"]["proficiency_bonus"] = 2
    doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
    doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1
    return compile_character(doc, actor_id=LEFT, reaction_plan={"ask": True}, typed_authority=make_typed_authority(), **kw)


def _make_engine(bundle):
    class MockEngine:
        def __init__(self, bundle):
            self.typed_bundle_documents = [bundle]
            self.typed_passive_rows = {LEFT: bundle.get("typed_passives", [])}
    return MockEngine(bundle)


def _make_actor(proficient_skills=None):
    class MockActor:
        def __init__(self, entity_id):
            self.entity_id = entity_id
            self.skills = proficient_skills or {}
            self.intelligence_score = 14
            self.saving_throws = {"INT": 2}
    return MockActor(LEFT)


def _make_context(engine, ability, skill, pb=2, identification=True, rank=None):
    """A check context marked the way a real producer marks one.

    ``identification`` uses combat/ext/identification_checks.identifying, the seam the table's own
    identification checks use, rather than a flag only this test sets (finding 1/2).
    """
    from combat.ext.identification_checks import identifying

    class MockContext:
        def __init__(self, engine, typed):
            self.engine = engine
            self.typed = typed

    typed = {"ability": ability, "skill": skill, "numbers": {"pb": pb}}
    if rank is not None:
        typed["skill_proficiency_rank"] = rank
    ctx = MockContext(engine, typed)
    return identifying(ctx, ability=ability, skill=skill) if identification else ctx


def test_circuit_scholar_compiles(tmp_path):
    """Test Circuit Scholar compiles correctly."""
    bundle = _compile_character([CIRCUIT_SCHOLAR])

    passives = bundle.get("typed_passives", [])
    circuit_rows = [p for p in passives if p.get("feature_id") == CIRCUIT_SCHOLAR]

    assert len(circuit_rows) == 1, f"Expected 1 Circuit Scholar row, got {len(circuit_rows)}"
    row = circuit_rows[0]
    assert row['feature_id'] == CIRCUIT_SCHOLAR
    assert row['kind'] == CIRCUIT_SCHOLAR
    assert row['choice_owner'] == 1
    assert 'Proficiency Bonus' in row['player_outcome']
    assert 'double your Proficiency Bonus' in row['player_outcome']


def test_circuit_scholar_check_bonus_not_proficient(tmp_path):
    """Test Circuit Scholar gives +PB on identification checks when not proficient."""
    bundle = _compile_character([CIRCUIT_SCHOLAR])
    engine = _make_engine(bundle)
    actor = _make_actor()

    from combat.ext.qiweaving_insights import owns, circuit_scholar_check_bonus

    row = owns(engine, actor, CIRCUIT_SCHOLAR)
    assert row is not None
    assert row['pb'] == 2

    for skill in ("Arcana", "Investigation", "Calligrapher's Supplies"):
        ctx = _make_context(engine, "INT", skill, identification=True)
        bonus = circuit_scholar_check_bonus(ctx, actor)
        assert bonus == 2, f"Expected +2 PB for non-proficient {skill}, got {bonus}"


def test_circuit_scholar_check_bonus_proficient(tmp_path):
    """Test Circuit Scholar gives +2*PB on identification checks when proficient."""
    bundle = _compile_character([CIRCUIT_SCHOLAR])
    bundle["skill_proficiency"] = {"Arcana": 1, "Investigation": 1, "Calligrapher's Supplies": 1}

    engine = _make_engine(bundle)
    actor = _make_actor(proficient_skills={"Arcana": 4, "Investigation": 4, "Calligrapher's Supplies": 4})

    from combat.ext.qiweaving_insights import circuit_scholar_check_bonus

    for skill in ("Arcana", "Investigation", "Calligrapher's Supplies"):
        ctx = _make_context(engine, "INT", skill, identification=True, rank=1)
        bonus = circuit_scholar_check_bonus(ctx, actor)
        assert bonus == 4, f"Expected +4 (2*PB) for proficient {skill}, got {bonus}"


def test_circuit_scholar_check_bonus_wrong_ability(tmp_path):
    """Test Circuit Scholar doesn't apply to non-Intelligence checks."""
    bundle = _compile_character([CIRCUIT_SCHOLAR])
    engine = _make_engine(bundle)
    actor = _make_actor()

    from combat.ext.qiweaving_insights import circuit_scholar_check_bonus

    for ability, skill in [("STR", "Athletics"), ("DEX", "Acrobatics"), ("WIS", "Insight"), ("CHA", "Deception")]:
        ctx = _make_context(engine, ability, skill, identification=True)
        bonus = circuit_scholar_check_bonus(ctx, actor)
        assert bonus is None, f"Expected None for {ability} ({skill}), got {bonus}"


def test_circuit_scholar_check_bonus_non_identification_skill(tmp_path):
    """Test Circuit Scholar doesn't apply to non-identification Intelligence checks."""
    bundle = _compile_character([CIRCUIT_SCHOLAR])
    engine = _make_engine(bundle)
    actor = _make_actor()

    from combat.ext.qiweaving_insights import circuit_scholar_check_bonus

    for skill in ("History", "Religion", "Nature"):
        ctx = _make_context(engine, "INT", skill, identification=False)
        bonus = circuit_scholar_check_bonus(ctx, actor)
        assert bonus is None, f"Expected None for INT ({skill}), got {bonus}"


def test_circuit_scholar_check_bonus_no_identification_flag(tmp_path):
    """A skill-name-only INT check must not receive the bonus (finding 1)."""
    bundle = _compile_character([CIRCUIT_SCHOLAR])
    engine = _make_engine(bundle)
    actor = _make_actor()

    from combat.ext.qiweaving_insights import circuit_scholar_check_bonus

    ctx = _make_context(engine, "INT", "Arcana", identification=False)
    assert circuit_scholar_check_bonus(ctx, actor) is None


def test_circuit_scholar_check_bonus_missing_rank_not_double(tmp_path):
    """Missing authoritative rank must not grant double PB (finding 2)."""
    bundle = _compile_character([CIRCUIT_SCHOLAR])
    engine = _make_engine(bundle)
    actor = _make_actor()

    from combat.ext.qiweaving_insights import circuit_scholar_check_bonus

    ctx = _make_context(engine, "INT", "Arcana", identification=True)  # no rank
    bonus = circuit_scholar_check_bonus(ctx, actor)
    assert bonus == 2, f"Expected +PB (not double) when rank missing, got {bonus}"


def test_circuit_scholar_feature_block_entry(tmp_path):
    """Test feature block entry exists and has correct hash."""
    from combat.typed_reactions import rules

    features = rules().get("features") or {}
    spec = features.get(CIRCUIT_SCHOLAR)

    assert spec is not None, "Circuit Scholar feature block entry should exist"
    assert spec["block"] == "insights_qiweaving"
    assert spec["text_sha256"] == "aeeccae06d97b599e530fdef9a251ca4936e58ec9dae110622b6672e476ae902"


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        test_circuit_scholar_compiles(p)
        test_circuit_scholar_check_bonus_not_proficient(p)
        test_circuit_scholar_check_bonus_proficient(p)
        test_circuit_scholar_check_bonus_wrong_ability(p)
        test_circuit_scholar_check_bonus_non_identification_skill(p)
        test_circuit_scholar_check_bonus_no_identification_flag(p)
        test_circuit_scholar_check_bonus_missing_rank_not_double(p)
        test_circuit_scholar_feature_block_entry(p)
        print("All Circuit Scholar tests passed!")