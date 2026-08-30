"""
Author the rule sets, objective definitions and reward tables the nineteen
objective modes are built from, and wire them onto the paired UCDGameModeData
and Deploy tile.

Companion to author_game_modes.py, which owns what a mode *is* - objective
mechanic, scale tier, composition, team and squad counts, and the tile names each
Part ships it under. This script owns what is layered on top: the rules, what the
player is told to do, and what it pays.

It imports that script's ROSTER rather than restating it, so a mode cannot end up
with two different scale tiers depending on which script ran last, and it creates
any UCDGameModeData that is missing - a rule set nothing references never reaches
a player. It also calls author_game_modes.apply() implicitly by sharing its
UI_MODE_DIR: tiles are a single global roster (one UCDGameModeUIEntry per
mechanic, PartDisplayNameOverrides carrying each Part's themed name), not
duplicated per Part plugin. That per-Part-plugin arrangement was tried briefly
(the theater plugins' own Content/UI/GameModeEntries/ folders and this script's
TILE_DIRS both pointed there for a while) and reverted 2026-08-20: SelectionTag
is the enumeration key every tag-driven list queries on, so two Parts each
authoring their own tile under the same UI.Selection.GameMode.* tag would enumerate
as duplicate tiles with nothing to tell them apart, and UCDGameModeUIEntry's own
IsDataValid never required a PartTag the way UCDMapUIEntry's does - the class was
built for one shared tile per mechanic from the start. See the Theater I plugin's
README ("Asset discovery") for the map/range/part tiles, which genuinely are
per-Part and stay that way.

Everything it writes lives in the GameModes plugin:

    /GameModes/Rules/DA_Rules_*           UCDGameModeRuleSet
    /GameModes/Objectives/DA_Objective_*  UCDObjectiveDefinition
    /GameModes/Rewards/DA_Rewards_*       UCDMatchRewardSet
    /GameModes/DataAssets/DA_GameMode_*   UCDGameModeData (created if missing)

There are twelve rule sets and seven reward tables across nineteen modes, not
nineteen of each: a rule set and a payout curve are shared by every mode with
the same shape, which is the whole reason they are separate assets from the mode
data.

RESTART THE EDITOR BEFORE RUNNING THIS: the gameplay tag table is read at
startup, so an editor that was already open when Config/Tags/GameModes.ini
landed does not know GameMode.ScoreEvent.* or GameMode.Objective.*. Every tag
below would then resolve to an invalid tag. This script reports that rather than
writing a blank tag onto an asset, so a forgotten restart shows up as a wall of
errors instead of a roster of unaddressable objectives.

Run from the Unreal Editor Python console:
    import author_game_mode_rules
    author_game_mode_rules.apply(dry_run=True)
    author_game_mode_rules.apply(dry_run=False)

Or headless:
    UnrealEditor-Cmd.exe <project> -run=pythonscript
        -script="import author_game_mode_rules; author_game_mode_rules.apply(False)"
"""

import unreal

RULES_DIR = "/GameModes/Rules"
OBJECTIVES_DIR = "/GameModes/Objectives"
REWARDS_DIR = "/GameModes/Rewards"
MODE_DATA_DIR = "/GameModes/DataAssets"

# The global Deploy tile roster - see the module docstring for why this is one
# shared directory rather than a per-Part-plugin one. Wiring them is the last
# step: a rule set nothing references is a rule set that never reaches a player.
TILE_DIRS = ["/Game/CollateralDamage/UI/Data/GameModes"]


# ---------------------------------------------------------------------------
# Rule sets
# ---------------------------------------------------------------------------
# Only fields that differ from the C++ class defaults are listed. The defaults
# are the standard PvP rules on purpose (see UCDGameModeRuleSet's class comment),
# so an omission here means "standard", never "unset".
#
#   combat / respawn / loadout / flow   nested struct overrides
#   ammo                                nested inside loadout
#   summary                             the lines the Deploy tile prints verbatim

