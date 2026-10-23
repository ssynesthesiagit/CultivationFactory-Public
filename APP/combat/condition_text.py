"""What each condition does, for the table's hover (owner 2026-09-27: "Id like to be able to hover over conditions and
have a mechanical description of its effects").

The mechanics are read from the rules the engine applies (combat/rules/typed_conditions.json: attack modes, speed 0, no
actions or reactions, saving-throw modes), so the text says what the fight will actually do; a short reading of the
condition (2024 rules, or the Tianxia talent that makes it) adds what the engine leaves to the GM.

The same two sources answer for every surface that has to show a condition without asking the API:
zone_readings() builds the lasting-area reader's copy from this module, so the sheet hover and the
area reader cannot drift apart (a second hand-written dictionary is what let them).
"""

from __future__ import annotations

import re
import functools
from typing import Any

from .typed_executor import rules
from .player_text import (keep_owner_words_in_note, reading as _player_reading,
                          reviewed_wording, rule_after_a_citation,
                          source_reading as _source_reading)

READING = {
    "bound_hand": "Binding Sleeve Method, Weapon Hand: Disadvantage on attacks using the bound hand or manipulator until the creature escapes. The table cannot distinguish hands, so it applies Disadvantage to all of that creature's attack rolls.",
    "cannot_teleport": "Dimensional Seal: the creature cannot teleport. The table blocks its own self-teleport abilities; the GM handles the printed restrictions on portals, extradimensional storage, pocket spaces and other spatial displacement.",
    "blinded": "It can't see, and fails any ability check that needs sight.",
    "charmed": "It can't attack its charmer or target them with harmful abilities; the charmer has Advantage on social checks against it. The table does not enforce these effects; your Game Master decides. "
               "A Beauty charm also carries what its talent says it forbids; unless stated otherwise, it ends when the charmer's side damages it or forces a damaging save.",
    "captivated": "Its attention is pulled to whoever captivated it: Disadvantage on Wisdom (Perception) checks to notice anyone else, no Opportunity Attacks against "
                  "anyone else. The GM handles the first hostile-action save and the resulting choice of target or action. Not mind control.",
    "deafened": "It can't hear, and fails any ability check that needs hearing.",
    "frightened": "While it can see the source of its fear, its attack rolls and ability checks have Disadvantage. It can't willingly take a step closer while that source is visible. The Game Master handles approach restrictions when it is unseen. Forced movement is unaffected.",
    "no_approach": "Kept at Distance: it cannot willingly move closer to the creature that applied this, whether that creature is in sight or not. Walking away still works, and so does anything that moves it without its choice (being pushed or dragged); a teleport of its own that lands it closer is refused.",
    "grappled": "Escape with an Action: Athletics or Acrobatics against the grapple's DC. Moving drags the grappler along only if it's allowed.",
    "incapacitated": "Its Concentration breaks.",
    "invisible": "It can't be seen without magic or a special sense.",
    "paralyzed": "It can't take actions or Reactions, move or speak. A hit by an attacker within 5 feet is a critical hit: roll twice the damage dice, without doubling flat bonuses.",
    "petrified": "It and its nonmagical equipment turn to stone: ten times the weight, no aging, no actions or Reactions, Speed 0, and Concentration ends. It takes half damage and can't become Poisoned. Attacks against it have Advantage; it automatically fails Strength and Dexterity saves. Weight and aging are tracked by your Game Master.",
    "poisoned": "Its attack rolls and all ability checks have Disadvantage.",
    "battle_rhythm": "It and its rider or mount are in perfect battle rhythm: the higher Speed for both, +2 AC, Advantage on Dexterity saving throws, difficult terrain ignored, "
                     "no Opportunity Attacks from movement; once a turn, after one hits, the other may move 10 feet or Shove as a Reaction.",
    "mounted": "It rides its mount and shares its space. A Controlled Mount moves as its rider directs, on the mount's Speed; a DC 10 Dexterity save "
               "keeps it in the saddle when the mount is moved against its will or either is knocked Prone; mounting and dismounting cost half its Speed.",
    "carrying": "It carries a rider in its space. The rider moves with it; a Controlled Mount takes no turn of its own and may only Dash, Disengage or Dodge "
                "(at its rider's direction), or Shove or Overrun with the rider's talents.",
    "prone": "It can only crawl; standing up costs half its Speed.",
    "restrained": "It is held fast in place.",
    "stunned": "It is Incapacitated and can't speak. Its Speed is unchanged.",
    "unconscious": "It is Incapacitated and Prone, so it can't take actions or Reactions, and drops what it holds. A hit by an attacker within 5 feet is a critical hit: roll twice the damage dice, without doubling flat bonuses.",
    "burning": "It is on fire: it takes Fire damage at the start of each of its turns for the effect's duration. It or an adjacent creature can use an Action to extinguish one Burn.",
    "battered": "Battered by a Berserker's Batter until the end of that Berserker's next turn: no penalty by itself; Exertion talents exploit it.",
    "kindled": "Embers from Fire Terrain cling to it until the start of the terrain's creator's next turn. Any ability that says it works on a Kindled creature works on it.",
    "smothered": "Soot fills its lungs (Soot in the Lungs, Smothering Cloud).",
    "reaction_denied": "Something has taken its Reaction until it recovers.",
    "no_disengage": "It can't take the Disengage action.",
    "held_fast": "Something holds it in place.",
    "anchored": "Heavenly Anchor: it cannot teleport, travel between planes, become Incorporeal, be moved against its will unless the moving effect beats the caster's Cultivation Save DC, or be carried away by ordinary environmental forces. An unwilling creature repeats the Charisma saving throw at the end of each of its turns; a success ends the effect.",
    "pinned": "It is pinned to the ground or a surface.",
    "pinning_volley": "Two attacks of one Barrage hit it. Speed is 0 until the start of its next turn.",
    # These two are applied to real state (combat/ext/mount_guard.py, combat/ext/glass_refraction.py) and so appear
    # as condition chips, but the engine applies no typed rule for them, so without a reading they showed no hover
    # text at all -- the same gap the owner playtest reported for "Golden Core" (MMX85).
    "meat_shield": "Meat Shield: the mount's body covers the rider from the edge the rider chose. Attacks from across "
                   "that edge cannot target the rider, and an attack that reaches the rider anyway is re-aimed at the "
                   "mount, which stays targetable normally. It ends with the free End Meat Shield action, when the "
                   "rider dismounts, or when the mount falls.",
    # The engine reads this on the creature that would REACT, not on the one that moves
    # (combat/typed_reactions.py: "wants_opportunity_attack" checks the reactor's own conditions), so the affected
    # creature stops being able to MAKE Opportunity Attacks.  Some sources hand out the restricted form --
    # Hammer Rebuke's "against you" saves the blacksmith (combat/ext/blacksmith_rebuke.py) -- and every source
    # sets its own expiry, so the text says so instead of naming one duration.
    "no_opportunity_attacks": "This creature cannot make an Opportunity Attack: when another creature leaves its reach or moves away from "
                              "it, it will not strike by Reaction. It can still be attacked this way, and it is not otherwise protected. "
                              "Some abilities limit this to a single creature, so it can still make Opportunity Attacks against everyone "
                              "else; the ability that applied it also decides how long it lasts (usually until the start of its next turn).",
    "court_of_falling_stars": "Active for 1 minute. Two Barrage hits can restore Martial Focus once per turn; other Court benefits are shown in the action text.",
    "court_falling_stars_ally": "Chosen when Court of Falling Stars activated. One attack roll against a creature hit twice by its creator's Barrage has Advantage.",
    "court_falling_stars_target": "Hit twice by one Barrage. A chosen Court of Falling Stars ally can use Advantage against it before the attacker's next turn.",
    "disarmed": "Its weapon lies where it fell; it can pick it up again (Take a dropped weapon).",
    "improvised": "It is fighting with an improvised weapon.",
    "guarding": "It guards an ally, stepping in to take attacks aimed at its ward (Deathless Guard).",
    "shell_ward": "Half Cover until the start of its next turn (a Living Painting Tortoise's Shell Ward): +2 against ranged attacks, the table's cover rule.",
    "dodge": "Dodging until the start of its next turn: attacks against it have Disadvantage if it can see the attacker, and it has Advantage on Dexterity saving throws. Both benefits end if it can't take actions or its Speed becomes 0; recovering does not restore this Dodge. Dodge costs an Action and no resource points.",
    "mark": "A technique has marked it. The Mark has no effect by itself; the technique's other abilities can use it. Its effects and duration depend on the technique that applied it.",
    "encumbered": "It carries more than 15 pounds per point of Strength. Its Speed is at most 5 feet, and its remaining movement this turn is reduced by the same amount. Dropping things lightens the load.",
    "unburdened": "It has put down enough to be under its capacity again: its own Speed returns (the movement it has left this turn grows by the difference).",
    "dropped_item": "It dropped something; the item lies where it fell until picked up.",
    "hidden": "It took the Hide action and beat DC 15 (Dexterity (Stealth)); its total is the DC to find it. It ends when it makes an attack roll, an enemy finds it with the Search action (Wisdom (Perception)), or it ends a move in an enemy's plain view.",
    "trap_setup": "What Set Trap will set next: its form, trigger, deployment and aim (change it with the free Trap buttons).",
    "netted": "Caught in a trap's net or noose: Restrained until it escapes with an Action (Athletics or Acrobatics against the trap-setter's Save DC).",
    "blossom_carried": "A dormant Blossom of the Flowers sphere rides it (a faint spiritual flower). Its maker may make it bloom; it withers in an hour, and this creature can use an Action to remove it.",
    "vessel_guarded": "Guarded by a puppet vessel (Puppetry, Guarding Vessel): +2 to Armor Class against the next attack roll made against it, until the start of its puppeteer's next turn.",
    "vessel_setup": "What the puppeteer set for the next puppet vessel: its form (Puppet Strike damage type) and, with Ironwood Practice Body, its construction (change them with the free Vessel buttons).",
    "figment_setup": "What the illusionist set for the next figment: sight and sound, a larger cube, no Concentration, a Potent Phantasm option and Selective Premise (change them with the free Figment buttons).",
    "banner_orders": "What the Banner Cultivator set for its Command Banner: the Banner Stance (or two with Fourfold Formation) and the standing Formation Maneuver (change them with the free Banner buttons).",
    "banner_step": "Free movement owed by a Command Banner: it may move that many feet without provoking Opportunity Attacks, added to its Speed at the start of its next turn.",
    "banner_brace": "Braced by an Officer's Command: Advantage on its next saving throw, until the start of its following turn.",
    "banner_imperial_spent": "The Imperial Standard of Heaven has been raised this scene (once per scene); it cannot be raised again until the scene ends.",
    "seal_free_used": "It has used the free Cut the Road Behind You of No Road Behind Me since its last long rest and cannot again until the next one.",
    "blossom_anchored": "A Traveling Garden's thorned field moves with it. An unwilling bearer repeats a Wisdom save at the end of each of its turns; a success ends the anchor.",
    "blossom_scripture": "Ten-Thousand Bloom Scripture: twice as many dormant Blossoms, Cultivate Blossom makes two, one Delayed Bloom a turn needs no action, and the first Blossom talent each turn costs 1 fewer CP (minimum 1). It lasts 1 minute.",
    "blossom_setup": "Which Blossom talent its next bloom will use, and its Seed, Lotus and corpse-flower settings (change them with the free Blossom buttons).",
    "blossom_medicine_used": "It has had a Medicinal Blossom's healing since its last short rest and cannot have it again until the next one.",
    "blossom_lotus_used": "It has been restored by a Spirit Lotus since its last short rest and cannot be again until the next one.",
    "blossom_trace": "A Scented Trace: the Blossom's maker knows roughly which way this creature is, within 10 miles times the maker's Proficiency Bonus, for 8 hours.",
    "blossom_false_death_used": "A Flower of False Death has already kept it standing; it cannot again until the next long rest.",
    "zone_effect": "What the area it stands in does to everyone inside, for as long as it stays there.",
    "shaping": "The talents its next area of that kind will carry.",
    "augments": "The augments its next use of that ability will carry.",
    "menu": "The options it has chosen from that ability's list (\"Choose three\") for its next use: they stay until it changes them, and choosing another replaces the one chosen longest ago.",
    "affliction": "Afflicted by a chosen set of effects that last together (its label names them: Symptom Cascade symptoms, Five-Venom Venom Effects, Meridian-Sealing Palm seals). Its Speed, AC, saves, Reactions, healing and start-of-turn damage follow the ones named; a successful repeat saving throw at the end of its turn ends all of them, or one, as the ability says.",
    "active_ability": "An ability of its own that lasts and that the GM applies (hover its name for what it does).",
    "hollowed": "Void: it can't reduce CP, Stamina or other printed technique costs below the listed cost, can't regain CP or Stamina from ordinary temporary effects, can't gain Temporary HP, and can't turn Invisible from an ordinary temporary supernatural effect. It doesn't reveal it, remove Cover, stop mundane hiding, end effects or stop normal healing. Unless the talent says otherwise, it lasts until the start of the applier's next turn.",
    "hollowed_item": "Empty Palm — Hollow the Weapon: one carried item is hollowed. Its cultivated properties stop working for the printed time — a weapon or Domain Armament can't be used to attack with, a Shield's +2 AC doesn't apply, and a floating Domain Armament goes inert. The physical item stays where it is; it is not destroyed, duplicated, moved or dropped.",
    "hollowed_asset": "Empty Palm — Unravel Manifestation: a summoned or projected Cultivation Asset is suppressed. It takes no Actions or Reactions and has Speed 0 for the printed time, and it stays on the table; it is not dismissed or destroyed.",
    "no_temp_hp": "It can't gain Temporary Hit Points.",
    "target_uses": "The creatures it has already used a once-per-creature ability on this fight (\"once per creature per rest\", \"once per target per scene\"): it can't use that ability on them again.",
    "mantle": "Its active Former-Life Mantle (Samsara Wheel, Echoes of Former Lives): the Mantle's while-active effects apply -- Speed, Opportunity Attack Disadvantage, Advantage on saves against Charmed, an extra weapon hit rider -- until it turns the Memory to another Mantle (Bonus Action, 1 Qi).",
    "shadow_mantle": "Shadow Mantle is active (Concentration, up to 1 minute): +2 AC; Resistance to Psychic and Necrotic damage; Advantage on Dexterity (Stealth) checks; Disadvantage on Opportunity Attacks made against it; and it sees normally through ordinary Darkness, though not supernatural Darkness.",
    "void_shell_hits": "Void Shell is active (Concentration, up to 1 minute): once per turn, when a creature hits it with a melee Cultivation Attack, that creature takes Force damage equal to its Proficiency Bonus. A confirmed hit retaliates even when it deals no damage.",
    "stone_shell": "Stone Womb Preservation: the target cannot move or take actions while the shell stands. The shell ends early on healing, dismissal, or damage equal to 10 + the Source key ability modifier + Proficiency Bonus.",
    "no_invisible": "It can't turn Invisible from an ordinary temporary supernatural effect.",
    "no_cp_regain": "It can't regain CP (Qi, Stamina, Resonance).",
    "no_dash": "It can't benefit from the Dash action.",
    "flustered": "A Jester's Punchline has rattled it: until the start of that Jester's next turn it can't take Reactions, and the next attack roll or ability check it makes has Disadvantage (the attack roll is automatic; the ability check is the GM's). After that roll only the Reaction loss remains.",
    "jester_applause": "A Jester's Punchline is watching the Foil's attack on it: the AC bonus (if any) applies to that roll only, and if the Foil misses, the Foil becomes Flustered.",
    # The Piercing Needle (owner's Sphere Compendium; combat/ext/needle*.py).
    "needle_court": "Court of Measured Openings (1 minute): one Feint each turn with no Action; a hostile that misses it in reach is Feinted with no Action; two different Exploits at once without expending Martial Focus; regains Martial Focus once per round when it uses Footwork. Ends if it is Incapacitated.",
    "needle_sovereign": "Sovereign Needle Incarnation (1 minute): Exploits twice per round (still once per attack), one Footwork per round without expending Martial Focus, and Martial Focus back when it wins a Disarm or Parry and Riposte reduces an attack's damage to 0. Its attacks count as magical, so a defence printed against nonmagical attacks no longer reduces them. Ends if it is Incapacitated. Rerolling Fatal Thrust's two d20s is your Game Master's call, since Fatal Thrust is not a talent this table has.",
    "needle_magical": "Its attacks count as magical (Sovereign Needle Incarnation).",
    "needle_greater_feint": "Fooled by a Greater Feint: the first attack roll each creature makes against it has Advantage, until the end of the feinter's next turn.",
    "needle_group_cover": "Group Cover: each other hostile creature next to the attacker has Disadvantage on attack rolls against the fencer until the start of the fencer's next turn.",
    "needle_lunge": "It lunged: -2 to attack rolls against targets within 5 feet until the start of its next turn.",
    "needle_arm_strike": "Arm Strike: -2 to attack rolls made with the chosen limb's weapon and to Strength and Dexterity checks that rely on that limb (GM picks the limb), for the duration.",
    "needle_soul_strike": "Soul Strike: -2 to its saving throws for the duration.",
    "needle_shadow_strike": "Shadow Strike: one temporary Exhaustion level (-2 to d20 Tests, -5 ft Speed), for the duration.",
    "needle_bleed_air": "Bleed Air: it starts choking after a number of rounds; while choking it drops to 0 Hit Points after its Constitution modifier in rounds. It ends when it is at full Hit Points.",
    "formation_cp_locked": "Suppressing Vein Pulse (failed save): it can't spend CP on Reactions, Counter effects or defensive sphere effects until the start of the array owner's next turn.",
    "formation_cp_tax": "Suppressing Vein Pulse (successful save): the next time it spends CP before the start of the array owner's next turn it spends 1 more.",
    "formation_teleport_dis": "Sealing Gate Pulse (successful save): Disadvantage on its next check or save to teleport, possess or travel spiritually, until the start of the array owner's next turn.",
    "formation_located": "Sensing Eye Pulse: the array's owner knows where it is, even Invisible or Hidden, until the start of the owner's next turn.",
    "formation_free_step": "Veiled Road Pulse: on its next turn it may move up to 10 feet without provoking Opportunity Attacks.",
    "formation_keyed": "Keyed to a formation array by its creator (Gate Keeper): the array's Difficult Terrain doesn't slow it and its hostile boundary effects don't touch it.",
    "formation_setup": "What the next array its owner sets will carry (second Pattern Layer, a line, keyed creatures); used up when the array is set.",
    "formation_exit": "Collapsing Exit: it may move up to 10 feet without Opportunity Attacks; ending outside the collapsed array's former area gives it Temporary HP equal to the array owner's Proficiency Bonus.",
    "formation_marked": "Eye of the Formation Master: it is the array's auxiliary Eye, so attacks against it have Advantage if the attacker is inside the array and can see it.",
    "formation_half_cover": "Harmonized Veiled Road: Half Cover (+2 AC against ranged attacks) while it stays inside the array, until the start of the array owner's next turn.",
    "formation_unlit": "Elemental Killing Array (Radiance): it gains no benefit from being Invisible or Hidden until the start of the array owner's next turn.",
    "formation_dim": "Elemental Killing Array (Shadow or Dark): Disadvantage on its next Wisdom (Perception) check, until the start of the array owner's next turn.",
    "formation_weak_con": "Elemental Killing Array (Blood or Poison): Disadvantage on its next Constitution saving throw, until the start of the array owner's next turn; that save uses it up.",
    "formation_spirit_locked": "Spirit-Lock Array: it can't be summoned or teleported, and can't teleport, until the start of the array owner's next turn.",
    "glamer_unending": "Obscuring Glamer (augment): its glamer doesn't end when it attacks, uses a technique or deals damage.",
    "violence_word": "Violence Word: on its next turn its Action must be an attack against the nearest creature.",
    "jinxed_name": "Jinxed Name: once a round -1d4 on an attack roll, ability check or saving throw; repeats the save at the end of its turns.",
    "jinxed_once": "Jinxed Name: -1d4 on its next attack roll or ability check.",
    "chain_of_misfortune": "Chain of Misfortune: its first misstep each round brings a misfortune; repeats the save at the end of its turns.",
    "chain_warning": "Chain of Misfortune: its next miss or failed save costs it its Reactions.",
    "chain_opening": "Chain of Misfortune: an ally's next attack against it has Advantage.",
    "fate_auspice": "An Auspice from its Fate caster (Release: its Reaction).",
    "guiding_star_free": "Guiding Star (released): it provokes no Opportunity Attacks for 1 minute.",
    "moving_star_ignore": "Moving Star (released): it ignores that condition until the end of its next turn.",
    "turning_wheel": "Turning Wheel Auspice: a bonus to attack and damage rolls, saving throws or ability checks.",
    "fate_sovereign": "Fate-Sovereign Incarnation: Fate Die d10; an ally's boon each turn.",
    "sovereign_boon": "Fate-Sovereign boon: +1 AC, +1 to saves or Advantage on its next attack.",
    "calamity": "Calamity Finds a Path: the chosen misfortunes until the start of the caster's next turn.",
    "lock_grip": "Lock Grip: Disadvantage on its next weapon attack roll.",
    "mirror_slick_immune": "Immune to Mirror-Slick Floor for now.",
    "bitter_edge": "Bitter Edge: its first hit each turn deals extra Cold damage.",
    "frost_guard": "Frost-Sheathed Guard: the first melee attacker to hit it gains a Fracture Mark.",
    "diamond_rime": "Diamond Rime Body: a melee attacker gets a Lattice Space under it.",
    "winter_crucible": "Immortal Winter Crucible: one more Lattice Space each time; a free spend on its turn.",
    "digestive_mantle": "Digestive Mantle: its chosen benefit is active.",
    "karma_chain": "Chain of Consequence: the next damage it deals returns to it as Psychic damage.",
    "karma_ten_thousand": "Ten Thousand Debts: the first harm it deals returns to it.",
    "karma_trial": "Trial of the Ledger: its first harm each turn costs 2d8 Psychic; its first heal gives 2d8 Temporary HP.",
    "karma_trial_once": "Trial of the Ledger: its first harm costs Psychic damage.",
    "karma_writ": "Judgment Writ: its first harm each turn costs Psychic damage.",
    "karma_bone": "Debt Written on Bone: its next damage brings the chosen consequence.",
    "karma_merit": "Merit Becomes Armor: healing another gives it Temporary HP once a round.",
    "karma_sovereign": "Karma-Sovereign Incarnation: Record the Deed reaches 300 feet.",
    "glass_tempered": "a tempered Glass Surface (its body, armor or held weapon) for its Faultline Marks and Refraction Responses.",
    "glass_incarnation": "always tempered; a free Refraction Response each round.",
    "glass_lens": "its first attack roll or technique gives it a Faultline Mark.",
    "glass_stored": "its next Faultline Strike or Glass Shard hit adds damage.",
    "glass_spared": "used this fight.",
    "glass_revealed": "its space is known until the start of the Glass cultivator's next turn.",
    "speech_damaged": "Haymaker: its speech and breath channel is damaged -- an ability that needs its voice calls for a Constitution save or fails.",
    "conditioned": "Intense Conditioning: the same category of action (an attack roll or a technique) calls for a Charisma save or fails.",
    "dug_in": "Dug-In Blow: Resistance to the named creature's next Bludgeoning, Piercing or Slashing hit.",
    "deep_root": "Deep Root Stance: its space is a Foundation Space; forced movement on it is shorter; a melee miss marks the attacker.",
    "patient_mountain": "Incarnation of the Patient Mountain: Foundation Spaces within 10 feet of it.",
    "sinking_dex": "Sinking Foot Rebuke: Disadvantage on its next Dexterity saving throw.",
    "shield_broken": "Sacrificial Shield: its Shield is broken -- no Shield Bonus (-2 AC) for the rest of the fight.",
    "extensive_defense": "Extensive Defense: every attack against it (and, with Cover Ally, allies within 5 feet) meets Active Defense's +2 AC without a Reaction, until the start of its next turn.",
    "second_answer": "Shield of the Second Answer: the next attack against it meets Active Defense's +2 AC without a Reaction, until the start of the shield-bearer's next turn.",
    "rooted_rim": "Mountain-Rooted Rim: forced movement on it is 10 feet shorter until the start of the shield-bearer's next turn; Advantage on a save against Prone from the attack it was protected from.",
    "glamer_muffled": "Obscuring Glamer (Muffle): Disadvantage to hear it; its heavy armor gives no Stealth Disadvantage.",
    "no_bonus_actions": "It can't take Bonus Actions.",
    "formation_maze_lost": "Formation Maze (failed save): it can't willingly move closer to the keyed ally, Array Eye or Node its owner chose, until the start of the array owner's next turn.",
    "formation_maze_slowed": "Formation Maze (successful save): its next 10 feet of movement inside the array cost 10 more feet.",
    "turbulent": "Its last technique was Turbulent (a Turbulent Field): the GM picks one complication -- visible backlash, noisy activation, reduced range, accidental self-exposure, or minor damage to an unattended nearby object. Regulated Breathing lets it repeat the save; Calm the Wild Meridian suppresses it.",
    "karma_court": "A Court of Cause and Effect stands around its owner: the owner's Record the Deed reaches 120 feet and may be used twice per round; a creature within 30 feet with one of the owner's Debt Imprints takes Psychic damage equal to the owner's Proficiency Bonus when it damages another creature, and one with the owner's Grace Imprint gains that much Temporary HP when it restores HP or takes harm for another (each once per turn). Ends with the owner's Concentration.",
    "storm_friend": "Chosen by a Turbulent Field's owner (Friend in the Storm): the Field does not affect it unless it chooses to be.",
    # Conditions a plug-in owns (combat/ext/*). The table may show them on a sheet or in a
    # lasting area, so the text lives here with the rest rather than in the plug-in.
    "blood_puppet": "A Blood Puppet's puppeteer chooses one command at the start of each of its turns: move it up to half its Speed toward the puppeteer or away from it, make it fall Prone, prevent it from taking Reactions, set its Speed to 0 until the end of that turn, or force it to drop what it holds.",
    "dream_sleep": "It is asleep: Unconscious and Prone, and cannot act. Taking damage wakes it.",
    "calamity_sovereign_incarnation": "Calamity-Sovereign Incarnation (1 minute, 5 CP): for a minute it is a vessel of destructive authority. CP is the pool its Destruction abilities pay their costs from; an augment is an extra Destruction talent that costs CP, and a Destruction Die is the die its Blast Type rolls to work out the blast's damage. Once on each of its turns, when it uses Destructive Blast, one augment costs 1 CP less (to a minimum of 0 CP); its Destructive Blast ignores Half Cover; objects and structures it damages take one more Destruction Die; when a creature within 30 feet damages it, it may use Returning Calamity (a Blast Shape that lets it release Destructive Blast as a Reaction against the creature that damaged it) without spending more CP, once per round.",
}


