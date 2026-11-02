"""Pure negative control accompanying Tortoise's real-table save/reload regressions."""
from types import SimpleNamespace as NS
import pytest

from combat.ext import ancestral_bloodline as bloodline


@pytest.mark.parametrize("already_prone", [False, True])
def test_tortoise_must_actually_remain_standing(monkeypatch, already_prone):
    conditions = {"lineage": NS(condition_id=bloodline.AFFINITY, data={"lineage": "jade_tortoise"})}
    if already_prone:
        conditions["prone"] = NS(condition_id="condition:typed.prone", data={})
    subject = NS(entity_id="tortoise", team_id="allies", conditions=conditions)
    ctx = NS(actor=NS(team_id="enemies"), engine=object())
    gains = []
    monkeypatch.setattr(bloodline, "gain_resonance", lambda engine, actor: gains.append(actor.entity_id))
    bloodline.resonance_save(ctx, subject, "STR", {"prone"}, False)
    assert gains == ([] if already_prone else ["tortoise"])
