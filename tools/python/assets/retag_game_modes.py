"""
Rebuild the Deploy mode roster and trim the start-screen Part list to Part I.

Applies the shipped mode names (UNSUNG, THE GRINDER, FRONTLINES, SKIRMISH, WARLORDS,
ATTRITION, OVER THE TOP, HOLDOUT, DEAD MAN'S LAND) over the old mechanic-named tiles,
adds the three tiles that had no asset yet, and deletes the Part II-V cards.

Pairs with the UI.Selection.GameMode / UI.Selection.Part tags in Config/Tags/Frontend.ini.
RESTART THE EDITOR BEFORE RUNNING THIS: the tag table is read at startup, so an editor that
was already open when Frontend.ini changed does not know the new tags and every
request_gameplay_tag call below will fail.

Run from the Unreal Editor Python console:
    import retag_game_modes
    retag_game_modes.apply(dry_run=True)
    retag_game_modes.apply(dry_run=False)

Afterwards, right-click Content/CollateralDamage/UI and choose "Fix Up Redirectors in Folder"
to clear the redirectors the renames leave behind.
"""

import unreal

MODE_DIR = "/Game/CollateralDamage/UI/Data/GameModes"
PART_DIR = "/Game/CollateralDamage/UI/Data/Parts"
MAP_DIR = "/Game/CollateralDamage/UI/Data/Maps"

TAG_ROOT = "UI.Selection.GameMode"

# Old asset name -> new asset name. Renaming (rather than create + delete) keeps whatever
# Icon the designer already assigned on the tile.
RENAMES = {
    "DA_GameMode_Warfare": "DA_GameMode_Grinder",
    "DA_GameMode_Conquest": "DA_GameMode_Frontlines",
    "DA_GameMode_Escalation": "DA_GameMode_Attrition",
    "DA_GameMode_SpecialOps": "DA_GameMode_Unsung",
    "DA_GameMode_LastStand": "DA_GameMode_Holdout",
    "DA_GameMode_Zombies": "DA_GameMode_DeadMansLand",
}

# Old mode tag -> new mode tag, for remapping the compatible-mode FilterTags on DA_Map_*.
TAG_REMAP = {
    "UI.Selection.GameMode.Warfare": "UI.Selection.GameMode.Grinder",
    "UI.Selection.GameMode.Conquest": "UI.Selection.GameMode.Frontlines",
    "UI.Selection.GameMode.Escalation": "UI.Selection.GameMode.Attrition",
    "UI.Selection.GameMode.SpecialOps": "UI.Selection.GameMode.Unsung",
    "UI.Selection.GameMode.LastStand": "UI.Selection.GameMode.Holdout",
    "UI.Selection.GameMode.Zombies": "UI.Selection.GameMode.DeadMansLand",
}

# The roster, in tile order. `identifier` matches FCDSessionSettings::GameModeIdentifier /
# FCDMatchmakingFilter::GameModeIdentifier; GameModeData is left alone here because the
# authoritative UCDGameModeData assets are not authored yet.
ROSTER = [
    {
        "asset": "DA_GameMode_QuickPlay",
        "tag": "UI.Selection.GameMode.QuickPlay",
        "display": "QUICK PLAY",
        "description": "Straight into the nearest match. No map vote, no waiting.",
        "identifier": "QuickPlay",
        "sort": 0,
        "quick_play": True,
    },
    {
        "asset": "DA_GameMode_Grinder",
        "tag": "UI.Selection.GameMode.Grinder",
        "display": "THE GRINDER",
        "description": "32v32 combined arms. Bodies fed into the front until one side runs out.",
        "identifier": "Grinder",
        "sort": 10,
        "quick_play": False,
    },
    {
        "asset": "DA_GameMode_Frontlines",
        "tag": "UI.Selection.GameMode.Frontlines",
        "display": "FRONTLINES",
        "description": "Two armies, a line of sectors, and a meter that only moves while you hold ground.",
        "identifier": "Frontlines",
        "sort": 20,
        "quick_play": False,
    },
    {
        "asset": "DA_GameMode_Attrition",
        "tag": "UI.Selection.GameMode.Attrition",
        "display": "ATTRITION",
        "description": "Bleed them white. Every sector you break stays broken - the enemy never gets it back.",
        "identifier": "Attrition",
        "sort": 30,
        "quick_play": False,
    },
    {
        "asset": "DA_GameMode_OverTheTop",
        "tag": "UI.Selection.GameMode.OverTheTop",
        "display": "OVER THE TOP",
        "description": "Whistle, ladder, open ground. Attackers take the sectors in order; defenders make every yard cost.",
        "identifier": "OverTheTop",
        "sort": 40,
        "quick_play": False,
    },
    {
        "asset": "DA_GameMode_Skirmish",
        "tag": "UI.Selection.GameMode.Skirmish",
        "display": "SKIRMISH",
        "description": "8v8, close and fast. No objectives, no vehicles - just the two sides and the ground between.",
        "identifier": "Skirmish",
        "sort": 50,
        "quick_play": False,
    },
    {
        "asset": "DA_GameMode_Warlords",
        "tag": "UI.Selection.GameMode.Warlords",
        "display": "WARLORDS",
        "description": "Four squads, no allies. Carve out what you can hold and kill anyone who wants it.",
        "identifier": "Warlords",
        "sort": 60,
        "quick_play": False,
    },
    {
        "asset": "DA_GameMode_Unsung",
        "tag": "UI.Selection.GameMode.Unsung",
        "display": "UNSUNG",
        "description": "Real operations nobody wrote down. Small squad, narrow objective, no reinforcements coming.",
        "identifier": "Unsung",
        "sort": 70,
        "quick_play": False,
    },
    {
        "asset": "DA_GameMode_Holdout",
        "tag": "UI.Selection.GameMode.Holdout",
        "display": "HOLDOUT",
        "description": "You and three others, dug in, no way out. Hold the chokepoint until the waves stop - or you do.",
        "identifier": "Holdout",
        "sort": 80,
        "quick_play": False,
    },
    {
        "asset": "DA_GameMode_DeadMansLand",
        "tag": "UI.Selection.GameMode.DeadMansLand",
        "display": "DEAD MAN'S LAND",
        "description": "The dead came back over the wire at Osowiec. Co-op survival against a horde that does not stop.",
        "identifier": "DeadMansLand",
        "sort": 90,
        "quick_play": False,
    },
]