def mechanics(rule: dict[str, Any]) -> list[str]:
    """The engine's rule for a condition, in words."""
    lines: list[str] = []
    mode = {"ADVANTAGE": "Advantage", "DISADVANTAGE": "Disadvantage"}
    if rule.get("no_actions"):
        lines.append("It can't take actions")
    if rule.get("no_reactions"):
        lines.append("It can't take Reactions")
    if rule.get("speed_zero"):
        lines.append("Its Speed is 0")
    if rule.get("attacks_have") in mode:
        qualifier = ' while it can see the source of its fear' if rule.get('roll_modes_require_source_visible') else ''
        lines.append(f"Its attack rolls have {mode[rule['attacks_have']]}{qualifier}")
    if rule.get("attacks_others_have") in mode:
        lines.append(f"Its attacks against anyone but its grappler have {mode[rule['attacks_others_have']]}")
    if rule.get("attacked_with") in mode:
        lines.append(f"Attack rolls against it have {mode[rule['attacked_with']]}")
    if rule.get("attacked_with_if_attacker_visible") in mode:
        lines.append(f"Attack rolls against it have {mode[rule['attacked_with_if_attacker_visible']]} if it can see the attacker")
    if rule.get("disabled_if_incapacitated_or_speed_zero"):
        lines.append("These benefits are lost if it is Incapacitated or its Speed is 0")
    if rule.get("attacked_within_5ft") in mode:
        lines.append(f"Attacks against it from within 5 feet have {mode[rule['attacked_within_5ft']]}")
    if rule.get("attacked_beyond_5ft") in mode:
        lines.append(f"Attacks against it from farther away have {mode[rule['attacked_beyond_5ft']]}")
    saves = rule.get("save_mode") or {}
    fails = [ability for ability, how in saves.items() if how == "AUTO_FAIL"]
    if fails:
        lines.append(f"It automatically fails {' and '.join(_ability(ability) for ability in fails)} saving throws")
    for ability, how in saves.items():
        if how in mode:
            lines.append(f"{mode[how]} on {_ability(ability)} saving throws")
    if rule.get("cant_hear"):
        lines.append("It can't hear: effects that need hearing don't reach it")
    if rule.get("ends_on_stand_up"):
        lines.append("Standing up ends it and costs half its Speed (round down); it can't stand with Speed 0")
    if rule.get("damage_resistances") == ["ALL"]:
        lines.append("It takes half damage from every damage type")
    elif kinds := [str(kind).title() for kind in (rule.get("damage_resistances") or ())]:
        # A condition that names its resisted kinds, as data rather than as prose (the damage_defenses reader is
        # combat/ext/standard_conditions.condition_defenses): say which, so the pill tells the player what it does.
        lines.append("It takes half damage from " + _listed(kinds) + " damage")
    if "poisoned" in (rule.get("condition_immunities") or ()):
        lines.append("It can't become Poisoned")
    if rule.get("no_cp_regain"):
        lines.append("It can't regain CP (Qi, Stamina, Resonance)")
    if rule.get("no_dash"):
        lines.append("It can't benefit from the Dash action")
    if rule.get("no_teleport"):
        lines.append("It can't teleport, and can't be teleported or summoned")
    if rule.get("no_cp_reactions"):
        lines.append("It can't spend CP on Reactions, Counter effects or defensive sphere effects")
    for skill, how in (rule.get("check_mode") or {}).items():
        if how in mode:
            label = 'ability' if skill == 'ALL' else _ability(skill)
            qualifier = ' while it can see the source of its fear' if rule.get('roll_modes_require_source_visible') else ''
            lines.append(f"{mode[how]} on {label} checks{qualifier}")
    if rule.get("concentration_mode") in mode:
        lines.append(f"{mode[rule['concentration_mode']]} on Concentration saving throws")
    if rule.get("healing_halved"):
        lines.append("Hit Points it regains are halved")
    if rule.get("no_disengage"):
        lines.append("It can't take the Disengage action")
    companions = {"no_temp_hp": "It can't gain Temporary Hit Points", "no_invisible": "It can't turn Invisible"}
    lines.extend(companions[name] for name in rule.get("companions") or [] if name in companions)
    return lines


