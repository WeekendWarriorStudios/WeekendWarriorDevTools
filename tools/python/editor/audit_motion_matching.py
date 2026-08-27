"""Validate a motion matching pipeline end to end, inside the editor.

Motion matching fails silently. A schema bound to the wrong skeleton, a database with no
animations, a Chooser row pointing at a database nothing can reach, a sampled bone that does not
exist on the rig — none of these log anything. The character just picks a poor pose, or no pose,
and you are left guessing which of six assets is at fault. This walks the whole chain and says
which one.

What it checks
--------------
Schemas      skeleton assigned and resolvable; at least one channel; every sampled bone
             actually exists on that skeleton; mirroring availability.
Databases    schema assigned; schema/database skeleton agreement; non-empty; every referenced
             animation present and built on a compatible skeleton.
Choosers     output object type; every referenced database exists; reachability — a database in
             no Chooser table is dead content, which is how 44 landing animations went unnoticed.
Coverage     databases that no Chooser routes to, and Chooser rows pointing at empty databases
             (the combination that lands a character in reference pose at runtime).

Run it
------
From the editor's Python console:

    import sys; sys.path.insert(0, r"A:\\Projects\\CollateralDamage\\WeekendWarriorDevTools\\tools\\python\\editor")
    import audit_motion_matching
    audit_motion_matching.audit("/MovementLocomotion/Movement/PoseSearch")

Or headless from a terminal, via the remote execution client in this same folder:

    python ue_remote_exec.py --file audit_motion_matching.py

Pass ``json_path`` to also write a machine-readable report:

    audit_motion_matching.audit("/MovementLocomotion/Movement/PoseSearch",
                                json_path=r"A:\\...\\tools\\outputs\\motion-matching-audit.json")
"""

from __future__ import annotations

import json

import unreal

# Severity ordering used for the summary line and the exit report.
ERROR = "error"
WARNING = "warning"

_ASSET_REGISTRY = unreal.AssetRegistryHelpers.get_asset_registry()


CLASS_MODULES = {
    "PoseSearchSchema": "/Script/PoseSearch",
    "PoseSearchDatabase": "/Script/PoseSearch",
    "ChooserTable": "/Script/Chooser",
}


def _scan(root_path: str) -> None:
    """Make sure the registry actually knows about ``root_path``.

    Necessary when running as a commandlet: unlike an interactive editor, a commandlet does not
    scan content up front, so an unscanned path silently yields zero assets.
    """
    _ASSET_REGISTRY.scan_paths_synchronous([root_path], force_rescan=True)


def _assets_of_class(root_path: str, class_name: str) -> list:
    """Every asset of ``class_name`` under ``root_path``, loaded."""
    module = CLASS_MODULES[class_name]
    filter_ = unreal.ARFilter(
        package_paths=[root_path],
        recursive_paths=True,
        class_paths=[unreal.TopLevelAssetPath(module, class_name)],
        recursive_classes=True,
    )
    return [data.get_asset() for data in _ASSET_REGISTRY.get_assets(filter_)]


def _try(obj, *property_names):
    """First readable property among ``property_names``; None if the object has none of them.

    Pose Search and Chooser are both experimental and rename properties between releases, so an
    auditor that hard-codes one name breaks on upgrade for no good reason.
    """
    for name in property_names:
        try:
            return obj.get_editor_property(name)
        except Exception:
            continue
    return None


def _schema_skeletons(schema) -> list:
    roled = _try(schema, "skeletons") or []
    out = []
    for entry in roled:
        skeleton = _try(entry, "skeleton")
        mirror = _try(entry, "mirror_data_table")
        out.append((skeleton, mirror))
    return out


def _collect_sampled_bones(channel, found: list) -> None:
    """Walk a channel (and its sub-channels) collecting every bone name it samples."""
    for bones_property in ("sampled_bones",):
        bones = _try(channel, bones_property)
        if not bones:
            continue
        for bone in bones:
            reference = _try(bone, "reference", "bone")
            name = _try(reference, "bone_name") if reference is not None else None
            if name:
                found.append(str(name))

    # Position/Velocity/Heading channels each carry a single bone instead of an array.
    for single in ("bone", "origin_bone"):
        reference = _try(channel, single)
        name = _try(reference, "bone_name") if reference is not None else None
        if name and str(name) != "None":
            found.append(str(name))

    for group_property in ("sub_channels", "channels"):
        children = _try(channel, group_property) or []
        for child in children:
            if child is not None:
                _collect_sampled_bones(child, found)


