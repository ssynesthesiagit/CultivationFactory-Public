"""Owner-sheet inputs shared by compiler-cache tests and headless receipts.

Read every shipped owner snapshot in the test fixtures and bundled archives.
These inputs are read directly; no installed character, database or live data
is consulted. Stock Gate 4 projections are already compiled and have no owner
sheet, so their behavior is checked with the six stock AI captures instead.
"""
import json
from pathlib import Path
import zipfile


def owner_character_fixtures(app_root: Path):
    """Yield (source label, owner sheet) for every complete shipped snapshot."""
    fixtures = app_root / 'tests/fixtures'
    for path in sorted(fixtures.rglob('*.json')):
        # Owner snapshots have an explicit schema; avoid loading saved fights
        # or large unrelated fixture payloads merely to identify characters.
        if 'owner_sheet' not in path.name.lower() and 'owner_character_sheet' not in path.name.lower():
            continue
        document = json.loads(path.read_bytes())
        if isinstance(document, dict) and 'identity' in document and 'ability_scores_and_statistics' in document:
            yield path.relative_to(app_root).as_posix(), document
    archives = sorted([*fixtures.rglob('*.zip'), *(app_root / 'BundledContent').glob('*.zip')])
    for path in archives:
        with zipfile.ZipFile(path) as archive:
            for member in sorted(archive.namelist()):
                if not member.endswith('Tianxia_Owner_Character_Sheet_v1.json'):
                    continue
                document = json.loads(archive.read(member))
                if 'identity' in document and 'ability_scores_and_statistics' in document:
                    yield path.relative_to(app_root).as_posix() + ':' + member, document