def _listed(words: list[str]) -> str:
    """A readable list: "Acid and Cold", "Acid, Cold and Fire"."""
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def _ability(code: str) -> str:
    return {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution", "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}.get(code, code)


@functools.lru_cache(maxsize=1)
def extension_readings() -> dict[str, str]:
    """Printed rules for the settings and trackers the extensions put on a creature.

    ``combat/ext/generated_status_text.py`` is the extensions' own record of where each
    extension-made condition comes from: its condition key maps to the printed record that
    explains it. Those keys are not engine rules in ``typed_conditions.json``, so nothing
    here knew about them, leaving the client catalog fallback empty when a row had no
    detail. The owner playtest (MMX85) reported a blank "Golden Core" hover. Reading them
    from the extensions' catalog keeps a single source of truth instead of a second,
    hand-copied list here.

    Use the owner's printed text without hand-written benefit summaries.
    The text is the complete printed section, never cut at a character count: a rule that
    stops mid-sentence is worse for a newcomer than a long one, and the browser truncates a
    native tooltip on its own.  Shared by every surface that shows a condition chip.

    Cached, like ``status_text.printed_rules()`` beside it: the rules text is static for the
    process and this runs on the conditions endpoint.  Callers must treat the result as
    read-only, the way they do with the printed rules.
    """
    from .ext.generated_status_text import SOURCES
    from .status_text import printed_excerpt

    readings: dict[str, str] = {}
    for key, record in SOURCES.items():
        text = printed_excerpt(record, source=True)
        if not text:
            continue
        readings[key] = text
    return readings


