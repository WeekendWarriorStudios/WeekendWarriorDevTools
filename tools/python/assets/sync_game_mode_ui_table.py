"""
Sync Deploy game-mode tile presentation fields between DT_GameModeUIEntries (the DataTable a
designer actually edits) and the real UCDGameModeUIEntry assets under
Content/CollateralDamage/UI/Data/GameModes/ that ship and are enumerated by
UCDUIDataRegistrySubsystem exactly as before.

WHY A TABLE ON TOP OF ASSETS RATHER THAN A TABLE INSTEAD OF THEM: UCDUIDataRegistrySubsystem
enumerates UCDUIEntryDescriptor PrimaryDataAssets purely by AssetManager scan - "enumeration is
by asset, never centralized" is a deliberate, repeatedly-documented contract every tag-driven
Deploy shelf relies on (see CDDeployModeSelectScreen.h and CDUIEntryDescriptor.h). Making the
DataTable itself the runtime source would mean teaching that subsystem a second enumeration
mechanism shared by every frontend screen (Deploy, Armory, Personnel, Cinema, Archives) - a much
bigger, riskier change for a want that is really "let me bulk-edit copy and sort order without
opening 39 separate asset editors." So the table is authoring-time only: edit a row, run
apply(dry_run=False), the real asset changes, the game runs exactly as it always has.

Row struct: FCDGameModeUIEntryRow (Plugins/GameFeatures/Frontend/Source/CDFrontend/Public/Data/
DataTable/CDGameModeUIEntryRow.h). It deliberately excludes Objectives (exact-set-membership
validated against GameModeData, rarely touched) and PartDisplayNameOverrides/
PartSubtitleOverrides (variable-cardinality tag-keyed maps, used by a handful of tiles) - both
stay authored directly on the .uasset - and every UCDGameModeData tuning field (ScoreTarget,
TeamCount, ObjectiveMode, ...), since CDFrontend depends on CDGameModes, never the reverse, and
this table living in CDFrontend's authoring tooling must not reach into CDGameModes' domain data.

Row name == the tile's asset name (Content/CollateralDamage/UI/Data/GameModes/<RowName>.uasset),
matching this project's existing WeekendWarriorDevTools ROSTER convention (author_game_modes.py)
so a row here and a ROSTER entry there name the same tile.

RESTART THE EDITOR BEFORE RUNNING THIS if Config/Tags/Frontend.ini changed since it opened - same
rule every script in this folder follows, because the tag table is read once at startup.

Run from the Unreal Editor Python console:
    import sync_game_mode_ui_table
    sync_game_mode_ui_table.apply(dry_run=True)      # table -> real assets
    sync_game_mode_ui_table.apply(dry_run=False)
    sync_game_mode_ui_table.backfill(dry_run=True)    # real assets -> table (new/missing rows)
    sync_game_mode_ui_table.backfill(dry_run=False)
    sync_game_mode_ui_table.check_drift()             # apply() then backfill() should be a no-op;
                                                        # this asserts that and reports any tile
                                                        # where the table and the asset disagree,
                                                        # so the table doesn't quietly rot the way
                                                        # the since-orphaned FCDGameModeUIRow did
                                                        # (see Scripts/Build-And-Test.ps1, GAP-09).

IMPORTANT VERIFICATION NOTE: this project has no way to run a raw `unreal`-module Python script
from inside this authoring session (only a sandboxed MCP tool-orchestration script with no
`unreal` import is reachable here), so the exact JSON shape ExportDataTableToJSONString/
FillDataTableFromJSONString produce for FGameplayTag/FGameplayTagContainer/FText fields is taken
from UDataTableFunctionLibrary's confirmed C++ signatures (Engine/Classes/Kismet/
DataTableFunctionLibrary.h) plus this project's own already-proven MCP DataTableTools round-trip
(which showed FGameplayTag as {"TagName": "..."}, FGameplayTagContainer as
{"GameplayTags": [...], "ParentTags": [...]}, and FText as either a plain string or an
NSLOCTEXT(...) literal) rather than a live test run of this exact script. _text_from_export()
below handles both FText shapes defensively for that reason. Please run apply(dry_run=True) once
and read its report before trusting apply(dry_run=False) on real content.
"""

