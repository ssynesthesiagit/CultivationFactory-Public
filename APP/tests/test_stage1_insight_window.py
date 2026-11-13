"""SOL77/MMX43: bounded Insight windows preserve variety, reachability and replay."""
from copy import deepcopy
import pytest

from app.core import FoundryError, canonical_json
from character_builder import CharacterBuilderService
from character_creation import CharacterCreationExecutionService
from character_creation.creative_controller.linear_menus import (
    build_insight_priorities_menu, build_path_choice_menu,
)
from character_creation.creative_controller.linear_walk import commit_option
from character_creation.service import PROVIDER_PROMPT_HARD_CAP_BYTES
from paged_selection_contract import (
    MAX_PAGES_PER_PAGED_SLOT, PAGED_SELECTION_SLOTS_KEY, PAGED_WINDOW_SEMANTICS,
    paged_max_pages,
)
from path_method_authority import CANONICAL_PATH_IDS
from project_store.service import ProjectStore
from stage1.insight_window import InsightWindows, insight_windows, _size, _shorten_choice, PRESENTATION_FIELDS
from stage1.service import Stage1ClipboardService
import character_creation.service as creation_module
import stage1.service as stage1_module

#: A Path whose Insights carry no Spheres or Talents of their own, so a real
#: walk that picks it opens more Insight options than one page can show.
QI_PATH = "tianxia.path.qi_cultivation"


def _option_for(menu, choice_id):
    return next(option for option in menu.options if choice_id in option.choice_ids)


def _project(db, *, seed="SOL77-A", concept="A thunder spear guardian", path=None):
    return CharacterBuilderService(db).create_project(
        working_name="SOL77 window regression", concept=concept, target_cl=20,
        power_band="standard", source_reference=None, creation_mode="detailed",
        ability_scores={}, selections={"path_choice": [path]} if path else {},
        autogen_seed=seed,
    )["project_id"]


def _ids(envelope):
    slot = next(row for row in envelope["decision_slots"] if row["slot_id"] == "insight_priorities")
    return [row["choice_id"] for row in slot["choices"]]


def _legacy_window(records, **kwargs):
    """The fixed-prefix presentation this lane replaced, for byte comparison."""
    return InsightWindows(windows=[records[: kwargs["limit"]]])


def _freeze_catalog_for_page_checks(service, pid, monkeypatch):
    # These page checks deliberately use one fixed catalog. Rebuilding the
    # same catalog for each page does not exercise additional window behavior.
    coverage = service.coverage.build(project_id=pid)
    catalog = service.catalog.effective_catalog(pid)
    monkeypatch.setattr(service.coverage, "build", lambda **kwargs: deepcopy(coverage))
    monkeypatch.setattr(service.catalog, "effective_catalog", lambda *args: deepcopy(catalog))
    return coverage, catalog


def test_different_seeds_and_concepts_offer_different_insight_windows(catalog_environment):
    db = catalog_environment["db"]
    service = Stage1ClipboardService(db)
    first = _ids(service.build_envelope(_project(db)))
    second = _ids(service.build_envelope(_project(db, seed="SOL77-B")))
    third = _ids(service.build_envelope(_project(db, concept="A poison healer and alchemist")))
    assert first != second
    assert first != third


def test_same_seed_concept_and_locks_reproduce_across_projects(catalog_environment):
    db = catalog_environment["db"]
    service = Stage1ClipboardService(db)
    assert _ids(service.build_envelope(_project(db))) == _ids(service.build_envelope(_project(db)))


def _frozen_creation_request(db, pid, key):
    """Freeze a real character-creation request, not a hand-built envelope."""
    stage1 = Stage1ClipboardService(db)
    creation = CharacterCreationExecutionService(db, stage1=stage1, provider=None,
                                                 project_store=ProjectStore(db))
    return creation._complete_request(
        pid, execution_mode="MANUAL_CHAT", idempotency_key=key,
        # The server-owned nonce must be at least 32 characters.
        manual_collection_nonce=f"{key}-manual-collection-000000000000",
    )