RULE_SETS = [
    {
        "asset": "DA_Rules_StandardPvP",
        "display": "STANDARD",
        "summary": ["FRIENDLY FIRE OFF", "5 SECOND RESPAWN", "CUSTOM LOADOUTS"],
        "combat": {},
        "respawn": {"policy": "TIMED", "allow_squad_spawn": True},
        "loadout": {},
        "flow": {"minimum_players_to_start": 4, "auto_balance_teams": True},
    },
    {
        "asset": "DA_Rules_ObjectiveWarfare",
        "display": "OBJECTIVE",
        "summary": ["FRIENDLY FIRE 50%", "SPAWN ON HELD GROUND", "OVERTIME ON A TIE"],
        # Ground held is worth something only if taking it from a teammate's line
        # of fire costs you. Half damage is the compromise the mode is tuned at.
        "combat": {"friendly_fire": "ENABLED", "friendly_fire_damage_scalar": 0.5},
        "respawn": {"policy": "TIMED", "allow_squad_spawn": True, "allow_capture_point_spawn": True},
        "loadout": {},
        "flow": {
            "minimum_players_to_start": 8,
            "allow_overtime": True,
            "overtime_duration_seconds": 120.0,
            "tiebreaker": "SUDDEN_DEATH",
        },
    },
    {
        "asset": "DA_Rules_AsymmetricAssault",
        "display": "ASSAULT",
        "summary": ["FIXED SIDES", "NO SPAWNING ON THE FRONT", "ATTACKERS ON A TICKET POOL"],
        "combat": {"friendly_fire": "ENABLED", "friendly_fire_damage_scalar": 0.5},
        # A sector is a frontline the attacker has to walk to. Spawning on it
        # would collapse the whole push-and-hold tension the mode is built on.
        "respawn": {"policy": "WAVE", "wave_interval_seconds": 15.0, "allow_capture_point_spawn": False},
        "loadout": {},
        "flow": {"minimum_players_to_start": 8, "allow_team_switch": False, "auto_balance_teams": False},
    },
    {
        "asset": "DA_Rules_LargeScale",
        "display": "COMBINED ARMS",
        "summary": ["FRIENDLY FIRE 50%", "WAVE REINFORCEMENTS", "VEHICLES AND ARTILLERY"],
        "combat": {"friendly_fire": "ENABLED", "friendly_fire_damage_scalar": 0.5},
        # At 64v64 a trickle of individual respawns is indistinguishable from
        # noise. Waves are what make a push readable as a push.
        "respawn": {"policy": "WAVE", "wave_interval_seconds": 20.0, "allow_squad_spawn": True,
                    "allow_capture_point_spawn": True},
        "loadout": {},
        "flow": {"minimum_players_to_start": 16, "mercy_score_differential": 400,
                 "mercy_earliest_fraction_elapsed": 0.6},
    },
    {
        "asset": "DA_Rules_Arcade",
        "display": "ARCADE",
        "summary": ["FRIENDLY FIRE OFF", "FAST RESPAWN", "NO MERCY RULE"],
        "combat": {"friendly_fire": "DISABLED"},
        "respawn": {"policy": "TIMED", "respawn_delay_override_seconds": 2.0},
        "loadout": {},
        "flow": {"minimum_players_to_start": 2, "tiebreaker": "MOST_ELIMINATIONS"},
    },
    {
        "asset": "DA_Rules_RoundElimination",
        "display": "ELIMINATION",
        "summary": ["ONE LIFE PER ROUND", "NO RESPAWNS", "SPECTATE UNTIL THE ROUND ENDS"],
        "combat": {"friendly_fire": "ENABLED", "friendly_fire_damage_scalar": 1.0},
        "respawn": {"policy": "ELIMINATION", "allow_spectate_after_death": True},
        "loadout": {},
        # No join-in-progress: a player dropped into a live elimination round
        # arrives already dead, which reads as a bug however it is explained.
        "flow": {"minimum_players_to_start": 2, "allow_join_in_progress": False,
                 "allow_team_switch": False, "tiebreaker": "SUDDEN_DEATH"},
    },
    {
        "asset": "DA_Rules_Marksman",
        "display": "MARKSMAN",
        "summary": ["BOLT ACTION ONLY", "ONE SHOT, ONE KILL", "ONE LIFE PER ROUND"],
        "combat": {"friendly_fire": "ENABLED", "friendly_fire_damage_scalar": 1.0,
                   "headshots_always_lethal": True},
        "respawn": {"policy": "ELIMINATION", "allow_spectate_after_death": True},
        "loadout": {"allowed_weapon_class_tags": ["Weapon.Class.Rifle", "Weapon.Class.Pistol"],
                    "allow_attachments": True},
        "flow": {"minimum_players_to_start": 2, "allow_join_in_progress": False,
                 "allow_team_switch": False, "tiebreaker": "SUDDEN_DEATH"},
    },
    {
        "asset": "DA_Rules_TrenchClose",
        "display": "TRENCH",
        "summary": ["MELEE, SHOTGUNS AND SIDEARMS", "HIGH LETHALITY", "ONE LIFE PER ROUND"],
        # A trench network is too tight to swing a rifle in. The restriction is an
        # allow-list, so a weapon class added later stays out until someone says
        # otherwise.
        #
        # Respawn was TIMED at 3s here, which read as "fast respawn" but is
        # incoherent against a round-based mode (RoundsToWin=5 in MODE_TUNING
        # below): with players continuously respawning, no round ever runs out
        # of a side to send, and UCDEliminationObjectiveComponent's round-life
        # tracking never sees a bucket empty out. Elimination is what the other
        # three round-based rule sets (RoundElimination, Marksman,
        # OneInTheChamber) all use for exactly this reason.
        "combat": {"friendly_fire": "ENABLED", "friendly_fire_damage_scalar": 1.0,
                   "outgoing_damage_multiplier": 1.25},
        "respawn": {"policy": "ELIMINATION", "allow_spectate_after_death": True},
        "loadout": {"allowed_weapon_class_tags": [
            "Weapon.Class.Melee", "Weapon.Class.Shotgun", "Weapon.Class.Pistol"]},
        "flow": {"minimum_players_to_start": 2, "allow_join_in_progress": False,
                 "tiebreaker": "MOST_ELIMINATIONS"},
    },
    {
        "asset": "DA_Rules_OneInTheChamber",
        "display": "ONE IN THE CHAMBER",
        "summary": ["ONE ROUND IN THE CHAMBER", "A KILL BUYS THE NEXT", "BAYONET WHEN EMPTY"],
        "combat": {"friendly_fire": "DISABLED", "headshots_always_lethal": True},
        "respawn": {"policy": "ELIMINATION", "allow_spectate_after_death": True},
        "loadout": {
            "allow_custom_loadouts": False,
            "allowed_weapon_class_tags": ["Weapon.Class.Pistol", "Weapon.Class.Melee"],
            "ammo": {"override_starting_ammo": True, "starting_rounds_in_magazine": 1,
                     "starting_reserve_rounds": 0, "rounds_refunded_per_elimination": 1,
                     "allow_ammo_pickups": False},
        },
        "flow": {"minimum_players_to_start": 2, "allow_join_in_progress": False,
                 "tiebreaker": "SUDDEN_DEATH"},
    },
    {
        "asset": "DA_Rules_WeaponLadder",
        "display": "LADDER",
        "summary": ["THE MODE PICKS YOUR WEAPON", "EVERY KILL PROMOTES YOU", "NO CUSTOM LOADOUTS"],
        "combat": {"friendly_fire": "DISABLED"},
        "respawn": {"policy": "TIMED", "respawn_delay_override_seconds": 2.0},
        "loadout": {"allow_custom_loadouts": False, "allow_attachments": False},
        "flow": {"minimum_players_to_start": 2, "tiebreaker": "MOST_ELIMINATIONS"},
    },
    {
        "asset": "DA_Rules_BattleRoyale",
        "display": "SCRAMBLE",
        "summary": ["DROP WITH NOTHING", "NO RESPAWNS", "NO JOINING IN PROGRESS"],
        "combat": {"friendly_fire": "REFLECTED", "friendly_fire_damage_scalar": 1.0},
        "respawn": {"policy": "ELIMINATION", "allow_squad_spawn": False,
                    "allow_spectate_after_death": True},
        "loadout": {"allow_custom_loadouts": False},
        "flow": {"minimum_players_to_start": 20, "allow_join_in_progress": False,
                 "auto_balance_teams": False, "allow_team_switch": False},
    },
    {
        "asset": "DA_Rules_CooperativePvE",
        "display": "COOPERATIVE",
        "summary": ["NO FRIENDLY FIRE", "NO SELF DAMAGE", "REVIVE YOUR SECTION"],
        # Co-op is the one place a satchel charge should not punish the player who
        # threw it for forgetting to walk away.
        "combat": {"friendly_fire": "DISABLED", "allow_self_damage": False},
        "respawn": {"policy": "WAVE", "wave_interval_seconds": 30.0, "allow_squad_spawn": True},
        "loadout": {},
        "flow": {"minimum_players_to_start": 1, "auto_balance_teams": False,
                 "allow_team_switch": False},
    },
    {
        "asset": "DA_Rules_TrainingSandbox",
        "display": "SANDBOX",
        "summary": ["NO WIN CONDITION", "NO CLOCK", "INSTANT RESPAWN"],
        "combat": {"friendly_fire": "DISABLED", "allow_self_damage": False,
                   "fall_damage_multiplier": 0.0},
        "respawn": {"policy": "TIMED", "respawn_delay_override_seconds": 0.0},
        "loadout": {},
        "flow": {"minimum_players_to_start": 1, "auto_balance_teams": False},
    },
]


# ---------------------------------------------------------------------------
# Objective definitions
# ---------------------------------------------------------------------------
#   component   UCDObjectiveComponent subclass that drives it, or None for an
#               objective the level or mission script completes
#   completion  ECDObjectiveCompletion value name
#   target      TargetCount. 0 means "all of them" or "unused" per the shape
#   required    bRequiredForVictory

