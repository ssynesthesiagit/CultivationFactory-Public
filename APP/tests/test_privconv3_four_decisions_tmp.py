"""PRIVCONV3F6: the option lists that carry the four typed decisions.

Prints the compiled option rows of the four records this lane turns on (Kindled Responses,
Overkindled Responses, Painted Beast, Tempered Response) and the typed decision data each one
carries (Special Attack flag, Defensive Discipline menu, printed cost, duration kind), so the
evidence shows which options exist and what each decision says.
"""
import json
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
AUTHORITY = json.loads((APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())
RECORDS = {
    "Kindled Responses": "TAL_YANG_KINDLED_RESPONSES",
    "Overkindled Responses": "TAL_YANG_OVERKINDLED_RESPONSES",
    "Painted Beast": "tianxia.talent.ink.painted_beast",
    "Tempered Response": "tianxia.path.body_refining.feature.tempered_response",
}
TALENTS = ["tianxia.talent.ink.painted_beast", "TAL_YANG_KINDLED_RESPONSES", "TAL_YANG_OVERKINDLED_RESPONSES",
           "tianxia.path.body_refining.feature.tempered_response"]


def test_the_four_decisions_carry_their_options():
    from combat.ext.effect_durations import kind_of
    from tests import auto8f1_table_support as table

    mechanics = AUTHORITY["mechanics"]
    for label, key in RECORDS.items():
        row = mechanics[key]
        print("=" * 72)
        print(label, key)
        for field in ("options", "disciplines", "special_attack", "printed_cost", "activation"):
            if field in row:
                print(f"  {field}: {json.dumps(row[field], ensure_ascii=False)[:700]}")
        print("  duration:", kind_of(row.get("duration")))
        for effect in row.get("effects") or []:
            if "duration" in effect:
                print("  effect duration:", kind_of(effect["duration"]), "|", effect.get("type"))

    tmp = Path(tempfile.mkdtemp(prefix="four-decisions-"))
    game = table.fixture(tmp, TALENTS, seed="BDIFF-privconv3-four-records", kit=table.AXE_KIT,
                         ask_actors=(table.FOE,))
    menu = game["menu"]()
    print("=" * 72)
    print("the compiled option rows of the fighter that owns the four records:")
    for group in menu.get("actions", []):
        for option in group.get("options", []):
            label = option.get("label") or ""
            if any(word in label for word in ("Painted", "Tempered", "Kindle", "Rising", "Fu (Short Axe)")):
                print("  option:", json.dumps(option, ensure_ascii=False)[:400])