def _insight_menu(request, envelope, page, committed=None):
    return build_insight_priorities_menu(
        request, envelope, committed,
        step_id="insight_priorities:1", ordinal=1, page=page, selection_index=1,
    )


def test_controller_reaches_an_insight_past_its_first_page(catalog_environment):
    """Real frozen request, legal menu pages and closed-world option commit.

    The controlled service walk in test_dcc_linear_s4 separately proves the
    page-four continuation; production prerequisites can leave fewer pages.
    """
    db = catalog_environment["db"]
    pid = _project(db)
    request = _frozen_creation_request(db, pid, "MMX43-reach")
    envelope = request["delegated_choice_envelope"]
    # The paging contract is frozen with the request, not rebuilt per page.
    assert envelope[PAGED_SELECTION_SLOTS_KEY]["insight_priorities"]["max_pages"] >= 6
    # The closed world holds the whole window chain rather than one window.
    # This is the pool that used to stop at the first thirty eligible Insights.
    allowed = set(envelope["allowed_choice_ids_by_slot"]["insight_priorities"])
    assert len(allowed) > 30, "the frozen request only offers the first window"

    # A real walk: choosing a Path unlocks the Path-gated Insights, so the
    # legal option set is wider than one page and the controller has to move on.
    path_menu = build_path_choice_menu(request, envelope, None)
    committed = commit_option(path_menu, _option_for(path_menu, QI_PATH).option_id, None)

    page_of: dict[str, int] = {}
    for page in range(1, envelope[PAGED_SELECTION_SLOTS_KEY]["insight_priorities"]["max_pages"] + 1):
        menu = _insight_menu(request, envelope, page, committed)
        assert menu is not None, page
        for option in menu.options:
            for record_id in option.choice_ids:
                page_of.setdefault(record_id, page)
        if menu.next_page_id is None:
            break
    else:
        raise AssertionError("the Insight menu never offered its final page")

    later = sorted(record_id for record_id, page in page_of.items() if page > 1)
    assert later, "no Insight is reachable past the first menu page"
    # Everything the controller can show is inside the frozen closed world.
    assert set(page_of) <= allowed
    # A later-page Insight commits through the real walk commit path.
    target = later[0]
    menu = _insight_menu(request, envelope, page_of[target], committed)
    option = next(row for row in menu.options if target in row.choice_ids)
    assert target in commit_option(menu, option.option_id, committed).by_slot["insight_priorities"]


def test_a_request_frozen_before_the_contract_keeps_the_three_page_ceiling():
    """A saved walk keeps its own ceiling: the contract only ever adds reach."""
    assert paged_max_pages({}, {"choices_by_slot": {}}, "insight_priorities", 3) == 3
    assert paged_max_pages({"paged_selection_slots": {}}, {}, "insight_priorities", 3) == 3
    # An ordinary slot inside a request that froze the Insight contract is
    # untouched, and a paged slot still never exceeds its own bound.
    frozen = {PAGED_SELECTION_SLOTS_KEY: {"insight_priorities": {"max_pages": 6}}}
    assert paged_max_pages({}, frozen, "path_choice", 3) == 3
    assert paged_max_pages({}, frozen, "insight_priorities", 3) == 6
    assert paged_max_pages(
        {}, {PAGED_SELECTION_SLOTS_KEY: {"insight_priorities": {"max_pages": 99}}},
        "insight_priorities", 3) == 99


def test_frozen_slot_publishes_the_whole_window_chain(catalog_environment):
    """One window is no longer the whole offer: the chain is frozen in the slot."""
    db = catalog_environment["db"]
    service = Stage1ClipboardService(db)
    envelope = service.build_envelope(_project(db))
    slot = next(row for row in envelope["decision_slots"] if row["slot_id"] == "insight_priorities")
    assert slot["selection_semantics"] == PAGED_WINDOW_SEMANTICS
    assert len(slot["choices"]) > 30


