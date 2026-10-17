"""Real CL3 initial-creation acquisition, distinct from combat-import proof."""
import pytest

from app.core import Database, FoundryError
from character_builder import CharacterBuilderService
from non_sphere_authority import NonSphereAuthorityService

BODY = 'tianxia.path.body_refining'
SCHOOL = 'tianxia.subpath.body.sky_treading_tendon_school'
LEGS = SCHOOL + '.feature.thousand_mile_legs'


def create(builder, cl):
    return builder.create_project(
        working_name='Thousand-Mile Legs source acquisition',
        concept='A Body Refining practitioner of the open Sky-Treading school.',
        target_cl=cl, power_band='standard', source_reference=None,
        creation_mode='detailed', ability_scores={},
        selections={'path_choice': [BODY], 'subpath_choice': [SCHOOL]},
    )


def test_real_builder_acquires_open_school_at_owning_cl3_and_cold_state(catalog_environment):
    db = catalog_environment['db']
    builder = CharacterBuilderService(db)
    with pytest.raises(FoundryError):
        create(builder, 2)
    created = create(builder, 3)
    pid = created['project_id']
    service = NonSphereAuthorityService(db)
    state = service.get_state(pid)
    path = next(row for row in state['paths'] if row['path_id'] == BODY)
    assert path['attainment'] == 3
    assert path['subpath_or_tradition_id'] == SCHOOL
    assert path['subpath_or_tradition_acquisition_provenance']['access_category'] == 'Open School'
    record = service.project_locked_subpath_catalog_record(SCHOOL)
    native = record['compatibility']['factory']['stage2_authority']
    assert native['owning_path_id'] == BODY and native['minimum_cl'] == 3
    row = next(row for row in native['feature_progression'] if row['canonical_id'] == LEGS)
    assert row['granted_at_cl'] == 3 and row['minimum_realm_band'] == 'Mortal'
    exported = service.export_state(pid)
    cold = NonSphereAuthorityService(Database(db.settings))
    assert cold.get_state(pid) == state
    assert cold.export_state(pid) == exported
