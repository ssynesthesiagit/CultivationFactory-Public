"""Native merge gate, independent of private model-seat fixture configuration.

Keep this public-CI entry point separate from replay-wrapper contract tests,
whose legacy fixture imports include private provider configuration.
"""


def test_merged_ground_view_keeps_objects_and_private_findings(tmp_path, monkeypatch):
    from tests.test_bloodsense_merge_perception import (
        test_ground_view_keeps_visible_objects_and_private_findings,
    )
    test_ground_view_keeps_visible_objects_and_private_findings(tmp_path, monkeypatch)
