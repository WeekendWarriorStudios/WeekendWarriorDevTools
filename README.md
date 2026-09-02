# Weekend Warrior Development Tools

A collection of PowerShell and Python utilities for Unreal Engine 5 project management, asset auditing, build automation, and editor scripting.

All PowerShell tools are project-agnostic — they accept a `-ProjectRoot` parameter and auto-detect the project when run from a `tools/` subfolder inside a UE5 project. Python tools run inside the Unreal Editor via the built-in `unreal` Python module.

---

## Directory Structure

```
tools/
├── build/              # Build & cleanup automation
├── inventory/          # Asset & plugin inventory & reporting
├── analysis/           # Asset analysis & metrics
├── quality/            # Code quality scanning
├── convert/            # Document format conversion
├── python/
│   ├── assets/         # Asset-related editor automation
│   ├── level/          # Level/world-related automation
│   └── editor/         # Editor session control & pipeline auditing
└── outputs/            # Generated JSON reports (gitignored)
```

Three execution contexts, and it matters which is which:

| Context | Where it runs | Scripts |
|---------|---------------|---------|
| PowerShell | Terminal, no editor needed | everything under `build/`, `inventory/`, `analysis/*.ps1`, `quality/`, `convert/` |
| System Python | Terminal, no editor needed | `analysis/uasset_inspect.py`, `python/editor/ue_remote_exec.py` |
| Editor Python | Inside Unreal, via console or `ue_remote_exec.py` | `python/assets/`, `python/level/`, `python/editor/audit_motion_matching.py` |

---

## PowerShell Tools

### build/ — Build & Maintenance

| Script | Description |
|--------|-------------|
| `clean-untracked.ps1` | Remove `Binaries/`, `Intermediate/`, `DerivedDataCache/` from project and plugins, with git-awareness for tracked files |
| `clean-and-regen.ps1` | Deep-clean all build artifacts **and** regenerate Visual Studio project files via UnrealBuildTool |
| `headless-cook.ps1` | Run a headless build-cook-package cycle via UAT (`RunUAT.bat`) without opening the editor |
| `setup-daily-cleanup.ps1` | Register a Windows Scheduled Task to run `clean-untracked.ps1` daily (requires Admin) |
| `build-log-parser.ps1` | Parse build/cook logs, extract warnings/errors into a ranked JSON report |
| `shader-monitor.ps1` | Monitor shader compilation status during cook, report on stalled/failed shaders |

**Usage:**
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build\clean-untracked.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build\clean-and-regen.ps1 -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build\headless-cook.ps1 -Config Shipping
```

### inventory/ — Asset & Plugin Inventory

| Script | Description |
|--------|-------------|
| `list-installed-plugins.ps1` | List all plugins (game features, project, engine) from `.uproject` and local `.uplugin` files |
| `generate-ue5-plugin-catalog.ps1` | Scan UE5 engine directory and output full JSON catalog of available engine plugins |
| `level-world-inventory.ps1` | Find all `.umap` files in `Content/` with path, category, and size |
| `list-animation-assets.ps1` | Inventory animation assets and Pose Search data across Game Feature plugins (auto-detects) |
| `project-health-report.ps1` | **Orchestrator** — runs all inventory tools and writes combined JSON health report |

**Usage:**
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\inventory\project-health-report.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\inventory\list-installed-plugins.ps1 -OutputPath C:\reports\plugins.json
```

### analysis/ — Asset Analysis & Metrics

| Script | Description |
|--------|-------------|
| `asset-prefix-breakdown.ps1` | Categorize `.uasset` files by naming prefix (`SM_`, `T_`, `BP_`, etc.) and flag cleanup violations |
| `count-assets-by-type.ps1` | Count all Content assets grouped by file extension and top-level folder |
| `find-large-assets.ps1` | Find assets above size threshold (default 10 MB), ranked by size |
| `memory-profile-reporter.ps1` | Parse memory profiler dumps, generate size breakdowns by category |
| `dependency-analyzer.ps1` | Find unused assets, circular dependencies, and broken redirects |
| `texture-streaming-analyzer.ps1` | Analyze streaming pool usage vs. config, flag oversubscription |
| `uasset_inspect.py` | **(Python)** Read what a `.uasset` references — name table, asset dependencies, node/class types — without launching the editor |

**Usage:**
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\analysis\find-large-assets.ps1 -ThresholdMB 50 -Top 25
powershell -NoProfile -ExecutionPolicy Bypass -File tools\analysis\count-assets-by-type.ps1

# uasset_inspect: which animations are in each Pose Search database?
python tools\analysis\uasset_inspect.py --refs --filter /MyPlugin/Animations --count "Databases\**\*.uasset"

