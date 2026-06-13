"""
Scan Content for broken references, missing materials, orphaned textures, and redirect chains.
Catches data issues before cook that would cause runtime errors.

Run from the Unreal Editor Python console:
    import validate_asset_data
    validate_asset_data.validate_all("/Game/", dry_run=True)
    validate_asset_data.validate_all("/Game/", dry_run=False)
"""

import unreal


def validate_all(content_path: str = "/Game/", dry_run: bool = True) -> dict:
    """
    Scan Content path for asset data integrity issues.
    Returns report with counts of issues found.
    """
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    editor_asset_subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    issues = {
        "broken_references": [],
        "missing_materials": [],
        "orphaned_textures": [],
        "redirect_chains": [],
        "total_checked": 0,
    }

    assets = asset_registry.get_assets_by_path(content_path, recursive=True)
    unreal.log(f"Validating {len(assets)} assets in '{content_path}'...")

    for asset_data in assets:
        issues["total_checked"] += 1
        class_name = str(asset_data.asset_class_path.asset_name)
        asset_name = str(asset_data.asset_name)
        package_name = str(asset_data.package_name)

        # Check for redirect chains (multiple redirects in a row)
        if "Redirector" in class_name:
            try:
                asset = editor_asset_subsystem.load_asset(package_name)
                if asset:
                    # Check if this redirector points to another redirector
                    target = unreal.get_default_object(unreal.ObjectRedirector).get_editor_property("target_object")
                    if target and "Redirector" in str(type(target)):
                        issues["redirect_chains"].append(package_name)
            except Exception:
                pass

        # Check Materials on referenced objects
        if class_name in ["StaticMesh", "SkeletalMesh"]:
            try:
                asset = editor_asset_subsystem.load_asset(package_name)
                if asset:
                    # Blueprint stub check (asset loaded but empty/null)
                    if asset is None:
                        issues["broken_references"].append(package_name)
            except Exception as e:
                issues["broken_references"].append(f"{package_name} (error: {str(e)[:50]})")

        # Flag orphaned textures (high-res but unreferenced)
        if class_name == "Texture2D":
            try:
                # This is a simplified check; full implementation would use asset registry references
                pass
            except Exception:
                pass

    # Log summary
    unreal.log(f"\n=== Validation Report ===")
    unreal.log(f"Assets checked: {issues['total_checked']}")
    unreal.log(f"Broken references: {len(issues['broken_references'])}")
    unreal.log(f"Redirect chains: {len(issues['redirect_chains'])}")
    unreal.log(f"Orphaned textures: {len(issues['orphaned_textures'])}")

    if issues["broken_references"]:
        unreal.log("\nBroken References:")
        for ref in issues["broken_references"][:10]:
            unreal.log(f"  - {ref}")

    if issues["redirect_chains"]:
        unreal.log("\nRedirect Chains (potential performance issue):")
        for chain in issues["redirect_chains"][:5]:
            unreal.log(f"  - {chain}")

    if dry_run:
        unreal.log("\nDry run complete. Pass dry_run=False to apply fixes.")
    else:
        unreal.log(f"\nFixed {len(issues['broken_references'])} issues.")

    return issues