_ALL_CONDITIONS: dict[str, Any] = {}
_ALL_CONDITIONS_LOCK = __import__("threading").Lock()


def all_conditions() -> dict[str, dict[str, Any]]:
    """Memoised :func:`_all_conditions` (2026-10-06: the character sheet rebuilt the whole table -- ~240 readings through
    the player-text cleaner -- once per attack button, 27,000 cleanups and most of a 13 s sheet load). The answer depends
    only on the owner-editable rules (``rules()`` returns the same object until its file changes), the READING
    lines and the extensions' cached readings, so it is cached per rules/reading snapshot and handed out as a deep copy."""
    import copy

    return copy.deepcopy(_condition_table())


def condition_reading(key: str) -> tuple[str, str] | None:
    """Read one condition's name and player text without copying the whole catalog.

    Attack-modifier descriptions use this shared read seam. Both returned values
    are immutable strings; mutable mechanics stay private or go through the copied
    all_conditions() API. Rules and handwritten-reading edits use the same cache
    invalidation as the full catalog, including cached missing entries.
    """
    row = _condition_table().get(key)
    return (row["name"], row["reading"]) if row else None


def condition_gist(key: str) -> str:
    """A few words on what a condition does in the fight, for compact ability cards (combat/tooltip_digest.py).

    The engine's own mechanics lines when it applies typed rules, else the first sentence of the reading. Read-only;
    returns a new string and shares the catalog's cache invalidation.
    """
    row = _condition_table().get(key)
    if not row:
        return ""
    lines = [str(line).rstrip(".") for line in row.get("mechanics") or []]
    if lines:
        return "; ".join(lines) + "."
    first = re.match(r"^(.*?[.!?])(?:\s|$)", str(row.get("reading") or ""))
    return (first[1] if first else str(row.get("reading") or "")).strip()


