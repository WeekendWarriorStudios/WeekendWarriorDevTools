param(
    [string]$ProjectRoot = '',
    [string]$OutputPath  = ''
)

$ErrorActionPreference = 'Stop'

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

if (-not $OutputPath) {
    $outDir = Join-Path $PSScriptRoot 'outputs'
    if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    $OutputPath = Join-Path $outDir 'installed-plugins.json'
}

function ConvertFrom-LenientJson {
    param([string]$Text)
    ($Text -replace ',(?=\s*[}\]])', '') | ConvertFrom-Json
}

function Read-UpluginMeta {
    param([string]$Path)
    $raw = Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue
    if (-not $raw) { return [ordered]@{} }
    $meta = ConvertFrom-LenientJson $raw
    [ordered]@{
        friendlyName   = if ($meta.FriendlyName)   { $meta.FriendlyName }   else { $null }
        version        = if ($meta.VersionName)     { $meta.VersionName }    else { $null }
        description    = if ($meta.Description)     { $meta.Description }    else { $null }
        category       = if ($meta.Category)        { $meta.Category }       else { $null }
        createdBy      = if ($meta.CreatedBy)       { $meta.CreatedBy }      else { $null }
        marketplaceUrl = if ($meta.MarketplaceURL)  { $meta.MarketplaceURL } else { $null }
    }
}

# --- auto-detect .uproject ---
$uprojectFiles = Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.uproject' -File -ErrorAction SilentlyContinue
if (-not $uprojectFiles) { Write-Error "No .uproject file found in: $ProjectRoot"; exit 1 }
$uprojectPath = $uprojectFiles[0].FullName
$projectName  = [System.IO.Path]::GetFileNameWithoutExtension($uprojectPath)

# --- .uproject plugin enabled map ---
$uproject     = ConvertFrom-LenientJson (Get-Content -LiteralPath $uprojectPath -Raw)
$uprojectMap  = @{}
foreach ($p in $uproject.Plugins) {
    $uprojectMap[$p.Name] = [bool]$p.Enabled
}

# --- Scan local .uplugin files ---
$pluginsRoot      = Join-Path $ProjectRoot 'Plugins'
$gameFeaturesRoot = Join-Path $pluginsRoot 'Game Features'

$allUplugins = Get-ChildItem -LiteralPath $pluginsRoot -Recurse -Filter '*.uplugin' -File |
               Sort-Object BaseName

$gameFeatures   = [System.Collections.Generic.List[object]]::new()
$projectPlugins = [System.Collections.Generic.List[object]]::new()
$localNames     = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

foreach ($file in $allUplugins) {
    $name        = $file.BaseName
    [void]$localNames.Add($name)

    # plugins not listed in .uproject are implicitly enabled when present locally
    $enabled     = if ($uprojectMap.ContainsKey($name)) { $uprojectMap[$name] } else { $true }
    $meta        = Read-UpluginMeta $file.FullName
    $relPath     = $file.DirectoryName.Substring($ProjectRoot.Length + 1).Replace('\', '/')

    $entry = [ordered]@{
        name           = $name
        enabled        = $enabled
        path           = $relPath
        friendlyName   = $meta.friendlyName
        version        = $meta.version
        description    = $meta.description
        category       = $meta.category
        createdBy      = $meta.createdBy
        marketplaceUrl = $meta.marketplaceUrl
    }

    if ($file.DirectoryName.StartsWith($gameFeaturesRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        $gameFeatures.Add($entry)
    } else {
        $projectPlugins.Add($entry)
    }
}

# --- Engine plugins (in .uproject but no local .uplugin) ---
$enginePlugins = $uprojectMap.Keys |
    Where-Object { -not $localNames.Contains($_) } |
    Sort-Object |
    ForEach-Object {
        [ordered]@{ name = $_; enabled = $uprojectMap[$_] }
    }

# --- Content packs (top-level Content/ folders, excluding project and system folders) ---
$systemFolders = [System.Collections.Generic.HashSet[string]]::new(
    [string[]]@($projectName, 'Collections', 'Developers', '__ExternalActors__', '__ExternalObjects__'),
    [System.StringComparer]::OrdinalIgnoreCase
)
$contentPacks = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'Content') -Directory |
    Where-Object { -not $systemFolders.Contains($_.Name) } |
    Sort-Object Name |
    ForEach-Object { $_.Name }

# --- Assemble output ---
$result = [ordered]@{
    generated    = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    projectFile  = (Split-Path $uprojectPath -Leaf)
    summary      = [ordered]@{
        gameFeatures   = $gameFeatures.Count
        projectPlugins = $projectPlugins.Count
        enginePlugins  = @($enginePlugins).Count
        contentPacks   = @($contentPacks).Count
    }
    gameFeatures   = $gameFeatures
    projectPlugins = $projectPlugins
    enginePlugins  = @($enginePlugins)
    contentPacks   = @($contentPacks)
}

$json = $result | ConvertTo-Json -Depth 6
Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8

Write-Host "Game features: $($gameFeatures.Count) | Project plugins: $($projectPlugins.Count) | Engine plugins: $(@($enginePlugins).Count) | Content packs: $(@($contentPacks).Count)"
Write-Host "Written to: $OutputPath"
