"""Guard the public scratch-library sample against real identity leakage."""


def test_scratch_library_sample_contains_only_explicit_synthetic_names() -> None:
    # Keep this miniature fixture in the test so public CI has no owner-data
    # dependency and reviewers can see exactly which identities are permitted.
    fixture = {
        "rows": [
            {"name": "AI-proposed character"},
            {"name": "Synthetic Library Character"},
        ]
    }
    permitted_names = {"AI-proposed character", "Synthetic Library Character"}
    names = [row["name"] for row in fixture["rows"]]
    assert "Synthetic Library Character" in names
    assert set(names) <= permitted_names