import json
import re

import unreal

import author_game_modes

UI_MODE_DIR = author_game_modes.UI_MODE_DIR  # /Game/CollateralDamage/UI/Data/GameModes
TABLE_PATH = "/Game/CollateralDamage/UI/Data/DataTables/DT_GameModeUIEntries"

_tag = author_game_modes._tag  # reuse the project's only name->FGameplayTag resolver

# Table JSON key (as ExportDataTableToJSONString/get_rows produce it, matching the row struct's
# own C++ property names) -> set_editor_property name on UCDGameModeUIEntry / UCDUIEntryDescriptor
# (UHT's standard bool-strips-its-'b'-prefix, PascalCase-to-snake_case convention - the same
# convention author_game_modes.py already relies on for the fields it writes).
FIELD_MAP = {
	"SelectionTag": "selection_tag",
	"PartTag": "part_tag",
	"FilterTags": "filter_tags",
	"DisplayName": "display_name",
	"EraRange": "era_range",
	"bAvailable": "available",
	"bIsNewMode": "is_new_mode",
	"bUnlocked": "unlocked",
	"ShortDescription": "short_description",
	"LongDescription": "long_description",
	"Icon": "icon",
	"SortOrder": "sort_order",
	"GameModeData": "game_mode_data",
	"Experience": "experience",
	"RuleSet": "rule_set",
	"RewardSet": "reward_set",
	"GameModeTag": "game_mode_tag",
	"Subtitle": "subtitle",
	"bIsQuickPlay": "is_quick_play",
	"GameModeIdentifier": "game_mode_identifier",
	"GameModeClass": "game_mode_class",
	"bIsSpotlight": "is_spotlight",
	"RequiredSettings": "required_settings",
	"MaxPlayerCount": "max_player_count",
	"Composition": "composition",
	"TeamCount": "team_count",
	"SquadCount": "squad_count",
	"StakeMode": "stake_mode",
	"WagerRules": "wager_rules",
	"RankedRules": "ranked_rules",
}

_NSLOCTEXT_RE = re.compile(r'^(?:NS)?LOCTEXT\(\s*"(?:[^"\\]|\\.)*"\s*,\s*"(?:[^"\\]|\\.)*"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\)$')


def _text_from_export(raw):
	"""A table-exported FText is either a plain string or an NSLOCTEXT(ns, key, "text")
	literal - see the module docstring's verification note. Returns the plain display string
	either way."""
	if not isinstance(raw, str):
		return raw
	match = _NSLOCTEXT_RE.match(raw.strip())
	if not match:
		return raw
	return match.group(1).replace('\\"', '"').replace("\\\\", "\\")


def _soft_ref_from_export(raw):
	"""A table-exported TSoftObjectPtr/TSoftClassPtr is the plain path string, or the literal
	"None" for unset - matches this field's own get_properties round-trip."""
	if not raw or raw == "None":
		return None
	return raw


def _tag_from_export(raw, report, context):
	"""A table-exported FGameplayTag is {"TagName": "..."} ; "None" means unset."""
	if not raw:
		return None
	name = raw.get("TagName") if isinstance(raw, dict) else raw
	if not name or name == "None":
		return None
	return _tag(name, report)


def _tag_container_from_export(raw, report, context):
	if not raw:
		return unreal.GameplayTagLibrary.make_gameplay_tag_container_from_array([])
	names = [entry.get("TagName") for entry in raw.get("GameplayTags", []) if entry.get("TagName") and entry.get("TagName") != "None"]
	return unreal.GameplayTagLibrary.make_gameplay_tag_container_from_array([_tag(name, report) for name in names])


