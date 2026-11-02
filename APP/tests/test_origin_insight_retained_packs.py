"""Provider-free regressions for new-character retained-pack menu scoping."""
import json

import pytest

from app.core import FoundryError
from character_builder.service import CharacterBuilderService
from contracts.canonical import canonical_record_hash


@pytest.fixture
def retained_origins(catalog_environment, fresh_db):
    with catalog_environment["db"].connection() as source, fresh_db.connection() as target:
        source.backup(target)
    with fresh_db.connection() as conn:
        pack = dict(conn.execute(
            "SELECT * FROM content_packs WHERE pack_id='tianxia.core.backgrounds.origins' "
            "ORDER BY version DESC LIMIT 1"
        ).fetchone())
        current = pack["version"]
        pack["version"] = "0.0.1"
        columns = list(pack)
        conn.execute(f"INSERT INTO content_packs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", list(pack.values()))
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM catalog_records WHERE pack_id=? AND pack_version=?",
            (pack["pack_id"], current),
        )]
        for row in rows:
            row.pop("row_id")
            row["pack_version"] = pack["version"]
            data = json.loads(row["data_json"])
            data["content_binding"]["pack_version"] = pack["version"]
            data["record_hash"] = canonical_record_hash(data)
            row["record_hash"] = data["record_hash"]
            row["data_json"] = json.dumps(data)
            columns = list(row)
            conn.execute(f"INSERT INTO catalog_records ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", list(row.values()))
    return CharacterBuilderService(fresh_db), current


def test_retained_pack_options_match_creation_bindings_and_background_routes(retained_origins):
    service, current = retained_origins
    categories = {row["slot_id"]: row for row in service.options()["categories"]}
    origins = {row["choice_id"]: row for row in categories["origin_insight_choice"]["choices"]}
    assert len(origins) == 50
    assert all(row["pack_version"] == current for row in origins.values())
    assert all(row["insight_authority"]["authority_type"] == "Background-Origin" for row in origins.values())
    raw_choices = service._choice_records(set(origins))
    assert all(row["insight_authority"]["source_occurrence_count"] == 1 for row in raw_choices.values())
    # Only an Origin whose printed proficiency options the typed grammar cannot
    # resolve (a trade or campaign-language option) is marked unavailable, and
    # then with the builder's single published reason.
    from character_builder.service import ORIGIN_PROFICIENCY_UNTYPED_REASON
    from character_creation.starting_proficiency_authority import origin_starting_proficiency_unresolved
    with service.db.connection() as conn:
        full_records = {
            row["record_id"]: json.loads(row["data_json"])
            for row in conn.execute(
                "SELECT record_id, data_json FROM catalog_records WHERE content_type='origin_insight' AND pack_version=?",
                (current,),
            )
        }
    untyped_ids = {
        record_id for record_id, record in full_records.items()
        if origin_starting_proficiency_unresolved(record_id, record)
    }
    assert len(untyped_ids) < len(origins)
    for origin_id, row in origins.items():
        if origin_id in untyped_ids:
            assert row.get("unavailable_reason") == ORIGIN_PROFICIENCY_UNTYPED_REASON, origin_id
        else:
            assert not row.get("unavailable_reason"), origin_id
    for background in categories["background_choice"]["choices"]:
        linked = set(background["related_choice_ids"]) & origins.keys()
        assert linked, background["name"]
        for origin_id in linked:
            selected = {"background_choice": [background["choice_id"]], "origin_insight_choice": [origin_id]}
            if origin_id in untyped_ids:
                # An Origin the grammar cannot type is refused at lock time
                # with the same published reason, never silently accepted.
                with pytest.raises(FoundryError) as error:
                    service._validated_selections(selected)
                assert error.value.message == ORIGIN_PROFICIENCY_UNTYPED_REASON
                continue
            normalized, records = service._validated_selections(selected)
            assert normalized == selected
            assert {p["pack_id"]: p["version"] for p in service._resolved_pack_locks(records)}["tianxia.core.backgrounds.origins"] == current
    with service.db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM catalog_records WHERE pack_id='tianxia.core.backgrounds.origins' AND pack_version='0.0.1'").fetchone()[0] > 50


def test_current_same_id_source_collision_still_quarantined(retained_origins):
    service, current = retained_origins
    with service.db.connection() as conn:
        row = dict(conn.execute(
            "SELECT * FROM catalog_records WHERE content_type='origin_insight' AND pack_version=? LIMIT 1", (current,),
        ).fetchone())
        row.pop("row_id")
        data = json.loads(row["data_json"])
        data["source"]["anchor"] += "-conflicting-source"
        data["source"]["source_hash"] = "a" * 64
        data["record_hash"] = canonical_record_hash(data)
        row.update(source_anchor=data["source"]["anchor"], source_hash=data["source"]["source_hash"], record_hash=data["record_hash"], data_json=json.dumps(data))
        columns = list(row)
        conn.execute(f"INSERT INTO catalog_records ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", list(row.values()))
    choice = service._choice_records({row["record_id"]})[row["record_id"]]
    assert choice["insight_authority"]["classification_code"] == "UNRESOLVED_DUPLICATE_INSIGHT_ID"
    assert choice["planning_priority_available"] is False
    assert choice["insight_authority"]["source_occurrence_count"] == 2
