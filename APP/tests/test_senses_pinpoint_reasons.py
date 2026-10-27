"""Sensed-creature labels keep the pinpointing sense that located a creature (SENSESP1F6R review).

An ally or an enemy that a pinpointing sense (Tremorsense) reaches, but ordinary sight does not, must be
labelled with that sense. The label is shown to the player as "you know its location because of <sense>".
"""
import pytest

from combat.canonical import canonical_sha256
from tests.r1i_service_support import FOE, OWNER, SECOND, fixture


def _owner_senses(rows):
    def grant(bundles):
        owner = bundles[0]
        owner["senses"] = {"rows": [{"sense": sense, "range_ft": 30, "when": "always"} for sense in rows]}
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)
    return grant


@pytest.mark.parametrize("target, rows, allies, expected", [
    # Ally located only by Tremorsense: the label names Tremorsense, not "allied_location".
    (SECOND, ["tremorsense"], (SECOND,), ["tremorsense"]),
    # Enemy seen by Spiritual Sense and also pinpointed by Tremorsense: both senses are named.
    (FOE, ["spiritual_sense", "tremorsense"], (), ["spiritual_sense", "tremorsense"]),
])
def test_pinpointed_creature_label_names_the_pinpointing_sense(tmp_path, monkeypatch, target, rows, allies, expected):
    combat, table, mid, _, _ = fixture(tmp_path, [], bundle_transform=_owner_senses(rows), allies=allies,
                                       seed="SENSESP1F7-pinpoint-" + target + "-" + "-".join(rows))
    session = combat._load_session(mid)
    engine = session.engine
    engine._apply_condition(engine.state.actors[target], "condition:typed.invisible", "test:pinpoint-label",
                            target, expires_on="UNTIL_REMOVED", data={})
    monkeypatch.setattr(table, "_load_state_session", lambda _match_id: session)

    row = table.state(mid, fog=True)["fog_perception"][OWNER]
    assert target in row["creatures"]
    assert sorted(row["sensed_creatures"][target]) == sorted(expected)
    assert OWNER not in row["sensed_creatures"]
