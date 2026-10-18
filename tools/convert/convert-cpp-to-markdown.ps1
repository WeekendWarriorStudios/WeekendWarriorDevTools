#Requires -Version 5.1
<#
.SYNOPSIS
    Converts Unreal Engine C++ headers and reflected content assets into Markdown documentation.

.DESCRIPTION
    Supports four workflows:

    1. Single-file mode
       Parses one C++ header and writes one Markdown file.

    2. Target plugin mode (-TargetPlugin)
       Scans only the specified plugin (by folder path or plugin name) and writes a single
         flattened Markdown file under Plugins\Custom or Plugins\Engine unless -NoFlatten is specified.

    3. Source scan mode (-ScanAll)
         Scans the project's Source folder, all project-local plugins, and enabled engine plugins
         with a C++ Source folder. Plugin output is separated into Plugins\Custom and Plugins\Engine.
         Flattened output is used unless -NoFlatten is specified.

    4. Content scan mode (-ScanContent)
       Runs UnrealEditor-Cmd.exe with a Python bootstrap to export documentation for
       Blueprints, graph assets, and Data Assets.

    Source scans default to scanning the project, all project-local plugins, and enabled
    engine plugins. They maintain
    Documentation\generated-api\markdown\source\manifest.json and only regenerate
    new or changed headers. Plugin release timestamps use the .uplugin file's UTC
    modification time because the descriptor has no standard release-date field.

.PARAMETER HeaderFile
    Header to convert in single-file mode.

.PARAMETER Output
    Markdown output path in single-file mode.

.PARAMETER ScanAll
    Recursively scan project, all project-local plugin, and enabled engine-plugin C++ headers.

.PARAMETER TargetPlugin
    Optional plugin name (e.g., "PCGExtendedToolkit") or full plugin directory path
    (e.g., "A:\Projects\AlterEgo\Plugins\PCGExtendedToolkit") to scan exclusively.

.PARAMETER NoFlatten
    When set, writes individual .md files per C++ header instead of flattening each plugin
    into a single <PluginName>.md file.

.PARAMETER ScanContent
    Run the Unreal content documentation exporter.

.PARAMETER ProjectRoot
    Project directory containing the .uproject file. Auto-detected when omitted.

.PARAMETER OutputDir
    Source documentation output directory.

.PARAMETER ContentOutputDir
    Content documentation output directory.

.PARAMETER ExcludePlugins
    Plugin names to exclude from source and content scans.

.PARAMETER EnginePath
    Unreal Engine installation root containing Engine\Binaries and Engine\Plugins.

.PARAMETER ContentExporterScript
    Optional explicit path to export_blueprint_graph_docs.py.

.PARAMETER DryRun
    Reports source scan actions without writing Markdown. For content scans, prints the
    Unreal Editor command without running it.

.EXAMPLE
    .\convert-cpp-to-markdown.ps1 -TargetPlugin "A:\Projects\AlterEgo\Plugins\PCGExtendedToolkit"

.EXAMPLE
    .\convert-cpp-to-markdown.ps1 -ProjectRoot "A:\Projects\AlterEgo" -TargetPlugin "PCGExtendedToolkit"

.EXAMPLE
    .\convert-cpp-to-markdown.ps1 -ScanAll -ProjectRoot "A:\MyProject" -EnginePath "A:\GE\UE_5.8"

.EXAMPLE
    .\convert-cpp-to-markdown.ps1 "Source\MyProject\Public\MyClass.h"
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$HeaderFile = "",

    [string]$Output = "",
    [switch]$ScanAll,
    [string]$TargetPlugin = "",
    [switch]$NoFlatten,
    [switch]$ScanContent,
    [string]$ProjectRoot = "",
    [string]$OutputDir = "",
    [string]$ContentOutputDir = "",
    [string[]]$ExcludePlugins = @(),
    [string]$EnginePath = "A:\GE\UE_5.8",
    [string]$ContentExporterScript = "",
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$BT = [char]96

# -----------------------------------------------------------------------------
# General helpers
# -----------------------------------------------------------------------------

function Write-Section([string]$Text) {
    Write-Host ""
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ("-" * $Text.Length) -ForegroundColor DarkCyan
}

function New-CaseInsensitiveSet {
    return New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
}

function Test-PathHasExcludedSegment([string]$Path, [string[]]$Segments) {
    foreach ($segment in @($Segments)) {
        if (-not $segment) { continue }
        $escaped = [regex]::Escape($segment)
        if ($Path -match "[\\/]$escaped[\\/]") { return $true }
    }
    return $false
}

function Get-NormalizedFullPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
}

