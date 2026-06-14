param(
    [string]$EngineRoot = '',
    [string]$OutputPath = ''
)

if (-not $EngineRoot) {
    # Try to auto-detect common UE5 locations
    $possibleEngines = @(
        'C:\Program Files\Epic Games\UE_5.7\Engine',
        'C:\Program Files (x86)\Epic Games\UE_5.7\Engine',
        'D:\Epic Games\UE_5.7\Engine',
        'E:\Epic Games\UE_5.7\Engine',
        'A:\GE\UE_5.7\Engine'
    )

    foreach ($path in $possibleEngines) {
        if (Test-Path $path) {
            $EngineRoot = $path
            break
        }
    }

    if (-not $EngineRoot) {
        Write-Error "Engine root not found. Tried: $($possibleEngines -join ', '). Please specify -EngineRoot parameter."
        exit 1
    }
}

if (-not $OutputPath) {
    $outDir = Join-Path $PSScriptRoot 'outputs'
    if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    $OutputPath = Join-Path $outDir 'UE5-Available-Plugins.json'
}

$ErrorActionPreference = 'Stop'

function ConvertFrom-LenientJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true, ValueFromPipeline = $true)]
        [string]$Text
    )

    process {
        $normalizedText = $Text -replace ',(?=\s*[}\]])', ''
        $normalizedText | ConvertFrom-Json
    }
}

$manifestFiles = Get-ChildItem -Path $EngineRoot -Recurse -Filter *.uplugin -File | Sort-Object FullName

$plugins = foreach ($file in $manifestFiles) {
    $manifest = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-LenientJson

    $relativePath = $file.FullName.Substring($EngineRoot.Length + 1).Replace('\', '/')
    $folderPath = [System.IO.Path]::GetDirectoryName($relativePath).Replace('\', '/')
    $segments = @()
    if ($folderPath) {
        $segments = @($folderPath.Split('/') | Where-Object { $_ })
    }

    $rootArea = if ($segments.Count -gt 0) { $segments[0] } else { $null }
    $folderCategory = if ($segments.Count -gt 1) { $segments[1] } else { $null }

    $modules = @()
    if ($manifest.Modules) {
        $modules = @(
            $manifest.Modules | ForEach-Object {
                [ordered]@{
                    name = $_.Name
                    type = $_.Type
                    loadingPhase = $_.LoadingPhase
                }
            }
        )
    }

    $pluginDependencies = @()
    if ($manifest.Plugins) {
        $pluginDependencies = @(
            $manifest.Plugins | ForEach-Object {
                [ordered]@{
                    name = $_.Name
                    enabled = [bool]$_.Enabled
                }
            }
        )
    }

    [ordered]@{
        pluginId = $file.BaseName
        displayName = if ($manifest.FriendlyName) { $manifest.FriendlyName } else { $file.BaseName }
        manifestFile = $file.Name
        manifestPath = $relativePath
        folderPath = $folderPath
        rootArea = $rootArea
        folderCategory = $folderCategory
        pathSegments = $segments
        category = $manifest.Category
        description = $manifest.Description
        createdBy = $manifest.CreatedBy
        createdByUrl = $manifest.CreatedByURL
        docsUrl = $manifest.DocsURL
        marketplaceUrl = $manifest.MarketplaceURL
        supportUrl = $manifest.SupportURL
        version = [ordered]@{
            fileVersion = $manifest.FileVersion
            version = $manifest.Version
            versionName = $manifest.VersionName
        }
        availability = [ordered]@{
            enabledByDefault = [bool]$manifest.EnabledByDefault
            canContainContent = [bool]$manifest.CanContainContent
            isBetaVersion = [bool]$manifest.IsBetaVersion
            installed = [bool]$manifest.Installed
        }
        moduleCount = $modules.Count
        modules = $modules
        dependencyCount = $pluginDependencies.Count
        pluginDependencies = $pluginDependencies
        rawManifest = $manifest
    }
}

$summary = [ordered]@{
    totalManifests = @($plugins).Count
    byRootArea = @(
        $plugins |
            Group-Object { $_.rootArea } |
            Sort-Object Name |
            ForEach-Object {
                [ordered]@{
                    rootArea = if ($_.Name) { $_.Name } else { '(root)' }
                    count = $_.Count
                }
            }
    )
    byFolderCategory = @(
        $plugins |
            Group-Object { $_.folderCategory } |
            Sort-Object Name |
            ForEach-Object {
                [ordered]@{
                    folderCategory = if ($_.Name) { $_.Name } else { '(none)' }
                    count = $_.Count
                }
            }
    )
    byDeclaredCategory = @(
        $plugins |
            Group-Object { $_.category } |
            Sort-Object Name |
            ForEach-Object {
                [ordered]@{
                    category = if ($_.Name) { $_.Name } else { '(none)' }
                    count = $_.Count
                }
            }
    )
    byEnabledByDefault = @(
        $plugins |
            Group-Object { if ($_.availability.enabledByDefault) { 'true' } else { 'false' } } |
            Sort-Object Name |
            ForEach-Object {
                [ordered]@{
                    enabledByDefault = $_.Name
                    count = $_.Count
                }
            }
    )
}

$output = [ordered]@{
    schemaVersion = '1.0'
    generatedAt = (Get-Date).ToString('o')
    engineRoot = $EngineRoot.Replace('\', '/')
    scanScope = [ordered]@{
        included = @('Engine/Plugins', 'Engine/Platforms', 'Engine/Source')
        excluded = @('Engine/../../../Projects/*/Plugins')
        note = 'This catalog covers engine-scoped plugin manifests only; project plugin folders are excluded.'
    }
    summary = $summary
    plugins = $plugins
}

$outputDir = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

$output | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Wrote $($summary.totalManifests) plugin manifests to $OutputPath"