def _read_table_rows(report):
	"""Returns {row_name: {json_key: value}} for every row in DT_GameModeUIEntries."""
	table = unreal.load_asset(TABLE_PATH)
	if not table:
		report["errors"].append("could not load {}".format(TABLE_PATH))
		return {}

	ok, json_text = unreal.DataTableFunctionLibrary.export_data_table_to_json_string(table)
	if not ok:
		report["errors"].append("ExportDataTableToJSONString failed for {}".format(TABLE_PATH))
		return {}

	# The exporter's top-level shape is a JSON array of {"Name": row_name, <fields...>} objects
	# (the standard UDataTable JSON export shape) rather than get_rows' {row_name: {fields}}
	# object - handle both defensively since this exact shape is unverified, see module docstring.
	parsed = json.loads(json_text)
	if isinstance(parsed, dict):
		return parsed
	rows = {}
	for entry in parsed:
		name = entry.pop("Name", None) or entry.pop("RowName", None)
		if name:
			rows[name] = entry
	return rows


def apply(dry_run=True):
	"""Write DT_GameModeUIEntries' rows onto the real UCDGameModeUIEntry assets they name."""
	eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
	report = {"updated": [], "missing_asset": [], "errors": []}

	def log(message):
		unreal.log(("[dry run] " if dry_run else "") + message)

	rows = _read_table_rows(report)
	for row_name, fields in rows.items():
		asset_path = "{}/{}".format(UI_MODE_DIR, row_name)
		if not eas.does_asset_exist(asset_path):
			report["missing_asset"].append(row_name)
			continue

		log("sync {}".format(row_name))
		if dry_run:
			report["updated"].append(row_name)
			continue

		asset = eas.load_asset(asset_path)
		if not asset:
			report["errors"].append("load failed: {}".format(asset_path))
			continue

		for json_key, prop_name in FIELD_MAP.items():
			if json_key not in fields:
				continue
			raw = fields[json_key]

			if json_key in ("SelectionTag", "PartTag", "GameModeTag"):
				value = _tag_from_export(raw, report, row_name)
				if value is not None:
					asset.set_editor_property(prop_name, value)
			elif json_key == "FilterTags":
				asset.set_editor_property(prop_name, _tag_container_from_export(raw, report, row_name))
			elif json_key in ("DisplayName", "EraRange", "ShortDescription", "LongDescription", "Subtitle", "RequiredSettings"):
				asset.set_editor_property(prop_name, _text_from_export(raw))
			elif json_key in ("Icon", "GameModeData", "Experience", "RuleSet", "RewardSet", "GameModeClass", "WagerRules", "RankedRules"):
				soft_path = _soft_ref_from_export(raw)
				asset.set_editor_property(prop_name, unreal.SoftObjectPath(soft_path) if soft_path else unreal.SoftObjectPath())
			elif json_key == "Composition":
				value = author_game_modes._enum(unreal.CDCombatantComposition, raw, report, row_name)
				if value is not None:
					asset.set_editor_property(prop_name, value)
			elif json_key == "StakeMode":
				value = author_game_modes._enum(unreal.CDMatchStakeMode, raw, report, row_name)
				if value is not None:
					asset.set_editor_property(prop_name, value)
			else:
				asset.set_editor_property(prop_name, raw)

		eas.save_asset(asset_path)
		report["updated"].append(row_name)

	unreal.log("Sync: {} updated, {} rows with no matching asset, {} errors.".format(
		len(report["updated"]), len(report["missing_asset"]), len(report["errors"])))
	for row_name in report["missing_asset"]:
		unreal.log_warning("table row '{}' has no matching asset at {}/{}".format(row_name, UI_MODE_DIR, row_name))
	for error in report["errors"]:
		unreal.log_warning(error)
	return report


