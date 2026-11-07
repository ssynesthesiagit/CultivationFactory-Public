"""Migrated plug-in variant families (combat/ext): one structured family per generator.

Each family is one executable action per legal variant, with ids and effects unchanged; the
family is identified by ActionDefinition.variant, never by parsing display names.
Folded Reach is not a family: main's condition design (combat/ext/folded_reach.py) compiles one
Folded Reach action and offers its origins dynamically, so tests/test_riders_c11.py covers it.
"""
import pytest

from combat.ext import figment
from tests.auto_worker1_support import LEFT as OWNER, fight
from tests.worker2_support import reload

SUBSTANTIAL = "tianxia.talent.illusion.substantial_phantasm"
ILLUSION = "tianxia.sphere.illusion"
WRESTLING = "tianxia.sphere.wrestling"
SAINT = "foundation.ancient_desolate_sacred_body_v0_2C.saint_body_rebuke"
CHOKE_HOLD = "TAL_WRESTLING_CHOKE_HOLD"


def _family(engine, axis):
    """A family is found by its structured choice axis (rebuke, hold, slam), never by base key or label:
    Substantial Phantasm keeps its original base key."""
    return [a for a in engine.action_catalog.values()
            if a.owner_id == OWNER and a.variant is not None and any(p.axis == axis for p in a.variant.choices)]


def _grant(talent):
    """(talents, spheres) giving a family its base ability: a grapple for the Slam, Create Figment for
    Substantial Phantasm. A talent with neither is granted alone."""
    if talent == "TAL_WRESTLING_GRANDSTANDING_SLAM":
        return [talent, CHOKE_HOLD], [WRESTLING]
    if talent == SUBSTANTIAL:
        return [figment.SELECTIVE, talent], [figment.SPHERE]
    return [talent], []


def _axes(actions):
    return {p.axis for a in actions for p in a.variant.choices}


def _synthetic_saint_family():
    """Public-safe fixture for Saint-Body Rebuke. A real Foundation is validated against its private published section,
    which the public copy scrambles, so fight() cannot build it on public CI. The generator itself is pure: run it on a
    synthetic compile input that owns the rebuke feature and check the same family shape."""
    from combat.ext import foundation_sacred_body as saint

    return saint.rebuke_choices({"owned_ids": [saint.REBUKE], "short": "synthetic", "actor_id": OWNER,
                                 "numbers": {"cl": 5, "pb": 2, "key_mod": 3, "save_dc": 13}})


def _assert_one_family(talent, family, axis, catalog):
    assert family, f"{talent} must grant a variant family in this fixture"
    assert len({a.variant.base_key for a in family}) == 1, "the family must share one base"
    assert _axes(family) <= {axis, "tempo"}
    for action in family:
        # Choice ids are derived from the executable id, which never changes.
        assert action.source_definition_id
        assert action.variant.base_label
    assert {a.source_definition_id for a in family} <= catalog


@pytest.mark.parametrize("talent,axis", [
    (SUBSTANTIAL, "hold"),
    (SAINT, "rebuke"),
    ("TAL_WRESTLING_GRANDSTANDING_SLAM", "slam"),
])
def test_variant_family_is_one_base_with_choice_axes(tmp_path, talent, axis):
    if talent == SAINT:
        # Public-safe synthetic fixture (see _synthetic_saint_family); the real Foundation runs in the private tier.
        family = _synthetic_saint_family()
        _assert_one_family(talent, family, axis, {a.source_definition_id for a in family})
        return
    talents, spheres = _grant(talent)
    combat, table, mid = fight(tmp_path, talents, spheres=spheres)
    engine = reload(tmp_path, mid)
    # A talent that stops granting its family must fail here, never skip.
    _assert_one_family(talent, _family(engine, axis), axis, set(engine.action_catalog))


def test_saint_body_rebuke_choices_public_fixture():
    """Exact Saint-Body Rebuke choices on the synthetic fixture: each executable id is its base plus its own choice suffix."""
    family = _synthetic_saint_family()
    base = "action:typed.synthetic.saint_body_rebuke"
    assert {a.variant.base_key for a in family} == {base}
    assert {(p.axis, p.key, p.label) for a in family for p in a.variant.choices} == {
        ("rebuke", "reactions", "No Reactions"), ("rebuke", "push", "Push 5 ft"),
        ("rebuke", "frame", "Frame Advantage"), ("rebuke", "off", "don't use it (no Pulse spent, no bonus damage)")}
    for action in family:
        assert action.source_definition_id.startswith(base + ".")


def test_structured_choices_name_the_executable_base(tmp_path):
    """Exact choices, and each executable id is its base action plus the choice's own suffix."""
    talents, spheres = _grant(SUBSTANTIAL)
    combat, table, mid = fight(tmp_path, talents, spheres=spheres)
    engine = reload(tmp_path, mid)
    family = _family(engine, "hold")
    assert family, f"{SUBSTANTIAL} must grant a variant family in this fixture"
    chosen = {(p.axis, p.key, p.label) for a in family for p in a.variant.choices if p.axis == "hold"}
    assert chosen == {("hold", "grappled", "Substantial Phantasm: Grappled"),
                      ("hold", "restrained", "Substantial Phantasm: Restrained")}
    for action in family:
        base = action.variant.base_key
        assert base in engine.action_catalog, "the base action stays executable in the catalogue"
        assert action.source_definition_id.startswith(base + ".")
        assert ".substantial." in action.source_definition_id[len(base):]


def test_variant_identity_survives_save_and_cold_reload(tmp_path):
    """ActionDefinition.variant is persisted: the saved catalogue and a cold reload keep every choice."""
    from combat.gate2_runtime_models import ActionDefinition

    talents, spheres = _grant(SUBSTANTIAL)
    combat, table, mid = fight(tmp_path, talents, spheres=spheres)
    engine = reload(tmp_path, mid)
    family = _family(engine, "hold")
    assert family, f"{SUBSTANTIAL} must grant a variant family in this fixture"
    for action in family:
        dumped = action.model_dump(mode="json")
        assert dumped["variant"] == action.variant.model_dump(mode="json")
        again = ActionDefinition.model_validate(dumped)
        assert again.variant == action.variant
        assert again.source_definition_id == action.source_definition_id
    cold = reload(tmp_path, mid)
    reloaded = {a.source_definition_id: a.variant for a in _family(cold, "hold")}
    assert reloaded == {a.source_definition_id: a.variant for a in family}


def test_legacy_action_without_variant_serializes_unchanged(tmp_path):
    """Old catalogues carry no variant key: exclude_if=None keeps their serialized shape."""
    from combat.gate2_runtime_models import ActionDefinition

    combat, table, mid = fight(tmp_path, [SUBSTANTIAL], spheres=[ILLUSION])
    engine = reload(tmp_path, mid)
    plain = [a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.variant is None]
    assert plain, "the fixture must carry ordinary actions"
    for action in plain[:20]:
        dumped = action.model_dump(mode="json")
        assert "variant" not in dumped
        assert ActionDefinition.model_validate(dumped).variant is None