def test_real_insight_keeps_typed_authority_and_provider_occurrences(catalog_environment, monkeypatch):
    import io
    import json
    import zipfile
    db = catalog_environment["db"]
    pid = _project(db)
    request = _frozen_creation_request(db, pid, "SOL77b-authority")
    envelope = request["delegated_choice_envelope"]
    authority = envelope["typed_choice_authority_by_slot"]["insight_priorities"]["stage2_authority_by_choice"]
    target, row = next((key, row) for key, row in authority.items() if row.get("allowed_cls") and row.get("ability_change"))
    stage_slot = next(slot for slot in request["stage1_prompt"]["envelope"]["decision_slots"] if slot["slot_id"] == "insight_priorities")
    assert stage_slot["selection_semantics"] == PAGED_WINDOW_SEMANTICS
    assert stage_slot["authority_contract"]["stage2_authority_by_choice"][target] == row
    service = CharacterCreationExecutionService(db, stage1=Stage1ClipboardService(db), provider=None, project_store=ProjectStore(db))
    monkeypatch.setattr(service, "get", lambda run_id: {"project_id": pid, "starting_revision": request["project_revision"], "request": request})
    package = service._complete_request_package("SOL77b-authority")
    with zipfile.ZipFile(io.BytesIO(package["payload"])) as archive:
        schema = json.loads(archive.read("RESPONSE_SCHEMA.json"))["preferred_response"]
    alternatives = schema["properties"]["acquisition_intent"]["properties"]["insight_occurrences"]["items"]["oneOf"]
    matches = [item for item in alternatives if item["properties"]["insight_id"]["const"] == target]
    assert matches
    assert matches[0]["properties"]["parameters"]["properties"]["ability"]["enum"] == sorted(row["ability_change"]["allowed_abilities"])


def test_shortening_real_choice_preserves_identity_authority_and_multiple_fields(catalog_environment):
    db = catalog_environment["db"]
    service = Stage1ClipboardService(db)
    pid = _project(db)
    record = next(row for row in service.catalog.effective_catalog(pid)["records"] if row["content_type"] == "cultivation_insight")
    choice = service._choice(record)
    choice.update(name="N" * 8000, description="D" * 8000, choice_id="identity" * 2000,
                  authority="authority" * 2000, content_type="classification" * 2000, publication_state="published" * 2000)
    immutable = {key: value for key, value in choice.items() if key not in PRESENTATION_FIELDS}
    budget = _size({**choice, "name": "", "description": ""}) + 500
    compact, shortened = _shorten_choice(choice, budget)
    assert shortened and compact is not None and _size(compact) <= budget
    assert {key: value for key, value in compact.items() if key not in PRESENTATION_FIELDS} == immutable
    assert len(compact["name"]) < 8000 and len(compact["description"]) < 8000
    assert choice["name"] == "N" * 8000
    assert _shorten_choice(choice, 100) == (None, False)


def test_all_fitting_overflow_rows_remain_reachable():
    from paged_selection_contract import paged_slot_contract
    records = [{"record_id": f"insight.{i:03}", "display_name": "Plain"} for i in range(151)]
    result = insight_windows(records, project={"project_id": "fixed", "user_locks": []},
                             effective_by_id={}, preferred={}, linked=set(), required=[], limit=50, choice=lambda row: row)
    assert {row["record_id"] for window in result.windows for row in window} == {row["record_id"] for row in records}
    assert not result.omitted_record_ids
    contract = paged_slot_contract({"selection_semantics": PAGED_WINDOW_SEMANTICS, "choices": records})
    assert contract["max_pages"] >= 14
    choices = [{"choice_id": row["record_id"], "name": row["display_name"]} for window in result.windows for row in window]
    envelope = {"choices_by_slot": {"insight_priorities": choices},
                "allowed_choice_ids_by_slot": {"insight_priorities": [row["choice_id"] for row in choices]},
                "selection_limits_by_slot": {"insight_priorities": {"final_min": 0, "final_max": 1, "allow_none": True}},
                PAGED_SELECTION_SLOTS_KEY: {"insight_priorities": contract}}
    reached = set()
    for page in range(1, contract["max_pages"] + 1):
        menu = _insight_menu({"request_sha256": "a" * 64}, envelope, page)
        reached.update(choice_id for option in menu.options for choice_id in option.choice_ids)
        if menu.next_page_id is None:
            break
    assert reached == {row["record_id"] for row in records}


