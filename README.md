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
│   └── level/          # Level/world-related automation
└── outputs/            # Generated JSON reports (gitignored)
```

---

## PowerShell Tools

### build/ — Build & Maintenance

| Script | Description |
|--------|-------------|
| `clean-untracked.ps1` | Remove `Binaries/`, `Intermediate/`, `DerivedDataCache/` from project and plugins, with git-awareness for tracked files |
| `clean-and-regen.ps1` | Deep-clean all build artifacts **and** regenerate Visual Studio project files via UnrealBuildTool |
| `headless-cook.ps1` | Run a headless build-cook-package cycle via UAT (`RunUAT.bat`) without opening the editor |
| `setup-daily-cleanup.ps1` | Register a Windows Scheduled Task to run `clean-untracked.ps1` daily (requires Admin) |

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

**Usage:**
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\analysis\find-large-assets.ps1 -ThresholdMB 50 -Top 25
powershell -NoProfile -ExecutionPolicy Bypass -File tools\analysis\count-assets-by-type.ps1
```

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

---

## Python Editor Scripts

These scripts run **inside the Unreal Editor** via `Edit > Execute Python Script` or the Python console. Requires the **Python Editor Script Plugin** enabled in your project.

### python/assets/ — Asset-Related Automation

| Script | Description |
|--------|-------------|
| `lint_asset_names.py` | Scan Content path and auto-rename assets violating UE5 naming conventions (`T_`, `SM_`, `BP_`, etc.) — supports dry-run |
| `generate_orm_texture.py` | Create channel-packed ORM texture asset (R=AO, G=Roughness, B=Metallic) from three source textures |

**Usage (editor Python console):**
```python
import sys
sys.path.insert(0, r"A:\Projects\MyGame\tools\python\assets")
import lint_asset_names
lint_asset_names.lint_and_fix_asset_names("/Game/MyProject", dry_run=True)
```

### python/level/ — Level/World Automation

| Script | Description |
|--------|-------------|
| `spawn_procedural_grid.py` | Spawn actors in configurable rows×cols grid in current level, with dry-run and clear utilities |

**Usage (editor Python console):**
```python
import sys
sys.path.insert(0, r"A:\Projects\MyGame\tools\python\level")
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
| Microsoft Edge | `convert/convert_html_to_pdf.ps1` |
| UE5 Python Editor Script Plugin | `python/` scripts |

---

## Notes

- All JSON outputs go to `tools/outputs/` (add to `.gitignore`).
- Scripts are project-agnostic and work with any UE5 project structure.
- PowerShell scripts auto-detect UE5 engine paths (can be overridden with `-EnginePath`).