function Get-RelativePathCompat([string]$BasePath, [string]$TargetPath) {
    $base = Get-NormalizedFullPath $BasePath
    $target = Get-NormalizedFullPath $TargetPath

    if ($target.StartsWith($base, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $target.Substring($base.Length).TrimStart('\', '/')
    }

    return $target
}

function Find-ProjectRoot([string]$StartDir) {
    $dir = Get-NormalizedFullPath $StartDir

    while ($dir) {
        $uprojects = @(Get-ChildItem -LiteralPath $dir -Filter '*.uproject' -File -ErrorAction SilentlyContinue)
        if ($uprojects.Count -gt 0) { return $dir }

        $parent = Split-Path -Parent $dir
        if (-not $parent -or $parent -eq $dir) { break }
        $dir = $parent
    }

    return ""
}

function Get-UProjectPath([string]$ResolvedProjectRoot) {
    $files = @(Get-ChildItem -LiteralPath $ResolvedProjectRoot -Filter '*.uproject' -File -ErrorAction SilentlyContinue)

    if ($files.Count -eq 0) {
        throw "No .uproject file was found directly under '$ResolvedProjectRoot'."
    }

    if ($files.Count -gt 1) {
        Write-Host "[WARN] Multiple .uproject files found. Using '$($files[0].Name)'." -ForegroundColor Yellow
    }

    return $files[0].FullName
}

function Resolve-ProjectRoot {
    if ($script:ProjectRoot) {
        if (-not (Test-Path -LiteralPath $script:ProjectRoot -PathType Container)) {
            throw "ProjectRoot does not exist: $script:ProjectRoot"
        }
        $script:ProjectRoot = (Resolve-Path -LiteralPath $script:ProjectRoot).Path
    }
    else {
        $searchStart = (Get-Location).Path
        if ($script:TargetPlugin -and (Test-Path -LiteralPath $script:TargetPlugin)) {
            $resolvedTarget = (Resolve-Path -LiteralPath $script:TargetPlugin).Path
            $searchStart = if (Test-Path -LiteralPath $resolvedTarget -PathType Leaf) {
                Split-Path -Parent $resolvedTarget
            } else {
                $resolvedTarget
            }
        }

        $script:ProjectRoot = Find-ProjectRoot $searchStart
        if (-not $script:ProjectRoot) {
            throw "Could not locate a .uproject file. Pass -ProjectRoot explicitly."
        }
    }

    return $script:ProjectRoot
}

# -----------------------------------------------------------------------------
# C++ parsing helpers
# -----------------------------------------------------------------------------

function Join-CommentLines([System.Collections.Generic.List[string]]$Lines) {
    return (($Lines | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() }) -join ' ')
}

function Count-Char([string]$Str, [char]$Ch) {
    $count = 0
    foreach ($c in $Str.ToCharArray()) {
        if ($c -eq $Ch) { $count++ }
    }
    return $count
}

function Read-MacroBlock([string[]]$Lines, [int]$StartIndex, [ref]$EndIndex) {
    $macro = $Lines[$StartIndex].Trim()
    $cursor = $StartIndex
    $opens = Count-Char $macro '('
    $closes = Count-Char $macro ')'

    while ($opens -gt $closes -and ($cursor + 1) -lt $Lines.Count) {
        $cursor++
        $macro += ' ' + $Lines[$cursor].Trim()
        $opens = Count-Char $macro '('
        $closes = Count-Char $macro ')'
    }

    $EndIndex.Value = $cursor
    return $macro
}

function Get-MacroArgs([string]$Macro) {
    $start = $Macro.IndexOf('(')
    if ($start -lt 0) { return "" }

    $depth = 0
    for ($i = $start; $i -lt $Macro.Length; $i++) {
        if ($Macro[$i] -eq '(') { $depth++ }
        elseif ($Macro[$i] -eq ')') {
            $depth--
            if ($depth -eq 0) {
                return $Macro.Substring($start + 1, $i - $start - 1)
            }
        }
    }

    return $Macro.Substring($start + 1)
}

function Parse-MethodDecl([string]$Decl, [string]$Access, [string]$Comment, [string]$Macro) {
    $ueSpecs = ""
    if ($Macro -match '^UFUNCTION\s*\((.*)\)$') { $ueSpecs = $Matches[1].Trim() }

    $clean = $Decl -replace '\s*\{[^{}]*\}\s*;?\s*$', ''
    $clean = $clean -replace '\s*=\s*(0|default|delete)\s*;?\s*$', ''
    $clean = $clean -replace ';\s*$', ''
    $clean = $clean.Trim()

    if (-not $clean -or $clean -match '^DECLARE_') { return $null }

    $qualifiers = [System.Collections.Generic.List[string]]::new()
    $qualifierPattern = '(?<=\))\s+(const|override|final|noexcept)\s*$'

    while ($clean -match $qualifierPattern) {
        $qualifiers.Insert(0, $Matches[1])
        $clean = ($clean -replace $qualifierPattern, '').Trim()
    }

    if ($clean -match '^(.*?)\s+([~\w]+)\s*\((.*)\)\s*$') {
        $prefixReturn = $Matches[1].Trim()
        $methodName = $Matches[2]
        $parameters = $Matches[3].Trim()
        $modifiers = [System.Collections.Generic.List[string]]::new()
        $returnType = $prefixReturn

        foreach ($modifier in @('virtual', 'static', 'inline', 'FORCEINLINE', 'FORCENOINLINE', 'explicit', 'constexpr', 'UE_NODISCARD', 'NODISCARD')) {
            while ($returnType -match "^$modifier\b(.*)$") {
                $modifiers.Add($modifier)
                $returnType = $Matches[1].Trim()
            }
        }

        $signature = "$returnType $methodName($parameters)".Trim()
        if ($qualifiers.Count -gt 0) { $signature += ' ' + ($qualifiers -join ' ') }

        return [PSCustomObject]@{
            Kind = 'method'; Name = $methodName; Signature = $signature
            ReturnType = $returnType; Params = $parameters
            Modifiers = ($modifiers -join ', '); Access = $Access
            Comment = $Comment; UESpecifiers = $ueSpecs
        }
    }

    if ($clean -match '^([~\w<>]+)\s*\((.*)\)\s*$') {
        return [PSCustomObject]@{
            Kind = 'method'; Name = $Matches[1]
            Signature = "$($Matches[1])($($Matches[2].Trim()))"
            ReturnType = ''; Params = $Matches[2].Trim(); Modifiers = ''
            Access = $Access; Comment = $Comment; UESpecifiers = $ueSpecs
        }
    }

    return $null
}

function Parse-PropertyDecl([string]$Decl, [string]$Access, [string]$Comment, [string]$Macro) {
    $ueSpecs = ""
    if ($Macro -match '^UPROPERTY\s*\((.*)\)$') { $ueSpecs = $Matches[1].Trim() }

    $clean = $Decl -replace '\s*=\s*[^;,]*', ''
    $clean = $clean -replace '\s*:\s*\d+', ''
    $clean = $clean -replace ';\s*$', ''
    $clean = $clean.Trim()

    if ($clean -match '^(.*?)\s+([A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*$') {
        $propertyType = $Matches[1].Trim()
        $propertyName = $Matches[2]
        if ($Matches[3]) { $propertyType += $Matches[3] }

        if (-not $propertyType -or $propertyName -match '^(class|struct|enum|typename|friend)$') {
            return $null
        }

        return [PSCustomObject]@{
            Kind = 'property'; Name = $propertyName; Type = $propertyType
            Access = $Access; Comment = $Comment; UESpecifiers = $ueSpecs
        }
    }

    return $null
}

function Parse-Header([string]$Path) {
    $raw = @(Get-Content -LiteralPath $Path -Encoding UTF8)
    $types = [System.Collections.Generic.List[PSCustomObject]]::new()
    $state = 'top'
    $depth = 0
    $currentType = $null
    $currentAccess = 'private'
    $pendingComment = [System.Collections.Generic.List[string]]::new()
    $pendingMacro = ""
    $pendingTypeSpec = ""
    $pendingTypeSpecArgs = ""
    $inBlockComment = $false
    $blockBuffer = [System.Collections.Generic.List[string]]::new()
    $i = 0

    while ($i -lt $raw.Count) {
        $trimmed = $raw[$i].Trim()

        if ($inBlockComment) {
            if ($trimmed -match '\*/') {
                $before = ($trimmed -split '\*/', 2)[0] -replace '^\*+\s*', ''
                if ($before.Trim()) { $blockBuffer.Add($before.Trim()) }
                foreach ($line in $blockBuffer) { $pendingComment.Add($line) }
                $blockBuffer.Clear()
                $inBlockComment = $false
            }
            else {
                $content = $trimmed -replace '^\*+\s*', ''
                if ($content) { $blockBuffer.Add($content) }
            }
            $i++; continue
        }

        if ($trimmed -match '^/\*') {
            if ($trimmed -match '^/\*.*\*/') {
                $content = $trimmed -replace '^/\*+\s*', '' -replace '\s*\*/.*$', ''
                if ($content.Trim()) { $pendingComment.Add($content.Trim()) }
            }
            else {
                $inBlockComment = $true
                $blockBuffer.Clear()
                $content = $trimmed -replace '^/\*+\s*', ''
                if ($content.Trim()) { $blockBuffer.Add($content.Trim()) }
            }
            $i++; continue
        }

        if ($trimmed -match '^//') {
            if ($trimmed -notmatch '^//\s*[-=]{3,}') {
                $pendingComment.Add(($trimmed -replace '^//\s*', ''))
            }
            $i++; continue
        }

        if (-not $trimmed) {
            if (-not $pendingMacro) { $pendingComment.Clear() }
            $i++; continue
        }

        if ($trimmed -match '^#') {
            $pendingComment.Clear(); $pendingMacro = ""
            $i++; continue
        }

        if ($state -eq 'top') {
            if ($trimmed -match '^(UCLASS|USTRUCT|UENUM|UINTERFACE)\s*\(') {
                $endIndex = $i
                $macro = Read-MacroBlock $raw $i ([ref]$endIndex)
                $i = $endIndex
                if ($macro -match '^(UCLASS|USTRUCT|UENUM|UINTERFACE)') {
                    $pendingTypeSpec = $Matches[1]
                    $pendingTypeSpecArgs = Get-MacroArgs $macro
                }
                $i++; continue
            }

            if ($trimmed -match '^(class|struct)\s+\w+\s*;') {
                $pendingComment.Clear(); $i++; continue
            }

            if ($trimmed -match '^(class|struct)\s+(\w+_API\s+)?(\w+)(?:\s*:\s*(?:public|protected|private)\s+([^\{]+?))?\s*(\{)?\s*$') {
                $kind = $Matches[1]
                $apiMacro = if ($Matches[2]) { $Matches[2].Trim() } else { "" }
                $currentType = [PSCustomObject]@{
                    Kind = $kind
                    SpecType = if ($pendingTypeSpec) { $pendingTypeSpec } else { $kind }
                    SpecArgs = $pendingTypeSpecArgs
                    ClassName = $Matches[3]
                    ParentClass = if ($Matches[4]) { $Matches[4].Trim() } else { "" }
                    Module = if ($apiMacro) { $apiMacro -replace '_API$', '' } else { "" }
                    Comment = Join-CommentLines $pendingComment
                    Members = [System.Collections.Generic.List[PSCustomObject]]::new()
                }

                $currentAccess = if ($kind -eq 'struct') { 'public' } else { 'private' }
                $state = if ($Matches[5]) { 'inType' } else { 'awaitingBrace' }
                $depth = 0
                $pendingComment.Clear(); $pendingMacro = ""
                $pendingTypeSpec = ""; $pendingTypeSpecArgs = ""
                $i++; continue
            }

            $pendingComment.Clear(); $pendingMacro = ""
        }
        elseif ($state -eq 'awaitingBrace') {
            if ($trimmed -match '^\{') { $state = 'inType' }
        }
        elseif ($state -eq 'inType') {
            if ($trimmed -match '^}\s*;?\s*$') {
                if ($depth -eq 0) {
                    $types.Add($currentType)
                    $currentType = $null
                    $state = 'top'
                }
                else { $depth-- }
                $pendingComment.Clear(); $pendingMacro = ""
                $i++; continue
            }

            if ($trimmed -eq '{') {
                $depth++
                $pendingComment.Clear()
                $i++; continue
            }

            if ($depth -gt 0) {
                $depth += (Count-Char $trimmed '{') - (Count-Char $trimmed '}')
                if ($depth -lt 0) { $depth = 0 }
                $pendingComment.Clear(); $pendingMacro = ""
                $i++; continue
            }

            if ($trimmed -match '^GENERATED') {
                $pendingComment.Clear(); $i++; continue
            }

            if ($trimmed -match '^(public|protected|private)\s*:') {
                $currentAccess = $Matches[1]
                $pendingComment.Clear(); $i++; continue
            }

            if ($trimmed -match '^(UPROPERTY|UFUNCTION|UMETA|UDELEGATE)\s*\(') {
                $endIndex = $i
                $pendingMacro = Read-MacroBlock $raw $i ([ref]$endIndex)
                $i = $endIndex + 1
                continue
            }

            if ($trimmed -match '^(friend\b|using\b|typedef\b|DECLARE_|DEFINE_|static_assert)') {
                $pendingComment.Clear(); $pendingMacro = ""
                $i++; continue
            }

            $declaration = $trimmed
            $cursor = $i
            $hasInlineBody = $declaration -match '\{[^{}]*\}'

            if (-not $hasInlineBody -and $declaration -notmatch '[;{]') {
                while (($cursor + 1) -lt $raw.Count -and $declaration -notmatch '[;{]') {
                    $cursor++
                    $declaration += ' ' + $raw[$cursor].Trim()
                }
                $i = $cursor
            }

            if ($declaration -match '\{\s*$' -and $declaration -notmatch '\{[^{}]*\}') {
                $depth += (Count-Char $declaration '{') - (Count-Char $declaration '}')
                $pendingComment.Clear(); $pendingMacro = ""
                $i++; continue
            }

            $comment = Join-CommentLines $pendingComment
            $member = $null

            if ($declaration -match '\(') {
                $member = Parse-MethodDecl $declaration $currentAccess $comment $pendingMacro
            }
            elseif ($declaration -match ';') {
                $member = Parse-PropertyDecl $declaration $currentAccess $comment $pendingMacro
            }

            if ($member) { $currentType.Members.Add($member) }
            $pendingComment.Clear(); $pendingMacro = ""
        }

        $i++
    }

    return @($types)
}

# -----------------------------------------------------------------------------
# Markdown generation
# -----------------------------------------------------------------------------

function Escape-MarkdownCell([string]$Text) {
    if ($null -eq $Text) { return "" }
    return $Text.Replace('|', '\|').Replace("`r", ' ').Replace("`n", ' ')
}

function Generate-Markdown(
    [PSCustomObject[]]$Types,
    [string]$HeaderPath,
    [string[]]$CppLines,
    [string]$SourceRelativePath = ""
) {
    $builder = [System.Text.StringBuilder]::new()
    $fileName = Split-Path -Leaf $HeaderPath
    $title = [System.IO.Path]::GetFileNameWithoutExtension($HeaderPath)
    $implemented = New-CaseInsensitiveSet

    foreach ($line in @($CppLines)) {
        if ($line -match '::\s*(\w+)\s*\(') { [void]$implemented.Add($Matches[1]) }
    }

    [void]$builder.AppendLine("# $title")
    [void]$builder.AppendLine()
    [void]$builder.AppendLine("**File:** $BT$fileName$BT")
    if ($SourceRelativePath) { [void]$builder.AppendLine("**Path:** $BT$SourceRelativePath$BT") }
    [void]$builder.AppendLine()

    foreach ($type in $Types) {
        $typeLabel = switch ($type.SpecType) {
            'UCLASS' { 'UObject Class' }
            'USTRUCT' { 'UStruct' }
            'UENUM' { 'UEnum' }
            'UINTERFACE' { 'UInterface' }
            'struct' { 'Struct' }
            default { 'Class' }
        }

        [void]$builder.AppendLine('---')
        [void]$builder.AppendLine()
        [void]$builder.AppendLine("## $($type.ClassName)")
        [void]$builder.AppendLine()

        $metadata = [System.Collections.Generic.List[string]]::new()
        $metadata.Add("**Type:** $typeLabel")
        if ($type.ParentClass) { $metadata.Add("**Inherits:** $BT$($type.ParentClass)$BT") }
        if ($type.Module) { $metadata.Add("**Module:** $($type.Module)") }
        [void]$builder.AppendLine($metadata -join ' | ')
        [void]$builder.AppendLine()

        if ($type.SpecArgs) {
            $tokens = @($type.SpecArgs -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
            if ($tokens.Count -gt 0) {
                [void]$builder.AppendLine('**Specifiers:** ' + (($tokens | ForEach-Object { "$BT$_$BT" }) -join ' '))
                [void]$builder.AppendLine()
            }
        }

        if ($type.Comment) {
            [void]$builder.AppendLine("> $($type.Comment)")
            [void]$builder.AppendLine()
        }

        $properties = @($type.Members | Where-Object { $_.Kind -eq 'property' })
        if ($properties.Count -gt 0) {
            [void]$builder.AppendLine('### Properties')
            [void]$builder.AppendLine()

            foreach ($access in @('public', 'protected', 'private')) {
                $group = @($properties | Where-Object { $_.Access -eq $access })
                if ($group.Count -eq 0) { continue }

                [void]$builder.AppendLine('#### ' + ($access.Substring(0, 1).ToUpper() + $access.Substring(1)))
                [void]$builder.AppendLine()
                [void]$builder.AppendLine('| Name | Type | Specifiers | Description |')
                [void]$builder.AppendLine('|---|---|---|---|')

                foreach ($property in $group) {
                    $specifiers = if ($property.UESpecifiers) { "$BT$($property.UESpecifiers)$BT" } else { "" }
                    $description = Escape-MarkdownCell $property.Comment
                    [void]$builder.AppendLine("| $BT$($property.Name)$BT | $BT$($property.Type)$BT | $specifiers | $description |")
                }
                [void]$builder.AppendLine()
            }
        }

        $methods = @($type.Members | Where-Object { $_.Kind -eq 'method' })
        if ($methods.Count -gt 0) {
            [void]$builder.AppendLine('### Methods')
            [void]$builder.AppendLine()

            foreach ($access in @('public', 'protected', 'private')) {
                $group = @($methods | Where-Object { $_.Access -eq $access })
                if ($group.Count -eq 0) { continue }

                [void]$builder.AppendLine('#### ' + ($access.Substring(0, 1).ToUpper() + $access.Substring(1)))
                [void]$builder.AppendLine()

                foreach ($method in $group) {
                    [void]$builder.AppendLine("##### $BT$($method.Signature)$BT")
                    [void]$builder.AppendLine()
                    $badges = [System.Collections.Generic.List[string]]::new()
                    if ($method.Modifiers) { $badges.Add("_$($method.Modifiers)_") }
                    if ($method.UESpecifiers) { $badges.Add("${BT}UFUNCTION($($method.UESpecifiers))${BT}") }
                    if ($implemented.Contains($method.Name)) { $badges.Add('_implemented in .cpp_') }

                    if ($badges.Count -gt 0) {
                        [void]$builder.AppendLine($badges -join ' | ')
                        [void]$builder.AppendLine()
                    }

                    if ($method.Comment) {
                        [void]$builder.AppendLine($method.Comment)
                        [void]$builder.AppendLine()
                    }
                }
            }
        }
    }

    return $builder.ToString()
}

function Build-HeaderMarkdownContent(
    [string]$HeaderPath,
    [string]$RelativePath = ""
) {
    Write-Host "Parsing : $HeaderPath" -ForegroundColor Cyan
    $types = @(Parse-Header $HeaderPath)

    if ($types.Count -eq 0) {
        Write-Host '  [SKIP] No supported class or struct declarations found.' -ForegroundColor DarkGray
        return $null
    }

    $names = ($types | ForEach-Object { $_.ClassName }) -join ', '
    Write-Host "  Types  : $names" -ForegroundColor Green

    $cppPath = [System.IO.Path]::ChangeExtension($HeaderPath, '.cpp')
    $cppLines = if (Test-Path -LiteralPath $cppPath) {
        @(Get-Content -LiteralPath $cppPath -Encoding UTF8)
    }
    else { @() }

    return (Generate-Markdown $types $HeaderPath $cppLines $RelativePath)
}

function Convert-SingleHeader(
    [string]$HeaderPath,
    [string]$OutputPath,
    [string]$RelativePath = "",
    [switch]$WhatIfOnly
) {
    $markdown = Build-HeaderMarkdownContent $HeaderPath $RelativePath
    if ($null -eq $markdown) { return $false }

    if ($WhatIfOnly) {
        Write-Host "  [DRY RUN] Output: $OutputPath" -ForegroundColor Yellow
        return $true
    }

    $parent = Split-Path -Parent $OutputPath
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    [System.IO.File]::WriteAllText($OutputPath, $markdown, [System.Text.UTF8Encoding]::new($false))
    Write-Host "  Written: $OutputPath" -ForegroundColor Green
    return $true
}

function Generate-FlattenedMarkdown(
    [string]$GroupTitle,
    [PSCustomObject[]]$Entries
) {
    $builder = [System.Text.StringBuilder]::new()
    $sortedEntries = @($Entries | Sort-Object EntryId)
    $entryWord = if ($sortedEntries.Count -eq 1) { "entry" } else { "entries" }

    [void]$builder.AppendLine("# $GroupTitle")
    [void]$builder.AppendLine()
    [void]$builder.AppendLine("_Compacted from $($sortedEntries.Count) Markdown $entryWord._")
    [void]$builder.AppendLine()
    [void]$builder.AppendLine("## Contents")
    [void]$builder.AppendLine()

    foreach ($entry in $sortedEntries) {
        [void]$builder.AppendLine("- $($entry.EntryId)")
    }

    [void]$builder.AppendLine()

    foreach ($entry in $sortedEntries) {
        [void]$builder.AppendLine("---")
        [void]$builder.AppendLine()
        [void]$builder.AppendLine("## $($entry.EntryId)")
        [void]$builder.AppendLine()
        [void]$builder.Append($entry.Markdown.TrimEnd("`r", "`n"))
        [void]$builder.AppendLine()
        [void]$builder.AppendLine()
    }

    return $builder.ToString()
}

# -----------------------------------------------------------------------------
# Plugin discovery
# -----------------------------------------------------------------------------

function Find-EnabledUProjectPlugins([string]$UProjectPath) {
    try {
        $json = Get-Content `
            -LiteralPath $UProjectPath `
            -Raw `
            -Encoding UTF8 |
            ConvertFrom-Json
    }
    catch {
        throw "Could not parse project descriptor '$UProjectPath': $($_.Exception.Message)"
    }

    $pluginsProperty = $json.PSObject.Properties['Plugins']
    if ($null -eq $pluginsProperty) {
        Write-Host '[WARN] The .uproject descriptor has no Plugins array.' -ForegroundColor Yellow
        return @()
    }

    return @(
        @($pluginsProperty.Value) |
        Where-Object {
            if ($null -eq $_) { return $false }

            $nameProperty = $_.PSObject.Properties['Name']
            $enabledProperty = $_.PSObject.Properties['Enabled']

            return (
                $null -ne $nameProperty -and
                -not [string]::IsNullOrWhiteSpace([string]$nameProperty.Value) -and
                $null -ne $enabledProperty -and
                $enabledProperty.Value -eq $true
            )
        } |
        ForEach-Object {
            [string]$_.PSObject.Properties['Name'].Value
        } |
        Sort-Object -Unique
    )
}

function Get-UPluginDependencies([string]$UPluginPath) {
    try {
        $json = Get-Content `
            -LiteralPath $UPluginPath `
            -Raw `
            -Encoding UTF8 |
            ConvertFrom-Json
    }
    catch {
        Write-Host "[WARN] Cannot parse plugin descriptor: $UPluginPath" -ForegroundColor Yellow
        return @()
    }

    $pluginsProperty = $json.PSObject.Properties['Plugins']
    if ($null -eq $pluginsProperty) {
        return @()
    }

    return @(
        @($pluginsProperty.Value) |
        Where-Object {
            if ($null -eq $_) { return $false }

            $nameProperty = $_.PSObject.Properties['Name']
            if (
                $null -eq $nameProperty -or
                [string]::IsNullOrWhiteSpace([string]$nameProperty.Value)
            ) {
                return $false
            }

            $enabledProperty = $_.PSObject.Properties['Enabled']

            return (
                $null -eq $enabledProperty -or
                $enabledProperty.Value -eq $true
            )
        } |
        ForEach-Object {
            [string]$_.PSObject.Properties['Name'].Value
        } |
        Sort-Object -Unique
    )
}

function New-PluginDescriptorIndex([string]$ResolvedProjectRoot, [string]$ResolvedEnginePath) {
    $index = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([System.StringComparer]::OrdinalIgnoreCase)
    $excludedSegments = @('Binaries', 'Intermediate', 'Saved', 'DerivedDataCache', 'Documentation', '.git', '.vs')
    $searchRoots = [System.Collections.Generic.List[PSCustomObject]]::new()
    $searchRoots.Add([PSCustomObject]@{ Path = $ResolvedProjectRoot; Priority = 0; Origin = 'Project' })

    $enginePluginsRoot = if ($ResolvedEnginePath) { Join-Path $ResolvedEnginePath 'Engine\Plugins' } else { '' }
    if ($enginePluginsRoot -and (Test-Path -LiteralPath $enginePluginsRoot -PathType Container)) {
        $searchRoots.Add([PSCustomObject]@{ Path = $enginePluginsRoot; Priority = 1; Origin = 'Engine' })
    }

    foreach ($searchRoot in $searchRoots) {
        Get-ChildItem -LiteralPath $searchRoot.Path -Filter '*.uplugin' -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { -not (Test-PathHasExcludedSegment $_.FullName $excludedSegments) } |
        ForEach-Object {
            $record = [PSCustomObject]@{
                PluginName = $_.BaseName
                DescriptorPath = $_.FullName
                PluginRoot = $_.Directory.FullName
                SourceRoot = Join-Path $_.Directory.FullName 'Source'
                Origin = $searchRoot.Origin
                Priority = $searchRoot.Priority
            }

            if (-not $index.ContainsKey($_.BaseName) -or $record.Priority -lt $index[$_.BaseName].Priority) {
                $index[$_.BaseName] = $record
            }
        }
    }

    return $index
}

function Resolve-TargetPluginRecord([string]$Target, $DescriptorIndex) {
    if (Test-Path -LiteralPath $Target) {
        $resolvedTarget = (Resolve-Path -LiteralPath $Target).Path
        $upluginFile = $null

        if (Test-Path -LiteralPath $resolvedTarget -PathType Leaf) {
            if ([System.IO.Path]::GetExtension($resolvedTarget) -ieq '.uplugin') {
                $upluginFile = Get-Item -LiteralPath $resolvedTarget
            }
            else {
                throw "TargetPlugin file must be a .uplugin descriptor or plugin directory: $Target"
            }
        }
        else {
            $upluginFile = Get-ChildItem -LiteralPath $resolvedTarget -Filter '*.uplugin' -File -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $upluginFile) {
                $upluginFile = Get-ChildItem -LiteralPath $resolvedTarget -Filter '*.uplugin' -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1
            }
        }

        if ($upluginFile) {
            $pluginRoot = $upluginFile.Directory.FullName
            $pluginName = $upluginFile.BaseName
            $descriptorPath = $upluginFile.FullName
        }
        else {
            $pluginRoot = $resolvedTarget
            $pluginName = Split-Path -Leaf $resolvedTarget
            $descriptorPath = "(directory target) $resolvedTarget"
        }

        $record = [PSCustomObject]@{
            PluginName = $pluginName
            DescriptorPath = $descriptorPath
            PluginRoot = $pluginRoot
            SourceRoot = Join-Path $pluginRoot 'Source'
            Origin = 'TargetPlugin'
            Priority = -1
        }

        $DescriptorIndex[$pluginName] = $record
        return $pluginName
    }

    return $Target
}

function Resolve-EnabledPluginNames([string[]]$InitialNames, $DescriptorIndex, [string[]]$ExcludedNames) {
    $resolved = New-CaseInsensitiveSet
    $excluded = New-CaseInsensitiveSet
    $pending = [System.Collections.Generic.Queue[string]]::new()

    foreach ($name in @($ExcludedNames)) { if ($name) { [void]$excluded.Add($name) } }
    foreach ($name in @($InitialNames)) {
        if ($name -and -not $excluded.Contains($name)) { $pending.Enqueue($name) }
    }

    while ($pending.Count -gt 0) {
        $pluginName = $pending.Dequeue()
        if ($resolved.Contains($pluginName) -or $excluded.Contains($pluginName)) { continue }
        [void]$resolved.Add($pluginName)

        if (-not $DescriptorIndex.ContainsKey($pluginName)) { continue }
        foreach ($dependency in @(Get-UPluginDependencies $DescriptorIndex[$pluginName].DescriptorPath)) {
            if ($dependency -and -not $resolved.Contains($dependency) -and -not $excluded.Contains($dependency)) {
                $pending.Enqueue($dependency)
            }
        }
    }

    return @($resolved | Sort-Object)
}

function Find-EnabledPluginSourceRoots([string[]]$EnabledNames,$DescriptorIndex, [string[]]$ExcludedNames) {$excluded = New-CaseInsensitiveSet
    foreach ($name in @($ExcludedNames)) { if ($name) { [void]$excluded.Add($name) } }$roots = [System.Collections.Generic.List[PSCustomObject]]::new()

    foreach ($pluginName in @($EnabledNames | Sort-Object -Unique)) {
        if (-not $pluginName -or $excluded.Contains($pluginName)) { continue }

        if (-not $DescriptorIndex.ContainsKey($pluginName)) {
            Write-Host "  [NOT FOUND] $pluginName" -ForegroundColor Red
            continue
        }

        $record = $DescriptorIndex[$pluginName]
        if (-not (Test-Path -LiteralPath $record.SourceRoot -PathType Container)) {
            Write-Host "  [NO SOURCE] $pluginName -> $($record.DescriptorPath)" -ForegroundColor Yellow
            continue
        }

        $roots.Add([PSCustomObject]@{
            PluginName = $pluginName
            SourceRoot = $record.SourceRoot
            DescriptorPath = $record.DescriptorPath
            Origin = $record.Origin
        })
        Write-Host "  [FOUND][$($record.Origin)]$pluginName -> $($record.SourceRoot)" -ForegroundColor Green
    }

    return @($roots)
}

# -----------------------------------------------------------------------------
# Source scan
# -----------------------------------------------------------------------------

function Test-PathWithinRoot([string]$Path, [string]$Root) {
    $normalizedPath = Get-NormalizedFullPath $Path
    $normalizedRoot = Get-NormalizedFullPath $Root
    return $normalizedPath.StartsWith(
        $normalizedRoot + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or $normalizedPath -eq $normalizedRoot
}

function Get-ExistingDocumentationManifest([string]$ManifestPath) {
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        return [PSCustomObject]@{ Entries = @() }
    }

    try {
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -eq $manifest.Entries) { $manifest | Add-Member -NotePropertyName Entries -NotePropertyValue @() }
        return $manifest
    }
    catch {
        Write-Host "[WARN] Cannot read documentation manifest; performing a full scan: $($_.Exception.Message)" -ForegroundColor Yellow
        return [PSCustomObject]@{ Entries = @() }
    }
}