def test_one_oversized_later_row_cannot_break_the_other_windows():
    """A single long catalog row is shortened, not a reason to lose every page."""
    records = [{"record_id": f"insight.{i:03}", "display_name": "Plain"} for i in range(50)]
    records.append({"record_id": "insight.huge", "display_name": "Huge", "summary": "x" * 200_000})
    windows = insight_windows(records, project={"project_id": "fixed", "user_locks": []},
                              effective_by_id={}, preferred={}, linked=set(), required=[],
                              limit=50, choice=lambda row: row)
    # The page the old code refused to build at all is still served.
    page_zero = [row["record_id"] for row in windows.windows[0]]
    assert page_zero
    assert "insight.000" in page_zero
    # The oversized row is shortened to its share of the window, and kept.
    assert "insight.huge" in windows.shortened_record_ids
    reachable = {row["record_id"] for window in windows.windows for row in window}
    assert "insight.huge" in reachable
    # The other rows that fit are still offered alongside it.
    assert reachable == {row["record_id"] for row in records}
    assert not windows.omitted_record_ids
    # Each window fits the old prefix budget; the entire catalog is retained.
    budget = sum(_size(row) for row in sorted(records, key=lambda row: row["record_id"])[:50])
    for window in windows.windows:
        assert sum(_size(windows.choice_overrides.get(row["record_id"]) or row) for row in window) <= budget


def test_preferred_linked_and_required_insights_keep_priority_and_repeat_required():
    records = [{"record_id": f"insight.{i:03}", "display_name": "Plain"} for i in range(100)]
    kwargs = dict(project={"project_id": "fixed", "user_locks": []}, effective_by_id={},
                  preferred={"insight.090": 0}, linked={"insight.080"}, required=["insight.090"],
                  limit=50, choice=lambda row: row)
    first = insight_windows(records, **kwargs).windows[0]
    assert [row["record_id"] for row in first[:2]] == ["insight.090", "insight.080"]
    assert insight_windows(records, **kwargs).windows[1][0]["record_id"] == "insight.090"


def test_lexical_concept_relevance_precedes_seeded_remainder():
    records = [{"record_id": str(i), "display_name": "Plain"} for i in range(60)]
    records[-1]["tags"] = ["thunder"]
    result = insight_windows(records, project={"project_id": "fixed", "user_locks": [{"field": "concept", "value": "thunder"}]},
                             effective_by_id={}, preferred={}, linked=set(), required=[],
                             limit=50, choice=lambda row: row).windows[0]
    assert result[0]["record_id"] == "59"


def test_persisted_legacy_prompt_and_prepared_envelope_remain_byte_identical(catalog_environment, monkeypatch):
    db = catalog_environment["db"]
    service = Stage1ClipboardService(db)
    pid = _project(db)
    with monkeypatch.context() as old:
        old.setattr(stage1_module, "insight_windows", _legacy_window)
        legacy = service.generate_prompt(pid)
    assert len(_ids(legacy["envelope"])) == 50
    reloaded = Stage1ClipboardService(db).get_prompt(legacy["prompt_id"])
    # generate_prompt additionally returns the transient deterministic flag;
    # retrieval returns the stored fields, including the exact prompt bytes.
    assert reloaded == {key: value for key, value in legacy.items() if key != "deterministic"}
    assert service.prepare_prompt(pid)["prompt_text"] == legacy["prompt_text"]
    assert canonical_json(service.prepare_prompt(pid)["envelope"]) == canonical_json(legacy["envelope"])


def test_fresh_creation_requests_honor_locked_other_options_page(catalog_environment):
    db = catalog_environment["db"]
    service = Stage1ClipboardService(db)
    pid = _project(db)
    page_one = _ids(service.build_envelope(pid, insight_page=1))
    ProjectStore(db).append_user_locks(pid, [{"field": "stage1.insight_window_page", "value": 1}])
    assert _ids(service.generate_prompt(pid)["envelope"]) == page_one


