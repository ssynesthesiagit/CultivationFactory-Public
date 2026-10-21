"""The heavily obscured hover card names the zone and says plainly that you can't see into it (SEAFOG)."""

from combat.status_text import zone_sight_text


def test_heavy_zone_card_names_the_zone_and_says_you_cannot_see_into_it():
    profile = {"name": "Gate of the Inner Sea", "obscured": "heavy", "visual": {"material": "water"}}
    text = zone_sight_text(profile, {})
    assert text.startswith("Heavily obscured (Gate of the Inner Sea): you can't see into it.")
    assert "cannot be seen from outside or by others inside" in text
