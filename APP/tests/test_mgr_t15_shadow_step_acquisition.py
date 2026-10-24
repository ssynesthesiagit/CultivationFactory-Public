"""Native exact Ninpo access, Qi attainment and reload; no GM bypass."""
import pytest
from app.core import FoundryError
from non_sphere_authority.service import NonSphereAuthorityService
from tests.test_ns1r_non_sphere_authority import authority, insert_project, QI, BODY
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event

PARENT = 'tianxia.subpath.qi.ninpo_adept'
STEP = PARENT + '.feature.shadow_step'
# NS1R validates every byte named by its identity manifest at construction,
# including non-executable Markdown. Declare those real dynamic inputs so
# public CI either exports the complete cleared dependency set or fails closed.
# These declarations grant no publication rights and change no loader policy.
INPUTS = (
    'non_sphere_authority/authority/NS1R_AUTHORITY_IDENTITIES.json',
    'non_sphere_authority/authority/Background_Core_Authority_v1.json',
    'non_sphere_authority/authority/Exact_Named_Method_Foundation_Overrides_v0_6.json',
    'non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json',
    'non_sphere_authority/authority/Foundation_Trait_Reference_v0_6.json',
    'non_sphere_authority/authority/Method_Compatibility_Trait_Taxonomy_v0_6.json',
    'non_sphere_authority/authority/Tianxia_Compatibility_Result_v0_6.schema.json',
    'non_sphere_authority/authority/Tianxia_Exact_Named_Overrides_v0_6.schema.json',
    'non_sphere_authority/authority/Tianxia_Foundation_Traits_v0_6.schema.json',
    'non_sphere_authority/authority/Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md',
    'non_sphere_authority/authority/Tianxia_Method_Compatibility_Traits_v0_6.schema.json',
    'non_sphere_authority/authority/Tianxia_Method_Registry_v0_6.schema.json',
    'non_sphere_authority/authority/Tianxia_Methods_Typed_Registry_v0_6.json',
    'non_sphere_authority/authority/Tianxia_PHB_Backgrounds_v2_BOOK_CLEAN_ORIGIN_RECONCILED_v0_6.md',
    'non_sphere_authority/authority/Tianxia_Path_Index_Master_P2A.json',
    'non_sphere_authority/authority/Tianxia_Subpath_Tradition_Index_Master_P2B.json',
    'non_sphere_authority/authority/Tianxia_Trait_Provenance_v0_6.schema.json',
    'non_sphere_authority/authority/body_refining.path_index.p2a.json',
    'non_sphere_authority/authority/open_ended_compatibility_resolver.py',
    'non_sphere_authority/authority/qi_cultivation.path_index.p2a.json',
    'non_sphere_authority/authority/spirit_awakening.path_index.p2a.json',
    'non_sphere_authority/authority/owner_subpaths.d/cai_clan.json',
)


def test_ninpo_exact_access_qi_cl3_and_cold_state(authority):
    service, db = authority
    pid = 'shadow-step-acquisition'
    insert_project(db, pid, target_cl=3)
    service.initialize_for_project(pid, target_cl=3, path_ids=[QI], method_id='METHOD-001')
    for path, code in ((BODY, 'NS1R_PATH_SUBPATH_MISMATCH'), (QI, 'NS1R_SUBPATH_CL3_REQUIRED')):
        with pytest.raises(FoundryError) as error:
            service.select_subpath(pid, path, PARENT)
        assert error.value.code == code
    service.allocate_advancement(pid, {QI: 2}, evidence_id=ap_award(db, service, pid, 'METHOD-001', 3, 2),
                                 idempotency_key='shadow-step-cl3')
    with pytest.raises(FoundryError) as error:
        service.select_subpath(pid, QI, PARENT)
    assert error.value.code == 'NS1R_RESTRICTED_TRADITION_ACCESS_REQUIRED'
    access = commit_authority_event(db, service, pid, 'subpath_access', {'selection_id': PARENT})
    service.select_subpath(pid, QI, PARENT, access_source_records=[access])
    fresh = NonSphereAuthorityService(db)
    state = fresh.get_state(pid)
    qi = next(p for p in state['paths'] if p['path_id'] == QI)
    assert qi['attainment'] == 3 and qi['subpath_or_tradition_id'] == PARENT
    source = fresh.subpaths[PARENT]
    assert source['prerequisites']['realm_band'] == 'Mortal'
    assert [r['canonical_id'] for r in source['feature_progression'] if r['granted_at_cl'] <= qi['attainment']] == [STEP]