# which gameplay tags does this Chooser filter on?
python tools\analysis\uasset_inspect.py --grep "State.Locomotion" CT_Locomotion_Master.uasset

# which anim graph node types is this Anim Blueprint built from?
python tools\analysis\uasset_inspect.py --classes ABP_Character.uasset
```

`uasset_inspect` is a reader, not a full parser: it recovers strings (names, paths, class and enum
identifiers) but not numeric property values. Use it to answer "does A still reference B", "is this
database actually empty", and "did that editor operation really save" — the last one matters, because
editor automation can report success without writing to disk.

### quality/ — Code Quality

| Script | Description |
|--------|-------------|
| `source-code-tech-debt-scanner.ps1` | Scan `.cpp`/`.h` files for `TODO`, `FIXME`, `HACK`, and `OPTIMIZE` comments |

**Usage:**
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\quality\source-code-tech-debt-scanner.ps1
```

### convert/ — Document Conversion

| Script | Description |
|--------|-------------|
| `convert_docx_to_pdf.ps1` | Convert `.docx` files to PDF using Microsoft Word (COM automation) |
| `convert_html_to_pdf.ps1` | Convert `.html` files to PDF using Microsoft Edge headless mode |
| `convert-markdown-to-pdf.ps1` | Convert a markdown tree to PDF, mirroring its folder structure (headless Edge/Chrome via puppeteer-core). Defaults to `Documentation\generated-api\markdown` -> `...\generated-api\pdf` |

---

## Python Editor Scripts

These scripts run **inside the Unreal Editor** via `Edit > Execute Python Script` or the Python console. Requires the **Python Editor Script Plugin** enabled in your project.

### python/assets/ — Asset-Related Automation

| Script | Description |
|--------|-------------|
| `bulk_move_assets.py` | **(Editor Python)** Relocate many assets between content roots in one reviewed pass, references intact — folder rules + per-asset overrides, dry-run by default. Codifies two traps: `delete_asset` silently leaves git-tracked `.uasset` files on disk, and deleting a redirector strands a phantom package on that name until the editor restarts |
| `lint_asset_names.py` | Scan Content path and auto-rename assets violating UE5 naming conventions (`T_`, `SM_`, `BP_`, etc.) — supports dry-run |
| `generate_orm_texture.py` | Create channel-packed ORM texture asset (R=AO, G=Roughness, B=Metallic) from three source textures |
| `validate-asset-data.py` | Scan Content for broken references, missing materials, orphaned textures, redirect chains |
| `blueprint-perf-advisor.py` | Profile heavy Blueprints, suggest optimization (Nativization, event graphs, tick settings) |
| `localization-gatherer.py` | Auto-scan Content for FText strings, organize into .po files by category |
| `nativization-recommender.py` | Analyze Blueprint complexity/call counts, recommend Nativization candidates |

**Usage (editor Python console):**
```python
import sys
sys.path.insert(0, r"A:\Projects\MyGame\tools\python\assets")

# Validate asset integrity
import validate_asset_data
validate_asset_data.validate_all("/Game/", dry_run=True)

# Get Blueprint optimization suggestions
import blueprint_perf_advisor
blueprint_perf_advisor.analyze_blueprints("/Game/", max_results=20)

# Find Nativization candidates
import nativization_recommender
nativization_recommender.recommend_nativization("/Game/", target_count=10)
```

### python/editor/ — Editor Session Control & Pipeline Auditing

| Script | Description |
|--------|-------------|
| `ue_remote_exec.py` | **(System Python)** Execute Python inside an *already-running* editor over the Python Remote Execution protocol — no restart, no clicking through the UI |
| `audit_motion_matching.py` | **(Editor Python)** Validate a Pose Search pipeline end to end: schemas, databases, Chooser routing, unreachable databases, empty databases a Chooser still points at |
| `wire_trajectory_to_pose_history.py` | **(Editor Python)** Connect an AnimInstance trajectory property to the Pose History node's Trajectory pin — the input motion matching silently fails without |
| `rebuild_motion_matching_animgraph.py` | **(Editor Python)** Replace a hand-rolled Sequence Player + `MotionMatch` graph with the real Motion Matching node, and splice in a Slot so montages are visible |

**Setup for `ue_remote_exec.py`** — once, in the editor:
**Edit > Project Settings > Plugins > Python > [x] Enable Remote Execution**. Takes effect
immediately; no restart required.

**Usage:**
```powershell
# what editors are running?
python tools\python\editor\ue_remote_exec.py --ping

# one-liners
python tools\python\editor\ue_remote_exec.py --eval "unreal.SystemLibrary.get_engine_version()"

# run an editor script from the terminal, or from CI
python tools\python\editor\ue_remote_exec.py --file tools\python\editor\audit_motion_matching.py
python tools\python\editor\ue_remote_exec.py --file tools\python\assets\validate-asset-data.py --json
```

