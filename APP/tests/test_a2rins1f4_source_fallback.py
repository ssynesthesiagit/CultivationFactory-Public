"""A rejected optional lineage extension must not remove standard gift choices."""
import pytest

from tests.test_a2rins1f4_lineage_source import SOURCE, owner_bundle


@pytest.mark.parametrize('source', [
    {**SOURCE, 'damage_types': ['cold']},
    {**SOURCE, 'damage_types': ['wildfire'], 'rules_text': 'Wildfire damage.'},
    {**SOURCE, 'source_id': ''},
    {**SOURCE, 'rules_text': ''},
    {**SOURCE, 'damage_types': 'Fire'},
])
def test_invalid_optional_source_preserves_standard_demon_choices(source):
    compiled = owner_bundle(source)
    names = {a['display_name'] for a in compiled['action_catalog']
             if '.lineage_gift.demon.' in a['source_definition_id']}
    assert names == {'Ancestral Bloodline: Demon-Blood -- ' + kind
                     for kind in ('Necrotic', 'Psychic', 'Poison')}
