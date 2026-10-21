"""Analyze presentation shared by its choices and generated status catalog.

Extended from fix/hunt10b (23538fdb), retaining its single source reading.
The core prose was not extracted as a talent in rules_text.json. The retained
source quotation in mind_hidden_eye's module docstring supplies this reading;
the base sphere record describes Stealth proficiency, not Analyze's check.
These hooks describe existing state only, including older saved trackers.
SKILLS labels riders14_eye's skill choices; characteristic_label is shared with
riders14_research: saved option/name keys
stay stable while the table and status catalog use plain display names.
"""
from . import hook

RULES = (
    "Analyze: inspect one creature you can see within 60 feet. "
    "Time: 10 minutes, or 1 Action by expending Martial Focus (the readiness required for this quick use). "
    "Choose Intelligence (Investigation) or Wisdom (Perception). "
    "The Analyze DC is 10 + the target's Challenge Rating, or 10 + half its Cultivation Level, "
    "rounded down, if it has no Challenge Rating. "
    "Success: learn one Analyzable Characteristic and the creature becomes Analyzed by you. "
    "Failure: learn nothing. Duration: 24 hours, or until you finish a Long Rest. "
    "Owning other Hidden Eye talents may add skills, change the time or range, or reveal more characteristics."
)

ABILITIES = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
             "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}
SKILLS = {"Investigation": "Intelligence", "Perception": "Wisdom", "History": "Intelligence",
          "Nature": "Intelligence", "Medicine": "Wisdom", "Survival": "Wisdom",
          "Deception": "Charisma", "Intimidation": "Charisma", "Persuasion": "Charisma"}


def characteristic_label(name):
    """Present a retained characteristic key without changing save/choice identity."""
    if name == "maximum_hp":
        return "Maximum Hit Points"
    if name.startswith("GM information "):
        return "Ask the GM: another characteristic (" + name.rsplit(" ", 1)[-1] + ")"
    if name.endswith(" Sense"):
        return name.removesuffix(" Sense").replace("_", " ").title() + " range"
    if name.endswith(" saving throw"):
        return ABILITIES.get(name.split(" ")[0], name.split(" ")[0]) + " saving throw bonus"
    if name.endswith(" Resistance"):
        return name.removesuffix(" Resistance").lower().capitalize() + " damage resistance"
    return name.replace("_", " ")


def status_reading(engine, row, data):
    """Only Analyze's mark and persisted attempt/knowledge trackers qualify."""
    key = str(row.get("condition_id") or "").removeprefix("condition:typed.")
    if key not in {"analyzed_by", "eye_attempts", "eye_known_characteristic"}:
        return None
    target = engine.state.actors.get(data.get("target_id"))
    name = target.display_name if target else "this creature"
    if key == "eye_known_characteristic":
        prefix = f"Learned about {name}: {characteristic_label(data.get('name', 'a characteristic'))} = {data.get('value', 'unknown')}. "
    elif key == "eye_attempts":
        prefix = f"Analyze attempts used against {name}: {int(data.get('used') or 0)}. "
    else:
        owner = engine.state.actors.get(row.get("source_actor_id"))
        prefix = f"This creature is Analyzed by {owner.display_name if owner else 'its analyzer'}. "
    return {"rules": prefix + RULES, "source_ability": "Analyze",
            "handling": "The table records this information until removed; rest and day-long expiry are handled by the GM."}


@hook("decision_text")
def decision_reading(engine, context, printed_rules):
    choice = context.get("reaction_source_id")
    if choice not in {"choice:needle.eye_approach", "choice:needle.eye_learn"}:
        return None
    actor_id = context.get("reactor_id")
    if not any(a.owner_id == actor_id and a.display_name == "Analyze" for a in engine.action_catalog.values()):
        return None
    learning = choice == "choice:needle.eye_learn"
    trigger = context.get("choice_trigger") or {}
    target = engine.state.actors.get(trigger.get("target_id"))
    name = target.display_name if target else "the selected creature"
    descriptions = {}
    for option in trigger.get("needle_options") or []:
        if not learning:
            descriptions[option] = f"Roll {SKILLS.get(option, 'the permitted ability')} ({option}) to Analyze {name}. Success learns characteristics and makes this creature Analyzed by you; failure learns nothing."
        elif option.startswith("GM information "):
            descriptions[option] = f"Ask the GM for one distinct Analyzable Characteristic of {name} that the table cannot reveal. This selection does not invent or automatically reveal a narrative fact."
        elif option.endswith(" Sense"):
            descriptions[option] = f"Learn {name}'s {characteristic_label(option)} in feet; this reveals its sensing distance, and does not grant you that sense."
        elif option == "Walking Speed":
            descriptions[option] = f"Learn how many feet {name} can walk on its turn without Dashing."
        elif option.endswith(" Resistance"):
            descriptions[option] = f"Learn {name}'s resistance to {option.split(' ')[0].lower()} damage (normally halves damage of that type)."
        else:
            descriptions[option] = f"Learn {name}'s current {characteristic_label(option)}. This reveals a combat statistic; it does not change it."
    summary = (f"Choose the listed number of distinct characteristics to learn about {name}; Ask the GM choices cover facts the table cannot reveal. "
               if learning else f"Choose one permitted skill to Analyze {name}. Roll that skill against the creature's Analyze DC; success learns characteristics and makes it Analyzed by you. ")
    actor = engine.state.actors[actor_id]
    if learning and target is not None and any(c.condition_id == "condition:typed.eye_court" for c in actor.conditions.values()) and engine._distance_actor_to_actor(actor, target) <= 60:
        summary += "Court of the Hidden Eye is active: successfully Analyzing a creature inside its 60-foot area around you teaches one additional characteristic, included in this selection count. "
    return {"rules": RULES, "summary": summary,
            "cost": "No additional action or resource cost for this selection; the triggering Analyze pays its own cost.",
            "limits": "The learned information and Analyzed benefit last 24 hours, or until you finish a Long Rest.",
            "option_descriptions": descriptions}
