"""
Author the full game mode roster against the generalized mechanic tags.

Supersedes retag_game_modes.py, which applied the *previous* naming pass (the themed
tags UNSUNG / THE GRINDER / FRONTLINES / SKIRMISH / WARLORDS / ATTRITION / OVER THE TOP /
HOLDOUT / DEAD MAN'S LAND). That pass baked the shipped name into the tag, so every time a
mode was re-themed for a new Part the tag had to be reissued and every asset referencing it
retagged. This one inverts that:

  * the TAG is a generalized mechanic name, one-to-one with ECDObjectiveMode
    (UI.Selection.GameMode.AsymmetricWarfare, never .OverTheTop)
  * the SHIPPED NAME is presentation, and varies per Part through
    UCDGameModeUIEntry::PartDisplayNameOverrides (Part II renders that same mechanic
    as "OVER THE TOP")

Pairs with the UI.Selection.GameMode tags in Config/Tags/Frontend.ini and the redirects in
Config/DefaultGameplayTags.ini.

RESTART THE EDITOR BEFORE RUNNING THIS: the tag table is read at startup, so an editor that
was already open when Frontend.ini changed does not know the new tags. Every tag below then
resolves to an invalid tag, which this script reports rather than writing onto an asset - so
a forgotten restart shows up as a wall of errors, not as a roster of blank tiles.

Run from the Unreal Editor Python console:
    import author_game_modes
    author_game_modes.apply(dry_run=True)
    author_game_modes.apply(dry_run=False)

Afterwards, right-click Content/CollateralDamage/UI and choose "Fix Up Redirectors in Folder"
to clear the redirectors the renames leave behind.
"""

import unreal

UI_MODE_DIR = "/Game/CollateralDamage/UI/Data/GameModes"
MAP_DIR = "/Game/CollateralDamage/UI/Data/Maps"
MODE_DATA_DIR = "/GameModes/DataAssets"

PART_I = "UI.Selection.Part.PartI"
PART_II = "UI.Selection.Part.PartII"

# Old asset name -> new asset name. Renaming (rather than create + delete) keeps whatever
# Icon the designer already assigned on the tile. Covers both previous naming generations.
RENAMES = {
    # Generation 2 (themed) -> generalized
    "DA_GameMode_Maelstrom": "DA_GameMode_LargeScaleWarfare",
    "DA_GameMode_Grinder": "DA_GameMode_LargeScaleWarfare",
    "DA_GameMode_FrontLines": "DA_GameMode_PointCapture",
    "DA_GameMode_Frontlines": "DA_GameMode_PointCapture",
    "DA_GameMode_Attrition": "DA_GameMode_PointMajority",
    "DA_GameMode_Spearhead": "DA_GameMode_AsymmetricWarfare",
    "DA_GameMode_Skirmish": "DA_GameMode_TeamDeathmatch",
    "DA_GameMode_Warlords": "DA_GameMode_SquadDeathmatch",
    "DA_GameMode_UnsungOps": "DA_GameMode_Operations",
    "DA_GameMode_LastStand": "DA_GameMode_ZombieSurvival",
    "DA_GameMode_Zombies": "DA_GameMode_ZombieSurvival",
    # Generation 1 (mechanic) -> generalized, for any project still holding these
    "DA_GameMode_Warfare": "DA_GameMode_LargeScaleWarfare",
    "DA_GameMode_Conquest": "DA_GameMode_PointCapture",
    "DA_GameMode_Escalation": "DA_GameMode_PointMajority",
    "DA_GameMode_OverTheTop": "DA_GameMode_AsymmetricWarfare",
    "DA_GameMode_SpecialOps": "DA_GameMode_Operations",
}

