#Requires -Version 5.1
<#
.SYNOPSIS
    Converts Unreal Engine C++ headers and reflected content assets into Markdown documentation.

.DESCRIPTION
    Supports three workflows:

    1. Single-file mode
       Parses one C++ header and writes one Markdown file.

    2. Source scan mode (-ScanAll)
       Scans the project's Source folder and every enabled plugin with a C++ Source folder.
       Plugin discovery includes:
         - Plugins located anywhere beneath the project root
         - Engine-installed plugins beneath Engine\Plugins
         - Plugins explicitly enabled in the .uproject
         - Enabled plugin dependencies declared in .uplugin files

    3. Content scan mode (-ScanContent)
       Runs UnrealEditor-Cmd.exe with a Python bootstrap to export documentation for
       Blueprints, graph assets, and Data Assets.

.PARAMETER HeaderFile
    Header to convert in single-file mode.

.PARAMETER Output
    Markdown output path in single-file mode.

.PARAMETER ScanAll
    Recursively scan project and enabled-plugin C++ headers.

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
    .\convert-cpp-to-markdown.ps1 -ScanAll -ProjectRoot "A:\MyProject" -EnginePath "A:\GE\UE_5.8"

.EXAMPLE
    .\convert-cpp-to-markdown.ps1 -ScanAll -DryRun

.EXAMPLE
    .\convert-cpp-to-markdown.ps1 -ScanContent -DryRun

.EXAMPLE
    .\convert-cpp-to-markdown.ps1 "Source\MyProject\Public\MyClass.h"
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$HeaderFile = "",

    [string]$Output = "",
    [switch]$ScanAll,
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
        $script:ProjectRoot = Find-ProjectRoot (Get-Location).Path
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