OBJECTIVES = [
    {
        "asset": "DA_Objective_Eliminate",
        "tag": "GameMode.Objective.Eliminate",
        "title": "OUT-KILL THEM",
        "hud": "ELIMINATE THE ENEMY",
        "briefing": "No ground to hold and nothing to carry. The side with the higher count when "
                    "the clock stops takes it.",
        "role": "PRIMARY",
        "component": "CDEliminationObjectiveComponent",
        "completion": "REACH_SCORE_TARGET",
        "target": 100,
        "required": True,
        "score_event": "GameMode.ScoreEvent.Elimination",
        "marker": False,
    },
    {
        "asset": "DA_Objective_HoldSectors",
        "tag": "GameMode.Objective.HoldSectors",
        "title": "HOLD THE SECTORS",
        "hud": "CAPTURE AND HOLD",
        "briefing": "The meter only moves while you are standing on ground you have taken. "
                    "Taking it is the cheap part.",
        "role": "PRIMARY",
        "component": "CDCapturePointObjectiveComponent",
        "completion": "REACH_SCORE_TARGET",
        "target": 500,
        "required": True,
        "score_event": "GameMode.ScoreEvent.HoldTick",
        "marker": True,
    },
    {
        "asset": "DA_Objective_BreakSectors",
        "tag": "GameMode.Objective.BreakSectors",
        "title": "BREAK THEIR LINE",
        "hud": "HOLD THE MAJORITY",
        "briefing": "Hold more sectors than they do and the meter fills. When it fills, one of "
                    "their sectors is gone for the rest of the match.",
        "role": "PRIMARY",
        "component": "CDCapturePointObjectiveComponent",
        "completion": "CAPTURE_SECTORS",
        "target": 3,
        "required": True,
        "score_event": "GameMode.ScoreEvent.PointEliminated",
        "marker": True,
    },
    {
        "asset": "DA_Objective_HoldRotatingPoint",
        "tag": "GameMode.Objective.HoldRotatingPoint",
        "title": "HOLD THE HILL",
        "hud": "HOLD THE ACTIVE POINT",
        "briefing": "One point, four squads, and ninety seconds before it moves somewhere else.",
        "role": "PRIMARY",
        "component": "CDCapturePointObjectiveComponent",
        "completion": "HOLD_POSITION",
        "target": 300,
        "required": True,
        "score_event": "GameMode.ScoreEvent.HoldTick",
        "marker": True,
    },
    {
        "asset": "DA_Objective_AdvanceFrontline",
        "tag": "GameMode.Objective.AdvanceFrontline",
        "title": "TAKE THE SECTORS",
        "hud": "ADVANCE THE FRONT",
        "briefing": "Every sector in order, out of a shared pool of lives. Taking one buys the "
                    "pool back up; stalling in front of one bleeds it dry.",
        "role": "PRIMARY",
        "component": "CDAsymmetricWarfareObjectiveComponent",
        "completion": "CAPTURE_SECTORS",
        "target": 0,
        "required": True,
        "score_event": "GameMode.ScoreEvent.SectorTaken",
        "marker": True,
    },
    {
        "asset": "DA_Objective_HoldFrontline",
        "tag": "GameMode.Objective.HoldFrontline",
        "title": "MAKE THEM PAY",
        "hud": "HOLD THE FRONT",
        "briefing": "You respawn and they do not. Every yard they take should cost them more "
                    "than they can afford.",
        "role": "SECONDARY",
        "component": None,
        "completion": "NONE",
        "target": 0,
        "required": False,
        "score_event": "GameMode.ScoreEvent.Defend",
        "marker": True,
    },
    {
        "asset": "DA_Objective_CaptureFlags",
        "tag": "GameMode.Objective.CaptureFlags",
        "title": "TAKE THEIR COLOURS",
        "hud": "CAPTURE THE FLAG",
        "briefing": "Into their base, out with their flag, and the whole way home again - while "
                    "yours is still where you left it.",
        "role": "PRIMARY",
        "component": None,
        "completion": "RETURN_FLAGS",
        "target": 3,
        "required": True,
        "score_event": "GameMode.ScoreEvent.FlagCaptured",
        "marker": True,
    },
    {
        "asset": "DA_Objective_ClimbWeaponLadder",
        "tag": "GameMode.Objective.ClimbWeaponLadder",
        "title": "WORK THE LADDER",
        "hud": "FINISH THE LADDER",
        "briefing": "Every kill hands you the next weapon on the rack. Finish the rack first.",
        "role": "PRIMARY",
        "component": "CDEliminationObjectiveComponent",
        "completion": "COMPLETE_WEAPON_LADDER",
        "target": 12,
        "required": True,
        "score_event": "GameMode.ScoreEvent.LadderAdvance",
        "marker": False,
    },
    {
        "asset": "DA_Objective_WinRounds",
        "tag": "GameMode.Objective.WinRounds",
        "title": "TAKE THE ROUNDS",
        "hud": "WIN THE ROUND",
        "briefing": "One life each. The round ends when one side has nobody left to send.",
        "role": "PRIMARY",
        "component": "CDEliminationObjectiveComponent",
        "completion": "WIN_ROUNDS",
        "target": 7,
        "required": True,
        "score_event": "GameMode.ScoreEvent.RoundWon",
        "marker": False,
    },
    {
        "asset": "DA_Objective_LastStanding",
        "tag": "GameMode.Objective.LastStanding",
        "title": "BE THE LAST",
        "hud": "SURVIVE",
        "briefing": "A hundred in and one out. Scavenge whatever you can find before the ring "
                    "makes the decision for you.",
        "role": "PRIMARY",
        # Was CDEliminationObjectiveComponent, which only ever counts kills and
        # has no notion of "who is still alive" - LastStanding is explicitly
        # excluded from the generic counted-progress evaluator for exactly
        # that reason (see UCDObjectiveDefinition::IsSatisfied). This is the
        # dedicated component built for the shape, matching how Asymmetric
        # Warfare gets its own rather than being forced into Elimination's.
        "component": "CDLastStandingObjectiveComponent",
        "completion": "LAST_STANDING",
        "target": 0,
        "required": True,
        "score_event": "GameMode.ScoreEvent.LastStanding",
        "marker": False,
    },
    {
        "asset": "DA_Objective_SurviveWaves",
        "tag": "GameMode.Objective.SurviveWaves",
        "title": "HOLD THE GROUND",
        "hud": "SURVIVE THE WAVE",
        "briefing": "They come in waves and each one is worse than the last. Hold what you have "
                    "and keep each other upright.",
        "role": "PRIMARY",
        "component": "CDEliminationObjectiveComponent",
        "completion": "SURVIVE_WAVES",
        "target": 10,
        "required": True,
        "score_event": "GameMode.ScoreEvent.WaveCleared",
        "marker": False,
    },
    {
        "asset": "DA_Objective_Extract",
        "tag": "GameMode.Objective.Extract",
        "title": "GET OUT ALIVE",
        "hud": "REACH EXTRACTION",
        "briefing": "Surviving is not the same as winning. Make the extraction point with the "
                    "section you came in with.",
        # Not what the match is scored on, but the match is not won without it -
        # exactly the case bRequiredForVictory exists to express independently of
        # the Primary/Secondary role.
        "role": "SECONDARY",
        "component": None,
        "completion": "REACH_EXTRACTION",
        "target": 1,
        "required": True,
        "score_event": "GameMode.ScoreEvent.Extraction",
        "marker": True,
    },
    {
        "asset": "DA_Objective_CompleteMission",
        "tag": "GameMode.Objective.CompleteMission",
        "title": "COMPLETE THE OPERATION",
        "hud": "FOLLOW THE ORDERS",
        "briefing": "A real operation nobody wrote down. Small section, narrow objective, no "
                    "reinforcements coming.",
        "role": "PRIMARY",
        "component": None,
        "completion": "NONE",
        "target": 0,
        # Mission script marks the beats. Left non-required so an unfinished
        # scripted stage cannot deadlock the match on its own.
        "required": False,
        "score_event": "GameMode.ScoreEvent.MissionObjective",
        "marker": True,
    },
    {
        "asset": "DA_Objective_Practice",
        "tag": "GameMode.Objective.Practice",
        "title": "NOTHING TO WIN",
        "hud": "TRAINING",
        "briefing": "Weapons, movement and armour, with nothing shooting back that you did not "
                    "ask for. There is no score here and there is no clock.",
        "role": "PRIMARY",
        "component": None,
        "completion": "NONE",
        "target": 0,
        "required": False,
        "score_event": "",
        "marker": False,
    },
]