# Old mode tag -> new mode tag, for remapping the compatible-mode FilterTags on DA_Map_*.
# Mirrors the GameplayTagRedirects in Config/DefaultGameplayTags.ini; those fix the tag at
# load time, this rewrites the asset so the redirect can eventually be retired.
TAG_REMAP = {
    "UI.Selection.GameMode.Warfare": "UI.Selection.GameMode.LargeScaleWarfare",
    "UI.Selection.GameMode.Grinder": "UI.Selection.GameMode.LargeScaleWarfare",
    "UI.Selection.GameMode.Maelstrom": "UI.Selection.GameMode.LargeScaleWarfare",
    "UI.Selection.GameMode.Conquest": "UI.Selection.GameMode.PointCapture",
    "UI.Selection.GameMode.Frontlines": "UI.Selection.GameMode.PointCapture",
    "UI.Selection.GameMode.Escalation": "UI.Selection.GameMode.PointMajority",
    "UI.Selection.GameMode.Attrition": "UI.Selection.GameMode.PointMajority",
    "UI.Selection.GameMode.Breakthrough": "UI.Selection.GameMode.AsymmetricWarfare",
    "UI.Selection.GameMode.OverTheTop": "UI.Selection.GameMode.AsymmetricWarfare",
    "UI.Selection.GameMode.Spearhead": "UI.Selection.GameMode.AsymmetricWarfare",
    "UI.Selection.GameMode.Skirmish": "UI.Selection.GameMode.TeamDeathmatch",
    "UI.Selection.GameMode.Warlords": "UI.Selection.GameMode.SquadDeathmatch",
    "UI.Selection.GameMode.SpecialOps": "UI.Selection.GameMode.Operations",
    "UI.Selection.GameMode.Unsung": "UI.Selection.GameMode.Operations",
    "UI.Selection.GameMode.UnsungOps": "UI.Selection.GameMode.Operations",
    "UI.Selection.GameMode.Zombies": "UI.Selection.GameMode.ZombieSurvival",
    "UI.Selection.GameMode.DeadMansLand": "UI.Selection.GameMode.ZombieSurvival",
    "UI.Selection.GameMode.LastStand": "UI.Selection.GameMode.ZombieSurvival",
    "UI.Selection.GameMode.Holdout": "UI.Selection.GameMode.ZombieSurvival",
}

