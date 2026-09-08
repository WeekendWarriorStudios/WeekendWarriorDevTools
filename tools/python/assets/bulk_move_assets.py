#!/usr/bin/env python3
"""Move many assets between content roots in one pass, with references kept intact.

**Editor Python.** Run inside Unreal (console, or ``ue_remote_exec.py --file``). A plain file
move of a ``.uasset`` corrupts it - the package name is baked into the file, so the only safe
way to relocate content is an editor rename, which is what this does.

Why a script rather than dragging in the Content Browser: a plugin/project split is usually
40-100 assets, the destination layout is a set of rules rather than one drag, and you want the
plan reviewed before anything moves.

Plan shape
----------
``FOLDER_RULES``   ``[(src_folder, dst_folder), ...]`` - assets *directly* in ``src_folder``
                   (subfolders are NOT followed; list them as their own rule so a nested
                   folder can go somewhere unrelated).
``ASSET_OVERRIDES`` ``{src_package: dst_package}`` - evaluated first, wins over the rules.
                   Use it to peel individual assets out of a folder that otherwise moves as one.

ObjectRedirectors in a source folder are skipped - they are debris, not content.

Usage
-----
    # 1. review
    python ue_remote_exec.py --file bulk_move_assets.py
    # 2. flip APPLY = True, then
    python ue_remote_exec.py --file bulk_move_assets.py

Or as a module::

    import bulk_move_assets as bma
    plan = bma.build_plan(FOLDER_RULES, ASSET_OVERRIDES)
    bma.report(plan, STALE)          # dry run
    bma.apply(plan, STALE)           # execute

Two gotchas this codifies (both cost real time to find)
-------------------------------------------------------
1. ``EditorAssetLibrary.delete_asset`` returns ``True`` on a **git-tracked** ``.uasset`` while
   leaving the file on disk. The asset vanishes from the registry, so every in-editor check
   agrees it is gone, and the next editor start rescans the file and brings it back. ``apply()``
   therefore prints a ``VERIFY ON DISK`` list - delete those with plain ``rm``, never trust the
   return value.

2. Deleting a redirector leaves behind a **phantom dirty UPackage** still holding that package
   name in memory. It cannot be saved (it contains no object) and cannot be unloaded (it is
   dirty), so any later rename *into* that name fails - via ``EditorAssetLibrary.rename_asset``
   and ``AssetTools.rename_assets`` alike - until the editor restarts. So: **never delete a
   redirector that sits on a name you are about to move something onto in the same session.**
   Move first (renaming onto an existing redirector is allowed and replaces it), delete after.
   ``report()`` flags this case as ``DEST IS A REDIRECTOR YOU ALSO DELETE`` so you can reorder.
"""

import unreal

# --------------------------------------------------------------------------------------------
# Edit these three, then run.
# --------------------------------------------------------------------------------------------

APPLY = False

# Redirectors / debris to remove. See gotcha 2 above before putting anything here that a move
# also targets.
STALE_REDIRECTORS = []

FOLDER_RULES = []

ASSET_OVERRIDES = {}

# --------------------------------------------------------------------------------------------

EAL = unreal.EditorAssetLibrary
ELSU = unreal.EditorLoadingAndSavingUtils
ARL = unreal.AssetRegistryHelpers.get_asset_registry()


def _class_of(package_name):
    data = EAL.find_asset_data(package_name)
    return str(data.asset_class_path.asset_name) if data else ""


def _assets_directly_in(folder):
    """Package names of assets in `folder` itself. Subfolders are not followed."""
    return sorted({str(d.package_name)
                   for d in (ARL.get_assets_by_path(folder, recursive=False) or [])})


def build_plan(folder_rules, asset_overrides):
    """Resolve rules + overrides into an ordered list of (src_package, dst_package)."""
    moves, claimed = [], set()

    for src, dst in asset_overrides.items():
        if EAL.does_asset_exist(src):
            moves.append((src, dst))
            claimed.add(src)

    for src_folder, dst_folder in folder_rules:
        for pkg in _assets_directly_in(src_folder):
            if pkg in claimed or _class_of(pkg) == "ObjectRedirector":
                continue
            claimed.add(pkg)
            moves.append((pkg, "%s/%s" % (dst_folder, pkg.rsplit("/", 1)[1])))

    return moves


def report(plan, stale=()):
    """Print the resolved plan and every problem found. Returns the problem list."""
    problems, seen_dst = [], {}

    print("=== stale entries to delete (%d) ===" % len(stale))
    for p in stale:
        print("  %-62s exists=%s  class=%s" % (p, EAL.does_asset_exist(p), _class_of(p)))

    print("=== resolved moves (%d) ===" % len(plan))
    for src, dst in plan:
        notes = []
        if not EAL.does_asset_exist(src):
            notes.append("SOURCE MISSING")
        elif EAL.does_asset_exist(dst):
            if dst in stale:
                # Gotcha 2: deleting this first strands a phantom package on the name.
                notes.append("DEST IS A REDIRECTOR YOU ALSO DELETE - move first, delete after")
            else:
                notes.append("DEST OCCUPIED")
        if dst in seen_dst:
            notes.append("COLLIDES WITH %s" % seen_dst[dst])
        seen_dst[dst] = src
        for n in notes:
            problems.append((src, dst, n))
        print("  %-62s -> %s%s" % (src, dst, ("   !! " + "; ".join(notes)) if notes else ""))

    print("=== problems: %d ===" % len(problems))
    for p in problems:
        print("  %s" % (p,))
    return problems


