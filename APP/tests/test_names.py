"""Seeded names by Dao (owner 2026-09-27: "a random name generator with seeds by dao type with variations and base it
on ancient chinese names"; factory_authoring/names.py)."""

from factory_authoring import names


def test_the_same_seed_gives_the_same_name_and_the_dao_changes_it():
    water = [row["name"] for row in names.suggestions("seed-1", 6, dao="kan")]
    assert water == [row["name"] for row in names.suggestions("seed-1", 6, dao="Water")]
    assert len(set(water)) == 6
    assert water != [row["name"] for row in names.suggestions("seed-1", 6, dao="li")]


def test_the_first_given_character_carries_the_dao():
    pool = {row[0].lower() for row in names.data()["trigrams"]["kan"]["chars"]}
    for index in range(20):
        row = names.generate(f"s{index}", dao="kan", style="classic")
        assert row["name"].split()[1].lower() in pool and row["hanzi"]


def test_avoided_names_are_skipped_and_courtesy_names_do_not_repeat_the_given_name():
    first = names.generate("x", dao="kan")
    assert names.generate("x", dao="kan", avoid=[first["name"]])["name"] != first["name"]
    for index in range(30):
        row = names.generate(f"c{index}", dao="kan", style="courtesy")
        name_hanzi, courtesy_hanzi = row["hanzi"].split("，字子")
        assert courtesy_hanzi and courtesy_hanzi not in name_hanzi