function Convert-SingleHeader(
    [string]$HeaderPath,
    [string]$OutputPath,
    [string]$RelativePath = "",
    [switch]$WhatIfOnly
) {
    Write-Host "Parsing : $HeaderPath" -ForegroundColor Cyan
    $types = @(Parse-Header $HeaderPath)

    if ($types.Count -eq 0) {
        Write-Host '  [SKIP] No supported class or struct declarations found.' -ForegroundColor DarkGray
        return $false
    }

    $names = ($types | ForEach-Object { $_.ClassName }) -join ', '
    Write-Host "  Types  : $names" -ForegroundColor Green

    if ($WhatIfOnly) {
        Write-Host "  [DRY RUN] Output: $OutputPath" -ForegroundColor Yellow
        return $true
    }

    $cppPath = [System.IO.Path]::ChangeExtension($HeaderPath, '.cpp')
    $cppLines = if (Test-Path -LiteralPath $cppPath) {
        @(Get-Content -LiteralPath $cppPath -Encoding UTF8)
    }
    else { @() }

    $parent = Split-Path -Parent $OutputPath
    if ($parent -and -not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $markdown = Generate-Markdown $types $HeaderPath $cppLines $RelativePath
    [System.IO.File]::WriteAllText($OutputPath, $markdown, [System.Text.UTF8Encoding]::new($false))
    Write-Host "  Written: $OutputPath" -ForegroundColor Green
    return $true
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

    # The Plugins dependency array is optional in valid .uplugin descriptors.
    # Inspect PSObject.Properties so Set-StrictMode does not throw when absent.
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

            # Missing Enabled means the dependency declaration is active.
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

    $enginePluginsRoot = Join-Path $ResolvedEnginePath 'Engine\Plugins'
    if (Test-Path -LiteralPath $enginePluginsRoot -PathType Container) {
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

function Find-EnabledPluginSourceRoots([string[]]$EnabledNames, $DescriptorIndex, [string[]]$ExcludedNames) {
    $excluded = New-CaseInsensitiveSet
    foreach ($name in @($ExcludedNames)) { if ($name) { [void]$excluded.Add($name) } }
    $roots = [System.Collections.Generic.List[PSCustomObject]]::new()

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
        Write-Host "  [FOUND][$($record.Origin)] $pluginName -> $($record.SourceRoot)" -ForegroundColor Green
    }

    return @($roots)
}

# -----------------------------------------------------------------------------
# Source scan
# -----------------------------------------------------------------------------

function Invoke-SourceScan {
    $resolvedRoot = Resolve-ProjectRoot
    $uprojectPath = Get-UProjectPath $resolvedRoot

    Write-Section 'Source scan configuration'
    Write-Host "Project root : $resolvedRoot" -ForegroundColor Cyan
    Write-Host "Project file : $uprojectPath" -ForegroundColor Cyan
    Write-Host "Engine root  : $EnginePath" -ForegroundColor Cyan

    $explicitNames = @(Find-EnabledUProjectPlugins $uprojectPath)
    $descriptorIndex = New-PluginDescriptorIndex $resolvedRoot $EnginePath
    $enabledNames = @(Resolve-EnabledPluginNames $explicitNames $descriptorIndex $ExcludePlugins)

    Write-Host "Explicit plugins : $($explicitNames.Count)" -ForegroundColor Cyan
    Write-Host "Resolved plugins : $($enabledNames.Count)" -ForegroundColor Cyan
    if ($enabledNames.Count -gt 0) { Write-Host ('  ' + ($enabledNames -join ', ')) -ForegroundColor DarkGray }

    Write-Section 'Enabled plugin source roots'
    $pluginRoots = @(Find-EnabledPluginSourceRoots $enabledNames $descriptorIndex $ExcludePlugins)

    $headers = [System.Collections.Generic.List[PSCustomObject]]::new()
    $excludedSegments = @('Intermediate', 'Binaries', 'ThirdParty')
    $projectSourceRoot = Join-Path $resolvedRoot 'Source'

    if (Test-Path -LiteralPath $projectSourceRoot -PathType Container) {
        Get-ChildItem -LiteralPath $projectSourceRoot -Filter '*.h' -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -notmatch '\.generated\.h$' -and
            -not (Test-PathHasExcludedSegment $_.FullName $excludedSegments)
        } |
        ForEach-Object {
            $headers.Add([PSCustomObject]@{
                HeaderPath = $_.FullName
                BucketDir = 'Project'
                SourceRoot = $projectSourceRoot
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

            $headers.Add([PSCustomObject]@{
                HeaderPath = $_.FullName
                BucketDir = Join-Path 'Plugins' (Join-Path $plugin.PluginName $moduleName)
                SourceRoot = $plugin.SourceRoot
            })
        }
    }

    $uniqueHeaders = @(
        $headers |
        Group-Object { $_.HeaderPath.ToLowerInvariant() } |
        ForEach-Object { $_.Group[0] } |
        Sort-Object HeaderPath
    )

    if ($uniqueHeaders.Count -eq 0) {
        Write-Host '[WARN] No eligible headers found.' -ForegroundColor Yellow
        return
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

    $nameCounts = @{}
    foreach ($record in $uniqueHeaders) {
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($record.HeaderPath)
        $key = "$($record.BucketDir)||$baseName"
        if (-not $nameCounts.ContainsKey($key)) { $nameCounts[$key] = 0 }
        $nameCounts[$key]++
    }

    $converted = 0
    $skipped = 0
    $failed = 0

    foreach ($record in $uniqueHeaders) {
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($record.HeaderPath)
        $key = "$($record.BucketDir)||$baseName"
        $markdownName = "$baseName.md"

        if ($nameCounts[$key] -gt 1) {
            $relativeSource = Get-RelativePathCompat $record.SourceRoot $record.HeaderPath
            $sourceDirectory = Split-Path -Parent $relativeSource
            $suffix = if ($sourceDirectory) { $sourceDirectory -replace '[\\/]+', '__' } else { 'Root' }
            $markdownName = "${baseName}__${suffix}.md"
        }

        $outputPath = Join-Path (Join-Path $script:OutputDir $record.BucketDir) $markdownName
        $relativeProjectPath = Get-RelativePathCompat $resolvedRoot $record.HeaderPath

        try {
            $success = Convert-SingleHeader $record.HeaderPath $outputPath $relativeProjectPath -WhatIfOnly:$DryRun
            if ($success) { $converted++ } else { $skipped++ }
        }
        catch {
            Write-Host "  [ERROR] $($_.Exception.Message)" -ForegroundColor Red
            $failed++
        }
        Write-Host ""
    }

    Write-Section 'Source scan summary'
    Write-Host "Converted : $converted" -ForegroundColor Green
    Write-Host "Skipped   : $skipped" -ForegroundColor Yellow
    Write-Host "Failed    : $failed" -ForegroundColor $(if ($failed -gt 0) { 'Red' } else { 'Green' })
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
    if ($ScanAll) { Invoke-SourceScan }
    if ($ScanContent) { Invoke-ContentScan }

    if (-not $ScanAll -and -not $ScanContent) {
        if (-not $HeaderFile) {
            throw 'Provide a .h file, or use -ScanAll and/or -ScanContent.'
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