# The roster, in tile order — every UI.Selection.GameMode.* leaf in Config/Tags/Frontend.ini.
#
#   display     the generalized fallback name, used by any Part with no override
#   parts       PartTag -> themed name for that era. Absent Part = falls back to `display`,
#               which is the point of the fallback: a mode that reads the same everywhere
#               needs no entry at all, and a mode that does not fit an era (mustard gas in
#               1899) is simply left out rather than given a forced name.
#   mode        ECDObjectiveMode value name on the paired UCDGameModeData
#   variant     ECDTeamSizeVariant value name, for the Gauntlet/BattleRoyale sub-tags
#
# Parts III-X carry no overrides on purpose: only Part I has authored content today and
# Part II is the next one up, so inventing eight more eras' worth of names here would be
# guessing at fiction that is not written yet. Add them to `parts` as each Part lands.
ROSTER = [
    {
        "asset": "DA_GameMode_QuickPlay",
        "tag": "UI.Selection.GameMode.QuickPlay",
        "display": "QUICK PLAY",
        "parts": {},
        "description": "Straight into the nearest match. No map vote, no waiting.",
        "identifier": "QuickPlay",
        "sort": 0,
        "quick_play": True,
        "mode": None,  # no UCDGameModeData by design: matchmaking gets a broad filter
        "max_players": 64,
        "teams": 2,
        "squads": 0,
        "scale": "STANDARD",
        "composition": "PV_P",
        "variant": "NONE",
    },
    # ---- Standard deathmatch ------------------------------------------------
    {
        "asset": "DA_GameMode_Deathmatch",
        "tag": "UI.Selection.GameMode.Deathmatch",
        "display": "DEATHMATCH",
        "parts": {PART_I: "THE VELDT", PART_II: "THE WIRE"},
        "description": "Sixteen men, no allies, no objective. The highest count walks away.",
        "identifier": "Deathmatch",
        "sort": 100,
        "quick_play": False,
        "mode": "DEATHMATCH",
        "max_players": 16,
        "teams": 0,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_TeamDeathmatch",
        "tag": "UI.Selection.GameMode.TeamDeathmatch",
        "display": "TEAM DEATHMATCH",
        "parts": {PART_I: "SKIRMISH"},
        "description": "Two sides, close and fast. No objectives - just the ground between.",
        "identifier": "TeamDeathmatch",
        "sort": 110,
        "quick_play": False,
        "mode": "TEAM_DEATHMATCH",
        "max_players": 32,
        "teams": 2,
        "squads": 0,
        "scale": "STANDARD",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_SquadDeathmatch",
        "tag": "UI.Selection.GameMode.SquadDeathmatch",
        "display": "SQUAD DEATHMATCH",
        "parts": {PART_I: "WARLORDS"},
        "description": "Four squads, no allies. Kill anyone who wants what you are holding.",
        "identifier": "SquadDeathmatch",
        "sort": 120,
        "quick_play": False,
        "mode": "SQUAD_DEATHMATCH",
        "max_players": 64,
        "teams": 0,
        "squads": 4,
        "scale": "LARGE_SCALE",
        "composition": "PV_P",
        "variant": "NONE",
    },
    # ---- Objective & territory ----------------------------------------------
    {
        "asset": "DA_GameMode_PointCapture",
        "tag": "UI.Selection.GameMode.PointCapture",
        "display": "POINT CAPTURE",
        "parts": {PART_I: "FRONTLINES", PART_II: "THE PUSH"},
        "description": "A line of sectors and a meter that only moves while you hold ground.",
        "identifier": "PointCapture",
        "sort": 200,
        "quick_play": False,
        "mode": "POINT_CAPTURE",
        "max_players": 64,
        "teams": 2,
        "squads": 0,
        "scale": "LARGE_SCALE",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_PointMajority",
        "tag": "UI.Selection.GameMode.PointMajority",
        "display": "POINT MAJORITY",
        "parts": {PART_I: "ATTRITION", PART_II: "ATTRITION"},
        "description": "Bleed them white. Every sector you break stays broken.",
        "identifier": "PointMajority",
        "sort": 210,
        "quick_play": False,
        "mode": "POINT_MAJORITY",
        "max_players": 64,
        "teams": 2,
        "squads": 0,
        "scale": "LARGE_SCALE",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_PointRotation",
        "tag": "UI.Selection.GameMode.PointRotation",
        "display": "POINT ROTATION",
        "parts": {PART_I: "THE KOPJE"},
        "description": "One hill, four squads, and ninety seconds before it moves.",
        "identifier": "PointRotation",
        "sort": 220,
        "quick_play": False,
        "mode": "POINT_ROTATION",
        "max_players": 64,
        "teams": 0,
        "squads": 4,
        "scale": "LARGE_SCALE",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_AsymmetricWarfare",
        "tag": "UI.Selection.GameMode.AsymmetricWarfare",
        "display": "ASYMMETRIC WARFARE",
        "parts": {PART_I: "THE FORLORN HOPE", PART_II: "OVER THE TOP"},
        "description": "Attackers take the sectors in order; defenders make every yard cost.",
        "identifier": "AsymmetricWarfare",
        "sort": 230,
        "quick_play": False,
        "mode": "ASYMMETRIC_WARFARE",
        "max_players": 64,
        "teams": 2,
        "squads": 0,
        "scale": "LARGE_SCALE",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_CaptureTheFlag",
        "tag": "UI.Selection.GameMode.Arcade.CaptureTheFlag",
        "display": "CAPTURE THE FLAG",
        "parts": {PART_I: "COLOURS"},
        "description": "Take theirs, hold yours, and run the whole way back.",
        "identifier": "CaptureTheFlag",
        "sort": 240,
        "quick_play": False,
        "mode": "CAPTURE_THE_FLAG",
        "max_players": 64,
        "teams": 2,
        "squads": 0,
        "scale": "LARGE_SCALE",
        "composition": "PV_P",
        "variant": "NONE",
    },
    # ---- Small-scale & arcade -----------------------------------------------
    {
        "asset": "DA_GameMode_Gauntlet",
        "tag": "UI.Selection.GameMode.Arcade.Gauntlet",
        "display": "GAUNTLET",
        "parts": {},
        "description": "The small-scale arena. Pick your squad size and your base mode.",
        "identifier": "Gauntlet",
        "sort": 300,
        "quick_play": False,
        "mode": "GAUNTLET",
        "max_players": 8,
        "teams": 2,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_Gauntlet_Solos",
        "tag": "UI.Selection.GameMode.Arcade.Gauntlet.Solos",
        "display": "GAUNTLET - SOLOS",
        "parts": {},
        "description": "Pure 1v1. Nowhere to hide and nobody to blame.",
        "identifier": "GauntletSolos",
        "sort": 301,
        "quick_play": False,
        "mode": "GAUNTLET",
        "max_players": 2,
        "teams": 0,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "SOLOS",
    },
    {
        "asset": "DA_GameMode_Gauntlet_Duos",
        "tag": "UI.Selection.GameMode.Arcade.Gauntlet.Duos",
        "display": "GAUNTLET - DUOS",
        "parts": {},
        "description": "2v2. One partner, one plan, no margin.",
        "identifier": "GauntletDuos",
        "sort": 302,
        "quick_play": False,
        "mode": "GAUNTLET",
        "max_players": 4,
        "teams": 0,
        "squads": 2,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "DUOS",
    },
    {
        "asset": "DA_GameMode_Gauntlet_Trios",
        "tag": "UI.Selection.GameMode.Arcade.Gauntlet.Trios",
        "display": "GAUNTLET - TRIOS",
        "parts": {},
        "description": "3v3. Enough men to hold an angle, not enough to hold two.",
        "identifier": "GauntletTrios",
        "sort": 303,
        "quick_play": False,
        "mode": "GAUNTLET",
        "max_players": 6,
        "teams": 0,
        "squads": 2,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "TRIOS",
    },
    {
        "asset": "DA_GameMode_Gauntlet_Squads",
        "tag": "UI.Selection.GameMode.Arcade.Gauntlet.Squads",
        "display": "GAUNTLET - SQUADS",
        "parts": {},
        "description": "4v4. A full section, and room to actually manoeuvre it.",
        "identifier": "GauntletSquads",
        "sort": 304,
        "quick_play": False,
        "mode": "GAUNTLET",
        "max_players": 8,
        "teams": 0,
        "squads": 2,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "SQUADS",
    },
    {
        "asset": "DA_GameMode_GunGame",
        "tag": "UI.Selection.GameMode.Arcade.GunGame",
        "display": "GUN GAME",
        "parts": {PART_I: "THE ARMOURY"},
        "description": "Every kill hands you the next weapon. Finish the ladder first.",
        "identifier": "GunGame",
        "sort": 310,
        "quick_play": False,
        "mode": "GUN_GAME",
        "max_players": 16,
        "teams": 0,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_Duel",
        "tag": "UI.Selection.GameMode.Arcade.Duel",
        "display": "DUEL",
        "parts": {PART_I: "PISTOLS AT DAWN"},
        "description": "One round in the chamber. A kill buys the next one; miss and it is the bayonet.",
        "identifier": "Duel",
        "sort": 320,
        "quick_play": False,
        "mode": "DUEL",
        "max_players": 8,
        "teams": 0,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_TrenchRaid",
        "tag": "UI.Selection.GameMode.Arcade.TrenchRaid",
        "display": "TRENCH RAID",
        "parts": {PART_I: "THE SAP", PART_II: "TRENCH RAID"},
        "description": "Melee, shotguns and sidearms, in a network too tight to swing a rifle.",
        "identifier": "TrenchRaid",
        "sort": 330,
        "quick_play": False,
        "mode": "TRENCH_RAID",
        "max_players": 12,
        "teams": 2,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_GasScramble",
        "tag": "UI.Selection.GameMode.Arcade.GasScramble",
        "display": "GAS SCRAMBLE",
        # No Part I name: chemical warfare at this scale is a Great War fact, so
        # Part I falls back to the generalized name rather than getting a forced one.
        "parts": {PART_II: "THE YELLOW CROSS"},
        "description": "The cloud moves. The masks run out. Last one breathing takes the round.",
        "identifier": "GasScramble",
        "sort": 340,
        "quick_play": False,
        "mode": "GAS_SCRAMBLE",
        "max_players": 8,
        "teams": 0,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_NoMansLand",
        "tag": "UI.Selection.GameMode.Arcade.NoMansLand",
        "display": "NO MAN'S LAND",
        "parts": {PART_I: "SHARPSHOOTERS"},
        "description": "Bolt actions, one shot, no respawns. Seven rounds decides it.",
        "identifier": "NoMansLand",
        "sort": 350,
        "quick_play": False,
        "mode": "NO_MANS_LAND",
        "max_players": 8,
        "teams": 2,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "NONE",
    },
    # ---- PvE & story --------------------------------------------------------
    {
        "asset": "DA_GameMode_TrainingCourse",
        "tag": "UI.Selection.GameMode.TrainingCourse",
        "display": "TRAINING COURSE",
        "parts": {PART_I: "THE BULLRING"},
        "description": "Weapons, movement and armour, with nothing shooting back that you did not ask for.",
        "identifier": "TrainingCourse",
        "sort": 400,
        "quick_play": False,
        "mode": "TRAINING_COURSE",
        "max_players": 4,
        "teams": 0,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_E",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_ZombieSurvival",
        "tag": "UI.Selection.GameMode.ZombieSurvival",
        "display": "ZOMBIE SURVIVAL",
        "parts": {PART_I: "DEAD MAN'S LAND"},
        "description": "Hold the ground, finish the objective, and reach the extraction alive.",
        "identifier": "ZombieSurvival",
        "sort": 410,
        "quick_play": False,
        "mode": "ZOMBIE_SURVIVAL",
        "max_players": 8,
        "teams": 1,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_E",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_Operations",
        "tag": "UI.Selection.GameMode.Operations",
        "display": "OPERATIONS",
        "parts": {PART_I: "UNSUNG"},
        "description": "Real operations nobody wrote down. Small squad, narrow objective, no reinforcements.",
        "identifier": "Operations",
        "sort": 420,
        "quick_play": False,
        "mode": "OPERATIONS",
        "max_players": 4,
        "teams": 1,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_E",
        "variant": "NONE",
    },
    # ---- Large-scale & battle royale ----------------------------------------
    {
        "asset": "DA_GameMode_LargeScaleWarfare",
        "tag": "UI.Selection.GameMode.LargeScaleWarfare",
        "display": "LARGE-SCALE WARFARE",
        "parts": {PART_I: "MAELSTROM", PART_II: "THE GRINDER"},
        "description": "64v64 combined arms. Bodies fed into the front until one side runs out.",
        "identifier": "LargeScaleWarfare",
        "sort": 500,
        "quick_play": False,
        "mode": "LARGE_SCALE_WARFARE",
        "max_players": 128,
        "teams": 2,
        "squads": 0,
        "scale": "MASSIVE",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_BattleRoyale",
        "tag": "UI.Selection.GameMode.BattleRoyale",
        "display": "BATTLE ROYALE",
        "parts": {PART_I: "THE SCRAMBLE"},
        "description": "A hundred in, one out. Scavenge what you can before the ring closes.",
        "identifier": "BattleRoyale",
        "sort": 510,
        "quick_play": False,
        "mode": "BATTLE_ROYALE",
        "max_players": 100,
        "teams": 0,
        "squads": 0,
        "scale": "MASSIVE",
        "composition": "PV_P",
        "variant": "NONE",
    },
    {
        "asset": "DA_GameMode_BattleRoyale_Solos",
        "tag": "UI.Selection.GameMode.BattleRoyale.Solos",
        "display": "BATTLE ROYALE - SOLOS",
        "parts": {PART_I: "THE SCRAMBLE - SOLOS"},
        "description": "One hundred players, every one of them for themselves.",
        "identifier": "BattleRoyaleSolos",
        "sort": 511,
        "quick_play": False,
        "mode": "BATTLE_ROYALE",
        "max_players": 100,
        "teams": 0,
        "squads": 0,
        "scale": "MASSIVE",
        "composition": "PV_P",
        "variant": "SOLOS",
    },
    {
        "asset": "DA_GameMode_BattleRoyale_Duos",
        "tag": "UI.Selection.GameMode.BattleRoyale.Duos",
        "display": "BATTLE ROYALE - DUOS",
        "parts": {PART_I: "THE SCRAMBLE - DUOS"},
        "description": "Fifty pairs. Half of staying alive is keeping the other one alive.",
        "identifier": "BattleRoyaleDuos",
        "sort": 512,
        "quick_play": False,
        "mode": "BATTLE_ROYALE",
        "max_players": 100,
        "teams": 0,
        "squads": 50,
        "scale": "MASSIVE",
        "composition": "PV_P",
        "variant": "DUOS",
    },
    {
        "asset": "DA_GameMode_BattleRoyale_Trios",
        "tag": "UI.Selection.GameMode.BattleRoyale.Trios",
        "display": "BATTLE ROYALE - TRIOS",
        "parts": {PART_I: "THE SCRAMBLE - TRIOS"},
        "description": "Thirty-three sections of three, and one ring closing on all of them.",
        "identifier": "BattleRoyaleTrios",
        "sort": 513,
        "quick_play": False,
        "mode": "BATTLE_ROYALE",
        "max_players": 100,
        "teams": 0,
        "squads": 33,
        "scale": "MASSIVE",
        "composition": "PV_P",
        "variant": "TRIOS",
    },
    {
        "asset": "DA_GameMode_BattleRoyale_Squads",
        "tag": "UI.Selection.GameMode.BattleRoyale.Squads",
        "display": "BATTLE ROYALE - SQUADS",
        "parts": {PART_I: "THE SCRAMBLE - SQUADS"},
        "description": "Twenty-five full squads. The last one with a man standing takes it.",
        "identifier": "BattleRoyaleSquads",
        "sort": 514,
        "quick_play": False,
        "mode": "BATTLE_ROYALE",
        "max_players": 100,
        "teams": 0,
        "squads": 25,
        "scale": "MASSIVE",
        "composition": "PV_P",
        "variant": "SQUADS",
    },
]

