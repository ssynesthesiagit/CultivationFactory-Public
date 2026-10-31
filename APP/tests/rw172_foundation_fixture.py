"""Synthetic Foundation catalog for the RW172 combat regressions.

The real catalog is authenticated elsewhere; these tests exercise combat rather
than the public export's deliberately scrambled catalog prose.
"""
import pytest
from non_sphere_authority import foundation_mechanics as fm

GOLDEN = 'ancient_desolate_sacred_body_v0_2C'
TYRANT = 'heaven_tyrant_body_v0_2D'
WOMB = 'heaven_devouring_shedding_womb_v0_2B'

FEATURES = {
    GOLDEN: [
        ('Saint-Body Frame', 'Awakened'), ('Generate Golden Sea Pulse', 'Awakened'),
        ('Golden Sea Guard', 'Awakened'), ('Saint-Body Rebuke', 'Awakened'),
        ('Refuse Heaven-Lock', 'Awakened'), ('Refined: Golden Blood Root', 'Refined'),
        ('Refined: Pressure Becomes Method', 'Refined'), ('Perfected: Sacred Body Wake', 'Perfected'),
    ],
    TYRANT: [
        ('Tyrant-Blood Frame', 'Awakened'), ('Generate Tyrant Form Pulse', 'Awakened'),
        ('Tyrant Blood Surge', 'Awakened'), ('Imperial Shoulder-Gate', 'Awakened'),
        ('Tyrant Form Crush', 'Awakened'), ('Refined: Nine-Form Blood', 'Refined'),
        ('Refined: Tyrant Momentum', 'Refined'), ('Perfected: Heaven Tyrant Blood Declaration', 'Perfected'),
    ],
    WOMB: [
        ('Devouring Womb Frame', 'Awakened'), ('Generate Devoured Origin Spark', 'Awakened'),
        ('Devouring Return', 'Awakened'), ('Origin-Seizing Blow', 'Awakened'),
        ('Shedding-Husk Surge', 'Awakened'), ('Refined: Black-Womb Refinement', 'Refined'),
        ('Refined: Imperishable Husk', 'Refined'), ('Perfected: Imperishable Heaven Womb', 'Perfected'),
    ],
}


@pytest.fixture
def synthetic_foundations(monkeypatch):
    records = {}
    for identity, names in FEATURES.items():
        blocks = []
        for name, stage in names:
            effect = ('Your maximum Hit Points increase by twice your Proficiency Bonus.'
                      if identity == GOLDEN and name == 'Saint-Body Frame' else 'Synthetic fixture.')
            blocks.append(f'#### {name}\n**Type:** Passive\n**Available At:** {stage}\n**Effect:** {effect}\n')
        records[identity] = {
            'foundation_id': identity, 'stage': 'Awakened',
            'compatible_path_ids': ['QI_CULTIVATION'], 'source': {'fixture': identity},
            'semantic_surfaces': {
                'resource': '### Fixture Pulse\n| **Maximum** | 1 |\n| **Starting Amount** | 0 |\n',
                'features': '\n'.join(blocks), 'progression': '',
            },
        }
    monkeypatch.setattr(fm, 'verified_foundation_records', lambda: records)
    return records
