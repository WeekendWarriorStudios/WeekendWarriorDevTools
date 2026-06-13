"""
Scan a Content folder path and rename assets that don't follow UE5 naming conventions.
Run from the Unreal Editor Python console or register as a startup script in
Project Settings > Plugins > Python.

Usage (editor console):
    import importlib, lint_asset_names
    importlib.reload(lint_asset_names)
    lint_asset_names.lint_and_fix_asset_names("/Game/MyProject", dry_run=True)
"""

import unreal

# Maps asset class name -> required prefix
NAMING_CONVENTIONS = {
    "Texture2D":                  "T_",
    "TextureCube":                "T_",
    "Material":                   "M_",
    "MaterialInstanceConstant":   "MI_",
    "MaterialFunction":           "MF_",
    "BlueprintGeneratedClass":    "BP_",
    "StaticMesh":                 "SM_",
    "SkeletalMesh":               "SK_",
    "AnimSequence":               "ANIM_",
    "AnimMontage":                "AM_",
    "AnimBlueprint":              "ABP_",
    "SoundWave":                  "SFX_",
    "SoundCue":                   "SFX_",
    "ParticleSystem":             "FX_",
    "NiagaraSystem":              "FX_",
    "NiagaraEmitter":             "FXE_",
    "PhysicsAsset":               "PHYS_",
    "PoseSearchSchema":           "PSS_",
    "PoseSearchDatabase":         "PSD_",
}


def lint_and_fix_asset_names(target_path: str = "/Game/", dry_run: bool = True) -> None:
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    editor_asset_subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    assets = asset_registry.get_assets_by_path(target_path, recursive=True)
    violations = []

    for asset_data in assets:
        class_name = str(asset_data.asset_class_path.asset_name)
        asset_name = str(asset_data.asset_name)

        if class_name not in NAMING_CONVENTIONS:
            continue

        prefix = NAMING_CONVENTIONS[class_name]
        if not asset_name.startswith(prefix):
            violations.append((asset_data, class_name, asset_name, prefix))

    unreal.log(f"Found {len(violations)} naming violation(s) in '{target_path}'.")

    for asset_data, class_name, asset_name, prefix in violations:
        correct_name = f"{prefix}{asset_name}"
        package_name = str(asset_data.package_name)
        parent_path = package_name.rsplit("/", 1)[0]
        new_path = f"{parent_path}/{correct_name}"

        if dry_run:
            unreal.log_warning(f"[DRY RUN] Would rename: {asset_name} -> {correct_name}  ({class_name})")
        else:
            unreal.log(f"Renaming: {asset_name} -> {correct_name}")
            editor_asset_subsystem.rename_asset(package_name, new_path)

    if dry_run:
        unreal.log("Dry run complete. Pass dry_run=False to apply changes.")
    else:
        unreal.log("Rename pass complete.")