Exit codes: `0` success, `1` the remote command raised, `2` no editor found / channel refused,
`3` usage error — so it slots into a build script without parsing output.

**`audit_motion_matching.py` from the editor console:**
```python
import sys; sys.path.insert(0, r"A:\Projects\CollateralDamage\WeekendWarriorDevTools\tools\python\editor")
import audit_motion_matching
audit_motion_matching.audit("/MyPlugin/Movement/PoseSearch")
```

Motion matching fails silently — a wrong skeleton, an empty database, or a database no Chooser
routes to produces a bad pose or reference pose with nothing in the log. This names the asset at
fault instead.

**Running editor Python with no editor open.** All three editor scripts also work as a commandlet,
which is how to use them from CI or while the editor is closed:

```powershell
& "$Engine\Binaries\Win64\UnrealEditor-Cmd.exe" MyProject.uproject `
    -run=pythonscript -script="...\audit_motion_matching.py" -unattended -nopause -nosplash
```

Two things to know about that mode. `unreal.log` output does **not** reach stdout under
`-unattended` — read `Saved/Logs/<Project>.log`, or have the script write its own file. And the
asset registry is not scanned up front the way it is in an interactive editor, so any script that
uses `ARFilter` must call `scan_paths_synchronous` first or it will quietly find zero assets.

### python/level/ — Level/World Automation

| Script | Description |
|--------|-------------|
| `spawn_procedural_grid.py` | Spawn actors in configurable rows×cols grid in current level, with dry-run and clear utilities |
| `world-partition-analyzer.py` | Analyze World Partition cell sizes, load distribution, streaming density |

**Usage (editor Python console):**
```python
import sys
sys.path.insert(0, r"A:\Projects\MyGame\tools\python\level")

# Analyze world partition efficiency
import world_partition_analyzer
world_partition_analyzer.analyze_world_partition(max_cells=50)

# Procedural grid spawning
import spawn_procedural_grid
spawn_procedural_grid.spawn_grid(
    actor_path="/Game/Core/Environment/BP_GridNode.BP_GridNode_C",
    rows=10, cols=10, spacing=300.0, dry_run=True
)
```

---

## Common Parameters

Most PowerShell scripts support:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-ProjectRoot` | Auto-detected (2 levels above script) | Path to UE5 project root |
| `-OutputPath` | `tools/outputs/<name>.json` | Where to write JSON output |
| `-DryRun` | `$false` | Preview changes without modifying |

---

## Setup

1. **Copy or clone** this repo into the root of your UE5 project, or run scripts with explicit `-ProjectRoot`.
2. **Add to .gitignore:**
   ```
   tools/outputs/
   ```
3. **Enable Python (optional):** In **Project Settings > Plugins**, search and enable **Python Editor Script Plugin**.
4. **Schedule cleanup (optional):** Run as Administrator:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File tools\build\setup-daily-cleanup.ps1
   ```

---

## Requirements

| Tool | Required For |
|------|--------------|
| Windows PowerShell 5.1+ | All `.ps1` scripts |
| Unreal Engine 5 project | All scripts |
| Git | `build/clean-untracked.ps1` (tracked-file detection) |
| UnrealBuildTool | `build/clean-and-regen.ps1` |
| RunUAT.bat | `build/headless-cook.ps1` |
| Microsoft Word | `convert/convert_docx_to_pdf.ps1` |
| Microsoft Edge | `convert/convert_html_to_pdf.ps1`, `convert/convert-markdown-to-pdf.ps1` (Chrome also works) |
| Node.js | `convert/convert_html_to_markdown.ps1`, `convert/convert-markdown-to-pdf.ps1` (npm packages auto-installed) |
| UE5 Python Editor Script Plugin | `python/` scripts |
| System Python 3.9+ | `analysis/uasset_inspect.py`, `python/editor/ue_remote_exec.py` (no third-party packages) |
| Python Remote Execution enabled | `python/editor/ue_remote_exec.py` (Project Settings > Plugins > Python) |

---

## Notes

- Run the Python tools from PowerShell, not Git Bash. Git Bash (MSYS) rewrites any argument that
  starts with `/` into a Windows path, which silently mangles UE package paths — a
  `--filter /MyPlugin/Animations` becomes a drive path and matches nothing, with no error. Prefix
  with `MSYS_NO_PATHCONV=1` if you must use Git Bash.
- All JSON outputs go to `tools/outputs/` (add to `.gitignore`).
- Scripts are project-agnostic and work with any UE5 project structure.
- PowerShell scripts auto-detect UE5 engine paths (can be overridden with `-EnginePath`).
