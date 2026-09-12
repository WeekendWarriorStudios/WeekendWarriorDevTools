#Requires -Version 5.1
<#
.SYNOPSIS
    Converts Unreal Engine's UDN documentation/tooltip source files to markdown.

.DESCRIPTION
    Walks <EnginePath>\Engine\Documentation\Source - Epic's UDN-format tooltip/help text that
    ships with every engine install (the same content that backs in-editor tooltips, and that
    used to back docs.unrealengine.com before Epic moved to the current dev.epicgames.com site)
    - and converts each matched file to markdown, mirroring the source's relative folder
    structure under -OutputDir.

    UDN is a lightweight bracket-tag markup that predates Epic's move to the current docs site:
        Key: Value                           header metadata (Title, Availability, Crumbs, ...)
        [EXCERPT:Name] ... [/EXCERPT:Name]   named content fragment (e.g. one enum value's tooltip)
        [VAR:Name] ... [/VAR]                named reusable snippet
        [REGION:tip] ... [/REGION]           callout box
        [COMMENT:...] ... [/COMMENT]         author-only note, dropped from the output
        [PUBLISH:Rocket] ... [/PUBLISH]      per-distribution-channel content, unwrapped as-is
    Everything else (**bold**, bullet lists, `---` rules, ![](image.png) images, [text](path)
    links) is already valid markdown and passes through unchanged. Each EXCERPT/VAR becomes its
    own heading, so a file with many named fragments (e.g. one EXCERPT per enum value) reads as a
    normal sectioned document instead of an unbroken wall of tooltip text. The single-value
    [VAR:ToolTipFullLink] fragment Epic uses to point a tooltip at its full doc page is rendered
    as a "See also" line instead of its own heading.

    Referenced local images are copied alongside their .md file at the same relative layout, so
    the generated tree can be browsed or zipped on its own with working image links.

    Only *.INT.udn (English) files are converted by default - Epic ships parallel .CHN/.JPN/.KOR
    translations of the same content; pass -Locales to add them.

.PARAMETER EnginePath
    Root of the Unreal Engine install (folder containing Engine\Documentation\...). Defaults to
    "A:\GE\UE_5.8".

.PARAMETER SourceDir
    UDN source root to scan. Defaults to <EnginePath>\Engine\Documentation\Source.

.PARAMETER ProjectRoot
    Project root used to resolve the default -OutputDir. Defaults to the folder three levels
    above this script (tools\convert -> tools -> WeekendWarriorDevTools -> ProjectRoot).

.PARAMETER OutputDir
    Where markdown is written. Defaults to
    <ProjectRoot>\Documentation\generated-api\markdown\unreal.

.PARAMETER Locales
    Locale suffixes to convert (matched against the "Name.<Locale>.udn" filename convention).
    Defaults to @('INT') - English only. The English output keeps the plain "<Name>.md" filename;
    any other requested locale is written alongside it as "<Name>.<Locale>.md".

.PARAMETER Exclude
    Path globs (relative to -SourceDir, forward slashes, wildcards via -like) to skip, e.g.
    "Shared/Enums/**".

.PARAMETER Max
    Stop after this many files. Useful for smoke-testing before a full run.

.PARAMETER Force
    Re-convert every file, ignoring up-to-date markdown.

.PARAMETER DryRun
    List what would be written without writing anything.

.EXAMPLE
    .\convert-udn-to-markdown.ps1
    .\convert-udn-to-markdown.ps1 -DryRun
    .\convert-udn-to-markdown.ps1 -Locales INT,CHN
    .\convert-udn-to-markdown.ps1 -Exclude "Shared/Enums/**" -Max 10
    .\convert-udn-to-markdown.ps1 -Force
#>
param(
    [string]$EnginePath = "A:\GE\UE_5.8",
    [string]$SourceDir = "",
    [string]$ProjectRoot = "",
    [string]$OutputDir = "",
    [string[]]$Locales = @('INT'),
    [string[]]$Exclude = @(),
    [int]$Max = 0,
    [switch]$Force,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# tools\convert -> tools -> WeekendWarriorDevTools -> <ProjectRoot>
if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
}
if (-not (Test-Path $ProjectRoot)) {
    Write-Host "[ERROR] Project root not found: $ProjectRoot" -ForegroundColor Red
    exit 1
}
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

if (-not $SourceDir) {
    $SourceDir = Join-Path $EnginePath "Engine\Documentation\Source"
}
if (-not (Test-Path $SourceDir)) {
    Write-Host "[ERROR] UDN source directory not found: $SourceDir" -ForegroundColor Red
    Write-Host "        Pass -EnginePath or -SourceDir explicitly." -ForegroundColor Red
    exit 1
}
$SourceDir = (Resolve-Path $SourceDir).Path.TrimEnd('\', '/')

if (-not $OutputDir) {
    $OutputDir = Join-Path $ProjectRoot "Documentation\generated-api\markdown\unreal"
}

# ---------------------------------------------------------------------------
# UDN -> markdown conversion
# ---------------------------------------------------------------------------

$OpenTagRe    = '^\s*\[(EXCERPT|VAR|REGION|COMMENT|PUBLISH):([^\]]*)\]\s*$'
$CloseTagRe   = '^\s*\[/(EXCERPT|VAR|REGION|COMMENT|PUBLISH)(?::[^\]]*)?\]\s*$'
$MetadataRe   = '^\s*([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*)$'
$VarCloseRe   = '^\s*\[/VAR\]\s*$'
$ImageRefRe   = '!\[[^\]]*\]\(([^)]+)\)'

$RegionLabels = @{
    tip        = 'Tip'
    warning    = 'Warning'
    note       = 'Note'
    important  = 'Important'
    simplenote = 'Note'
    raw        = 'Note'
}

function Get-UdnMetadata {
    param([string[]]$Lines)

    $meta = [ordered]@{}
    $i = 0
    while ($i -lt $Lines.Count) {
        $line = $Lines[$i]
        if ($line -match $MetadataRe) {
            $meta[$Matches[1]] = $Matches[2].Trim()
            $i++
        } else {
            break
        }
    }
    return @{ Meta = $meta; BodyStart = $i }
}

# Converts the body lines of one .udn file (after the header metadata block) to markdown lines.
function ConvertTo-UdnBody {
    param([string[]]$Lines, [int]$StartIndex)

    $out = New-Object System.Collections.Generic.List[string]
    $stack = New-Object System.Collections.Generic.List[hashtable]
    $headingDepth = 0
    $regionDepth = 0
    $commentDepth = 0

    $i = $StartIndex
    while ($i -lt $Lines.Count) {
        $line = $Lines[$i]

        if ($commentDepth -gt 0) {
            if ($line -match $OpenTagRe -and $Matches[1] -eq 'COMMENT') { $commentDepth++ }
            elseif ($line -match $CloseTagRe -and $Matches[1] -eq 'COMMENT') { $commentDepth-- }
            $i++
            continue
        }

        if ($line -match $OpenTagRe) {
            $tag = $Matches[1]
            $name = $Matches[2].Trim()

            if ($tag -eq 'COMMENT') {
                $commentDepth = 1
                $i++
                continue
            }

            if ($tag -eq 'VAR' -and $name -eq 'ToolTipFullLink') {
                # Single-value fragment: Epic points a tooltip at its full doc page this way.
                # Collect the (usually one-line) body and render it as a "See also" note instead
                # of a heading of its own.
                $j = $i + 1
                $valueLines = New-Object System.Collections.Generic.List[string]
                while ($j -lt $Lines.Count -and $Lines[$j] -notmatch $VarCloseRe) {
                    if ($Lines[$j].Trim()) { $valueLines.Add($Lines[$j].Trim()) }
                    $j++
                }
                if ($valueLines.Count -gt 0) {
                    $out.Add("")
                    $out.Add("*See also: $($valueLines -join ' ')*")
                }
                $i = $j + 1
                continue
            }

            if ($tag -eq 'EXCERPT' -or $tag -eq 'VAR') {
                $level = [Math]::Min(2 + $headingDepth, 6)
                $stack.Add(@{ Tag = $tag })
                $headingDepth++
                $out.Add("")
                $out.Add(("#" * $level) + " " + $name)
                $out.Add("")
                $i++
                continue
            }

            if ($tag -eq 'REGION') {
                $stack.Add(@{ Tag = $tag })
                $regionDepth++
                $label = $RegionLabels[$name.ToLowerInvariant()]
                if (-not $label) { $label = 'Note' }
                $out.Add(">")
                $out.Add("> **${label}:**")
                $i++
                continue
            }

            # PUBLISH (or any other future tag): unwrap, content passes through as-is.
            $stack.Add(@{ Tag = $tag })
            $i++
            continue
        }

        if ($line -match $CloseTagRe) {
            $tag = $Matches[1]
            # Best-effort pop: match the nearest open frame of the same tag type so a stray or
            # misnested close never throws off the whole file.
            for ($k = $stack.Count - 1; $k -ge 0; $k--) {
                if ($stack[$k].Tag -eq $tag) {
                    $stack.RemoveAt($k)
                    break
                }
            }
            if ($tag -eq 'EXCERPT' -or $tag -eq 'VAR') { $headingDepth = [Math]::Max(0, $headingDepth - 1) }
            if ($tag -eq 'REGION') { $regionDepth = [Math]::Max(0, $regionDepth - 1) }
            $i++
            continue
        }

        if ($regionDepth -gt 0) {
            if ($line.Trim()) { $out.Add("> " + $line) } else { $out.Add(">") }
        } else {
            $out.Add($line)
        }
        $i++
    }

    # Collapse runs of blank lines and trim the ends - the tag markers leave a lot of them behind.
    $collapsed = New-Object System.Collections.Generic.List[string]
    $prevBlank = $false
    foreach ($l in $out) {
        $isBlank = -not $l.Trim()
        if ($isBlank -and $prevBlank) { continue }
        $collapsed.Add($l)
        $prevBlank = $isBlank
    }
    while ($collapsed.Count -gt 0 -and -not $collapsed[0].Trim()) { $collapsed.RemoveAt(0) }
    while ($collapsed.Count -gt 0 -and -not $collapsed[$collapsed.Count - 1].Trim()) { $collapsed.RemoveAt($collapsed.Count - 1) }

    return ,$collapsed
}

function ConvertTo-YamlScalar {
    param([string]$Value)
    if ($null -eq $Value) { return '""' }
    return '"' + ($Value -replace '\\', '\\\\' -replace '"', '\"') + '"'
}

function Convert-UdnFile {
    param(
        [string]$FullName,
        [string]$RelPath,     # forward-slash path relative to SourceDir, e.g. Shared/Foo/Foo.INT.udn
        [string]$Locale
    )

    $rawLines = Get-Content -LiteralPath $FullName -Encoding UTF8
    $parsed = Get-UdnMetadata -Lines $rawLines
    $meta = $parsed.Meta
    $bodyLines = ConvertTo-UdnBody -Lines $rawLines -StartIndex $parsed.BodyStart

    $title = if ($meta.Contains('Title') -and $meta['Title']) { $meta['Title'] } else { [System.IO.Path]::GetFileNameWithoutExtension((Split-Path -Leaf $FullName)) }

    $md = New-Object System.Collections.Generic.List[string]
    $md.Add("---")
    $md.Add("title: $(ConvertTo-YamlScalar $title)")
    $md.Add("source: $(ConvertTo-YamlScalar "Engine/Documentation/Source/$RelPath")")
    $md.Add("locale: $(ConvertTo-YamlScalar $Locale)")
    if ($meta.Contains('Availability')) { $md.Add("availability: $(ConvertTo-YamlScalar $meta['Availability'])") }
    if ($meta.Contains('Description') -and $meta['Description']) { $md.Add("description: $(ConvertTo-YamlScalar $meta['Description'])") }
    $md.Add("converted_at: $(ConvertTo-YamlScalar ([DateTime]::UtcNow.ToString('o')))")
    $md.Add("---")
    $md.Add("")
    $md.Add("# $title")
    $md.Add("")
    if ($meta.Contains('Description') -and $meta['Description']) {
        $md.Add("_$($meta['Description'])_")
        $md.Add("")
    }
    foreach ($l in $bodyLines) { $md.Add($l) }
    $md.Add("")

    return ($md -join "`n")
}

# ---------------------------------------------------------------------------
# Discovery + orchestration
# ---------------------------------------------------------------------------

function Test-ExcludedRelPath {
    param([string]$RelPath, [string[]]$Patterns)
    foreach ($pattern in $Patterns) {
        if ($RelPath -like $pattern) { return $true }
    }
    return $false
}

$localeAlt = ($Locales | ForEach-Object { [regex]::Escape($_) }) -join '|'
$localeSuffixRe = "\.(?<loc>$localeAlt)$"

Write-Host "UDN source  : $SourceDir" -ForegroundColor Cyan
Write-Host "Markdown out: $OutputDir" -ForegroundColor Cyan
Write-Host "Locales     : $($Locales -join ', ')" -ForegroundColor Cyan
Write-Host ""

$allUdn = Get-ChildItem -Path $SourceDir -Recurse -File -Filter *.udn
$records = New-Object System.Collections.Generic.List[object]

foreach ($item in $allUdn) {
    if ($item.BaseName -notmatch $localeSuffixRe) { continue }
    $locale = $Matches['loc'].ToUpperInvariant()
    $trueBase = $item.BaseName.Substring(0, $item.BaseName.Length - $locale.Length - 1)

    $relPath = $item.FullName.Substring($SourceDir.Length).TrimStart('\', '/') -replace '\\', '/'
    if (Test-ExcludedRelPath -RelPath $relPath -Patterns $Exclude) { continue }

    $relDir = Split-Path -Parent $relPath
    $suffix = if ($locale -eq 'INT') { '' } else { ".$locale" }
    $mdName = "$trueBase$suffix.md"
    $outDir = if ($relDir) { Join-Path $OutputDir $relDir } else { $OutputDir }

    $records.Add([PSCustomObject]@{
        FullName = $item.FullName
        RelPath  = $relPath
        RelDir   = $relDir
        Locale   = $locale
        OutDir   = $outDir
        OutPath  = Join-Path $outDir $mdName
        SrcDir   = $item.DirectoryName
        LastWrite = $item.LastWriteTimeUtc
    })
}

Write-Host "Found $($records.Count) UDN file(s) to convert." -ForegroundColor Cyan

$converted = 0
$skipped = 0
$imagesCopied = 0

foreach ($rec in $records) {
    if ($Max -gt 0 -and $converted -ge $Max) { break }

    $upToDate = (-not $Force) -and (Test-Path $rec.OutPath) -and ((Get-Item $rec.OutPath).LastWriteTimeUtc -ge $rec.LastWrite)
    if ($upToDate) {
        Write-Host "  [SKIP] $($rec.RelPath) (up to date)" -ForegroundColor DarkGray
        $skipped++
        continue
    }

    if ($DryRun) {
        Write-Host "  [DRY RUN] $($rec.RelPath) -> $($rec.OutPath)" -ForegroundColor Yellow
        $converted++
        continue
    }

    try {
        $markdown = Convert-UdnFile -FullName $rec.FullName -RelPath $rec.RelPath -Locale $rec.Locale
        New-Item -ItemType Directory -Force -Path $rec.OutDir | Out-Null
        Set-Content -LiteralPath $rec.OutPath -Value $markdown -Encoding UTF8 -NoNewline

        foreach ($m in [regex]::Matches($markdown, $ImageRefRe)) {
            $imgRel = $m.Groups[1].Value.Trim()
            if ($imgRel -match '^\w+://') { continue }
            $imgSrc = Join-Path $rec.SrcDir $imgRel
            if (-not (Test-Path $imgSrc)) { continue }
            $imgDst = Join-Path $rec.OutDir $imgRel
            $imgDstDir = Split-Path -Parent $imgDst
            if ($imgDstDir -and -not (Test-Path $imgDstDir)) { New-Item -ItemType Directory -Force -Path $imgDstDir | Out-Null }
            if ($Force -or -not (Test-Path $imgDst) -or (Get-Item $imgSrc).LastWriteTimeUtc -gt (Get-Item $imgDst).LastWriteTimeUtc) {
                Copy-Item -LiteralPath $imgSrc -Destination $imgDst -Force
                $imagesCopied++
            }
        }

        Write-Host "  [OK] $($rec.RelPath) -> $($rec.OutPath.Substring($OutputDir.Length).TrimStart('\','/'))" -ForegroundColor Green
        $converted++
    } catch {
        Write-Host "  [ERROR] $($rec.RelPath): $($_.Exception.Message)" -ForegroundColor Red
        $skipped++
    }
}

Write-Host ""
if ($DryRun) {
    Write-Host "[DRY RUN] Would convert: $converted  Would skip: $skipped" -ForegroundColor Yellow
} else {
    Write-Host "Done. Converted: $converted  Skipped: $skipped  Images copied: $imagesCopied" -ForegroundColor Green
    Write-Host "Markdown written to: $OutputDir" -ForegroundColor Green
}