def test_largest_path_every_display_window_stays_within_legacy_byte_budget(catalog_environment, monkeypatch):
    db = catalog_environment["db"]
    service = Stage1ClipboardService(db)
    measurements = []
    for path in CANONICAL_PATH_IDS:
        service = Stage1ClipboardService(db)
        pid = _project(db, path=path)
        _freeze_catalog_for_page_checks(service, pid, monkeypatch)
        real = stage1_module.insight_windows
        def checked(records, **kwargs):
            result = real(records, **kwargs)
            legacy = sorted(records, key=lambda row: (0 if row["record_id"] in kwargs["preferred"] else 1,
                            kwargs["preferred"].get(row["record_id"], 10**9), row["record_id"]))
            budget = sum(_size(kwargs["choice"](row)) for row in legacy[:kwargs["limit"]])
            sizes = [sum(_size(result.choice_overrides.get(row["record_id"]) or kwargs["choice"](row)) for row in window)
                     for window in result.windows]
            assert sizes and max(sizes) <= budget
            assert all(len(window) <= 30 for window in result.windows)
            assert {row["record_id"] for window in result.windows for row in window} | set(result.omitted_record_ids) == {row["record_id"] for row in records}
            measurements.append((path, budget, max(sizes)))
            return result
        with monkeypatch.context() as check:
            check.setattr(stage1_module, "insight_windows", checked)
            service.build_envelope(pid)
    print("SOL77 display window bytes (Path, budget, largest window):", measurements)


def _model_facing_prompt_bytes(creation, project_id, kwargs):
    """Return the real model-facing prompt size for a freshly frozen request."""
    request = creation._complete_request(project_id, **kwargs)
    return len(creation._provider_prompt({"request": request}).encode("utf-8"))


def test_largest_path_actual_character_creation_provider_prompt_stays_bounded(catalog_environment, monkeypatch):
    """The window may never cost a project the capacity it already had.

    Two facts about this projection drive what can honestly be asserted here.
    First, on the base code it is already refused for these projects: no
    cue/display rung squeezes it under the shipped hard cap, so the cap is
    lifted here only to obtain a size.  Second, the returned size is a step
    function of that compaction search -- whichever rung first clears the
    target wins -- so a smaller window can select a larger rung.  Comparing the
    two byte counts directly would assert a claim that is not true of this
    change, so the invariant kept is the capacity one: a window must never
    push a project that used to fit over the cap.  Window growth is measured
    where it is unambiguous, on the prompt text itself.
    """
    db = catalog_environment["db"]
    measurements = []
    for path in CANONICAL_PATH_IDS:
        pid = _project(db, path=path)
        stage1 = Stage1ClipboardService(db)
        _freeze_catalog_for_page_checks(stage1, pid, monkeypatch)
        creation = CharacterCreationExecutionService(db, stage1=stage1, provider=None,
                                                     project_store=ProjectStore(db))
        kwargs = dict(execution_mode="MANUAL_CHAT", idempotency_key="SOL77-prompt-size",
                      manual_collection_nonce="SOL77-measurement-nonce-unchanged-0000")
        with monkeypatch.context() as measure:
            measure.setattr(creation_module, "PROVIDER_PROMPT_HARD_CAP_BYTES", 32 * 1024 * 1024)
            with monkeypatch.context() as old:
                old.setattr(stage1_module, "insight_windows", _legacy_window)
                before = _model_facing_prompt_bytes(creation, pid, kwargs)
            after = _model_facing_prompt_bytes(creation, pid, kwargs)
        cap = PROVIDER_PROMPT_HARD_CAP_BYTES
        assert after <= cap or before > cap, (path, before, after, cap)
        measurements.append((path, before, after, before <= cap))
    print("SOL77 model-facing UTF-8 bytes (Path, before, after, before_fits_cap), cap:",
          measurements, PROVIDER_PROMPT_HARD_CAP_BYTES)


@pytest.mark.parametrize("page", [-1, True, "1"])
def test_insight_pages_reject_invalid_indices(page):
    with pytest.raises(FoundryError, match="page"):
        insight_windows([], project={"project_id": "fixed", "user_locks": []}, effective_by_id={},
                        preferred={}, linked=set(), required=[], limit=50,
                        choice=lambda row: row).page(page)