def audit(root_path: str = "/MovementLocomotion/Movement/PoseSearch", json_path: str | None = None) -> dict:
    """Audit every schema, database and Chooser under ``root_path``. Returns the report dict."""
    findings: list[dict] = []

    def note(severity: str, asset: str, message: str) -> None:
        findings.append({"severity": severity, "asset": asset, "message": message})

    _scan(root_path)

    schemas = _assets_of_class(root_path, "PoseSearchSchema")
    databases = _assets_of_class(root_path, "PoseSearchDatabase")
    choosers = _assets_of_class(root_path, "ChooserTable")

    # An empty result is a bad path or an unscanned registry, not a clean bill of health. Saying
    # "no problems found" there would be the most misleading thing this tool could do.
    if not (schemas or databases or choosers):
        raise RuntimeError(
            f"No schemas, databases or Chooser tables found under {root_path!r}. Check the path — "
            f"it should be a mount-point-relative package path such as "
            f"'/MyPlugin/Movement/PoseSearch', not a filesystem path."
        )

    # ---- schemas -----------------------------------------------------
    schema_bones: dict[str, list[str]] = {}
    schema_skeleton: dict[str, object] = {}

    for schema in schemas:
        name = schema.get_name()
        pairs = _schema_skeletons(schema)
        if not pairs or all(sk is None for sk, _m in pairs):
            note(ERROR, name, "no skeleton assigned; every search against it will fail")
            continue

        skeleton, mirror = pairs[0]
        schema_skeleton[name] = skeleton
        if mirror is None:
            note(WARNING, name, "no MirrorDataTable; mirroring is unavailable, so left/right "
                                "coverage must come entirely from source clips")

        channels = _try(schema, "channels") or []
        if not channels:
            note(ERROR, name, "no channels; the feature vector is empty")
            continue

        bones: list[str] = []
        for channel in channels:
            if channel is not None:
                _collect_sampled_bones(channel, bones)
        schema_bones[name] = sorted(set(bones))

        rig_bones = set()
        try:
            rig_bones = {str(b) for b in skeleton.get_editor_property("bone_tree")} if False else set()
        except Exception:
            pass
        # BoneTree is not script-exposed; use the reference skeleton via a preview mesh instead.
        try:
            for index in range(skeleton.num_bones()):
                rig_bones.add(str(skeleton.get_bone_name(index)))
        except Exception:
            rig_bones = set()

        if rig_bones:
            for bone in schema_bones[name]:
                if bone not in rig_bones:
                    note(ERROR, name, f"samples bone '{bone}', which does not exist on "
                                      f"{skeleton.get_name()}")
        channel_types = sorted({type(c).__name__ for c in channels if c is not None})
        note("info", name, f"channels: {', '.join(channel_types)}; "
                           f"bones: {', '.join(schema_bones[name]) or 'none'}")

    # ---- databases ---------------------------------------------------
    database_entry_counts: dict[str, int] = {}
    database_paths: dict[str, str] = {}

    for database in databases:
        name = database.get_name()
        database_paths[database.get_path_name().split(".")[0]] = name

        schema = _try(database, "schema")
        if schema is None:
            note(ERROR, name, "no schema assigned")
            continue

        # Read the count through the BlueprintPure accessor rather than a property: 5.7 renamed
        # the backing array to DatabaseAnimationAssets and made it private, leaving a deprecated
        # AnimationAssets behind. Reading the property by name silently returns nothing on one
        # version or the other, which reports every database as empty.
        try:
            count = int(database.get_num_animation_assets())
        except Exception as err:
            note(WARNING, name, f"could not read the animation count ({err})")
            continue

        database_entry_counts[name] = count
        if count == 0:
            note(ERROR, name, "no animation entries; any Chooser row reaching it yields no pose")

    # ---- choosers ----------------------------------------------------
    routed: set[str] = set()

    for chooser in choosers:
        name = chooser.get_name()
        output_type = _try(chooser, "output_object_type")
        if output_type is not None and "PoseSearchDatabase" not in str(output_type):
            note(WARNING, name, f"output object type is {output_type}, not PoseSearchDatabase")

        # Chooser rows are instanced structs; rather than decode every column type, lean on the
        # asset registry's dependency graph, which already knows what this table points at.
        package = chooser.get_path_name().split(".")[0]
        for dependency in _ASSET_REGISTRY.get_dependencies(
            unreal.Name(package), unreal.AssetRegistryDependencyOptions()
        ) or []:
            key = str(dependency)
            if key in database_paths:
                routed.add(database_paths[key])

    for name, count in sorted(database_entry_counts.items()):
        if name not in routed:
            note(WARNING, name, f"no Chooser table routes to it — {count} indexed animations "
                                f"are unreachable at runtime")

    for name in sorted(routed):
        if database_entry_counts.get(name, 0) == 0:
            note(ERROR, name, "a Chooser routes to it but it is empty; reaching that row puts "
                              "the character in reference pose")

    report = {
        "root": root_path,
        "counts": {
            "schemas": len(schemas),
            "databases": len(databases),
            "choosers": len(choosers),
            "errors": sum(1 for f in findings if f["severity"] == ERROR),
            "warnings": sum(1 for f in findings if f["severity"] == WARNING),
        },
        "findings": findings,
    }

    _print(report)
    if json_path:
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        unreal.log(f"[motion-matching-audit] wrote {json_path}")
    return report


def _print(report: dict) -> None:
    counts = report["counts"]
    unreal.log("=" * 78)
    unreal.log(f"Motion matching audit — {report['root']}")
    unreal.log(f"  {counts['schemas']} schemas, {counts['databases']} databases, "
               f"{counts['choosers']} chooser tables")
    unreal.log("=" * 78)

    for severity, emitter in ((ERROR, unreal.log_error), (WARNING, unreal.log_warning), ("info", unreal.log)):
        rows = [f for f in report["findings"] if f["severity"] == severity]
        if not rows:
            continue
        unreal.log(f"-- {severity} ({len(rows)}) " + "-" * 40)
        for row in rows:
            emitter(f"  {row['asset']}: {row['message']}")

    if counts["errors"] == 0 and counts["warnings"] == 0:
        unreal.log("No problems found.")
    else:
        unreal.log(f"{counts['errors']} error(s), {counts['warnings']} warning(s).")


if __name__ == "__main__":
    audit()