def _condition_table() -> dict[str, dict[str, Any]]:
    """Private snapshot; consumers must copy it or expose only immutable values."""
    source = rules()
    readings = dict(READING)
    reading_key = tuple(readings.items())
    with _ALL_CONDITIONS_LOCK:
        cached = _ALL_CONDITIONS.get("entry")
        if cached is None or cached[0] is not source or cached[2] != reading_key:
            # Built and stored as one (source, table) pair, so a request holding an older rules snapshot can never be
            # handed a table built from a newer one (or the reverse) by a concurrent request.
            cached = (source, _all_conditions_from(source, readings=readings), reading_key)
            _ALL_CONDITIONS["entry"] = cached
            _ALL_CONDITIONS["builds"] = _ALL_CONDITIONS.get("builds", 0) + 1
        return cached[1]


def _all_conditions() -> dict[str, dict[str, Any]]:
    """The uncached build against the current rules (tests compare the cache with it)."""
    return _all_conditions_from(rules())


def _all_conditions_from(source: dict[str, Any], *, readings: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """{condition key: {"name", "reading", "mechanics": [...]}} for the mapped condition sources.

    A row without its own detail needs a resolvable entry here for its hover text.
    Three sources supply them: the engine rules in ``typed_conditions.json``, the short
    ``READING`` lines, and the extensions' own catalog for the settings and trackers they
    create. ``tests/test_condition_tooltips.py`` guards their mapped readings,
    exempting internal markers that do not appear as chips. Dotted catalog keys
    still need a separate client lookup fix when a row has no detail.

    That guarantee is about the keys this function serves, not about every status the
    engine can produce: a condition invented outside all three (an ad-hoc tracker, a
    scratch audit status) still reaches a chip with a blank hover. Those are tracked
    separately rather than papered over with filler text, because inventing a reading for
    a rule nobody has written down is worse than showing nothing.
    """
    readings = READING if readings is None else readings
    table = source.get("conditions") or {}
    aliases = source.get("condition_aliases") or {}
    extension = extension_readings()
    keys = sorted(set(table) | set(readings) | set(aliases) | set(extension))
    out = {}
    for key in keys:
        canonical = aliases.get(key, key)
        rule = dict(table.get(canonical) or {})
        # Colour metadata is not a condition description. These trackers already
        # receive their owning plug-in's row-specific detail; adding an empty
        # catalog entry would falsely advertise a fallback reading for them.
        if set(rule) == {"pill_tone"} and canonical not in readings and canonical not in extension:
            continue
        lines = mechanics(rule)
        # A hand-written READING is already player prose, but the raw evidence
        # sentence the engine falls back on cites the file that typed the
        # condition, so both go through the same cleaner before the table can
        # show either.
        raw_rule = rule.get("_rule") or ""
        reviewed = reviewed_wording(raw_rule) if raw_rule and canonical not in readings else None
        if reviewed is not None:
            text = reviewed
        else:
            source_text = readings.get(canonical) or (plain_reading(raw_rule) if raw_rule else "") or extension.get(canonical, "")
            # An extension entry is a quote of the printed record, so it keeps the
            # printed wording instead of being reflowed as a player card.
            if not readings.get(canonical) and not raw_rule and canonical in extension:
                text = _source_reading(source_text)
            else:
                text = _player_reading(source_text)
        out[key] = {"name": canonical.replace("_", " ").title(), "reading": text, "mechanics": lines,
                    "automated": bool(lines), "rule": rule}
    return out


# What a lasting area shows for a condition it has no plain reading and no engine rule for.
GM_FALLBACK = "The Game Master resolves what this does"

# A parenthetical that names the workshop rather than the fight: a file, a lane, a rule key, a
# collector class or a book. A player hovers a zone to learn what will happen to them, so these go.
_SOURCE_NOTE = re.compile(r"combat/|tools/|\.py\b|gate[1-9]|typed_|reviewed_final|model_v2|Factory|rider|block_|"
                          r"subpath|lane\b|owner 20|Cultivator|Sphere|Compendium|Source Record|Master Ledger|"
                          r"this table|the table|the engine", re.I)
# The same, for a whole sentence: only what talks about the implementation, so a printed word that
# merely shares a name with the workshop ("a Banner Cultivator set its Stance") still reaches a player.
_IMPLEMENTATION = re.compile(r"combat/|tools/|\.py\b|gate[1-9]|typed_|reviewed_final|model_v2|block_|subpath|"
                             r"this table|the table|the engine|adjudicated|no generic|lane\b|owner 20", re.I)
_PARENTHETICAL = re.compile(r"\s*\((?:[^()]|\([^()]*\))*\)")
# The workshop named as the actor of something a fight does. "The table applies the penalties" is
# the owner saying the fight already tracks them, so the sentence is kept with the fight as its
# actor instead of dropped: what it does, to whom, and when is the part a player plans around.
_FIGHT_SUBJECT = re.compile(r"\b(?:this|the) (?:table|engine)\b", re.I)
# What the workshop cannot do, or what it only has for itself, which is the other way a sentence can
# open with it. Either is a fact about the build and not about the creature, so a sentence carrying
# one still goes whole: "the table blocks its own self-teleport abilities" tells a player nothing
# they can act on, and "the table cannot distinguish hands" is a limit they should never be shown.
_WORKSHOP_LIMIT = re.compile(r"\bcannot\b|\bcan\s?not\b|\bhas\s+no\b|\bhave\s+no\b|\blacks?\b|"
                             r"\bno \w+ (?:system|rule|trigger|row|hook)\b|\bdoes\s+not\b|\bdo\s+not\b|"
                             r"\bis\s+not\b|\bare\s+not\b|\bnot (?:modelled|implemented|registered|typed|"
                             r"carried|supported|enforced)\b|\bnothing\s|\bits own\b|\btheir own\b|"
                             r"\bitself\b|\binternal\b", re.I)
# A clause that hands an effect to the Game Master. Dropping it tells the player the fight does
# something it only asks the Game Master to do, so a filtered reading keeps the clause (or, when
# the source only says "GM-adjudicated", says plainly that the Game Master resolves it).
_MANUAL = re.compile(r"\b(?:Game Master|GM)\b")
# The file part of a workshop note, and the workshop's own word for a note it leaves itself. Both
# are bookkeeping: a player cannot act on a path, and "GM reminder" says nothing they can use.
_FILE_REFERENCE = re.compile(r"[\w./-]*\.py\b|combat/[\w./-]*|tools/[\w./-]*|\bgate[1-9]\b|"
                             r"\btyped_[\w]+\b|\bblock_[\w]+\b|\bthis table\b|\bthe table\b|\bthe engine\b", re.I)
_GM_JARGON = re.compile(r"\b(?:reminder|rider|adjudicated|judged|managed)\b", re.I)
# The Game Master's name on its own, and a bare "it": after both are gone, the clause had nothing
# but the name to say, which is what MANUAL_NOTE is for.
_ONLY_THE_NAME = re.compile(r"\b(?:your|the)?\s*game\s+master\b|\bit\b", re.I)
# The workshop's short form of the name, spelled out before a player reads it.
_GAMMASTER = re.compile(r"\bGM\b")
# The restatement for a source that named the Game Master only as a workshop word.
MANUAL_NOTE = "Your Game Master resolves it."
_WORDS = re.compile(r"[a-z0-9']+")
_FILLER = frozenset("it its on the a an has have with from to and of that are be they're their".split())


def _sentence(clause: str) -> str:
    """A clause a player reads as its own sentence, without lowercasing what the GM's name spells.

    The Game Master's name is spelled out rather than left as "GM": the readings a player meets
    use the full name everywhere, so a kept clause that says "the GM" is the one place a newcomer
    has to guess at a workshop abbreviation."""
    clause = _GAMMASTER.sub("Game Master", clause.strip(" .;,"))
    return f"{clause[:1].upper()}{clause[1:]}." if clause else ""


def _plain_manual(clause: str) -> str:
    """One Game Master instruction lifted out of a workshop parenthetical, said plainly.

    The workshop writes its instructions as a dash and then a note to itself ("nothing clears it
    on rest yet -- GM reminder"), so the text after the dash is the instruction. A file path and a
    workshop word go; the Game Master's name is spelled out, like everywhere else a player reads.
    What is left is either a sentence a player can plan around ("Until the Game Master ends it")
    or nothing but the name, and a bare name says nothing useful -- then the module's own
    restatement is used instead.
    """
    tail = re.split(r"\s*-{2,}\s*", clause)[-1]
    text = _FILE_REFERENCE.sub(" ", tail)
    text = _GM_JARGON.sub(" ", text)
    text = _GAMMASTER.sub("Game Master", re.sub(r"\s+", " ", text).strip(" .;,-"))
    sentence = _sentence(text)
    if not sentence:
        return ""
    if re.fullmatch(r"(?:your |the )?Game Master call\.?", sentence, re.I):
        return MANUAL_NOTE  # A bare adjudication label, not a distinct responsibility.
    return MANUAL_NOTE if not _ONLY_THE_NAME.sub("", sentence).strip(" .;,") else sentence


def _lift_manual_notes(text: str, lifted: list[str]) -> str:
    """The text with the workshop's own parts of each parenthetical removed, keeping what a player needs.

    A parenthetical that names a file often also says who still has to do the work, and dropping
    the whole thing would promise a plain reading the fight does not deliver: a condition that says
    it lasts "until a short or long rest (… -- GM reminder)" reads as if the rest ends it, while
    the stored condition waits for the Game Master to clear it. Each such instruction is appended
    to `lifted`, in order, for plain_reading() to keep once.

    A note can also carry the owner's own words beside the citation, and those are not workshop
    bookkeeping: "combat/ext/stone_womb.py ends it early on healing" is the build naming its
    subject, and the predicate after it is how the protection ends, while "Rest Hold,
    combat/ext/hold_still.py" is the ability that explains the rule. The shared player cleaner
    already judges a bracket a part at a time (player_text.keep_owner_words_in_note), so it answers
    here instead of a second set of rules that would drift. A clause that handed a duty to the Game
    Master is not offered to it, so a lifted instruction cannot also survive inside a rule.

    What comes back is dropped whole when it still names the workshop: "Sphere of Sand" or "the
    table" is provenance a player cannot act on, and half of a note is worse than none.
    """
    def drop(match: re.Match[str]) -> str:
        note = match.group(0)
        if not _SOURCE_NOTE.search(note):
            return note
        kept: list[str] = []
        for clause in note.strip().strip("()").split(";"):
            if _MANUAL.search(clause):
                lifted.append(_plain_manual(clause))
                continue
            kept.append(clause)
        if not kept:
            return ""
        kept_note = keep_owner_words_in_note(f" ({'; '.join(kept)})")
        return "" if _SOURCE_NOTE.search(kept_note) else kept_note

    return _PARENTHETICAL.sub(drop, text or "")


def plain_reading(text: str) -> str:
    """A reading with the workshop's own bookkeeping removed, for a surface nobody can ask about:
    a parenthetical naming a file, a lane or a collector class is dropped, and a sentence that says
    what the table or the engine does or does not do loses that clause -- and, when the clause opens
    the sentence, the whole sentence, so no half of it is left standing. What the fight actually
    does arrives separately, through mechanics().

    Who resolves an effect is never workshop bookkeeping, though: a clause that gives a decision,
    damage or an expiry to the Game Master is kept, so a reading never promises a roll the fight
    only asks the Game Master to make. That holds inside a parenthetical too: the instruction is
    lifted out before the note around it is judged (_lift_manual_notes). Nor is a rule printed
    beside a citation: the note is asked what the owner wrote rather than dropped whole, so how a
    protection ends survives the file that implements it."""
    lifted: list[str] = []
    stripped = _lift_manual_notes(text, lifted)
    kept: list[str] = []

    def manual_key(clause: str) -> str:
        # Deduplicate wording, not the actor: an expiry and a damage roll are different duties.
        normalized = _sentence(clause).casefold().rstrip(".")
        return re.sub(r"\b(?:your|the) game master\b", "game master", normalized)

    def keep_manual(clause: str) -> None:
        instruction = _sentence(clause)
        said = {manual_key(part) for text in kept
                for part in re.split(r"(?<=\.)\s+|;", text) if _MANUAL.search(part)}
        if instruction and manual_key(instruction) not in said:
            kept.append(instruction)

    for sentence in re.split(r"(?<=\.)\s+", re.sub(r"\s+", " ", stripped)):
        sentence = sentence.strip()
        if not sentence:
            continue
        marker = _IMPLEMENTATION.search(sentence)
        if marker is None:
            kept.append(sentence)
            continue
        if not sentence[:marker.start()].strip(" ,;:"):
            # The whole sentence is about the implementation; keep only what it says the Game
            # Master still resolves, which is the part a player acts on.
            for clause in sentence.split(";"):
                if _MANUAL.search(clause):
                    keep_manual(clause)
            # Unless it says what the fight itself already does, which is a fact about the
            # creature, not about the build: "the table applies the penalties" told a player the
            # fight tracks Exhaustion for them, and dropping it left them to work that out. A
            # clause that handed work to the Game Master is left out, because the loop above
            # already restated it and saying it twice would be worse than not saying it.
            restated = " ".join(clause.strip() for clause in sentence.split(";")
                                if not _MANUAL.search(clause))
            if _FIGHT_SUBJECT.search(restated) and not _WORKSHOP_LIMIT.search(restated):
                kept.append(_sentence(_FIGHT_SUBJECT.sub("the fight", restated)))
            continue
        cut = sentence.find(";", marker.end())
        part = re.sub(r"[,;:]?\s*(?:which|and)?\s*$", "", sentence[:marker.start() if cut < 0 else cut]).strip()
        # The cut clause may be the only thing that said a Game Master still resolves the effect.
        note = bool(_MANUAL.search(sentence[cut + 1 if cut >= 0 else marker.start():]))
        # A clause cut for naming the build can still be a rule whose subject was that file, which
        # is what player_text.plain() rescues before it drops the clause. Without the rescue
        # "…; combat/ext/silken_whip.py offers its attack while it stands" lost the whole rule.
        rescued = rule_after_a_citation(sentence[marker.start():])
        if note or rescued:
            # Whatever survived the cut is its own sentence: the source only said "GM-adjudicated",
            # or a rule now follows the citation that was cut away with the author's ";".
            part = _sentence(part)
        if part:
            kept.append(part)
        if rescued:
            kept.append(_sentence(rescued))
        if note:
            keep_manual(MANUAL_NOTE)
    for instruction in lifted:
        keep_manual(instruction)
    # A generic workshop reminder adds nothing once a specific responsibility is stated.
    generic = manual_key(MANUAL_NOTE)
    if any(_MANUAL.search(part) and manual_key(part) != generic for part in kept):
        kept = [part for part in kept if manual_key(part) != generic]
    return " ".join(part for part in (part.strip() for part in kept) if part).strip()


def _said(line: str) -> set[str]:
    return {word for word in _WORDS.findall(line.casefold()) if word not in _FILLER}


def _together(gloss: str, lines: list[str]) -> str:
    """The reading first, then what the engine applies, as whole sentences and without saying it twice."""
    out = [gloss] if gloss else []
    said = _said(gloss)
    said_text = gloss.casefold()
    for line in lines:
        flat = line.casefold().rstrip(".")
        head = re.split(r"[:,]", line, 1)[0].casefold().rstrip(".")
        words = _said(line)
        if flat in said_text or (head and head in said_text) or (words and words <= said):
            continue  # the reading already says this one
        out.append(line)
        said |= words
        said_text += f" {flat}"
    return " ".join(f"{part.rstrip(' ;:,')}{'' if part.rstrip(' ;:,')[-1:] in '.!?' else '.'}" for part in out)


def zone_readings() -> dict[str, str]:
    """{condition key: what a lasting area says about it} for every condition the table may show.

    Built from the same reading and the same engine mechanics the sheet hover uses, so a player
    reading an area and a player reading a condition pill are told the same thing. A condition with
    neither a plain reading nor an engine rule says the Game Master resolves it."""
    out: dict[str, str] = {}
    for key, row in all_conditions().items():
        out[key] = _together(plain_reading(row["reading"]), row["mechanics"]) or GM_FALLBACK
    return out