function Get-ManifestEntryValue($Entry, [string]$PropertyName) {
    if ($null -eq $Entry) { return $null }
    $property = $Entry.PSObject.Properties[$PropertyName]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Remove-EmptyParentDirectories([string]$Path, [string]$StopAt) {
    $current = Split-Path -Parent $Path
    $stop = Get-NormalizedFullPath $StopAt
    while ($current -and (Test-PathWithinRoot $current $stop) -and $current -ne $stop) {
        $children = @(Get-ChildItem -LiteralPath $current -Force -ErrorAction SilentlyContinue)
        if ($children.Count -gt 0) { break }
        Remove-Item -LiteralPath $current -Force
        $current = Split-Path -Parent $current
    }
}

function Invoke-SourceScan {
    $resolvedRoot = Resolve-ProjectRoot
    $uprojectPath = Get-UProjectPath $resolvedRoot
    $projectTitle = [System.IO.Path]::GetFileNameWithoutExtension($uprojectPath)

    Write-Section 'Source scan configuration'
    Write-Host "Project root : $resolvedRoot" -ForegroundColor Cyan
    Write-Host "Project file : $uprojectPath" -ForegroundColor Cyan
    Write-Host "Flatten mode : $(-not$NoFlatten)" -ForegroundColor Cyan

    if ($TargetPlugin) {
        Write-Host "Target plugin: $TargetPlugin" -ForegroundColor Cyan
        $targetIsPath = Test-Path -LiteralPath $TargetPlugin
        $engineSearchPath = if ($targetIsPath) { "" } else { $EnginePath }
        $descriptorIndex = New-PluginDescriptorIndex $resolvedRoot $engineSearchPath
        $resolvedPluginName = Resolve-TargetPluginRecord $TargetPlugin $descriptorIndex
        $enabledNames = @($resolvedPluginName)
    }
    else {
        Write-Host "Engine root  : $(if ($EnginePath) {$EnginePath } else { '(not set - engine plugins skipped)' })" -ForegroundColor Cyan
        $explicitNames = @(Find-EnabledUProjectPlugins $uprojectPath)
        $descriptorIndex = New-PluginDescriptorIndex $resolvedRoot $EnginePath
        $projectPluginNames = @(
            $descriptorIndex.Values |
            Where-Object { $_.Origin -eq 'Project' } |
            ForEach-Object { $_.PluginName }
        )
        $initialPluginNames = @($explicitNames + $projectPluginNames | Sort-Object -Unique)
        $enabledNames = @(Resolve-EnabledPluginNames $initialPluginNames $descriptorIndex $ExcludePlugins)
        Write-Host "Explicit plugins : $($explicitNames.Count)" -ForegroundColor Cyan
        Write-Host "Project plugins  : $($projectPluginNames.Count)" -ForegroundColor Cyan
    }

    Write-Host "Resolved plugins : $($enabledNames.Count)" -ForegroundColor Cyan
    if ($enabledNames.Count -gt 0) { Write-Host ('  ' + ($enabledNames -join ', ')) -ForegroundColor DarkGray }

    Write-Section 'Enabled plugin source roots'
    $pluginRoots = @(Find-EnabledPluginSourceRoots $enabledNames $descriptorIndex $ExcludePlugins)
    $pluginReleases = @{}
    foreach ($plugin in $pluginRoots) {
        $releasePath = if (Test-Path -LiteralPath $plugin.DescriptorPath -PathType Leaf) {
            $plugin.DescriptorPath
        }
        else {
            $plugin.SourceRoot
        }
        $releaseItem = Get-Item -LiteralPath $releasePath
        $version = ''
        $versionName = ''
        if ($plugin.DescriptorPath -and (Test-Path -LiteralPath $plugin.DescriptorPath -PathType Leaf)) {
            try {
                $pluginDescriptor = Get-Content -LiteralPath $plugin.DescriptorPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $version = [string]$pluginDescriptor.Version
                $versionName = [string]$pluginDescriptor.VersionName
            }
            catch {
                Write-Host "[WARN] Cannot read plugin version metadata: $($plugin.DescriptorPath)" -ForegroundColor Yellow
            }
        }
        $pluginReleases[$plugin.PluginName] = [PSCustomObject]@{
            PluginName = $plugin.PluginName
            Version = $version
            VersionName = $versionName
            DescriptorPath = $plugin.DescriptorPath
            TimestampSource = if (Test-Path -LiteralPath $plugin.DescriptorPath -PathType Leaf) { 'PluginDescriptorLastWriteTimeUtc' } else { 'PluginSourceRootLastWriteTimeUtc' }
            PluginReleaseTimestampUtc = $releaseItem.LastWriteTimeUtc.ToString('o')
        }
    }

    $headers = [System.Collections.Generic.List[PSCustomObject]]::new()
    $excludedSegments = @('Intermediate', 'Binaries', 'ThirdParty')
    $projectSourceRoot = Join-Path $resolvedRoot 'Source'

    if (-not $TargetPlugin -and (Test-Path -LiteralPath $projectSourceRoot -PathType Container)) {
        Get-ChildItem -LiteralPath $projectSourceRoot -Filter '*.h' -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -notmatch '\.generated\.h$' -and
            -not (Test-PathHasExcludedSegment $_.FullName $excludedSegments)
        } |
        ForEach-Object {
            $relative = Get-RelativePathCompat $projectSourceRoot $_.FullName
            $parts = $relative -split '[\\/]'
            $moduleName = if ($parts.Count -gt 1) { $parts[0] } else { $projectTitle }

            $headers.Add([PSCustomObject]@{
                HeaderPath = $_.FullName
                BucketDir = 'Project'
                SourceRoot = $projectSourceRoot
                GroupKey = 'Project'
                GroupTitle = $projectTitle
                FlatRelOut = 'Project.md'
                ModuleName = $moduleName
                PluginName = ''
                PluginReleaseTimestampUtc = ''
            })
        }
    }

    foreach ($plugin in $pluginRoots) {
        Get-ChildItem -LiteralPath $plugin.SourceRoot -Filter '*.h' -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -notmatch '\.generated\.h$' -and
            -not (Test-PathHasExcludedSegment $_.FullName $excludedSegments)
        } |
        ForEach-Object {
            $relative = Get-RelativePathCompat $plugin.SourceRoot $_.FullName
            $parts = $relative -split '[\\/]'
            $moduleName = if ($parts.Count -gt 1) { $parts[0] } else { 'Root' }
            $pluginOutputCategory = if ($plugin.Origin -eq 'Engine') { 'Engine' } else { 'Custom' }
            $pluginOutputRoot = Join-Path 'Plugins' $pluginOutputCategory

            $headers.Add([PSCustomObject]@{
                HeaderPath = $_.FullName
                BucketDir = Join-Path $pluginOutputRoot (Join-Path $plugin.PluginName $moduleName)
                SourceRoot = $plugin.SourceRoot
                GroupKey = "Plugin::$($plugin.PluginName)"
                GroupTitle = $plugin.PluginName
                FlatRelOut = Join-Path $pluginOutputRoot "$($plugin.PluginName).md"
                ModuleName = $moduleName
                PluginName = $plugin.PluginName
                PluginReleaseTimestampUtc = $pluginReleases[$plugin.PluginName].PluginReleaseTimestampUtc
            })
        }
    }

    $uniqueHeaders = @($headers |
        Group-Object { $_.HeaderPath.ToLowerInvariant() } |
        ForEach-Object { $_.Group[0] } |
        Sort-Object HeaderPath
    )

    if ($uniqueHeaders.Count -eq 0) {
        Write-Host '[WARN] No eligible headers found.' -ForegroundColor Yellow
    }

    if (-not $script:OutputDir) {
        $script:OutputDir = Join-Path $resolvedRoot 'Documentation\generated-api\markdown\source'
    }
    else {
        $script:OutputDir = Get-NormalizedFullPath $script:OutputDir
    }

    Write-Section 'Header conversion'
    Write-Host "Headers    : $($uniqueHeaders.Count)" -ForegroundColor Cyan
    Write-Host "Output dir : $script:OutputDir" -ForegroundColor Cyan

    $manifestPath = Join-Path $script:OutputDir 'manifest.json'
    $existingManifest = Get-ExistingDocumentationManifest $manifestPath
    $previousEntries = @{}
    $scopeRoots = [System.Collections.Generic.List[string]]::new()
    if (-not $TargetPlugin -and (Test-Path -LiteralPath $projectSourceRoot -PathType Container)) {
        $scopeRoots.Add($projectSourceRoot)
    }
    foreach ($plugin in $pluginRoots) { $scopeRoots.Add($plugin.SourceRoot) }

    $retainedEntries = [System.Collections.Generic.List[object]]::new()
    foreach ($entry in @($existingManifest.Entries)) {
        if (-not $entry.SourcePath) { continue }
        $sourceKey = (Get-NormalizedFullPath $entry.SourcePath).ToLowerInvariant()
        $inScope = $false
        foreach ($scopeRoot in $scopeRoots) {
            if (Test-PathWithinRoot $entry.SourcePath $scopeRoot) { $inScope = $true; break }
        }
        if ($inScope) { $previousEntries[$sourceKey] = $entry }
        else { $retainedEntries.Add($entry) }
    }

    $nameCounts = @{}
    foreach ($record in $uniqueHeaders) {
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($record.HeaderPath)
        $key = "$($record.BucketDir)|$baseName"
        if (-not $nameCounts.ContainsKey($key)) { $nameCounts[$key] = 0 }
        $nameCounts[$key]++
    }

    $converted = 0
    $skipped = 0
    $failed = 0
    $unchanged = 0
    $updated = 0
    $flattenedGroups = @{}
    $scanList = [System.Collections.Generic.List[object]]::new()
    $manifestEntries = [System.Collections.Generic.List[object]]::new()
    foreach ($entry in $retainedEntries) { $manifestEntries.Add($entry) }
    $currentSourcePaths = @{}

    foreach ($record in $uniqueHeaders) {
        $sourcePath = Get-NormalizedFullPath $record.HeaderPath
        $sourceKey = $sourcePath.ToLowerInvariant()
        $currentSourcePaths[$sourceKey] = $true
        $sourceInfo = Get-Item -LiteralPath $record.HeaderPath
        $sourceTimestamp = $sourceInfo.LastWriteTimeUtc.ToString('o')
        $sourceHash = (Get-FileHash -LiteralPath $record.HeaderPath -Algorithm SHA256).Hash
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($record.HeaderPath)
        $nameKey = "$($record.BucketDir)|$baseName"
        $entryStem = $baseName

        if ($nameCounts[$nameKey] -gt 1) {
            $relativeSource = Get-RelativePathCompat $record.SourceRoot $record.HeaderPath
            $sourceDirectory = Split-Path -Parent $relativeSource
            $suffix = if ($sourceDirectory) { $sourceDirectory -replace '[\\/]+', '__' } else { 'Root' }
            $entryStem = "${baseName}__${suffix}"
        }

        $markdownName = "$entryStem.md"
        $outputPath = Join-Path (Join-Path $script:OutputDir $record.BucketDir) $markdownName
        $flatOutputPath = Join-Path $script:OutputDir $record.FlatRelOut
        $relativeProjectPath = Get-RelativePathCompat $resolvedRoot $record.HeaderPath
        $previous = if ($previousEntries.ContainsKey($sourceKey)) { $previousEntries[$sourceKey] } else { $null }
        $cachedMarkdown = Get-ManifestEntryValue $previous 'CachedMarkdown'
        $legacyCachePath = Get-ManifestEntryValue $previous 'CachePath'
        if ($null -eq $cachedMarkdown -and $legacyCachePath) {
            $legacyCacheFullPath = Join-Path $script:OutputDir $legacyCachePath
            if ((Test-PathWithinRoot $legacyCacheFullPath $script:OutputDir) -and
                (Test-Path -LiteralPath $legacyCacheFullPath -PathType Leaf)) {
                $cachedMarkdown = Get-Content -LiteralPath $legacyCacheFullPath -Raw -Encoding UTF8
            }
        }
        $pluginVersion = ''
        $pluginVersionName = ''
        if ($record.PluginName) {
            $pluginVersion = $pluginReleases[$record.PluginName].Version
            $pluginVersionName = $pluginReleases[$record.PluginName].VersionName
        }
        $sourceChanged = $null -eq $previous -or
            $previous.SourceLastWriteTimeUtc -ne $sourceTimestamp -or
            [long]$previous.SourceLength -ne [long]$sourceInfo.Length -or
            (Get-ManifestEntryValue $previous 'SourceSha256') -ne $sourceHash
        $releaseChanged = $null -ne $previous -and
            ((Get-ManifestEntryValue $previous 'PluginReleaseTimestampUtc') -ne $record.PluginReleaseTimestampUtc -or
                (Get-ManifestEntryValue $previous 'PluginVersion') -ne $pluginVersion -or
                (Get-ManifestEntryValue $previous 'PluginVersionName') -ne $pluginVersionName)
        $previousHasDocumentation = $null -ne $previous -and
            [bool](Get-ManifestEntryValue $previous 'HasDocumentation')
        $flatOutputMissing = -not (Test-Path -LiteralPath $flatOutputPath -PathType Leaf)
        $individualOutputMissing = -not (Test-Path -LiteralPath $outputPath -PathType Leaf)
        $cacheContentMissing = $previousHasDocumentation -and $null -eq $cachedMarkdown
        $artifactMissing = if ($NoFlatten) { $individualOutputMissing } else { $flatOutputMissing }
        $needsParse = $sourceChanged -or $releaseChanged -or $cacheContentMissing -or ($NoFlatten -and $artifactMissing)
        $status = if ($null -eq $previous) { 'New' }
            elseif ($sourceChanged -or $releaseChanged) { 'Updated' }
            elseif ($artifactMissing) { 'Rebuilt' }
            else { 'Unchanged' }

        $scanList.Add([PSCustomObject]@{
            Status = $status
            Plugin = $record.PluginName
            SourcePath = $sourcePath
            SourceLastWriteTimeUtc = $sourceTimestamp
            SourceSha256 = $sourceHash
            PluginReleaseTimestampUtc = $record.PluginReleaseTimestampUtc
        })

        if (-not $NoFlatten) {
            if (-not $flattenedGroups.ContainsKey($record.GroupKey)) {
                $flattenedGroups[$record.GroupKey] = [PSCustomObject]@{
                    GroupTitle = $record.GroupTitle
                    OutputPath = $flatOutputPath
                    Entries = [System.Collections.Generic.List[PSCustomObject]]::new()
                    NeedsWrite = -not (Test-Path -LiteralPath $flatOutputPath -PathType Leaf)
                }
            }
            if ($needsParse) { $flattenedGroups[$record.GroupKey].NeedsWrite = $true }
        }

        $markdown = $null
        try {
            if ($needsParse) {
                $markdown = Build-HeaderMarkdownContent $record.HeaderPath $relativeProjectPath
                if ($null -ne $markdown) {
                    $cachedMarkdown = $markdown
                    $converted++
                    if (-not $DryRun -and $NoFlatten) {
                        $parent = Split-Path -Parent $outputPath
                        if ($parent -and -not (Test-Path -LiteralPath $parent)) {
                            New-Item -ItemType Directory -Path $parent -Force | Out-Null
                        }
                        [System.IO.File]::WriteAllText($outputPath, $markdown, [System.Text.UTF8Encoding]::new($false))
                    }
                }
                else {
                    $cachedMarkdown = ''
                    $skipped++
                    if (-not $DryRun -and $NoFlatten -and (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
                        Remove-Item -LiteralPath $outputPath -Force
                    }
                }
            }
            elseif (-not $NoFlatten) {
                if ($previousHasDocumentation) {
                    $markdown = $cachedMarkdown
                }
                else {
                    $skipped++
                }
                $unchanged++
            }
            else {
                $unchanged++
            }

            if ($null -ne $markdown -and -not $NoFlatten) {
                $flattenedGroups[$record.GroupKey].Entries.Add([PSCustomObject]@{
                    EntryId = "$($record.ModuleName)\\$entryStem"
                    Markdown = $markdown
                })
            }

            $manifestEntries.Add([PSCustomObject]@{
                SourcePath = $sourcePath
                SourceLastWriteTimeUtc = $sourceTimestamp
                SourceLength = [long]$sourceInfo.Length
                SourceSha256 = $sourceHash
                PluginName = $record.PluginName
                PluginVersion = $pluginVersion
                PluginVersionName = $pluginVersionName
                PluginReleaseTimestampUtc = $record.PluginReleaseTimestampUtc
                GroupKey = $record.GroupKey
                GroupTitle = $record.GroupTitle
                EntryId = "$($record.ModuleName)\\$entryStem"
                OutputPath = Get-RelativePathCompat $script:OutputDir $outputPath
                FlatOutputPath = Get-RelativePathCompat $script:OutputDir $flatOutputPath
                CachedMarkdown = $cachedMarkdown
                HasDocumentation = ($null -ne $markdown -or $previousHasDocumentation) -and $cachedMarkdown -ne ''
            })
        }
        catch {
            Write-Host "  [ERROR] $($_.Exception.Message)" -ForegroundColor Red
            $failed++
            if ($null -ne $previous) { $manifestEntries.Add($previous) }
        }
    }

    foreach ($sourceKey in @($previousEntries.Keys)) {
        if ($currentSourcePaths.ContainsKey($sourceKey)) { continue }
        $removedEntry = $previousEntries[$sourceKey]
        $scanList.Add([PSCustomObject]@{
            Status = 'Removed'
            Plugin = $removedEntry.PluginName
            SourcePath = $removedEntry.SourcePath
            SourceLastWriteTimeUtc = $removedEntry.SourceLastWriteTimeUtc
            PluginReleaseTimestampUtc = $removedEntry.PluginReleaseTimestampUtc
        })
        if (-not $NoFlatten -and $removedEntry.GroupKey) {
            if (-not $flattenedGroups.ContainsKey($removedEntry.GroupKey)) {
                $oldFlatPath = Join-Path $script:OutputDir $removedEntry.FlatOutputPath
                $flattenedGroups[$removedEntry.GroupKey] = [PSCustomObject]@{
                    GroupTitle = $removedEntry.GroupTitle
                    OutputPath = $oldFlatPath
                    Entries = [System.Collections.Generic.List[PSCustomObject]]::new()
                    NeedsWrite = $true
                }
            }
            else { $flattenedGroups[$removedEntry.GroupKey].NeedsWrite = $true }
        }
        if (-not $DryRun) {
            $stalePaths = @($removedEntry.OutputPath, (Get-ManifestEntryValue $removedEntry 'CachePath'))
            foreach ($staleRelativePath in $stalePaths) {
                if (-not $staleRelativePath) { continue }
                $stalePath = Join-Path $script:OutputDir $staleRelativePath
                if ((Test-PathWithinRoot $stalePath $script:OutputDir) -and (Test-Path -LiteralPath $stalePath -PathType Leaf)) {
                    Remove-Item -LiteralPath $stalePath -Force
                }
            }
        }
    }

    if (-not $NoFlatten -and $flattenedGroups.Count -gt 0) {
        Write-Section 'Flattened plugin output'
        foreach ($groupKey in ($flattenedGroups.Keys | Sort-Object)) {
            $group = $flattenedGroups[$groupKey]
            if (-not $group.NeedsWrite) { continue }
            $flatPath = $group.OutputPath
            if ($group.Entries.Count -eq 0) {
                if (-not $DryRun -and (Test-PathWithinRoot $flatPath $script:OutputDir) -and (Test-Path -LiteralPath $flatPath -PathType Leaf)) {
                    Remove-Item -LiteralPath $flatPath -Force
                    Write-Host "  Removed: $flatPath" -ForegroundColor Yellow
                }
                continue
            }

            $entryCount = $group.Entries.Count
            if ($DryRun) {
                Write-Host "  [DRY RUN] $($group.GroupTitle) ($entryCount entries) -> $flatPath" -ForegroundColor Yellow
                continue
            }

            $parent = Split-Path -Parent $flatPath
            if ($parent -and -not (Test-Path -LiteralPath $parent)) {
                New-Item -ItemType Directory -Path $parent -Force | Out-Null
            }

            $flatMarkdown = Generate-FlattenedMarkdown $group.GroupTitle $group.Entries.ToArray()
            [System.IO.File]::WriteAllText($flatPath, $flatMarkdown, [System.Text.UTF8Encoding]::new($false))
            Write-Host "  Written: $flatPath ($entryCount entries)" -ForegroundColor Green
        }
    }

    if (-not $DryRun) {
        if (-not $NoFlatten) {
            foreach ($entry in $previousEntries.Values) {
                foreach ($legacyRelativePath in @($entry.OutputPath, (Get-ManifestEntryValue $entry 'CachePath'))) {
                    if (-not $legacyRelativePath) { continue }
                    $legacyPath = Join-Path $script:OutputDir $legacyRelativePath
                    if ((Test-PathWithinRoot $legacyPath $script:OutputDir) -and
                        (Test-Path -LiteralPath $legacyPath -PathType Leaf)) {
                        Remove-Item -LiteralPath $legacyPath -Force
                        $directoryBoundary = if ($legacyRelativePath -match '(^|[\\/])\.cache([\\/]|$)') {
                            Join-Path $script:OutputDir '.cache'
                        }
                        else {
                            Join-Path $script:OutputDir 'Plugins'
                        }
                        Remove-EmptyParentDirectories $legacyPath $directoryBoundary
                    }
                }

                $oldFlatRelativePath = Get-ManifestEntryValue $entry 'FlatOutputPath'
                if ($oldFlatRelativePath) {
                    $oldFlatPath = Join-Path $script:OutputDir $oldFlatRelativePath
                    $oldFlatPathIsReferenced = @($manifestEntries | Where-Object {
                        $candidatePath = Get-ManifestEntryValue $_ 'FlatOutputPath'
                        $candidatePath -and
                        (Get-NormalizedFullPath (Join-Path $script:OutputDir $candidatePath)) -eq
                        (Get-NormalizedFullPath $oldFlatPath)
                    }).Count -gt 0

                    if (-not $oldFlatPathIsReferenced -and
                        (Test-PathWithinRoot $oldFlatPath $script:OutputDir) -and
                        (Test-Path -LiteralPath $oldFlatPath -PathType Leaf)) {
                        Remove-Item -LiteralPath $oldFlatPath -Force
                    }
                }
            }
        }

        $manifest = [PSCustomObject]@{
            FormatVersion = 1
            GeneratedAtUtc = [DateTime]::UtcNow.ToString('o')
            ProjectRoot = $resolvedRoot
            PluginReleaseTimestamps = @($pluginReleases.Values | Sort-Object PluginName)
            ScanList = @($scanList.ToArray())
            Entries = @($manifestEntries.ToArray() | Sort-Object SourcePath)
        }
        $manifestParent = Split-Path -Parent $manifestPath
        if (-not (Test-Path -LiteralPath $manifestParent -PathType Container)) {
            New-Item -ItemType Directory -Path $manifestParent -Force | Out-Null
        }
        $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
        Write-Host "Manifest  : $manifestPath" -ForegroundColor Cyan
    }

    if ($scanList.Count -gt 0) {
        Write-Section 'Incremental scan list'
        $scanList | Sort-Object Status, SourcePath | ForEach-Object {
            Write-Host ("  {0,-9} {1}" -f $_.Status, $_.SourcePath) -ForegroundColor $(if ($_.Status -eq 'Updated' -or $_.Status -eq 'New') { 'Green' } elseif ($_.Status -eq 'Removed') { 'Yellow' } else { 'DarkGray' })
        }
    }

    Write-Section 'Source scan summary'
    Write-Host "Converted : $converted" -ForegroundColor Green
    Write-Host "Unchanged : $unchanged" -ForegroundColor Cyan
    Write-Host "Skipped   : $skipped" -ForegroundColor Yellow
    Write-Host "Failed    : $failed" -ForegroundColor $(if ($failed -gt 0) { 'Red' } else { 'Green' })
    if (-not $NoFlatten) {
        Write-Host "Flattened : $($flattenedGroups.Count) file(s)" -ForegroundColor Cyan
    }
    if ($DryRun) { Write-Host 'Dry run completed. No Markdown files were written.' -ForegroundColor Yellow }
}

