"""Sovereign Identity reads the attempted effect's own Source CL (hook level).

Table-level coverage is tests/test_h52_immortal_spirit_table.py. No summon in combat/rules/summons.json can Charm or
Frighten yet, so the summon and missing-CL authority paths are exercised here directly on the condition_attempt hook:
compiled summon bundles carry no top-level CL (combat/summons.py) while their actions' typed numbers do.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from combat.ext.spirit_awakening import SOVEREIGN_MARKER, sovereign_identity_blocks_lower_conditions as attempt

OWNER, SOURCE, SUMMONER = "actor:factory.owner", "actor:factory.source", "actor:factory.summoner"
MARKER = "action:typed.owner.immortal_spirit.sovereign_identity"


def _engine(bundles):
    catalog = {MARKER: SimpleNamespace(parameters={SOVEREIGN_MARKER: True, "typed": {"numbers": {"cl": 20}}})}
    return SimpleNamespace(action_catalog=catalog, typed_bundle_documents=tuple(bundles))


def _actor(entity_id, action_ids=(), summon=None):
    return SimpleNamespace(entity_id=entity_id, action_ids=tuple(action_ids), summon=summon)


OWNER_ACTOR = _actor(OWNER, [MARKER])
OWNER_BUNDLE = {"actor_id": OWNER, "cl": 20}


def _run(source, numbers, bundles, condition="frightened", subject=OWNER_ACTOR):
    ctx = SimpleNamespace(engine=_engine([OWNER_BUNDLE, *bundles]), actor=source, numbers=numbers)
    return attempt(ctx, subject, {"type": "condition", "condition": condition})


@pytest.mark.parametrize(("numbers", "bundles", "summon", "expected", "why"), [
    ({"cl": 19}, [{"actor_id": SOURCE, "cl": 20}], None, False, "the effect's own CL19 wins over its actor's CL20"),
    ({"cl": 20}, [{"actor_id": SOURCE, "cl": 10}], None, None, "an equal-CL effect keeps its printed procedure"),
    ({"cl": 20}, [{"actor_id": SOURCE}], {"owner": SUMMONER}, None, "summon action carries CL20; bundle has none"),
    ({"cl": 12}, [{"actor_id": SOURCE}], {"owner": SUMMONER}, False, "summon action carries CL12"),
    ({}, [{"actor_id": SOURCE}, {"actor_id": SUMMONER, "cl": 20}], {"owner": SUMMONER}, None, "summoner's CL20"),
    ({}, [{"actor_id": SOURCE}, {"actor_id": SUMMONER, "cl": 9}], {"owner": SUMMONER}, False, "summoner's CL9"),
    ({}, [{"actor_id": SOURCE, "cl": 15}], None, False, "no compiled CL: the actor's CL15"),
    ({}, [], None, False, "no typed authority at all: an ordinary effect"),
    ({}, [{"actor_id": SOURCE}], None, None, "typed source with no recorded CL: unknown is never treated as 0"),
    ({"cl": 0}, [{"actor_id": SOURCE}], None, None, "a placeholder 0 is not a Source CL"),
])
def test_attempted_effect_source_cl(numbers, bundles, summon, expected, why):
    assert _run(_actor(SOURCE, summon=summon), numbers, bundles) is expected, why
    assert _run(_actor(SOURCE, summon=summon), numbers, bundles, "charmed") is expected, why


def test_only_charm_and_frighten_and_only_for_the_owner():
    lower = ({"cl": 5}, [{"actor_id": SOURCE, "cl": 5}])
    assert _run(_actor(SOURCE), *lower, condition="restrained") is None
    assert _run(_actor(SOURCE), *lower, subject=_actor("actor:factory.other")) is None


def test_a_charm_or_frighten_the_owner_imposes_on_itself_is_willing():
    assert _run(OWNER_ACTOR, {"cl": 1}, []) is None