# ---------------------------------------------------------------------------
# Reward tables
# ---------------------------------------------------------------------------
#   awards      list of (score event tag, label, score, xp, currency)
#   outcome     FCDMatchOutcomeRewards field overrides
#   placement   list of (min, max, label, xp, currency)
#   bonuses     list of (score event tag, label, required count, xp, currency)
#
# Score and XP move independently on purpose: a capture swings the match far
# harder than a kill and pays roughly the same, which is what stops an objective
# mode being played as a deathmatch with extra steps.

REWARDS = [
    {
        "asset": "DA_Rewards_Standard",
        "display": "STANDARD PAYOUT",
        "awards": [
            ("GameMode.ScoreEvent.Elimination", "KILL", 1, 100, 5),
            ("GameMode.ScoreEvent.Elimination.Headshot", "HEADSHOT", 1, 150, 8),
            ("GameMode.ScoreEvent.Elimination.Melee", "CLOSE WORK", 1, 175, 10),
            ("GameMode.ScoreEvent.Elimination.LongRange", "LONG SHOT", 1, 175, 10),
            ("GameMode.ScoreEvent.Assist", "ASSIST", 0, 50, 2),
            ("GameMode.ScoreEvent.Spot", "SPOTTED", 0, 20, 1),
        ],
        "outcome": {
            "victory_experience": 1500, "victory_currency": 150,
            "defeat_experience": 600, "defeat_currency": 60,
            "draw_experience": 900, "draw_currency": 90,
            "experience_per_minute_played": 40, "max_time_played_experience": 800,
        },
        "placement": [],
        "bonuses": [
            ("GameMode.ScoreEvent.Elimination", "MARKSMAN - 15 KILLS", 15, 400, 40),
            ("GameMode.ScoreEvent.Elimination.Headshot", "PRECISION - 5 HEADSHOTS", 5, 300, 30),
        ],
        "multiplier": 1.0,
    },
    {
        "asset": "DA_Rewards_Objective",
        "display": "OBJECTIVE PAYOUT",
        "awards": [
            ("GameMode.ScoreEvent.Elimination", "KILL", 1, 80, 4),
            ("GameMode.ScoreEvent.Elimination.Headshot", "HEADSHOT", 1, 120, 6),
            ("GameMode.ScoreEvent.Assist", "ASSIST", 0, 40, 2),
            ("GameMode.ScoreEvent.Capture", "CAPTURE", 50, 250, 15),
            ("GameMode.ScoreEvent.Neutralize", "NEUTRALISED", 25, 125, 8),
            ("GameMode.ScoreEvent.Defend", "DEFENCE", 10, 120, 6),
            ("GameMode.ScoreEvent.HoldTick", "GROUND HELD", 1, 2, 0),
            ("GameMode.ScoreEvent.PointEliminated", "SECTOR BROKEN", 0, 500, 40),
            ("GameMode.ScoreEvent.Spot", "SPOTTED", 0, 25, 1),
        ],
        "outcome": {
            "victory_experience": 2000, "victory_currency": 200,
            "defeat_experience": 900, "defeat_currency": 90,
            "draw_experience": 1300, "draw_currency": 130,
            "experience_per_minute_played": 50, "max_time_played_experience": 1200,
        },
        "placement": [],
        "bonuses": [
            ("GameMode.ScoreEvent.Capture", "SPEARHEAD - 5 CAPTURES", 5, 500, 50),
            ("GameMode.ScoreEvent.Defend", "BULWARK - 10 DEFENCES", 10, 400, 40),
        ],
        "multiplier": 1.0,
    },
    {
        "asset": "DA_Rewards_LargeScale",
        "display": "COMBINED ARMS PAYOUT",
        "awards": [
            ("GameMode.ScoreEvent.Elimination", "KILL", 1, 80, 4),
            ("GameMode.ScoreEvent.Elimination.Headshot", "HEADSHOT", 1, 120, 6),
            ("GameMode.ScoreEvent.Elimination.Vehicle", "ARMOUR KILL", 5, 350, 25),
            ("GameMode.ScoreEvent.Elimination.Penetration", "THROUGH COVER", 1, 160, 9),
            ("GameMode.ScoreEvent.Assist", "ASSIST", 0, 40, 2),
            ("GameMode.ScoreEvent.Capture", "CAPTURE", 50, 250, 15),
            ("GameMode.ScoreEvent.Defend", "DEFENCE", 10, 120, 6),
            ("GameMode.ScoreEvent.HoldTick", "GROUND HELD", 1, 2, 0),
            ("GameMode.ScoreEvent.Revive", "STRETCHER BEARER", 0, 150, 10),
            ("GameMode.ScoreEvent.Resupply", "RESUPPLY", 0, 60, 3),
            ("GameMode.ScoreEvent.Spot", "SPOTTED", 0, 25, 1),
        ],
        # A 45-minute Mukden-scale match is not worth what a four-minute Duel is,
        # and the per-minute rate plus the multiplier is where that difference is
        # expressed - not by inflating every award row.
        "outcome": {
            "victory_experience": 2500, "victory_currency": 250,
            "defeat_experience": 1200, "defeat_currency": 120,
            "draw_experience": 1700, "draw_currency": 170,
            "experience_per_minute_played": 60, "max_time_played_experience": 2400,
        },
        "placement": [],
        "bonuses": [
            ("GameMode.ScoreEvent.Capture", "SPEARHEAD - 5 CAPTURES", 5, 500, 50),
            ("GameMode.ScoreEvent.Revive", "SECTION MEDIC - 8 REVIVES", 8, 450, 45),
        ],
        "multiplier": 1.15,
    },
    {
        "asset": "DA_Rewards_Arcade",
        "display": "ARCADE PAYOUT",
        "awards": [
            ("GameMode.ScoreEvent.Elimination", "KILL", 1, 60, 3),
            ("GameMode.ScoreEvent.Elimination.Headshot", "HEADSHOT", 1, 90, 5),
            ("GameMode.ScoreEvent.Elimination.Melee", "CLOSE WORK", 1, 120, 7),
            ("GameMode.ScoreEvent.RoundWon", "ROUND", 0, 250, 20),
            ("GameMode.ScoreEvent.LadderAdvance", "PROMOTED", 0, 80, 4),
        ],
        # A short match pays less per match and more per minute; the whole point
        # of an arcade playlist is that it is over quickly.
        "outcome": {
            "victory_experience": 700, "victory_currency": 70,
            "defeat_experience": 300, "defeat_currency": 30,
            "draw_experience": 450, "draw_currency": 45,
            "experience_per_minute_played": 55, "max_time_played_experience": 500,
        },
        "placement": [],
        "bonuses": [
            ("GameMode.ScoreEvent.Elimination", "RAMPAGE - 20 KILLS", 20, 350, 35),
        ],
        "multiplier": 1.0,
    },
    {
        "asset": "DA_Rewards_Elimination",
        "display": "ELIMINATION PAYOUT",
        "awards": [
            ("GameMode.ScoreEvent.Elimination", "KILL", 1, 120, 7),
            ("GameMode.ScoreEvent.Elimination.Headshot", "HEADSHOT", 1, 160, 10),
            ("GameMode.ScoreEvent.Elimination.LongRange", "LONG SHOT", 1, 200, 12),
            ("GameMode.ScoreEvent.Elimination.Melee", "CLOSE WORK", 1, 200, 12),
            ("GameMode.ScoreEvent.RoundWon", "ROUND", 0, 300, 25),
        ],
        "outcome": {
            "victory_experience": 900, "victory_currency": 90,
            "defeat_experience": 400, "defeat_currency": 40,
            "draw_experience": 600, "draw_currency": 60,
            "experience_per_minute_played": 45, "max_time_played_experience": 600,
        },
        "placement": [],
        "bonuses": [
            ("GameMode.ScoreEvent.RoundWon", "UNBROKEN - 5 ROUNDS", 5, 400, 40),
        ],
        "multiplier": 1.0,
    },
    {
        "asset": "DA_Rewards_BattleRoyale",
        "display": "SCRAMBLE PAYOUT",
        "awards": [
            ("GameMode.ScoreEvent.Elimination", "KILL", 1, 150, 10),
            ("GameMode.ScoreEvent.Elimination.Headshot", "HEADSHOT", 1, 200, 14),
            ("GameMode.ScoreEvent.Assist", "ASSIST", 0, 70, 4),
            ("GameMode.ScoreEvent.Revive", "PICKED THEM UP", 0, 180, 12),
        ],
        # Almost everything is in the placement bands: a hundred-player mode where
        # the payout came mostly from kills would pay third place less than a
        # first-round drop that got lucky.
        "outcome": {
            "victory_experience": 0, "victory_currency": 0,
            "defeat_experience": 200, "defeat_currency": 20,
            "draw_experience": 200, "draw_currency": 20,
            "experience_per_minute_played": 35, "max_time_played_experience": 900,
        },
        "placement": [
            (1, 1, "LAST ONE STANDING", 3000, 300),
            (2, 5, "TOP FIVE", 1500, 150),
            (6, 10, "TOP TEN", 900, 90),
            (11, 25, "TOP TWENTY-FIVE", 500, 50),
            (26, 50, "TOP FIFTY", 250, 25),
        ],
        "bonuses": [
            ("GameMode.ScoreEvent.Elimination", "BLOODY WORK - 8 KILLS", 8, 600, 60),
        ],
        "multiplier": 1.0,
    },
    {
        "asset": "DA_Rewards_CooperativePvE",
        "display": "COOPERATIVE PAYOUT",
        "awards": [
            ("GameMode.ScoreEvent.Elimination", "KILL", 1, 40, 2),
            ("GameMode.ScoreEvent.Elimination.Headshot", "HEADSHOT", 1, 60, 3),
            ("GameMode.ScoreEvent.Revive", "STRETCHER BEARER", 0, 200, 15),
            ("GameMode.ScoreEvent.Resupply", "RESUPPLY", 0, 80, 4),
            ("GameMode.ScoreEvent.WaveCleared", "WAVE HELD", 0, 350, 30),
            ("GameMode.ScoreEvent.MissionObjective", "OBJECTIVE", 0, 500, 45),
            ("GameMode.ScoreEvent.Extraction", "EXTRACTED", 0, 1200, 120),
        ],
        # Co-op has no losing side to console, so the defeat term is a wipe. It
        # still pays: a section that got to wave nine and died earned that.
        "outcome": {
            "victory_experience": 2000, "victory_currency": 200,
            "defeat_experience": 700, "defeat_currency": 70,
            "draw_experience": 700, "draw_currency": 70,
            "experience_per_minute_played": 45, "max_time_played_experience": 1500,
        },
        "placement": [],
        "bonuses": [
            ("GameMode.ScoreEvent.WaveCleared", "DUG IN - 10 WAVES", 10, 800, 80),
            ("GameMode.ScoreEvent.Revive", "NOBODY LEFT BEHIND - 5 REVIVES", 5, 400, 40),
        ],
        "multiplier": 1.0,
    },
]