# Part II-V cards come off the start screen; the design docs under
# Documentation/collateral-damage-design-documentation/Settings remain the roadmap record.
PARTS_TO_DELETE = ["DA_Part_II", "DA_Part_III", "DA_Part_IV", "DA_Part_V"]


def _tag(tag_name: str) -> unreal.GameplayTag:
    return unreal.GameplayTagLibrary.request_gameplay_tag(unreal.Name(tag_name))


def apply(dry_run: bool = True) -> dict:
    """
    Rebuild the mode roster and trim the Part list. Returns a report of what changed.
    """
    eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()

    report = {"renamed": [], "created": [], "updated": [], "deleted": [], "remapped_maps": [], "errors": []}

    def log(message: str) -> None:
        unreal.log(("[dry run] " if dry_run else "") + message)

    # 1. Rename the tiles that are keeping their authored icon.
    for old_name, new_name in RENAMES.items():
        old_path = f"{MODE_DIR}/{old_name}"
        new_path = f"{MODE_DIR}/{new_name}"

        if not eas.does_asset_exist(old_path):
            continue
        if eas.does_asset_exist(new_path):
            report["errors"].append(f"{new_path} already exists; skipped rename of {old_name}")
            continue

        log(f"rename {old_name} -> {new_name}")
        if not dry_run and not eas.rename_asset(old_path, new_path):
            report["errors"].append(f"rename failed: {old_path} -> {new_path}")
            continue
        report["renamed"].append(f"{old_name} -> {new_name}")

    # 2. Create the tiles that never had an asset, then write every tile's presentation data.
    for entry in ROSTER:
        asset_path = f"{MODE_DIR}/{entry['asset']}"

        if not eas.does_asset_exist(asset_path):
            log(f"create {entry['asset']}")
            if dry_run:
                report["created"].append(entry["asset"])
                continue

            asset = asset_tools.create_asset(
                entry["asset"], MODE_DIR, unreal.CDGameModeUIEntry, unreal.DataAssetFactory()
            )
            if not asset:
                report["errors"].append(f"create failed: {asset_path}")
                continue
            report["created"].append(entry["asset"])
        else:
            if dry_run:
                report["updated"].append(entry["asset"])
                continue
            asset = eas.load_asset(asset_path)
            if not asset:
                report["errors"].append(f"load failed: {asset_path}")
                continue
            report["updated"].append(entry["asset"])

        asset.set_editor_property("selection_tag", _tag(entry["tag"]))
        asset.set_editor_property("display_name", entry["display"])
        asset.set_editor_property("short_description", entry["description"])
        asset.set_editor_property("sort_order", entry["sort"])
        asset.set_editor_property("game_mode_identifier", entry["identifier"])
        asset.set_editor_property("is_quick_play", entry["quick_play"])
        eas.save_asset(asset_path)
        log(f"wrote {entry['asset']} ({entry['display']}, sort {entry['sort']})")

    # 3. Point each map's compatible-mode FilterTags at the renamed mode tags.
    for map_asset in eas.list_assets(MAP_DIR, recursive=False, include_folder=False):
        asset = eas.load_asset(map_asset)
        if not asset:
            continue

        current = unreal.GameplayTagLibrary.break_gameplay_tag_container(
            asset.get_editor_property("filter_tags")
        )
        names = [str(tag.to_string()) for tag in current]
        if not any(name in TAG_REMAP for name in names):
            continue

        remapped = [TAG_REMAP.get(name, name) for name in names]
        log(f"remap FilterTags on {map_asset}: {names} -> {remapped}")
        report["remapped_maps"].append(map_asset)

        if dry_run:
            continue

        asset.set_editor_property(
            "filter_tags",
            unreal.GameplayTagLibrary.make_gameplay_tag_container_from_array(
                [_tag(name) for name in remapped]
            ),
        )
        eas.save_asset(map_asset)

    # 4. Trim the Part list down to Part I.
    for part_name in PARTS_TO_DELETE:
        part_path = f"{PART_DIR}/{part_name}"
        if not eas.does_asset_exist(part_path):
            continue

        log(f"delete {part_name}")
        if not dry_run and not eas.delete_asset(part_path):
            report["errors"].append(f"delete failed: {part_path}")
            continue
        report["deleted"].append(part_name)

    unreal.log(
        f"Mode roster: {len(report['renamed'])} renamed, {len(report['created'])} created, "
        f"{len(report['updated'])} updated, {len(report['remapped_maps'])} maps remapped, "
        f"{len(report['deleted'])} Part cards deleted, {len(report['errors'])} errors."
    )
    for error in report["errors"]:
        unreal.log_warning(error)

    return report
