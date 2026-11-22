"""MMX118: the fight log names a condition the way the sheet does, never by its raw id.

HUNT112 #2 (P3, round-24 LIVE 42e43e14), read verbatim by the owner in H112-02 step 138::

    Smoke Test Duo applied Spirit Awakening Pressure Choice to Smoke Test Duo
      (Spiritual Pressure: Revealed Disturbance (learn its state)); until removed.

"Spirit Awakening Pressure Choice" is an internal id title-cased into a fake name. The cause was
``combat/history_feed.py:288``, which only used a condition's recorded player-facing label when the
label *also* carried ``points`` -- a field only one plug-in (``ext/docket_walls.py``) ever writes. So
every other condition that stored a good label fell through to the id branch, and the same class of
line was logged for ``No Invisible``, ``Check Mode``, ``Concentration Mode`` and ``No Temp Hp``.

The sheet's condition pills already read that stored label, so the log and the sheet now agree.
The payload shape below is the one ``combat/gate3_reducer.py`` actually produces: it records the
whole condition under ``gate3_condition_after`` (``GATE3_CONDITION_KEY``), so the label is available
to the feed without any engine change.
"""
from combat.history_feed import format_history_feed
from combat.ext.talismans import QI_STORAGE
from tests.test_mmx118_cp_pool import ME, _fight, _prepared_count, send_talisman

ID_SMELLS = ("condition:", "Unnamed effect", "typed.", "Check Mode", "Concentration Mode",
             "No Invisible", "No Temp Hp")

APPLIED = {
    "event_type": "CONDITION_APPLIED",
    "actor_id": "actor:factory.reader",
    "target_ids": ["actor:factory.reader"],
    "source_definition_id": "tianxia.talent.talismans.qi_storage_talisman",
    "payload": {
        "condition_id": QI_STORAGE + ":prepared:1",
        "instance_id": QI_STORAGE + ":prepared:1",
        "expires_on": "UNTIL_REMOVED",
        "gate3_condition_after": {
            "condition_id": QI_STORAGE + ":prepared:1",
            "expires_on": "UNTIL_REMOVED",
            # The label the plug-in stored, and the sheet's condition pill already shows.
            "data": {"stored_cp": 2, "label": "Qi Storage Talisman: 2 CP stored"},
        },
    },
}


def _summary(event, actor_names=None):
    rows = format_history_feed([event], [], pre_state=None, post_state={},
                               actor_names=actor_names or {"actor:factory.reader": "Reader"},
                               definition_names={})
    return str(rows[0]["summary"])


def test_a_labelled_condition_is_named_by_its_label_not_its_id():
    """The regression: without the fix this line read the title-cased id, or 'Unnamed effect'."""
    line = _summary(APPLIED)
    assert "Qi Storage Talisman: 2 CP stored" in line, line
    for smell in ID_SMELLS:
        assert smell not in line, f"log line exposes an internal id ({smell!r}): {line!r}"


def test_a_label_without_points_is_still_used():
    """The old gate needed ``points`` as well as ``label``; a label alone must be enough."""
    event = {**APPLIED, "payload": {**APPLIED["payload"],
             "gate3_condition_after": {**APPLIED["payload"]["gate3_condition_after"],
                                       "data": {"label": "Meld: Clearsight"}}}}
    line = _summary(event)
    assert "Meld: Clearsight" in line, line
    assert "condition:" not in line, line


