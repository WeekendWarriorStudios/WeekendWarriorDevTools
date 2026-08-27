#!/usr/bin/env python3
"""Read what a .uasset references without opening the Unreal Editor.

Cooked-asset tooling and the editor both need a loaded project; this does not. It walks the
package file directly and recovers every length-prefixed string in it — which in practice means
the name table (property names, class names, enum values, gameplay tags) plus every object path
in the import/export tables. That is enough to answer the questions that otherwise cost an editor
launch:

  * which animations are actually in this Pose Search database, and how many
  * which gameplay tags a Chooser table filters on, and which databases it routes to
  * which anim graph node types a given Anim Blueprint is built from
  * what skeleton a schema or database is bound to
  * whether asset A still references asset B after a refactor

It is deliberately a *reader*, not a parser: it does not decode property values, so it will tell
you that a schema has a Trajectory channel but not that channel's weight. For numeric values,
open the asset. Everything it does report is ground truth from the file on disk, which makes it
the right tool for verifying that an editor operation actually saved (see the caution in the
project's asset-delete notes about tools reporting success without writing).

Usage
-----
    python uasset_inspect.py MMDB_Jog.uasset
    python uasset_inspect.py --grep "State.Locomotion" Choosers/*.uasset
    python uasset_inspect.py --refs Databases/**/*.uasset
    python uasset_inspect.py --classes CD_MovementLocomotion.uasset
    python uasset_inspect.py --refs --filter /Movement/Human/Animations --count Databases/*.uasset
    python uasset_inspect.py --json --refs MMDB_*.uasset > refs.json

As a module
-----------
    from uasset_inspect import read_strings, referenced_packages

    for path in Path("Databases").rglob("*.uasset"):
        anims = referenced_packages(path, prefix="/MovementLocomotion/Movement/Human/Animations")
        print(path.stem, len(anims))
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import struct
import sys
from pathlib import Path

PRINTABLE = frozenset(range(0x20, 0x7F))
UASSET_MAGIC = 0x9E2A83C1

# A package path is any string that looks like /Mount/Point/Asset. Distinguishing a *package*
# path from a /Script/Module class path matters because callers almost always want one or the
# other, never both mixed together.
SCRIPT_PREFIX = "/Script/"


def read_strings(path: str | os.PathLike, min_length: int = 2) -> list[tuple[int, str]]:
    """Return every ``(offset, text)`` FString found in the package, in file order.

    Scans for the UE serialization shape — int32 length, that many bytes, trailing NUL — rather
    than parsing the package summary, whose layout shifts between engine versions and custom
    version registrations. Overlapping candidates are skipped so a long string cannot be
    re-reported from an offset inside itself.
    """
    data = Path(path).read_bytes()
    if len(data) < 4 or struct.unpack_from("<I", data, 0)[0] != UASSET_MAGIC:
        raise ValueError(f"{path} is not a .uasset package (bad magic)")

    found: list[tuple[int, str]] = []
    consumed_to = -1
    index = 0
    end = len(data) - 4
    while index < end:
        (length,) = struct.unpack_from("<i", data, index)
        if 1 < length <= 400 and index + 4 + length <= len(data):
            chunk = data[index + 4: index + 4 + length]
            if chunk[-1] == 0 and all(byte in PRINTABLE for byte in chunk[:-1]):
                text = chunk[:-1].decode("ascii")
                if len(text) >= min_length and index >= consumed_to:
                    found.append((index, text))
                    consumed_to = index + 4 + length
                    index = consumed_to
                    continue
        index += 1
    return found


def referenced_packages(path, prefix: str | None = None) -> list[str]:
    """Unique ``/Mount/Path/Asset`` package paths the file references, sorted.

    Excludes ``/Script/...`` class paths (use :func:`referenced_classes` for those) and the
    package's own path, so what comes back is the asset's outbound dependencies.
    """
    own_stem = Path(path).stem
    seen = set()
    for _offset, text in read_strings(path):
        if not text.startswith("/") or text.startswith(SCRIPT_PREFIX):
            continue
        if " " in text or "'" in text:
            continue
        if text.rsplit("/", 1)[-1] == own_stem:
            continue
        if prefix and not text.startswith(prefix):
            continue
        seen.add(text)
    return sorted(seen)


def referenced_classes(path) -> list[str]:
    """Unique class/type names the file references — ``/Script/Module`` entries and the bare
    UCLASS names beside them, which is what identifies node types inside a Blueprint."""
    seen = set()
    for _offset, text in read_strings(path):
        if text.startswith(SCRIPT_PREFIX):
            seen.add(text)
    return sorted(seen)


def _iter_targets(patterns: list[str]) -> list[Path]:
    targets: list[Path] = []
    for pattern in patterns:
        # Let the shell's glob through untouched when it already expanded, and expand ourselves
        # (recursively, so ** works) when it did not — PowerShell does not glob for us.
        matches = [Path(m) for m in glob.glob(pattern, recursive=True)]
        if matches:
            targets.extend(m for m in matches if m.is_file())
        elif Path(pattern).is_file():
            targets.append(Path(pattern))
        else:
            print(f"warning: no file matched {pattern!r}", file=sys.stderr)
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect .uasset packages without launching Unreal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="+", metavar="UASSET", help="files or glob patterns")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--refs", action="store_true", help="only referenced package paths")
    mode.add_argument("--classes", action="store_true", help="only referenced /Script class paths")

    parser.add_argument("--grep", metavar="TEXT", help="case-insensitive substring filter on results")
    parser.add_argument("--filter", metavar="PREFIX", help="with --refs, keep only paths under PREFIX")
    parser.add_argument("--count", action="store_true", help="print a count per file instead of the entries")
    parser.add_argument("--offsets", action="store_true", help="show byte offsets (full string mode only)")
    parser.add_argument("--json", action="store_true", help="emit JSON keyed by file")

    args = parser.parse_args(argv)
    targets = _iter_targets(args.paths)
    if not targets:
        print("No .uasset files matched.", file=sys.stderr)
        return 2

    report: dict[str, object] = {}
    exit_code = 0

    for target in targets:
        try:
            if args.refs:
                entries = referenced_packages(target, prefix=args.filter)
            elif args.classes:
                entries = referenced_classes(target)
            else:
                entries = [text for _offset, text in read_strings(target)]
                if args.offsets:
                    entries = [f"{offset:<9} {text}" for offset, text in read_strings(target)]
        except (ValueError, OSError) as err:
            print(f"{target}: {err}", file=sys.stderr)
            exit_code = 1
            continue

        if args.grep:
            needle = args.grep.lower()
            entries = [e for e in entries if needle in e.lower()]

        report[str(target)] = len(entries) if args.count else entries

    if args.json:
        print(json.dumps(report, indent=2))
        return exit_code

    multiple = len(report) > 1
    for name, entries in report.items():
        if args.count:
            print(f"{entries:>6}  {name}")
            continue
        if multiple:
            print(f"\n===== {name} =====")
        for entry in entries:
            print(f"  {entry}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
