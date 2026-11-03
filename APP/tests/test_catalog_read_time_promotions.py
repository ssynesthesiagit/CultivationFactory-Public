"""Read-time catalog promotions that unblock creation-time legality.

Two catalog data shapes were making most of the rulebook unbuildable:

* 526 of 2,988 talents carry a fully typed ``requires <talent>`` relation
  without a ``kind``; the normalizer parked it as retained and coverage
  blocked the talent from Stage 1 (PREREQUISITE_NOT_NORMALIZED).
* 30 of 31 Backgrounds have no ``background_packages`` in their Stage 2
  authority; Stage 1 offers no Background without one.

Both are repaired when the effective catalog is projected, so Stage 1,
coverage, the sealed envelope and Stage 2's locked copies all agree.
"""

from __future__ import annotations

from copy import deepcopy

from catalog.service import BACKGROUND_PACK_VERSION, derive_background_packages, promote_typed_retained_prerequisites


def _talent(retained) -> dict:
    return {
        "record_id": "TAL_DEATH_BONE_BASTION",
        "content_type": "talent",
        "legality": {"acquisition_channels": ["ordinary-sphere-talent"], "incompatibilities": [], "minimum_cl": 5, "prerequisites": []},
        "compatibility": {"factory": {"retained_prerequisites": retained, "stage2_authority": {"sphere_id": "tianxia.sphere.death"}}},
    }


def test_typed_retained_prerequisites_are_published_with_inferred_kind() -> None:
    record = _talent([{"operator": "requires", "target_id": "TAL_DEATH_BONE_WARD"}, "free text that stays retained"])
    assert promote_typed_retained_prerequisites(record) is True
    assert record["legality"]["prerequisites"] == [{"kind": "talent", "target_id": "TAL_DEATH_BONE_WARD", "operator": "requires"}]
    assert record["compatibility"]["factory"]["retained_prerequisites"] == ["free text that stays retained"]
    # Idempotent: a second pass changes nothing.
    again = deepcopy(record)
    assert promote_typed_retained_prerequisites(again) is False
    assert again == record


def test_relations_with_a_kind_or_unknown_operator_are_left_alone() -> None:
    record = _talent([{"kind": "talent", "operator": "requires", "target_id": "TAL_X"}, {"operator": "maybe", "target_id": "TAL_Y"}])
    assert promote_typed_retained_prerequisites(record) is False
    assert record["legality"]["prerequisites"] == []


def test_background_packages_are_derived_from_dependencies_by_sphere_key() -> None:
    record = {
        "record_id": "tianxia.background.ancestral_shrine_keeper",
        "content_type": "background",
        "dependencies": [
            "tianxia.background_sphere.spirit_companions", "tianxia.background_sphere.karma", "tianxia.background_sphere.talismans",
            "tianxia.background_talent.spirit_companions.iron_courtesy", "tianxia.background_talent.karma.witness_seal",
            "tianxia.background_talent.talismans.warding_talisman", "tianxia.origin_insight.shrine_child",
        ],
        "compatibility": {"factory": {"stage2_authority": {"allowed_kinds": ["background_acquisition"]}}},
    }
    assert derive_background_packages(record) is True
    packages = record["compatibility"]["factory"]["stage2_authority"]["background_packages"]
    assert packages == [
        {"sphere_record_id": "tianxia.background_sphere.spirit_companions", "talent_record_id": "tianxia.background_talent.spirit_companions.iron_courtesy"},
        {"sphere_record_id": "tianxia.background_sphere.karma", "talent_record_id": "tianxia.background_talent.karma.witness_seal"},
        {"sphere_record_id": "tianxia.background_sphere.talismans", "talent_record_id": "tianxia.background_talent.talismans.warding_talisman"},
    ]


def test_hand_authored_background_packages_are_never_overridden() -> None:
    record = {
        "record_id": "tianxia.background.abandoned_orphan",
        "content_type": "background",
        "dependencies": ["tianxia.background_sphere.scoundrel", "tianxia.background_talent.scoundrel.grifter_s_hands"],
        "compatibility": {"factory": {"stage2_authority": {"background_packages": [{"sphere_record_id": "tianxia.sphere.scoundrel", "talent_record_id": "TAL_SCOUNDREL_HIDDEN_TOOL_CACHE"}]}}},
    }
    before = deepcopy(record)
    assert derive_background_packages(record) is False
    assert record == before


def test_rebuild_promotes_stored_rows_without_moving_the_pinned_core_pack_hash(catalog_environment) -> None:
    # Integration over the real bundled Factory: the core pack hash must stay
    # exactly the pinned value (compiler authority and every project lock
    # depend on it) while the stored rows carry the promotions and coverage
    # stops blocking prerequisite-chained talents.
    import json
    from character_creation.compiler_selection_authority import PINNED_CORE_PACK_HASH
    from catalog.coverage import Stage1CatalogCoverageService

    report = catalog_environment["report"]
    assert report["pack_hash"] == PINNED_CORE_PACK_HASH
    db = catalog_environment["db"]
    with db.connection() as conn:
        bastion = json.loads(conn.execute("SELECT data_json FROM catalog_records WHERE record_id='TAL_DEATH_BONE_BASTION' ORDER BY row_id DESC LIMIT 1").fetchone()["data_json"])
        keeper = json.loads(conn.execute("SELECT data_json FROM catalog_records WHERE record_id='tianxia.background.ancestral_shrine_keeper' ORDER BY row_id DESC LIMIT 1").fetchone()["data_json"])
    assert {"kind": "talent", "target_id": "TAL_DEATH_BONE_WARD", "operator": "requires"} in bastion["legality"]["prerequisites"]
    assert bastion["compatibility"]["factory"]["retained_prerequisites"] == []
    packages = keeper["compatibility"]["factory"]["stage2_authority"]["background_packages"]
    assert {"sphere_record_id": "tianxia.background_sphere.karma", "talent_record_id": "tianxia.background_talent.karma.witness_seal"} in packages
    # Origin grammar coverage on the published Origins: every Origin whose
    # options are all skills resolves; the rest all carry tool, kit, language
    # or trade options and are excluded from presentation by Stage 1.
    from character_creation.starting_proficiency_authority import _origin_entry, origin_starting_proficiency_unresolved
    with db.connection() as origin_conn:
        origins = [
            json.loads(row["data_json"])
            for row in origin_conn.execute(
                "SELECT data_json FROM catalog_records WHERE content_type='origin_insight' AND pack_version=?",
                (BACKGROUND_PACK_VERSION,),
            ).fetchall()
        ]
    assert len(origins) == 50
    resolved = {row["record_id"] for row in origins if _origin_entry(row["record_id"], row) is not None}
    assert "tianxia.origin_insight.grave_courtesy" in resolved
    assert len(resolved) >= 29
    excluded = {row["record_id"] for row in origins if origin_starting_proficiency_unresolved(row["record_id"], row)}
    assert excluded.isdisjoint(resolved) and excluded | resolved == {row["record_id"] for row in origins}
    coverage = Stage1CatalogCoverageService(db).build()
    skeleton = next(c for c in coverage["categories"] if c["slot_id"] == "advancement_skeleton")
    assert "TAL_DEATH_BONE_BASTION" in set(skeleton["selectable_record_ids"])