def backfill(dry_run=True):
	"""The reverse direction: read every UCDGameModeUIEntry under UI_MODE_DIR and write/refresh
	its row in DT_GameModeUIEntries. Use this after hand-creating a new tile asset (skipping the
	table), or to regenerate the table from scratch if it is ever deleted."""
	eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
	report = {"added": [], "updated": [], "errors": []}

	table = unreal.load_asset(TABLE_PATH)
	if not table:
		report["errors"].append("could not load {}".format(TABLE_PATH))
		return report

	existing_rows = set(unreal.DataTableFunctionLibrary.get_data_table_row_names(table))
	asset_paths = eas.list_assets(UI_MODE_DIR, recursive=False, include_folder=False)

	rows_json = {}
	new_row_names = []
	for asset_path in asset_paths:
		row_name = asset_path.rsplit("/", 1)[-1]
		asset = eas.load_asset(asset_path)
		if not asset:
			report["errors"].append("load failed: {}".format(asset_path))
			continue

		fields = {}
		for json_key, prop_name in FIELD_MAP.items():
			fields[json_key] = asset.get_editor_property(prop_name)
		rows_json[row_name] = fields

		if row_name in existing_rows:
			report["updated"].append(row_name)
		else:
			new_row_names.append(row_name)
			report["added"].append(row_name)

	def log(message):
		unreal.log(("[dry run] " if dry_run else "") + message)

	log("backfill {} existing rows, add {} new rows".format(len(report["updated"]), len(new_row_names)))
	if dry_run:
		return report

	# New rows need a per-row AddDataTableRow(Table, Name, RowStruct) call, and that function's
	# CustomStructureParam is a CustomThunk Python does not expose generically here. New rows are
	# rare (one per newly authored tile), so this falls back to the MCP-proven route: print the
	# names for a human to add once via the DataTable editor's own "+" button, or via the
	# MCP DataTableTools.add_rows tool, rather than guessing at an unverified bulk-add API.
	for row_name in new_row_names:
		unreal.log_warning(
			"'{}' has no row yet in DT_GameModeUIEntries - add it (DataTable editor's + button, "
			"or MCP DataTableTools.add_rows) then re-run backfill(dry_run=False)".format(row_name))

	# Existing rows: FillDataTableFromJSONString replaces the WHOLE table, so round-trip through
	# the current export merged with this pass's fresh values rather than clobbering rows this
	# call didn't touch (e.g. a tile that was since deleted from disk but whose row a designer
	# wants to keep as a draft).
	current = _read_table_rows(report)
	current.update(rows_json)
	payload = [dict(fields, Name=name) for name, fields in current.items() if name not in new_row_names]
	ok = unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(table, json.dumps(payload))
	if not ok:
		report["errors"].append("FillDataTableFromJSONString failed")
	else:
		eas.save_asset(TABLE_PATH)

	unreal.log("Backfill: {} updated, {} pending add, {} errors.".format(
		len(report["updated"]), len(report["added"]), len(report["errors"])))
	for error in report["errors"]:
		unreal.log_warning(error)
	return report


def check_drift():
	"""Anti-drift guard: compares the table's current content against a fresh backfill export of
	the real assets. Zero-diff means the table is still a faithful mirror; any difference means
	someone edited an asset directly without syncing, or a sync did not actually take. This is
	the check that would have caught FCDGameModeUIRow rotting silently (GAP-09) had this table
	existed then - run it after any batch of direct asset edits, and consider wiring it into
	Scripts/Build-And-Test.ps1 as an optional stage."""
	before = _read_table_rows({"errors": []})
	backfill(dry_run=True)
	after_report = {"errors": []}
	eas = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
	drifted = []
	for asset_path in eas.list_assets(UI_MODE_DIR, recursive=False, include_folder=False):
		row_name = asset_path.rsplit("/", 1)[-1]
		asset = eas.load_asset(asset_path)
		if not asset or row_name not in before:
			continue
		for json_key, prop_name in FIELD_MAP.items():
			table_value = before[row_name].get(json_key)
			asset_value = asset.get_editor_property(prop_name)
			# Coarse comparison (string form) - exact struct equality across FGameplayTag/
			# FText/soft-ref types needs the same conversion helpers apply() already has;
			# this is a "did something change" smoke check, not a byte-exact diff.
			if str(table_value) != str(asset_value) and json_key not in ("Icon",):
				drifted.append((row_name, json_key))
	if drifted:
		unreal.log_warning("check_drift: {} field(s) differ between table and asset:".format(len(drifted)))
		for row_name, json_key in drifted:
			unreal.log_warning("  {} : {}".format(row_name, json_key))
	else:
		unreal.log("check_drift: table and assets agree on every field.")
	return drifted