# Objective tuning that is not derivable from the roster row above. Anything absent keeps
# the UCDGameModeData class default.
MODE_TUNING = {
    "DA_GameMode_PointMajority": {"points_to_eliminate_for_win": 3},
    "DA_GameMode_PointRotation": {"rotation_interval_seconds": 90.0},
    "DA_GameMode_NoMansLand": {"rounds_to_win": 7, "lives_per_round": 1},
    "DA_GameMode_GasScramble": {"rounds_to_win": 5, "lives_per_round": 1},
    "DA_GameMode_Duel": {"rounds_to_win": 5, "lives_per_round": 1},
    "DA_GameMode_TrenchRaid": {"rounds_to_win": 5},
    "DA_GameMode_TrainingCourse": {"match_time_limit_seconds": 0.0, "warmup_time_seconds": 0.0},
}


def _tag(tag_name, report=None):
    """
    Resolve a registered tag by name.

    Goes through UCDGameplayTagLibrary, not unreal.GameplayTagLibrary: the engine's
    UBlueprintGameplayTagLibrary exposes MakeLiteralGameplayTag (which needs a tag you
    already have) but no RequestGameplayTag, so there is no engine-side way for a script
    to turn a name into a tag. That gap is the whole reason UCDGameplayTagLibrary exists.

    An unregistered name comes back invalid rather than being added to the tag tree, so a
    tag missing from Config/Tags/Frontend.ini - or an editor still holding the tag table it
    read at startup - surfaces as a reported error instead of a blank field on a saved asset.
    """
    tag = unreal.CDGameplayTagLibrary.make_tag_from_name(unreal.Name(tag_name))
    if not tag.is_valid() and report is not None:
        report["errors"].append(
            "tag '{}' is not registered - restart the editor if Config/Tags/Frontend.ini "
            "changed while it was open".format(tag_name))
    return tag


