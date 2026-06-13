# Weekend Warrior Development Tools

A collection of PowerShell and Python utilities for Unreal Engine 5 project management, asset auditing, build automation, and editor scripting.

All PowerShell tools are project-agnostic — they accept a `-ProjectRoot` parameter and auto-detect the project when run from a `tools/` subfolder inside a UE5 project. Python tools run inside the Unreal Editor via the built-in `unreal` Python module.

---

## PowerShell Tools (`tools/`)

### Build & Maintenance

| Script | Description |
|--------|-------------|
| `clean-untracked.ps1` | Remove `Binaries/`, `Intermediate/`, `DerivedDataCache/` from the project and plugins, with git-awareness to skip tracked files |
| `clean-and-regen.ps1` | Deep-clean all build artifacts (including `.vs/` and `Saved/`) **and** regenerate Visual Studio project files via UnrealBuildTool |
| `headless-cook.ps1` | Run a headless build-cook-package cycle via UAT (`RunUAT.bat`) without opening the editor |
| `setup-daily-cleanup.ps1` | Register a Windows Scheduled Task to run `clean-untracked.ps1` daily (requires Admin) |

### Project Inventory

| Script | Description |
|--------|-------------|
| `list-installed-plugins.ps1` | List all plugins (game features, project, engine) from the `.uproject` file and local `.uplugin` files |
| `generate-ue5-plugin-catalog.ps1` | Scan the UE5 engine directory and output a full JSON catalog of available engine plugins |
| `level-world-inventory.ps1` | Find all `.umap` files in `Content/` and report path, category, and file size |
| `list-animation-assets.ps1` | Inventory animation assets and Pose Search data across Game Feature plugins (auto-detects plugins) |

### Asset Analysis

| Script | Description |
|--------|-------------|
| `asset-prefix-breakdown.ps1` | Categorize `.uasset` files by naming prefix (`SM_`, `T_`, `BP_`, etc.) and flag assets needing cleanup |
| `count-assets-by-type.ps1` | Count all Content assets grouped by file extension and top-level folder |
| `find-large-assets.ps1` | Find assets above a size threshold (default 10 MB), ranked by size |

### Code Quality

| Script | Description |
|--------|-------------|
| `source-code-tech-debt-scanner.ps1` | Scan `.cpp`/`.h` files for `TODO`, `FIXME`, `HACK`, and `OPTIMIZE` comments |

### Document Conversion

| Script | Description |
|--------|-------------|
| `convert_docx_to_pdf.ps1` | Convert `.docx` files to PDF using Microsoft Word (COM automation) |
| `convert_html_to_pdf.ps1` | Convert `.html` files to PDF using Microsoft Edge headless mode |

### Reporting

| Script | Description |
|--------|-------------|
| `project-health-report.ps1` | Orchestrator — runs all inventory tools and writes a combined JSON health report |

---

## Python Editor Scripts (`tools/python/`)

These scripts run **inside the Unreal Editor** via `Edit > Execute Python Script` or the Python console. They require the `Python Editor Script Plugin` to be enabled in your project.

| Script | Description |
|--------|-------------|
| `lint_asset_names.py` | Scan a Content path and auto-rename assets that violate UE5 naming conventions (`T_`, `SM_`, `BP_`, etc.) — supports dry-run mode |
| `generate_orm_texture.py` | Create a channel-packed ORM texture asset (R=AO, G=Roughness, B=Metallic) from three source textures |
| `spawn_procedural_grid.py` | Spawn actors in a configurable rows×cols grid in the current level, with dry-run and clear utilities |

---

## Usage

### PowerShell

Run any script from the repo root (or from the `tools/` folder of your UE5 project):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\<script-name>.ps1
```

**Common parameters** (most scripts support these):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-ProjectRoot` | Two levels above `tools/` | Path to your UE5 project root |
| `-OutputPath` | `tools/outputs/<name>.json` | Where to write JSON output |
| `-DryRun` | `$false` | Preview changes without modifying anything |

**Examples:**

```powershell
# Deep clean + regen VS project files
powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean-and-regen.ps1

# Headless cook for Shipping
powershell -NoProfile -ExecutionPolicy Bypass -File tools\headless-cook.ps1 -Config Shipping -StagingDir D:\Builds\MyGame

# Find assets over 50 MB
powershell -NoProfile -ExecutionPolicy Bypass -File tools\find-large-assets.ps1 -ThresholdMB 50

# Full project health report
powershell -NoProfile -ExecutionPolicy Bypass -File tools\project-health-report.ps1
```

### Python (Unreal Editor)

Open the editor Python console (`Window > Developer Tools > Python`):

```python
# Dry-run naming lint on a folder
import lint_asset_names
lint_asset_names.lint_and_fix_asset_names("/Game/MyProject", dry_run=True)

# Apply fixes
lint_asset_names.lint_and_fix_asset_names("/Game/MyProject", dry_run=False)

# Preview procedural grid spawn
import spawn_procedural_grid
spawn_procedural_grid.spawn_grid(
    actor_path="/Game/Core/Environment/BP_GridNode.BP_GridNode_C",
    rows=10, cols=10, spacing=300.0, dry_run=True
)
```

To run a Python script on editor startup, register it in **Project Settings > Plugins > Python > Startup Scripts**.

---

## Setup

1. **Clone** this repo or copy the `tools/` folder into the root of your UE5 project.
2. Add `tools/outputs/` to your project's `.gitignore` — outputs are local and not meant to be committed.
3. For daily cleanup automation, run `setup-daily-cleanup.ps1` as Administrator.
4. For Python editor scripts, enable the **Python Editor Script Plugin** in your project plugins list.

---

## Requirements

| Requirement | Used by |
|-------------|---------|
| Windows PowerShell 5.1+ | All `.ps1` scripts |
| Unreal Engine 5 project | All scripts |
| Git | `clean-untracked.ps1` (tracked-file detection) |
| UnrealBuildTool | `clean-and-regen.ps1` |
| RunUAT.bat | `headless-cook.ps1` |
| Microsoft Word | `convert_docx_to_pdf.ps1` |
| Microsoft Edge | `convert_html_to_pdf.ps1` |
| UE5 Python Editor Script Plugin | All `python/` scripts |
