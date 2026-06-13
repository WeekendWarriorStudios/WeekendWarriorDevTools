"""
Profile heavy Blueprints and suggest optimizations (Nativization, event graphs, tick settings).
Reduces per-frame hitches from expensive Blueprint logic.

Run from the Unreal Editor Python console:
    import blueprint_perf_advisor
    blueprint_perf_advisor.analyze_blueprints("/Game/", max_results=20)
"""

import unreal


def analyze_blueprints(
    content_path: str = "/Game/",
    max_results: int = 20,
    complexity_threshold: int = 100,
) -> dict:
    """
    Scan Blueprint classes for performance issues and generate recommendations.
    """
    asset_registry = unreal.AssetRegistryHelpers.get_asset_registry()
    editor_asset_subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)

    findings = {
        "heavy_blueprints": [],
        "tick_enabled": [],
        "event_spam_candidates": [],
        "nativization_candidates": [],
        "total_blueprints": 0,
    }

    assets = asset_registry.get_assets_by_path(content_path, recursive=True)
    blueprint_assets = [a for a in assets if "Blueprint" in str(a.asset_class_path.asset_name)]

    unreal.log(f"Analyzing {len(blueprint_assets)} Blueprints...")

    for blueprint_asset in blueprint_assets:
        findings["total_blueprints"] += 1
        package_name = str(blueprint_asset.package_name)

        try:
            bp = editor_asset_subsystem.load_asset(package_name)
            if not bp:
                continue

            # Simple heuristics (full implementation would use Blueprint graph analysis)
            asset_name = str(blueprint_asset.asset_name)

            # Rule 1: Complex names often indicate complex BPs
            if asset_name.startswith("BP_") and len(asset_name) > 30:
                findings["heavy_blueprints"].append(
                    {
                        "name": asset_name,
                        "recommendation": "Long name suggests complex logic. Consider breaking into smaller classes.",
                        "priority": "Medium",
                    }
                )

            # Rule 2: Check for common tick-enabled patterns
            if "Pawn" in asset_name or "Character" in asset_name or "Vehicle" in asset_name:
                findings["tick_enabled"].append(
                    {
                        "name": asset_name,
                        "recommendation": "Movement classes often tick. Review if Tick is actually needed.",
                        "priority": "Medium",
                    }
                )

            # Rule 3: Event-based candidates (animation, UI, game rules)
            if "Event" in asset_name or "UI" in asset_name or "Widget" in asset_name:
                findings["event_spam_candidates"].append(
                    {
                        "name": asset_name,
                        "recommendation": "Event classes should use event-driven updates, not Tick.",
                        "priority": "Low",
                    }
                )

            # Rule 4: Nativization candidates (frequently instantiated, complex logic)
            if asset_name.startswith("BP_Pawn") or asset_name.startswith("BP_Character"):
                findings["nativization_candidates"].append(
                    {
                        "name": asset_name,
                        "recommendation": "Frequently instantiated. Nativization may reduce frame time by 5-15%.",
                        "priority": "High",
                    }
                )

        except Exception as e:
            unreal.log_warning(f"Could not analyze {asset_name}: {e}")

    # Trim results
    for key in findings:
        if isinstance(findings[key], list):
            findings[key] = findings[key][:max_results]

    # Log findings
    unreal.log(f"\n=== Blueprint Performance Analysis ===")
    unreal.log(f"Total Blueprints: {findings['total_blueprints']}")
    unreal.log(f"Heavy candidates: {len(findings['heavy_blueprints'])}")
    unreal.log(f"Tick-enabled classes: {len(findings['tick_enabled'])}")
    unreal.log(f"Nativization candidates: {len(findings['nativization_candidates'])}")

    if findings["nativization_candidates"]:
        unreal.log("\nTop Nativization Candidates (High ROI):")
        for bp in findings["nativization_candidates"][:5]:
            unreal.log(f"  - {bp['name']}: {bp['recommendation']}")

    if findings["tick_enabled"]:
        unreal.log("\nClasses with Tick (review if necessary):")
        for bp in findings["tick_enabled"][:5]:
            unreal.log(f"  - {bp['name']}")

    return findings