# -----------------------------------------------------------------------------
# Content scan
# -----------------------------------------------------------------------------

function Convert-ToPythonRawString([string]$Value) {
    return $Value.Replace("'", "\\'")
}

function Invoke-ContentScan {
    $resolvedRoot = Resolve-ProjectRoot
    $uprojectPath = Get-UProjectPath $resolvedRoot
    if (-not $EnginePath) {
        throw 'Content scan requires -EnginePath.'
    }
    $editorCommand = Join-Path $EnginePath 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe'

    if (-not (Test-Path -LiteralPath $editorCommand -PathType Leaf)) {
        throw "UnrealEditor-Cmd.exe not found: $editorCommand"
    }

    if (-not $script:ContentExporterScript) {
        $candidatePaths = @(
            (Join-Path $resolvedRoot 'WeekendWarriorDevTools\tools\python\assets\export_blueprint_graph_docs.py'),
            (Join-Path $resolvedRoot 'tools\python\assets\export_blueprint_graph_docs.py')
        )
        $script:ContentExporterScript = $candidatePaths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    }

    if (-not $script:ContentExporterScript -or -not (Test-Path -LiteralPath $script:ContentExporterScript -PathType Leaf)) {
        throw 'Content exporter not found. Pass -ContentExporterScript explicitly.'
    }

    if (-not $script:ContentOutputDir) {
        $script:ContentOutputDir = Join-Path $resolvedRoot 'Documentation\generated-api\markdown\content'
    }

    $exporterDirectory = Split-Path -Parent $script:ContentExporterScript
    $escapedExporterDirectory = Convert-ToPythonRawString $exporterDirectory
    $escapedOutputDirectory = Convert-ToPythonRawString $script:ContentOutputDir
    $pythonExclusions = '[' + (($ExcludePlugins | ForEach-Object { "r'$(Convert-ToPythonRawString $_)'" }) -join ', ') + ']'
    $bootstrapPath = Join-Path $env:TEMP 'wws_export_content_docs_bootstrap.py'

    $bootstrap = @(
        'import sys',
        "sys.path.insert(0, r'$escapedExporterDirectory')",
        'import export_blueprint_graph_docs as exporter',
        "exporter.export_all_content_docs(output_dir=r'$escapedOutputDirectory', exclude_plugins=$pythonExclusions)"
    )

    if (-not $DryRun) {
        Set-Content -LiteralPath $bootstrapPath -Value $bootstrap -Encoding UTF8
    }

    $arguments = @(
        "`"$uprojectPath`"",
        '-run=pythonscript',
        "-Script=`"$bootstrapPath`"",
        '-unattended',
        '-nopause',
        '-nosplash',
        '-stdout',
        '-FullStdOutLogOutput'
    )

    Write-Section 'Content scan configuration'
    Write-Host "Project file : $uprojectPath" -ForegroundColor Cyan
    Write-Host "Editor       : $editorCommand" -ForegroundColor Cyan
    Write-Host "Exporter     : $script:ContentExporterScript" -ForegroundColor Cyan
    Write-Host "Output       : $script:ContentOutputDir" -ForegroundColor Cyan

    if ($DryRun) {
        Write-Host ''
        Write-Host '[DRY RUN] Bootstrap content:' -ForegroundColor Yellow
        $bootstrap | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkYellow }
        Write-Host ''
        Write-Host '[DRY RUN] Command:' -ForegroundColor Yellow
        Write-Host "`"$editorCommand`" $($arguments -join ' ')" -ForegroundColor Yellow
        return
    }

    & $editorCommand @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Editor content scan failed with exit code $LASTEXITCODE."
    }

    Write-Host 'Content scan completed.' -ForegroundColor Green
}

# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

try {
    $runSourceScan = $ScanAll -or
        (-not [string]::IsNullOrWhiteSpace($TargetPlugin)) -or
        (-not $HeaderFile -and -not $ScanContent)

    if ($runSourceScan) { Invoke-SourceScan }
    if ($ScanContent) { Invoke-ContentScan }

    if (-not $runSourceScan -and -not $ScanContent) {
        if (-not $HeaderFile) {
            throw 'Provide a .h file, or use -TargetPlugin, -ScanAll, and/or -ScanContent.'
        }

        if (-not (Test-Path -LiteralPath $HeaderFile -PathType Leaf)) {
            throw "Header file not found: $HeaderFile"
        }

        if ([System.IO.Path]::GetExtension($HeaderFile) -ine '.h') {
            throw 'Single-file mode requires a .h file.'
        }

        $HeaderFile = (Resolve-Path -LiteralPath $HeaderFile).Path
        if (-not $Output) {
            $Output = [System.IO.Path]::ChangeExtension($HeaderFile, '.md')
        }

        [void](Convert-SingleHeader $HeaderFile $Output -WhatIfOnly:$DryRun)
    }
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}