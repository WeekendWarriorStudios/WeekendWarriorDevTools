"""
Author the full game mode roster against the generalized mechanic tags.

Supersedes retag_game_modes.py, which applied the *previous* naming pass (the themed
tags UNSUNG / THE GRINDER / FRONTLINES / SKIRMISH / WARLORDS / ATTRITION / OVER THE TOP /
HOLDOUT / DEAD MAN'S LAND). That pass baked the shipped name into the tag, so every time a
mode was re-themed for a new Part the tag had to be reissued and every asset referencing it
retagged. This one inverts that:

  * the TAG is a generalized mechanic name, one-to-one with ECDObjectiveMode
    (UI.Selection.GameMode.Capture.AsymmetricWarfare, never .OverTheTop)
  * the SHIPPED NAME is presentation, and varies per Part through
    UCDGameModeUIEntry::PartDisplayNameOverrides (Part II renders that same mechanic
    as "OVER THE TOP")

Pairs with the UI.Selection.GameMode tags in Config/Tags/Frontend.ini, which also carries the
GameplayTagRedirects for every rename this roster has been through.

Note the tag hierarchy is an ENUMERATION KEY, not the Deploy layout: which shelf a mode appears
on is UCDGameModeData::ShelfFilterTags (UI.Shelf.*), authored per mode data asset and not
touched here. That split is deliberate - see the comment above the Deploy Shelf Filter Tags
block in Frontend.ini - so the UI.Selection.GameMode.* tree below can be reorganized without
moving anything on screen.

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

# Old mode tag -> current mode tag, for remapping the compatible-mode FilterTags on DA_Map_*.
# Mirrors the GameplayTagRedirects in Config/Tags/Frontend.ini; those fix the tag at load time,
# this rewrites the asset so the redirect can eventually be retired.
#
# Three generations deep now. Generation 3 (the flat mechanic names this script itself wrote on
# 2026-08-20) is in here too, because the hierarchy was re-nested under category tags immediately
# afterwards and nothing rewrote the assets that had already been saved.
#
# CAUTION: this is a legacy-migration table, and three of its left-hand names came back into use
# as CATEGORY tags in the re-nesting - UI.Selection.GameMode.Deathmatch, .Gauntlet and
# .BattleRoyale are all live parent tags today. Remapping them is only correct for data authored
# before 2026-08-20, when they were leaves. Do not reach for this table to migrate anything newer.
TAG_REMAP = {
    # Generation 1/2 (mechanic and themed) -> current
    "UI.Selection.GameMode.Warfare": "UI.Selection.GameMode.LargeScale.Warfare",
    "UI.Selection.GameMode.Grinder": "UI.Selection.GameMode.LargeScale.Warfare",
    "UI.Selection.GameMode.Maelstrom": "UI.Selection.GameMode.LargeScale.Warfare",
    "UI.Selection.GameMode.Conquest": "UI.Selection.GameMode.Capture.PointCapture",
    "UI.Selection.GameMode.Frontlines": "UI.Selection.GameMode.Capture.PointCapture",
    "UI.Selection.GameMode.Escalation": "UI.Selection.GameMode.Capture.PointMajority",
    "UI.Selection.GameMode.Attrition": "UI.Selection.GameMode.Capture.PointMajority",
    "UI.Selection.GameMode.Breakthrough": "UI.Selection.GameMode.Capture.AsymmetricWarfare",
    "UI.Selection.GameMode.OverTheTop": "UI.Selection.GameMode.Capture.AsymmetricWarfare",
    "UI.Selection.GameMode.Spearhead": "UI.Selection.GameMode.Capture.AsymmetricWarfare",
    "UI.Selection.GameMode.Skirmish": "UI.Selection.GameMode.Deathmatch.TeamDeathmatch",
    "UI.Selection.GameMode.Warlords": "UI.Selection.GameMode.Deathmatch.SquadDeathmatch",
    "UI.Selection.GameMode.SpecialOps": "UI.Selection.GameMode.Stories.Operations.Operations",
    "UI.Selection.GameMode.Unsung": "UI.Selection.GameMode.Stories.Operations.Operations",
    "UI.Selection.GameMode.UnsungOps": "UI.Selection.GameMode.Stories.Operations.Operations",
    "UI.Selection.GameMode.Zombies": "UI.Selection.GameMode.Stories.Zombies.ZombieSurvival",
    "UI.Selection.GameMode.DeadMansLand": "UI.Selection.GameMode.Stories.Zombies.ZombieSurvival",
    "UI.Selection.GameMode.LastStand": "UI.Selection.GameMode.Stories.Zombies.ZombieSurvival",
    "UI.Selection.GameMode.Holdout": "UI.Selection.GameMode.Stories.Zombies.ZombieSurvival",
    # Generation 3 (flat generalized) -> current. See the CAUTION above before reusing these.
    "UI.Selection.GameMode.Deathmatch": "UI.Selection.GameMode.Deathmatch.Deathmatch",
    "UI.Selection.GameMode.TeamDeathmatch": "UI.Selection.GameMode.Deathmatch.TeamDeathmatch",
    "UI.Selection.GameMode.SquadDeathmatch": "UI.Selection.GameMode.Deathmatch.SquadDeathmatch",
    "UI.Selection.GameMode.PointCapture": "UI.Selection.GameMode.Capture.PointCapture",
    "UI.Selection.GameMode.PointMajority": "UI.Selection.GameMode.Capture.PointMajority",
    "UI.Selection.GameMode.PointRotation": "UI.Selection.GameMode.Capture.PointRotation",
    "UI.Selection.GameMode.AsymmetricWarfare": "UI.Selection.GameMode.Capture.AsymmetricWarfare",
    "UI.Selection.GameMode.Arcade.CaptureTheFlag": "UI.Selection.GameMode.Capture.CaptureTheFlag",
    "UI.Selection.GameMode.Arcade.Gauntlet": "UI.Selection.GameMode.Gauntlet",
    "UI.Selection.GameMode.Arcade.Gauntlet.Solos": "UI.Selection.GameMode.Gauntlet.Solos",
    "UI.Selection.GameMode.Arcade.Gauntlet.Duos": "UI.Selection.GameMode.Gauntlet.Duos",
    "UI.Selection.GameMode.Arcade.Gauntlet.Trios": "UI.Selection.GameMode.Gauntlet.Trios",
    "UI.Selection.GameMode.Arcade.Gauntlet.Squads": "UI.Selection.GameMode.Gauntlet.Squads",
    "UI.Selection.GameMode.TrainingCourse": "UI.Selection.GameMode.Training.TrainingCourse",
    "UI.Selection.GameMode.ZombieSurvival": "UI.Selection.GameMode.Stories.Zombies.ZombieSurvival",
    "UI.Selection.GameMode.Operations": "UI.Selection.GameMode.Stories.Operations.Operations",
    "UI.Selection.GameMode.LargeScaleWarfare": "UI.Selection.GameMode.LargeScale.Warfare",
    "UI.Selection.GameMode.BattleRoyale": "UI.Selection.GameMode.LargeScale.BattleRoyale",
    "UI.Selection.GameMode.BattleRoyale.Solos": "UI.Selection.GameMode.LargeScale.BattleRoyale.Solos",
    "UI.Selection.GameMode.BattleRoyale.Duos": "UI.Selection.GameMode.LargeScale.BattleRoyale.Duos",
    "UI.Selection.GameMode.BattleRoyale.Trios": "UI.Selection.GameMode.LargeScale.BattleRoyale.Trios",
    "UI.Selection.GameMode.BattleRoyale.Squads": "UI.Selection.GameMode.LargeScale.BattleRoyale.Squads",
}

# The roster, in tile order — every UI.Selection.GameMode.* leaf in Config/Tags/Frontend.ini.
#
#   display     the generalized fallback name, used by any Part with no override
#   subtitle    optional. The buy-in line on a wager/ranked tile. Omit the key entirely to
#               leave an authored subtitle alone rather than blanking it.
#   parts       PartTag -> themed name for that era. Absent Part = falls back to `display`,
#               which is the point of the fallback: a mode that reads the same everywhere
#               needs no entry at all, and a mode that does not fit an era (mustard gas in
#               1899) is simply left out rather than given a forced name.
#   mode        ECDObjectiveMode value name on the paired UCDGameModeData
#   variant     ECDTeamSizeVariant value name, for the Gauntlet/BattleRoyale sub-tags
#
# One leaf tag has no row: UI.Selection.GameMode.Arcade.GasScramble is registered but has no
# DA_GameMode_GasScramble asset. Its row is kept below so a run creates the tile - the tag was
# authored deliberately and enumeration is by asset, so today it produces nothing on screen.
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
        "tag": "UI.Selection.GameMode.Deathmatch.Deathmatch",
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
        "tag": "UI.Selection.GameMode.Deathmatch.TeamDeathmatch",
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
        "tag": "UI.Selection.GameMode.Deathmatch.SquadDeathmatch",
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
        "tag": "UI.Selection.GameMode.Capture.PointCapture",
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
        "tag": "UI.Selection.GameMode.Capture.PointMajority",
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
        "tag": "UI.Selection.GameMode.Capture.PointRotation",
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
        "tag": "UI.Selection.GameMode.Capture.AsymmetricWarfare",
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
        "tag": "UI.Selection.GameMode.Capture.CaptureTheFlag",
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
        "tag": "UI.Selection.GameMode.Gauntlet",
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
        "tag": "UI.Selection.GameMode.Gauntlet.Solos",
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
        "tag": "UI.Selection.GameMode.Gauntlet.Duos",
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
        "tag": "UI.Selection.GameMode.Gauntlet.Trios",
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
        "tag": "UI.Selection.GameMode.Gauntlet.Squads",
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
        "tag": "UI.Selection.GameMode.Training.TrainingCourse",
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
        "tag": "UI.Selection.GameMode.Stories.Zombies.ZombieSurvival",
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
        "tag": "UI.Selection.GameMode.Stories.Operations.Operations",
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
        "tag": "UI.Selection.GameMode.LargeScale.Warfare",
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
        "tag": "UI.Selection.GameMode.LargeScale.BattleRoyale",
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
        "tag": "UI.Selection.GameMode.LargeScale.BattleRoyale.Solos",
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
        "tag": "UI.Selection.GameMode.LargeScale.BattleRoyale.Duos",
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
        "tag": "UI.Selection.GameMode.LargeScale.BattleRoyale.Trios",
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
        "tag": "UI.Selection.GameMode.LargeScale.BattleRoyale.Squads",
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
    # ---- Wagered ------------------------------------------------------------
    # Third rule layer over an existing mechanic, not new mechanics: every row below reuses an
    # ECDObjectiveMode that already ships unwagered above, and differs only in what is on the
    # table. The stake itself is NOT listed here - StakeMode/WagerRules/RankedRules are mirrored
    # off the paired UCDGameModeData at write time (see apply()), because
    # UCDGameModeUIEntry::IsDataValid errors on the tile and the mode data disagreeing about
    # stakes, and a second hand-maintained copy in this table is exactly how they would.
    #
    # `subtitle` appears here and nowhere above because a wager tile has to state its buy-in
    # before a player commits. Rows without the key leave whatever subtitle is authored alone.
    {
        "asset": "DA_GameMode_Wager_Deathmatch",
        "tag": "UI.Selection.GameMode.Wager.Deathmatch",
        "display": "WAGER DEATHMATCH",
        "subtitle": "250 CREDITS TO ENTER",
        "parts": {},
        "description": "Same sixteen men, same no allies - except now 250 credits rides on it, and losing forfeits the stake.",
        "identifier": "WagerDeathmatch",
        "sort": 600,
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
        "asset": "DA_GameMode_Wager_Duel",
        "tag": "UI.Selection.GameMode.Wager.Duel",
        "display": "WAGER DUEL",
        "subtitle": "2,500 CREDITS TO ENTER",
        "parts": {},
        "description": "One round in the chamber, blood money on the table. A kill buys the next round; a miss buys nothing back.",
        "identifier": "WagerDuel",
        "sort": 610,
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
        "asset": "DA_GameMode_Wager_TeamDeathmatch",
        "tag": "UI.Selection.GameMode.Wager.Deathmatch.TeamDeathmatch",
        "display": "WAGER TEAM DEATHMATCH",
        "subtitle": "2,500 CREDITS TO ENTER",
        "parts": {},
        "description": "Same two sides as always - except now 2,500 credits and a patch ride on it, and losing forfeits the stake.",
        "identifier": "WagerTeamDeathmatch",
        "sort": 615,
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
        "asset": "DA_GameMode_Wager_PointRotation",
        "tag": "UI.Selection.GameMode.Wager.PointRotation",
        "display": "WAGER POINT ROTATION",
        "subtitle": "1,000 CREDITS TO ENTER",
        "parts": {},
        "description": "Four squads, one relocating point, 1,000 credits riding on whoever is standing on it when it matters.",
        "identifier": "WagerPointRotation",
        "sort": 620,
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
        "asset": "DA_GameMode_Wager_Duos_SquadDeathmatch",
        "tag": "UI.Selection.GameMode.Wager.Gauntlet.Duos.SquadDeathmatch",
        "display": "WAGER DUOS - SQUAD DEATHMATCH",
        "subtitle": "250 CREDITS TO ENTER",
        "parts": {},
        "description": "Four duos, no allies between them, 250 credits a head and a draft for whatever the losers staked.",
        "identifier": "WagerDuosSquadDeathmatch",
        "sort": 630,
        "quick_play": False,
        "mode": "SQUAD_DEATHMATCH",
        "max_players": 8,
        "teams": 0,
        "squads": 4,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "DUOS",
    },
    {
        "asset": "DA_GameMode_Wager_Duos_TeamDeathmatch",
        "tag": "UI.Selection.GameMode.Wager.Gauntlet.Duos.TeamDeathmatch",
        "display": "WAGER DUOS - TEAM DEATHMATCH",
        "subtitle": "1,000 CREDITS TO ENTER",
        "parts": {},
        "description": "Two pairs, 1,000 credits, no second half to this match.",
        "identifier": "WagerDuosTeamDeathmatch",
        "sort": 631,
        "quick_play": False,
        "mode": "TEAM_DEATHMATCH",
        "max_players": 4,
        "teams": 2,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "DUOS",
    },
    {
        "asset": "DA_GameMode_Wager_Squads_SquadDeathmatch",
        "tag": "UI.Selection.GameMode.Wager.Gauntlet.Squads.SquadDeathmatch",
        "display": "WAGER SQUADS - SQUAD DEATHMATCH",
        "subtitle": "250 CREDITS TO ENTER",
        "parts": {},
        "description": "Four full squads, no allies, 250 credits a head on the table.",
        "identifier": "WagerSquadsSquadDeathmatch",
        "sort": 632,
        "quick_play": False,
        "mode": "SQUAD_DEATHMATCH",
        "max_players": 16,
        "teams": 0,
        "squads": 4,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "SQUADS",
    },
    {
        "asset": "DA_GameMode_Wager_Squads_TeamDeathmatch",
        "tag": "UI.Selection.GameMode.Wager.Gauntlet.Squads.TeamDeathmatch",
        "display": "WAGER SQUADS - TEAM DEATHMATCH",
        "subtitle": "1,000 CREDITS TO ENTER",
        "parts": {},
        "description": "Two four-man sides, 1,000 credits, nothing else on the line.",
        "identifier": "WagerSquadsTeamDeathmatch",
        "sort": 633,
        "quick_play": False,
        "mode": "TEAM_DEATHMATCH",
        "max_players": 8,
        "teams": 2,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "SQUADS",
    },
    {
        "asset": "DA_GameMode_Wager_Trios_SquadDeathmatch",
        "tag": "UI.Selection.GameMode.Wager.Gauntlet.Trios.SquadDeathmatch",
        "display": "WAGER TRIOS - SQUAD DEATHMATCH",
        "subtitle": "1,000 CREDITS TO ENTER",
        "parts": {},
        "description": "Four trios, no allies, 1,000 credits per player on the table.",
        "identifier": "WagerTriosSquadDeathmatch",
        "sort": 634,
        "quick_play": False,
        "mode": "SQUAD_DEATHMATCH",
        "max_players": 12,
        "teams": 0,
        "squads": 4,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "TRIOS",
    },
    {
        "asset": "DA_GameMode_Wager_Trios_TeamDeathmatch",
        "tag": "UI.Selection.GameMode.Wager.Gauntlet.Trios.TeamDeathmatch",
        "display": "WAGER TRIOS - TEAM DEATHMATCH",
        "subtitle": "1,000 CREDITS TO ENTER",
        "parts": {},
        "description": "Two three-man sides, 1,000 credits, straight up.",
        "identifier": "WagerTriosTeamDeathmatch",
        "sort": 635,
        "quick_play": False,
        "mode": "TEAM_DEATHMATCH",
        "max_players": 6,
        "teams": 2,
        "squads": 0,
        "scale": "CLOSE_QUARTERS",
        "composition": "PV_P",
        "variant": "TRIOS",
    },
    # ---- Ranked -------------------------------------------------------------
    # Invite-only ladder. The tile still ships for an ineligible player (rendered locked) -
    # see UCDRankedRuleSet::IsEligibleForInvite - so these are ordinary roster rows, not
    # something gated out of the roster itself.
    {
        "asset": "DA_GameMode_Ranked_Deathmatch",
        "tag": "UI.Selection.GameMode.Ranked.Deathmatch",
        "display": "RANKED DEATHMATCH",
        "subtitle": "INVITE ONLY - RATING AT STAKE",
        "parts": {},
        "description": "The ladder's deathmatch. No credits down - the stake is rating, and leaving costs it.",
        "identifier": "RankedDeathmatch",
        "sort": 700,
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
        "asset": "DA_GameMode_Ranked_PointRotation",
        "tag": "UI.Selection.GameMode.Ranked.PointRotation",
        "display": "RANKED POINT ROTATION",
        "subtitle": "INVITE ONLY - RATING AT STAKE",
        "parts": {},
        "description": "The ladder's objective mode. No credits down - the stake is rating, and leaving costs it.",
        "identifier": "RankedPointRotation",
        "sort": 701,
        "quick_play": False,
        "mode": "POINT_ROTATION",
        "max_players": 64,
        "teams": 0,
        "squads": 4,
        "scale": "LARGE_SCALE",
        "composition": "PV_P",
        "variant": "NONE",
    },
]

# Objective tuning that is not derivable from the roster row above. Anything absent keeps
# the UCDGameModeData class default.
#
# On min_players: every small-scale mode below sat at UCDGameModeData's default of 16 until
# 2026-09-03, which is ABOVE MaxPlayers on all of them - the mode could never reach its own start
# threshold. Each value is the mode's own DevComment in Config/Tags/Frontend.ini rather than a
# guess: the fixed-format Gauntlet variants need a full lobby (their wagered equivalents were
# already authored min == max), Duel is "2 to 8-player", Trench Raid "4v4 or 6v6", No Man's Land
# and Gas Scramble are 8-player round elimination, and the two co-op PvE modes are explicitly
# solo-playable ("1 to 4-player", "Up to 8-player").
MODE_TUNING = {
    "DA_GameMode_PointMajority": {"points_to_eliminate_for_win": 3},
    "DA_GameMode_PointRotation": {"rotation_interval_seconds": 90.0},
    "DA_GameMode_NoMansLand": {"min_players": 8, "rounds_to_win": 7, "lives_per_round": 1},
    "DA_GameMode_GasScramble": {"min_players": 8, "rounds_to_win": 5, "lives_per_round": 1},
    "DA_GameMode_Duel": {"min_players": 2, "rounds_to_win": 5, "lives_per_round": 1},
    "DA_GameMode_TrenchRaid": {"min_players": 8, "rounds_to_win": 5, "lives_per_round": 1},
    "DA_GameMode_Gauntlet": {"min_players": 8},
    "DA_GameMode_Gauntlet_Solos": {"min_players": 2},
    "DA_GameMode_Gauntlet_Duos": {"min_players": 4},
    "DA_GameMode_Gauntlet_Trios": {"min_players": 6},
    "DA_GameMode_Gauntlet_Squads": {"min_players": 8},
    "DA_GameMode_Operations": {"min_players": 1},
    "DA_GameMode_TrainingCourse": {"match_time_limit_seconds": 0.0, "warmup_time_seconds": 0.0},
    # Matches DA_Objective_SurviveWaves' own TargetCount (author_game_mode_rules.py) -
    # UCDSurviveWavesObjectiveComponent feeds the generic score-target win
    # condition one point per wave, so the two have to agree on 10 or the
    # match and the briefing disagree about how many waves it takes.
    "DA_GameMode_ZombieSurvival": {"min_players": 1, "score_target": 10},
    # Matches DA_Objective_CaptureFlags' own TargetCount - first team to 3
    # captures wins, and UCDCaptureTheFlagObjectiveComponent's FlagCaptured
    # credit is what has to reach this number.
    "DA_GameMode_CaptureTheFlag": {"score_target": 3},

    # Wagered and ranked modes run short and tight: a match with credits or rating on it cannot
    # be a thirty-minute commitment, and the longer warmup is the window to back out before the
    # stake is escrowed. min_players is authored here rather than left at the class default
    # because a wager match that starts under-filled hands someone a walkover for real money.
    "DA_GameMode_Wager_Deathmatch": {
        "min_players": 8, "score_target": 40, "match_time_limit_seconds": 900.0, "warmup_time_seconds": 45.0},
    "DA_GameMode_Wager_Duel": {
        "min_players": 2, "rounds_to_win": 5, "lives_per_round": 1,
        "match_time_limit_seconds": 600.0, "warmup_time_seconds": 45.0},
    "DA_GameMode_Wager_TeamDeathmatch": {"warmup_time_seconds": 45.0},
    "DA_GameMode_Wager_PointRotation": {
        "score_target": 300, "match_time_limit_seconds": 600.0, "warmup_time_seconds": 45.0},
    "DA_GameMode_Wager_Duos_SquadDeathmatch": {
        "min_players": 8, "score_target": 40, "match_time_limit_seconds": 720.0, "warmup_time_seconds": 45.0},
    "DA_GameMode_Wager_Duos_TeamDeathmatch": {
        "min_players": 4, "score_target": 30, "match_time_limit_seconds": 720.0, "warmup_time_seconds": 45.0},
    "DA_GameMode_Wager_Squads_SquadDeathmatch": {
        "min_players": 16, "score_target": 40, "match_time_limit_seconds": 720.0, "warmup_time_seconds": 45.0},
    "DA_GameMode_Wager_Squads_TeamDeathmatch": {
        "min_players": 8, "score_target": 30, "match_time_limit_seconds": 720.0, "warmup_time_seconds": 45.0},
    "DA_GameMode_Wager_Trios_SquadDeathmatch": {
        "min_players": 12, "score_target": 40, "match_time_limit_seconds": 720.0, "warmup_time_seconds": 45.0},
    "DA_GameMode_Wager_Trios_TeamDeathmatch": {
        "min_players": 6, "score_target": 30, "match_time_limit_seconds": 720.0, "warmup_time_seconds": 45.0},
    "DA_GameMode_Ranked_Deathmatch": {
        "min_players": 8, "score_target": 50, "match_time_limit_seconds": 900.0},
    "DA_GameMode_Ranked_PointRotation": {
        "min_players": 16, "score_target": 300, "match_time_limit_seconds": 600.0},
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
    # unreal.GameplayTag has no is_valid() of its own - the struct exposes no
    # members at all in Python - so validity has to come from the tag library.
    if not unreal.GameplayTagLibrary.is_gameplay_tag_valid(tag) and report is not None:
        report["errors"].append(
            "tag '{}' is not registered - restart the editor if Config/Tags/Frontend.ini "
            "changed while it was open".format(tag_name))
    return tag


#: Object-valued tile fields that are a presentation copy of the paired UCDGameModeData's, not a
#: second source of truth. UCDGameModeUIEntry::IsDataValid raises an error for each one that
#: disagrees - the match runs on the mode data's value, so a tile out of step advertises rules,
#: rewards or stakes the player is not going to get. Mirrored rather than listed per roster row
#: for exactly that reason: a hand-maintained second copy here would be one more place to drift.
#:
#: Every one needs converting rather than assigning across: UCDGameModeData holds these as hard
#: TObjectPtr and UCDGameModeUIEntry as TSoftObjectPtr, so the tile can draw a briefing panel
#: without pulling the whole mode payload in behind it.
MIRRORED_FROM_MODE_DATA = [
    "rule_set",
    "reward_set",
    "wager_rules",
    "ranked_rules",
]


def _soft(value):
    """Hard reference off the mode data -> soft reference for the tile. Unset stays unset."""
    return unreal.SoftObjectPath(value.get_path_name()) if value else unreal.SoftObjectPath()


def _mirror_mode_data(tile, mode_data, report, context):
    """
    Copy the drift-validated presentation fields off the mode data onto its tile.

    Reports rather than raises, on the same reasoning as _enum: a property that will not
    round-trip should name itself and let the rest of the roster finish, not abort the run
    with the content half written.
    """
    for prop in MIRRORED_FROM_MODE_DATA:
        try:
            tile.set_editor_property(prop, _soft(mode_data.get_editor_property(prop)))
        except Exception as error:
            report["errors"].append("{}: could not mirror {} - {}".format(context, prop, error))

    # StakeMode is a plain enum on both sides, so it copies straight across. It is the field that
    # decides whether the stakes panel renders at all, which is why the tile carries its own copy.
    try:
        tile.set_editor_property("stake_mode", mode_data.get_editor_property("stake_mode"))
    except Exception as error:
        report["errors"].append("{}: could not mirror stake_mode - {}".format(context, error))

    # IsDataValid compares objective membership only, not order, so rebuilding the list wholesale
    # is safe - the tile is free to brief them in whatever order reads best.
    try:
        objectives = mode_data.get_editor_property("objectives") or []
        tile.set_editor_property("objectives", [_soft(o) for o in objectives if o])
    except Exception as error:
        report["errors"].append("{}: could not mirror objectives - {}".format(context, error))


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
        # Optional on purpose - a row with no `subtitle` leaves whatever a designer authored in
        # place rather than blanking it, which is what an unconditional write would do.
        if "subtitle" in entry:
            asset.set_editor_property("subtitle", entry["subtitle"])
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
        _mirror_mode_data(asset, data_asset, report, entry["asset"])
        eas.save_asset(asset_path)

    # 4. Point each map's compatible-mode FilterTags at the generalized mode tags.
    for map_asset in eas.list_assets(MAP_DIR, recursive=False, include_folder=False):
        asset = eas.load_asset(map_asset)
        if not asset:
            continue

        current = unreal.GameplayTagLibrary.break_gameplay_tag_container(
            asset.get_editor_property("filter_tags"))
        names = [str(unreal.GameplayTagLibrary.get_tag_name(tag)) for tag in current]
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