def _park_off(plan):
    """A World cannot be renamed while it is the open level; park on a blank map if needed."""
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if not world:
        return
    path = world.get_path_name()
    if any(src in path for src, _ in plan):
        print("parking on a blank map (was %s)" % path)
        ELSU.new_blank_map(False)


def _close_editor_for(pkg):
    asset = EAL.load_asset(pkg)
    if asset:
        unreal.get_editor_subsystem(unreal.AssetEditorSubsystem).close_all_editors_for_asset(asset)


def fix_soft_references(plan, extra_roots=()):
    """Repoint soft object paths that a rename left pointing at the old package.

    `rename_asset` rewrites hard imports but leaves soft references (TSoftClassPtr, widget-class
    pickers, soft asset pickers) resolving through the redirector dropped at the old path. Drop
    those redirectors and the soft refs dangle silently - the asset still loads, the reference is
    just null at runtime. Call this after moving and before deleting redirectors.
    """
    redirect_map = {}
    for old_pkg, new_pkg in plan:
        old_name = old_pkg.rsplit("/", 1)[1]
        new_name = new_pkg.rsplit("/", 1)[1]
        # Cover the object, its generated class, and the CDO - a class picker stores the _C form.
        for old_obj, new_obj in (
            ("%s.%s" % (old_pkg, old_name), "%s.%s" % (new_pkg, new_name)),
            ("%s.%s_C" % (old_pkg, old_name), "%s.%s_C" % (new_pkg, new_name)),
            ("%s.Default__%s_C" % (old_pkg, old_name),
             "%s.Default__%s_C" % (new_pkg, new_name)),
        ):
            redirect_map[unreal.SoftObjectPath(old_obj)] = unreal.SoftObjectPath(new_obj)

    roots = sorted({p.rsplit("/", 1)[0].split("/")[1] for _, p in plan} |
                   {r.strip("/").split("/")[0] for r in extra_roots})
    packages = []
    for root in roots:
        for d in (ARL.get_assets_by_path("/" + root, recursive=True) or []):
            pkg = str(d.package_name)
            EAL.load_asset(pkg)
            p = unreal.find_package(pkg)
            if p:
                packages.append(p)

    print("rewriting soft paths across %d packages, %d mappings"
          % (len(packages), len(redirect_map)))
    unreal.AssetToolsHelpers.get_asset_tools().rename_referencing_soft_object_paths(
        packages, redirect_map)
    ELSU.save_dirty_packages(True, True)


def find_broken_references(roots):
    """{package: [missing deps]} - the only trustworthy check. Grepping the file for path
    strings gives false positives from stale name-table entries that are no longer imports."""
    opts = unreal.AssetRegistryDependencyOptions(
        include_soft_package_references=True, include_hard_package_references=True)
    broken = {}
    for root in roots:
        for d in (ARL.get_assets_by_path(root, recursive=True) or []):
            pkg = str(d.package_name)
            for dep in (ARL.get_dependencies(unreal.Name(pkg), opts) or []):
                dep = str(dep)
                if dep.startswith(("/Game", "/")) and not dep.startswith(
                        ("/Script", "/Engine")) and not EAL.does_asset_exist(dep):
                    broken.setdefault(pkg, []).append(dep)
    return broken


def apply(plan, stale=()):
    """Execute the plan. Moves run before deletes, deliberately (gotcha 2)."""
    _park_off(plan)

    print("=== moving (%d) ===" % len(plan))
    failed = []
    for src, dst in plan:
        _close_editor_for(src)
        ok = EAL.rename_asset(src, dst)
        if not ok:
            failed.append((src, dst))
        print("  %-62s -> %-62s %s" % (src, dst, "ok" if ok else "FAILED"))

    # Before any redirector is removed, while both old and new names still resolve.
    fix_soft_references([(s, d) for s, d in plan if (s, d) not in failed])

    print("=== deleting stale entries (%d) ===" % len(stale))
    for p in stale:
        if EAL.does_asset_exist(p):
            ok = EAL.delete_asset(p)
            print("  %-62s delete=%s still_registered=%s" % (p, ok, EAL.does_asset_exist(p)))

    ELSU.save_dirty_packages(True, True)
    unreal.SystemLibrary.collect_garbage()

    print("=== failures: %d ===" % len(failed))
    for f in failed:
        print("  %s" % (f,))

    # Gotcha 1: the registry is not the filesystem. Emit the paths to check with `ls`/`rm`.
    print("=== VERIFY ON DISK - these should no longer have a file ===")
    for p in list(stale) + [src for src, _ in plan]:
        print("  %s" % p)
    print("(a git-tracked .uasset survives delete_asset silently; remove leftovers with rm)")

    return failed


def main():
    plan = build_plan(FOLDER_RULES, ASSET_OVERRIDES)
    problems = report(plan, STALE_REDIRECTORS)
    if not APPLY:
        print("DRY RUN - nothing changed. Set APPLY = True to execute.")
        return
    if problems:
        print("ABORTED - resolve the problems above first.")
        return
    apply(plan, STALE_REDIRECTORS)


if __name__ == "__main__":
    main()