def test_a_labelled_condition_still_says_who_applied_it_what_and_for_how_long():
    """MMX118f1 review #1: a label is a *name*. Using it must not swallow the duration.

    The label branch used to emit the whole line as ``"<target>: <label>."``, which dropped the actor
    who applied it, the source that applied it, and the expiry calculated for it -- so a player could
    read ``Spirit Awakening Pressure Choice`` and learn neither who put it there nor when it ends.
    The id branch below it always said all three; a labelled condition must say exactly as much.
    """
    caster, victim = "actor:factory.caster", "actor:factory.victim"
    event = {**APPLIED, "actor_id": caster, "target_ids": [victim],
             "source_definition_id": "tianxia.talent.talismans.qi_storage_talisman",
             "payload": {**APPLIED["payload"], "expires_on": "END_OF_HOLDER_NEXT_TURN",
                         "display_name": "Spirit Awakening Pressure",
                         "target_id": victim,
                         "gate3_condition_after": {"condition_id": QI_STORAGE + ":prepared:1",
                                                   "expires_on": "END_OF_HOLDER_NEXT_TURN",
                                                   "data": {"label": "Spirit Awakening Pressure Choice"}}}}
    line = _summary(event, actor_names={caster: "Smoke Test Duo", victim: "Yun Xiao"})
    assert "Spirit Awakening Pressure Choice" in line, line
    # Who applied it.
    assert "Smoke Test Duo" in line, line
    # What applied it.
    assert "Spirit Awakening Pressure" in line, line
    # How long it lasts -- the whole point of the fix.
    assert "Yun Xiao's next turn ends" in line, line
    for smell in ID_SMELLS:
        assert smell not in line, f"log line exposes an internal id ({smell!r}): {line!r}"


def test_a_labelled_condition_named_by_its_label_still_reads_as_a_sentence():
    """The UNTIL_REMOVED shape must stay readable and must keep naming the target and the source."""
    line = _summary(APPLIED, actor_names={"actor:factory.reader": "Smoke Test Duo"})
    assert line.startswith("Smoke Test Duo applied the "), line
    assert "Qi Storage Talisman: 2 CP stored" in line, line
    assert line.rstrip().endswith("."), line
    assert "until removed" in line, line


REMOVED = {
    "event_type": "CONDITION_REMOVED",
    "actor_id": "actor:factory.reader",
    "target_ids": ["actor:factory.reader"],
    "source_definition_id": "tianxia.talent.talismans.qi_storage_talisman",
    "payload": {
        "condition_id": QI_STORAGE + ":prepared:1",
        "instance_id": QI_STORAGE + ":prepared:1",
        "display_name": "Qi Storage Talisman",
        "gate3_condition_before": {
            "condition_id": QI_STORAGE + ":prepared:1",
            "expires_on": "UNTIL_REMOVED",
            "data": {"stored_cp": 2, "label": "Qi Storage Talisman: 2 CP stored"},
        },
    },
}


def test_the_removal_line_also_names_a_labelled_condition_by_its_label():
    """MMX118f1 review #1/#7: the removal branch is new and needed its own regression.

    Without it, renaming the removal branch to a label could silently start printing the raw
    ``condition:typed...`` id again, which is the exact regression the applied branch was written to fix.
    """
    line = _summary(REMOVED, actor_names={"actor:factory.reader": "Smoke Test Duo"})
    assert "Qi Storage Talisman: 2 CP stored" in line, line
    assert "removed from Smoke Test Duo" in line, line
    for smell in ID_SMELLS:
        assert smell not in line, f"removal line exposes an internal id ({smell!r}): {line!r}"


def test_a_condition_with_no_label_still_resolves_a_readable_name():
    """No label to borrow: the existing resolver's answer must not leak the raw id."""
    event = {**APPLIED, "payload": {**APPLIED["payload"],
             "gate3_condition_after": {**APPLIED["payload"]["gate3_condition_after"],
                                       "data": {}}}}
    line = _summary(event)
    assert "condition:" not in line, line


def test_the_pressed_button_logs_readable_pools_and_no_internal_ids(tmp_path):
    """Service level: the real table feed for the repaired button names Stamina, not an id."""
    charges = [2] + [0] * (_prepared_count() - 1)
    combat, table, mid = _fight(tmp_path, charges=charges, start=0)
    assert send_talisman(table, mid, combat) == "COMMITTED"
    lines = [str(row.get("summary") or "") for row in table.events(mid, 0)["events"]]
    assert any("Qi Storage Talisman" in line and "Stamina" in line for line in lines), lines
    for line in lines:
        assert "resource:core." not in line, f"log line leaks a resource id: {line!r}"
        assert "tianxia.talent" not in line, f"log line leaks an ability id: {line!r}"
