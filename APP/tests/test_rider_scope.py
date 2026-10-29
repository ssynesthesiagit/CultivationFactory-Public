import json

import pytest

from tools.rider_scope import APP, CLASSES, totals


def test_inventory_counts_and_rejects_duplicate_or_stale_annotations(tmp_path):
    mechanics = {"A": {"riders": ["one", "two"]}}
    row = {"index": 0, "text": "one", "class": "CANT_TABLE",
           "reason": "campaign", "by": "read"}
    path = tmp_path / "scope.json"

    def write(rows):
        path.write_text(json.dumps({"rider_scope": {"A": rows}}), encoding="utf-8")

    write([row])
    counts = totals(mechanics, tmp_path)
    assert counts["CANT_TABLE"] == 1
    assert counts["UNCLASSIFIED"] == 1
    assert sum(counts.values()) == 2
    authority = json.loads((APP / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    status_dir = APP / 'combat/rules/feature_status.d'
    actual = totals(authority, status_dir)
    annotations = [row for file in status_dir.glob('*.json')
                   for rows in json.loads(file.read_text()).get('rider_scope', {}).values()
                   for row in rows]
    for name in CLASSES:
        assert actual[name] == sum(row['class'] == name for row in annotations)
    assert sum(actual.values()) == sum(len(row.get('riders', [])) for row in authority.values())
    write([row, row])
    with pytest.raises(ValueError, match="duplicate or stale"):
        totals(mechanics, tmp_path)
    write([{**row, "text": "old"}])
    with pytest.raises(ValueError, match="duplicate or stale"):
        totals(mechanics, tmp_path)