# ---------------------------------------------------------------------------
# Mode -> (rule set, objectives, reward table)
# ---------------------------------------------------------------------------
# Keyed by the DA_GameMode_* asset name author_game_modes.py writes. Twelve rule
# sets and seven reward tables cover all nineteen modes plus their variants,
# which is the reuse those assets exist for.

MODE_WIRING = {
    "DA_GameMode_Deathmatch": ("DA_Rules_StandardPvP", ["DA_Objective_Eliminate"], "DA_Rewards_Standard"),
    "DA_GameMode_TeamDeathmatch": ("DA_Rules_StandardPvP", ["DA_Objective_Eliminate"], "DA_Rewards_Standard"),
    "DA_GameMode_SquadDeathmatch": ("DA_Rules_StandardPvP", ["DA_Objective_Eliminate"], "DA_Rewards_Standard"),

    "DA_GameMode_PointCapture": ("DA_Rules_ObjectiveWarfare",
                                 ["DA_Objective_HoldSectors", "DA_Objective_Eliminate"], "DA_Rewards_Objective"),
    "DA_GameMode_PointMajority": ("DA_Rules_ObjectiveWarfare",
                                  ["DA_Objective_BreakSectors", "DA_Objective_Eliminate"], "DA_Rewards_Objective"),
    "DA_GameMode_PointRotation": ("DA_Rules_ObjectiveWarfare",
                                  ["DA_Objective_HoldRotatingPoint", "DA_Objective_Eliminate"], "DA_Rewards_Objective"),
    "DA_GameMode_AsymmetricWarfare": ("DA_Rules_AsymmetricAssault",
                                      ["DA_Objective_AdvanceFrontline", "DA_Objective_HoldFrontline"],
                                      "DA_Rewards_Objective"),
    "DA_GameMode_CaptureTheFlag": ("DA_Rules_ObjectiveWarfare",
                                   ["DA_Objective_CaptureFlags", "DA_Objective_Eliminate"], "DA_Rewards_Objective"),
    "DA_GameMode_LargeScaleWarfare": ("DA_Rules_LargeScale",
                                      ["DA_Objective_HoldSectors", "DA_Objective_Eliminate"], "DA_Rewards_LargeScale"),

    "DA_GameMode_Gauntlet": ("DA_Rules_Arcade", ["DA_Objective_Eliminate"], "DA_Rewards_Arcade"),
    "DA_GameMode_Gauntlet_Solos": ("DA_Rules_Arcade", ["DA_Objective_Eliminate"], "DA_Rewards_Arcade"),
    "DA_GameMode_Gauntlet_Duos": ("DA_Rules_Arcade", ["DA_Objective_Eliminate"], "DA_Rewards_Arcade"),
    "DA_GameMode_Gauntlet_Trios": ("DA_Rules_Arcade", ["DA_Objective_Eliminate"], "DA_Rewards_Arcade"),
    "DA_GameMode_Gauntlet_Squads": ("DA_Rules_Arcade", ["DA_Objective_Eliminate"], "DA_Rewards_Arcade"),

    "DA_GameMode_GunGame": ("DA_Rules_WeaponLadder", ["DA_Objective_ClimbWeaponLadder"], "DA_Rewards_Arcade"),
    "DA_GameMode_Duel": ("DA_Rules_OneInTheChamber", ["DA_Objective_WinRounds"], "DA_Rewards_Elimination"),
    "DA_GameMode_TrenchRaid": ("DA_Rules_TrenchClose", ["DA_Objective_WinRounds"], "DA_Rewards_Elimination"),
    "DA_GameMode_GasScramble": ("DA_Rules_RoundElimination", ["DA_Objective_WinRounds"], "DA_Rewards_Elimination"),
    "DA_GameMode_NoMansLand": ("DA_Rules_Marksman", ["DA_Objective_WinRounds"], "DA_Rewards_Elimination"),

    # Training pays nothing by design, so it is the one mode with no reward table
    # - and UCDGameModeData::IsDataValid does not warn about it, because
    # ModeHasNoScoreWinner covers exactly this case.
    "DA_GameMode_TrainingCourse": ("DA_Rules_TrainingSandbox", ["DA_Objective_Practice"], None),
    "DA_GameMode_ZombieSurvival": ("DA_Rules_CooperativePvE",
                                   ["DA_Objective_SurviveWaves", "DA_Objective_Extract"], "DA_Rewards_CooperativePvE"),
    "DA_GameMode_Operations": ("DA_Rules_CooperativePvE",
                               ["DA_Objective_CompleteMission", "DA_Objective_Extract"], "DA_Rewards_CooperativePvE"),

    "DA_GameMode_BattleRoyale": ("DA_Rules_BattleRoyale", ["DA_Objective_LastStanding"], "DA_Rewards_BattleRoyale"),
    "DA_GameMode_BattleRoyale_Solos": ("DA_Rules_BattleRoyale", ["DA_Objective_LastStanding"], "DA_Rewards_BattleRoyale"),
    "DA_GameMode_BattleRoyale_Duos": ("DA_Rules_BattleRoyale", ["DA_Objective_LastStanding"], "DA_Rewards_BattleRoyale"),
    "DA_GameMode_BattleRoyale_Trios": ("DA_Rules_BattleRoyale", ["DA_Objective_LastStanding"], "DA_Rewards_BattleRoyale"),
    "DA_GameMode_BattleRoyale_Squads": ("DA_Rules_BattleRoyale", ["DA_Objective_LastStanding"], "DA_Rewards_BattleRoyale"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tag_name_of(tag):
    """
    The name of a tag, or "" when it is unset.

    unreal.GameplayTag exposes no members of its own in Python - the struct comes
    back with an empty property bag, so tag.tag_name, tag.to_string() and
    tag.is_valid() all raise AttributeError. Both facts have to come from
    UBlueprintGameplayTagLibrary instead.
    """
    if not tag or not unreal.GameplayTagLibrary.is_gameplay_tag_valid(tag):
        return ""

    return str(unreal.GameplayTagLibrary.get_tag_name(tag))


def _tag(tag_name, report):
    """
    Resolve a registered tag by name through the project's own tag library.

    unreal.GameplayTagLibrary exposes MakeLiteralGameplayTag, which needs a tag
    you already have, and UGameplayTagsManager::RequestGameplayTag is not a
    UFUNCTION - so UCDGameplayTagLibrary is the only route from a name to a tag
    in editor Python. An unregistered name comes back invalid rather than being
    added to the tree, which is what turns a forgotten editor restart into a
    reported error instead of a blank field on a saved asset.
    """
    if not tag_name:
        return unreal.GameplayTag()

    tag = unreal.CDGameplayTagLibrary.make_tag_from_name(unreal.Name(tag_name))
    if not _tag_name_of(tag):
        report["errors"].append(
            "tag '{}' is not registered - restart the editor if Config/Tags/GameModes.ini "
            "changed while it was open".format(tag_name))
    return tag


def _tag_container(tag_names, report):
    return unreal.GameplayTagLibrary.make_gameplay_tag_container_from_array(
        [_tag(name, report) for name in tag_names])


def _enum(enum_type, value_name, report, context):
    value = getattr(enum_type, value_name, None)
    if value is None:
        report["errors"].append("{}: no {} value named {}".format(context, enum_type, value_name))
    return value


def _apply_struct(owner, struct_property, overrides, report, context):
    """
    Read a nested struct property, apply overrides, write it back.

    Editing the struct in place does not stick: get_editor_property returns a
    copy for a USTRUCT-valued property, so every override has to be followed by a
    set_editor_property of the whole struct or the asset saves unchanged.
    """
    struct_value = owner.get_editor_property(struct_property)
    for field, value in overrides.items():
        try:
            struct_value.set_editor_property(field, value)
        except Exception as error:  # noqa: BLE001 - reported, never raised
            report["errors"].append("{}: {}.{} = {!r} failed ({})".format(
                context, struct_property, field, value, error))
    owner.set_editor_property(struct_property, struct_value)


def _ensure_asset(path, directory, name, asset_class, report):
    """
    Load the asset, or create it if it is genuinely not there.

    Loading first rather than asking does_asset_exist: that goes through the
    asset registry, and a commandlet starts before the registry has finished
    scanning plugin content. A second run of this script then believed every
    asset the first run wrote was missing, tried to create each one on top of a
    package already on disk, and reported 61 "create failed" errors. load_asset
    hits the package itself, so it answers correctly either way.
    """
    eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    existing = eas.load_asset(path)
    if existing:
        return existing, False

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    created = asset_tools.create_asset(name, directory, asset_class, unreal.DataAssetFactory())
    if not created:
        report["errors"].append("create failed: {}".format(path))
        return None, False

    return created, True


def _object_path(directory, name):
    return "{}/{}.{}".format(directory, name, name)


# ---------------------------------------------------------------------------
# Authoring passes
# ---------------------------------------------------------------------------

def _author_rule_sets(dry_run, report):
    eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    for entry in RULE_SETS:
        path = "{}/{}".format(RULES_DIR, entry["asset"])

        if dry_run:
            report["rules"].append(entry["asset"])
            continue

        asset, created = _ensure_asset(path, RULES_DIR, entry["asset"], unreal.CDGameModeRuleSet, report)
        if not asset:
            continue

        asset.set_editor_property("display_name", entry["display"])
        asset.set_editor_property("rule_summary_lines", [unreal.Text(line) for line in entry["summary"]])

        combat = dict(entry["combat"])
        if "friendly_fire" in combat:
            policy = _enum(unreal.CDFriendlyFirePolicy, combat["friendly_fire"], report, entry["asset"])
            if policy is None:
                del combat["friendly_fire"]
            else:
                combat["friendly_fire"] = policy
        _apply_struct(asset, "combat", combat, report, entry["asset"])

        respawn = dict(entry["respawn"])
        if "policy" in respawn:
            policy = _enum(unreal.CDRespawnPolicy, respawn["policy"], report, entry["asset"])
            if policy is None:
                del respawn["policy"]
            else:
                respawn["policy"] = policy
        _apply_struct(asset, "respawn", respawn, report, entry["asset"])

        loadout = dict(entry["loadout"])
        ammo = loadout.pop("ammo", None)
        for field in ("allowed_weapon_class_tags", "blocked_weapon_class_tags"):
            if field in loadout:
                loadout[field] = _tag_container(loadout[field], report)
        _apply_struct(asset, "loadout", loadout, report, entry["asset"])

        if ammo:
            # Ammo is a struct inside a struct, so the outer one has to be read,
            # mutated and written back as a whole - the same copy-semantics trap
            # _apply_struct exists for, one level deeper.
            loadout_value = asset.get_editor_property("loadout")
            ammo_value = loadout_value.get_editor_property("ammo")
            for field, value in ammo.items():
                ammo_value.set_editor_property(field, value)
            loadout_value.set_editor_property("ammo", ammo_value)
            asset.set_editor_property("loadout", loadout_value)

        flow = dict(entry["flow"])
        if "tiebreaker" in flow:
            tiebreaker = _enum(unreal.CDTiebreaker, flow["tiebreaker"], report, entry["asset"])
            if tiebreaker is None:
                del flow["tiebreaker"]
            else:
                flow["tiebreaker"] = tiebreaker
        _apply_struct(asset, "flow", flow, report, entry["asset"])

        eas.save_asset(path)
        report["rules"].append("{} {}".format("created" if created else "updated", entry["asset"]))


def _author_objectives(dry_run, report):
    eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    for entry in OBJECTIVES:
        path = "{}/{}".format(OBJECTIVES_DIR, entry["asset"])

        if dry_run:
            report["objectives"].append(entry["asset"])
            continue

        asset, created = _ensure_asset(path, OBJECTIVES_DIR, entry["asset"], unreal.CDObjectiveDefinition, report)
        if not asset:
            continue

        asset.set_editor_property("objective_tag", _tag(entry["tag"], report))
        asset.set_editor_property("title", entry["title"])
        asset.set_editor_property("hud_prompt", entry["hud"])
        asset.set_editor_property("briefing_text", entry["briefing"])
        asset.set_editor_property("target_count", entry["target"])
        asset.set_editor_property("required_for_victory", entry["required"])
        asset.set_editor_property("show_world_marker", entry["marker"])
        asset.set_editor_property("completion_score_event_tag", _tag(entry["score_event"], report))

        role = _enum(unreal.CDObjectiveRole, entry["role"], report, entry["asset"])
        if role is not None:
            asset.set_editor_property("role", role)

        completion = _enum(unreal.CDObjectiveCompletion, entry["completion"], report, entry["asset"])
        if completion is not None:
            asset.set_editor_property("completion", completion)

        if entry["component"]:
            component_class = getattr(unreal, entry["component"], None)
            if component_class is None:
                report["errors"].append("{}: no class named unreal.{}".format(
                    entry["asset"], entry["component"]))
            else:
                asset.set_editor_property("objective_component_class", component_class)

        eas.save_asset(path)
        report["objectives"].append("{} {}".format("created" if created else "updated", entry["asset"]))


def _author_rewards(dry_run, report):
    eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    for entry in REWARDS:
        path = "{}/{}".format(REWARDS_DIR, entry["asset"])

        if dry_run:
            report["rewards"].append(entry["asset"])
            continue

        asset, created = _ensure_asset(path, REWARDS_DIR, entry["asset"], unreal.CDMatchRewardSet, report)
        if not asset:
            continue

        asset.set_editor_property("display_name", entry["display"])
        asset.set_editor_property("experience_multiplier", entry["multiplier"])

        awards = []
        for tag_name, label, score, xp, currency in entry["awards"]:
            award = unreal.CDScoreAward()
            award.set_editor_property("event_tag", _tag(tag_name, report))
            award.set_editor_property("display_name", label)
            award.set_editor_property("score_points", score)
            award.set_editor_property("experience_points", xp)
            award.set_editor_property("currency", currency)
            awards.append(award)
        asset.set_editor_property("score_awards", awards)

        _apply_struct(asset, "outcome_rewards", entry["outcome"], report, entry["asset"])

        placements = []
        for low, high, label, xp, currency in entry["placement"]:
            placement = unreal.CDPlacementReward()
            placement.set_editor_property("min_placement", low)
            placement.set_editor_property("max_placement", high)
            placement.set_editor_property("display_name", label)
            placement.set_editor_property("experience_points", xp)
            placement.set_editor_property("currency", currency)
            placements.append(placement)
        asset.set_editor_property("placement_rewards", placements)

        bonuses = []
        for tag_name, label, required, xp, currency in entry["bonuses"]:
            bonus = unreal.CDPerformanceBonus()
            bonus.set_editor_property("event_tag", _tag(tag_name, report))
            bonus.set_editor_property("display_name", label)
            bonus.set_editor_property("required_count", required)
            bonus.set_editor_property("experience_points", xp)
            bonus.set_editor_property("currency", currency)
            bonuses.append(bonus)
        asset.set_editor_property("performance_bonuses", bonuses)

        eas.save_asset(path)
        report["rewards"].append("{} {}".format("created" if created else "updated", entry["asset"]))




def _load_roster(report):
    """
    The mode roster, imported rather than restated.

    author_game_modes.py owns what a mode *is* - objective mechanic, scale tier,
    composition, team and squad counts, and the tile's per-Part names. This
    script owns the rules, objectives and payout layered on top. Importing its
    table is what keeps a mode from having two different scale tiers depending on
    which script last ran.

    Only the data tables are imported; that script's apply() writes tiles to the
    same /Game/CollateralDamage/UI/Data/GameModes this script's TILE_DIRS reads
    from (see the module docstring), so calling it here would just recreate the
    tiles this script expects to already exist, not create a second roster.
    """
    try:
        import author_game_modes
    except ImportError as error:
        report["errors"].append(
            "could not import author_game_modes ({}). Both scripts must be on the editor's "
            "Python path - see Project Settings > Plugins > Python > Additional Paths.".format(error))
        return [], {}

    return author_game_modes.ROSTER, author_game_modes.MODE_TUNING


def _author_mode_data(dry_run, report):
    """
    Create any missing UCDGameModeData, then wire its rules, objectives and rewards.

    Creation is here rather than left to author_game_modes.py because a rule set
    nothing references is a rule set that never reaches a player, and today only
    DA_GameMode_PointRotation exists on disk. The scale and objective values come
    from that script's roster, so this creates the same asset it would have.
    """
    eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
    roster, tuning = _load_roster(report)

    for entry in roster:
        # Quick Play has no mode data by design: matchmaking gets a broad filter
        # rather than one mode.
        if not entry["mode"]:
            continue

        mode_asset = entry["asset"]
        wiring = MODE_WIRING.get(mode_asset)
        if not wiring:
            report["errors"].append(
                "{} is in the roster but has no rules/objectives/rewards row here".format(mode_asset))
            continue

        path = "{}/{}".format(MODE_DATA_DIR, mode_asset)

        if dry_run:
            report["modes"].append("{} {}".format(
                "create" if not eas.does_asset_exist(path) else "update", mode_asset))
            continue

        asset, created = _ensure_asset(path, MODE_DATA_DIR, mode_asset, unreal.CDGameModeData, report)
        if not asset:
            continue

        objective = _enum(unreal.CDObjectiveMode, entry["mode"], report, mode_asset)
        scale = _enum(unreal.CDScaleTier, entry["scale"], report, mode_asset)
        composition = _enum(unreal.CDCombatantComposition, entry["composition"], report, mode_asset)
        variant = _enum(unreal.CDTeamSizeVariant, entry["variant"], report, mode_asset)

        if objective is not None:
            asset.set_editor_property("objective_mode", objective)
        if scale is not None:
            asset.set_editor_property("scale_tier", scale)
        if composition is not None:
            asset.set_editor_property("composition", composition)
        if variant is not None:
            asset.set_editor_property("team_size_variant", variant)

        asset.set_editor_property("max_players", entry["max_players"])
        asset.set_editor_property("team_count", entry["teams"])
        asset.set_editor_property("squad_count", entry["squads"])

        for prop, value in tuning.get(mode_asset, {}).items():
            asset.set_editor_property(prop, value)

        # ---- the part this script is actually for --------------------------
        rules, objectives, rewards = wiring

        rule_asset = eas.load_asset(_object_path(RULES_DIR, rules)) if rules else None
        if rules and not rule_asset:
            report["errors"].append("{}: rule set {} not found".format(mode_asset, rules))
        asset.set_editor_property("rule_set", rule_asset)

        reward_asset = eas.load_asset(_object_path(REWARDS_DIR, rewards)) if rewards else None
        if rewards and not reward_asset:
            report["errors"].append("{}: reward set {} not found".format(mode_asset, rewards))
        asset.set_editor_property("reward_set", reward_asset)

        resolved_objectives = []
        for objective_asset in objectives:
            loaded = eas.load_asset(_object_path(OBJECTIVES_DIR, objective_asset))
            if not loaded:
                report["errors"].append("{}: objective {} not found".format(mode_asset, objective_asset))
                continue
            resolved_objectives.append(loaded)
        asset.set_editor_property("objectives", resolved_objectives)

        eas.save_asset(path)
        report["modes"].append("{} {}".format("created" if created else "updated", mode_asset))


def _wire_tiles(dry_run, report):
    """
    Point each Deploy tile at its mode data and mirror the briefing assets onto it.

    Tiles are matched by GameModeTag, not by asset name: the Part I tiles are
    named for the mode (DeathMatch, MajorityCapture, Gauntlet_Solos) while the
    mode data is named DA_GameMode_*, and today the tag is the only field those
    tiles actually carry. It is also the field the whole tag-driven frontend
    enumerates on, so matching on anything else would be matching on the part
    that is allowed to drift.

    The tile's rule/objective/reward fields are presentation only - the match
    runs on the mode data's - but UCDGameModeUIEntry::IsDataValid errors when the
    two disagree, so writing both from one table here is what keeps that check
    green rather than permanently red.
    """
    eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
    roster, _ = _load_roster(report)

    by_tag = {entry["tag"]: entry["asset"] for entry in roster if entry["mode"]}

    for tile_dir in TILE_DIRS:
        if not eas.does_directory_exist(tile_dir):
            report["errors"].append("tile directory {} does not exist".format(tile_dir))
            continue

        for tile_path in eas.list_assets(tile_dir, recursive=True, include_folder=False):
            tile = eas.load_asset(tile_path)
            if not tile or not isinstance(tile, unreal.CDGameModeUIEntry):
                continue

            # GameModeTag is the roster filter and SelectionTag is the enumeration
            # key; they are the same value on a mode tile, and several Part I tiles
            # only ever had the second one set. Falling back is what stops those
            # tiles being silently skipped over a field nobody filled in.
            tag_name = _tag_name_of(tile.get_editor_property("game_mode_tag"))
            if not tag_name:
                tag_name = _tag_name_of(tile.get_editor_property("selection_tag"))
            mode_asset = by_tag.get(tag_name)

            if not mode_asset:
                # Quick Play, or a tile whose tag is not in the roster. Either way
                # there is no mode data to mirror, and inventing one here would
                # hide the mismatch instead of surfacing it.
                report["unwired_tiles"].append("{} (tag '{}')".format(tile_path, tag_name))
                continue

            if dry_run:
                report["tiles"].append("{} -> {}".format(tile_path, mode_asset))
                continue

            rules, objectives, rewards = MODE_WIRING[mode_asset]

            # Loaded objects, not SoftObjectPaths: a TSoftObjectPtr property is
            # still typed, and Python refuses to nativize a bare path into one
            # ("Cannot nativize 'SoftObjectPath' as 'Object'"). Handing it the
            # object is what actually writes the soft reference. None clears it.
            tile.set_editor_property(
                "game_mode_data", eas.load_asset(_object_path(MODE_DATA_DIR, mode_asset)))
            tile.set_editor_property(
                "rule_set", eas.load_asset(_object_path(RULES_DIR, rules)) if rules else None)
            tile.set_editor_property(
                "reward_set", eas.load_asset(_object_path(REWARDS_DIR, rewards)) if rewards else None)
            tile.set_editor_property(
                "objectives",
                [eas.load_asset(_object_path(OBJECTIVES_DIR, o)) for o in objectives])

            eas.save_asset(tile_path)
            report["tiles"].append("{} -> {}".format(tile_path, mode_asset))


def _scan_content(report):
    """
    Force the asset registry to scan the directories this script reads and writes.

    A commandlet does not wait for the initial registry scan, so list_assets on a
    plugin content directory can legitimately come back empty on a cold start.
    Everything here is a handful of small data assets, so a synchronous scan costs
    nothing next to being wrong about what already exists.
    """
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous(
        [RULES_DIR, OBJECTIVES_DIR, REWARDS_DIR, MODE_DATA_DIR] + list(TILE_DIRS),
        force_rescan=True)


def apply(dry_run=True):
    """Author every rule set, objective and reward table, then wire them up."""
    report = {
        "rules": [],
        "objectives": [],
        "rewards": [],
        "modes": [],
        "tiles": [],
        "unwired_tiles": [],
        "errors": [],
    }

    _scan_content(report)

    # Order matters: the mode data and tile passes resolve assets the first three
    # passes create, so one real run never has to be repeated to pick up its own
    # output, and one dry run reports the whole chain.
    _author_rule_sets(dry_run, report)
    _author_objectives(dry_run, report)
    _author_rewards(dry_run, report)
    _author_mode_data(dry_run, report)
    _wire_tiles(dry_run, report)

    unreal.log("{}Game mode rules: {} rule sets, {} objectives, {} reward tables, "
               "{} mode data, {} tiles wired, {} tiles left unwired, {} errors.".format(
                   "[dry run] " if dry_run else "",
                   len(report["rules"]), len(report["objectives"]), len(report["rewards"]),
                   len(report["modes"]), len(report["tiles"]),
                   len(report["unwired_tiles"]), len(report["errors"])))

    for tile in report["unwired_tiles"]:
        unreal.log_warning("tile has no roster mode to mirror: {}".format(tile))
    for error in report["errors"]:
        unreal.log_warning(error)

    return report