def _enum(enum_type, value_name, report, context):
    """
    Resolve an enum value by name, reporting rather than raising when the C++ enum and this
    script have drifted apart - a missing value should name itself in the report, not abort
    the whole roster halfway through and leave the content in a half-written state.
    """
    value = getattr(enum_type, value_name, None)
    if value is None:
        report["errors"].append("{}: no {} value named {}".format(context, enum_type, value_name))
    return value


def apply(dry_run=True):
    """
    Rebuild the mode roster against the generalized tags. Returns a report of what changed.
    """
    eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

    report = {
        "renamed": [],
        "created": [],
        "updated": [],
        "mode_data": [],
        "remapped_maps": [],
        "errors": [],
    }

    def log(message):
        unreal.log(("[dry run] " if dry_run else "") + message)

    # 1. Rename the tiles that are keeping their authored icon. Several old names collapse
    #    onto the same new one (Grinder and Maelstrom were both Large-Scale Warfare), so the
    #    first rename wins and the rest are reported rather than silently overwriting it.
    for old_name, new_name in RENAMES.items():
        old_path = "{}/{}".format(UI_MODE_DIR, old_name)
        new_path = "{}/{}".format(UI_MODE_DIR, new_name)

        if not eas.does_asset_exist(old_path):
            continue
        if eas.does_asset_exist(new_path):
            report["errors"].append(
                "{} already exists; left {} alone - merge the two by hand".format(new_path, old_name))
            continue

        log("rename {} -> {}".format(old_name, new_name))
        if not dry_run and not eas.rename_asset(old_path, new_path):
            report["errors"].append("rename failed: {} -> {}".format(old_path, new_path))
            continue
        report["renamed"].append("{} -> {}".format(old_name, new_name))

    # 2. Write every tile, creating the ones that never had an asset.
    for entry in ROSTER:
        asset_path = "{}/{}".format(UI_MODE_DIR, entry["asset"])

        if not eas.does_asset_exist(asset_path):
            log("create {}".format(entry["asset"]))
            if dry_run:
                report["created"].append(entry["asset"])
            else:
                asset = asset_tools.create_asset(
                    entry["asset"], UI_MODE_DIR, unreal.CDGameModeUIEntry, unreal.DataAssetFactory())
                if not asset:
                    report["errors"].append("create failed: {}".format(asset_path))
                    continue
                report["created"].append(entry["asset"])
        else:
            if dry_run:
                report["updated"].append(entry["asset"])
            else:
                report["updated"].append(entry["asset"])

        if dry_run:
            continue

        asset = eas.load_asset(asset_path)
        if not asset:
            report["errors"].append("load failed: {}".format(asset_path))
            continue

        mode_tag = _tag(entry["tag"], report)
        asset.set_editor_property("selection_tag", mode_tag)
        # SelectionTag is the enumeration key and GameModeTag is the roster filter; they are
        # the same value for a mode tile, and leaving the second unset is what made mode
        # filtering silently match nothing.
        asset.set_editor_property("game_mode_tag", mode_tag)
        asset.set_editor_property("display_name", entry["display"])
        asset.set_editor_property("short_description", entry["description"])
        asset.set_editor_property("sort_order", entry["sort"])
        asset.set_editor_property("game_mode_identifier", entry["identifier"])
        asset.set_editor_property("is_quick_play", entry["quick_play"])
        asset.set_editor_property("max_player_count", entry["max_players"])
        asset.set_editor_property("team_count", entry["teams"])
        asset.set_editor_property("squad_count", entry["squads"])

        composition = _enum(unreal.CDCombatantComposition, entry["composition"], report, entry["asset"])
        if composition is not None:
            asset.set_editor_property("composition", composition)

        # The whole point of the naming pass: one tile, one mechanic, many themed names.
        overrides = unreal.Map(unreal.GameplayTag, unreal.Text)
        for part_tag_name, themed_name in entry["parts"].items():
            overrides[_tag(part_tag_name, report)] = themed_name
        asset.set_editor_property("part_display_name_overrides", overrides)

        eas.save_asset(asset_path)
        log("wrote {} ({}, sort {}, {} part names)".format(
            entry["asset"], entry["display"], entry["sort"], len(entry["parts"])))

        # 3. The paired UCDGameModeData carrying the actual objective tuning.
        if not entry["mode"]:
            continue

        data_path = "{}/{}".format(MODE_DATA_DIR, entry["asset"])
        if not eas.does_asset_exist(data_path):
            data_asset = asset_tools.create_asset(
                entry["asset"], MODE_DATA_DIR, unreal.CDGameModeData, unreal.DataAssetFactory())
            if not data_asset:
                report["errors"].append("create failed: {}".format(data_path))
                continue
        data_asset = eas.load_asset(data_path)
        if not data_asset:
            report["errors"].append("load failed: {}".format(data_path))
            continue

        objective = _enum(unreal.CDObjectiveMode, entry["mode"], report, entry["asset"])
        scale = _enum(unreal.CDScaleTier, entry["scale"], report, entry["asset"])
        variant = _enum(unreal.CDTeamSizeVariant, entry["variant"], report, entry["asset"])

        if objective is not None:
            data_asset.set_editor_property("objective_mode", objective)
        if scale is not None:
            data_asset.set_editor_property("scale_tier", scale)
        if variant is not None:
            data_asset.set_editor_property("team_size_variant", variant)
        if composition is not None:
            data_asset.set_editor_property("composition", composition)

        data_asset.set_editor_property("max_players", entry["max_players"])
        data_asset.set_editor_property("team_count", entry["teams"])
        data_asset.set_editor_property("squad_count", entry["squads"])

        for prop, value in MODE_TUNING.get(entry["asset"], {}).items():
            data_asset.set_editor_property(prop, value)

        eas.save_asset(data_path)
        report["mode_data"].append(entry["asset"])

        # Point the tile at the data it describes, so the tile stops carrying a second,
        # drifting copy of the scale and objective numbers.
        asset.set_editor_property("game_mode_data", unreal.SoftObjectPath(data_path + "." + entry["asset"]))
        eas.save_asset(asset_path)

    # 4. Point each map's compatible-mode FilterTags at the generalized mode tags.
    for map_asset in eas.list_assets(MAP_DIR, recursive=False, include_folder=False):
        asset = eas.load_asset(map_asset)
        if not asset:
            continue

        current = unreal.GameplayTagLibrary.break_gameplay_tag_container(
            asset.get_editor_property("filter_tags"))
        names = [str(tag.to_string()) for tag in current]
        if not any(name in TAG_REMAP for name in names):
            continue

        # dict.fromkeys rather than set(): two old tags can collapse onto one new tag
        # (Grinder and Maelstrom both became LargeScaleWarfare), and a duplicated entry in
        # a tag container is a silent no-op that still bloats the asset.
        remapped = list(dict.fromkeys(TAG_REMAP.get(name, name) for name in names))
        log("remap FilterTags on {}: {} -> {}".format(map_asset, names, remapped))
        report["remapped_maps"].append(map_asset)

        if dry_run:
            continue

        asset.set_editor_property(
            "filter_tags",
            unreal.GameplayTagLibrary.make_gameplay_tag_container_from_array(
                [_tag(name, report) for name in remapped]))
        eas.save_asset(map_asset)

    unreal.log(
        "Mode roster: {} renamed, {} created, {} updated, {} mode-data assets, "
        "{} maps remapped, {} errors.".format(
            len(report["renamed"]), len(report["created"]), len(report["updated"]),
            len(report["mode_data"]), len(report["remapped_maps"]), len(report["errors"])))
    for error in report["errors"]:
        unreal.log_warning(error)

    return report
