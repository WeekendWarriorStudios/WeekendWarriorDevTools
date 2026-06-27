#Requires -Version 5.1
<#
.SYNOPSIS
    Converts C++ header (and matching .cpp) files to structured markdown documentation.

.DESCRIPTION
    Single-file mode: parse one .h and write one .md.
    Scan mode (-ScanAll): discover every .h under Source/ and Plugins/GameFeatures/,
    skip Intermediate/Binaries/generated files, and write markdown to -OutputDir.

.PARAMETER HeaderFile
    Path to a single .h file (single-file mode).

.PARAMETER Output
    Output .md path for single-file mode.  Defaults to same dir/name as the header.

.PARAMETER ScanAll
    Scan Source/ and Plugins/GameFeatures/ for all .h files and batch-convert them.

.PARAMETER ProjectRoot
    UE project root directory.  Auto-detected from nearest .uproject when omitted.

.PARAMETER OutputDir
    Directory for batch output.  Defaults to <ProjectRoot>\Documentation\generated-api\.

.PARAMETER ExcludePlugins
    Additional plugin folder names to skip during scan. Intermediate, Binaries,
    ThirdParty, and PCGExtendedToolkit are always excluded.

.EXAMPLE
    .\convert-cpp-to-markdown.ps1 "Plugins\GF_Traversal\CRChaosMoverComponent.h"
    .\convert-cpp-to-markdown.ps1 "Source\MyClass.h" -Output "Docs\MyClass.md"
    .\convert-cpp-to-markdown.ps1 -ScanAll
    .\convert-cpp-to-markdown.ps1 -ScanAll -OutputDir "Docs\API" -ExcludePlugins PCGExtendedToolkit
#>
param(
    [Parameter(Position = 0)]
    [string]$HeaderFile = "",

    [string]$Output = "",

    [switch]$ScanAll,

    [string]$ProjectRoot = "",

    [string]$OutputDir = "",

    [string[]]$ExcludePlugins = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Backtick character for markdown code-spans without confusing PS5.1 parser
$BT = [char]96

function Join-CommentLines([System.Collections.Generic.List[string]]$Lines) {
    return ($Lines | Where-Object { $_.Trim() } | ForEach-Object { $_.Trim() }) -join " "
}

function Count-Char([string]$Str, [char]$Ch) {
    $count = 0
    foreach ($c in $Str.ToCharArray()) { if ($c -eq $Ch) { $count++ } }
    return $count
}

# Reads a macro that may span lines until its outer parens are balanced.
# Updates $EndIndex (by-ref) to the last line consumed.
function Read-MacroBlock([string[]]$Lines, [int]$StartIdx, [ref]$EndIdx) {
    $macro = $Lines[$StartIdx].Trim()
    $j     = $StartIdx
    $opens  = Count-Char $macro '('
    $closes = Count-Char $macro ')'
    while ($opens -gt $closes -and ($j + 1) -lt $Lines.Count) {
        $j++
        $macro += " " + $Lines[$j].Trim()
        $opens  = Count-Char $macro '('
        $closes = Count-Char $macro ')'
    }
    $EndIdx.Value = $j
    return $macro
}

# Gets the argument string from inside the outermost parens of a macro call.
function Get-MacroArgs([string]$Macro) {
    $start = $Macro.IndexOf('(')
    if ($start -lt 0) { return "" }
    $d = 0
    for ($k = $start; $k -lt $Macro.Length; $k++) {
        if ($Macro[$k] -eq '(') { $d++ }
        elseif ($Macro[$k] -eq ')') {
            $d--
            if ($d -eq 0) { return $Macro.Substring($start + 1, $k - $start - 1) }
        }
    }
    return $Macro.Substring($start + 1)
}

# ---------------------------------------------------------------------------
# Member parsers
# ---------------------------------------------------------------------------

function Parse-MethodDecl([string]$Decl, [string]$Access, [string]$Comment, [string]$Macro) {
    $ueSpecs = ""
    if ($Macro -match '^UFUNCTION\s*\(([^)]*)\)') { $ueSpecs = $Matches[1].Trim() }

    # Remove inline body and trailing ;
    $clean = $Decl -replace '\s*\{[^}]*\}\s*;?\s*$', ''
    $clean = $clean -replace '\s*=\s*0\s*;?\s*$', ''
    $clean = $clean -replace ';\s*$', ''
    $clean = $clean.Trim()

    if ($clean -match '^DECLARE_') { return $null }

    # Strip trailing qualifiers: const, override, final
    $quals = [System.Collections.Generic.List[string]]::new()
    foreach ($q in @('final', 'override', 'const')) {
        if ($clean -match "(?<=\))\s+$q\s*$") {
            $quals.Insert(0, $q) | Out-Null
            $clean = $clean -replace "(?<=\))\s+$q\s*$", ''
            $clean = $clean.Trim()
        }
    }

    # Match:  [leading-mods]  ReturnType  MethodName(Params)
    if ($clean -match '^(.*?)\s+(\w+)\s*\(([^)]*)\)\s*$') {
        $prefixReturn = $Matches[1].Trim()
        $methodName   = $Matches[2]
        $params       = $Matches[3].Trim()

        $mods = [System.Collections.Generic.List[string]]::new()
        $returnType = $prefixReturn
        foreach ($mod in @('virtual','static','inline','FORCEINLINE','FORCENOINLINE','explicit','UE_NODISCARD','NODISCARD')) {
            while ($returnType -match "^$mod\b(.*)") {
                $mods.Add($mod) | Out-Null
                $returnType = $Matches[1].Trim()
            }
        }

        $sig = "$returnType $methodName($params)"
        if ($quals.Count -gt 0) { $sig += " " + ($quals -join " ") }

        return [PSCustomObject]@{
            Kind         = "method"
            Name         = $methodName
            Signature    = $sig.Trim()
            ReturnType   = $returnType
            Params       = $params
            Modifiers    = ($mods -join ", ")
            Access       = $Access
            Comment      = $Comment
            UESpecifiers = $ueSpecs
        }
    }

    # Constructor / destructor (no return type)
    if ($clean -match '^([\w~<>]+)\s*\(([^)]*)\)\s*$') {
        return [PSCustomObject]@{
            Kind         = "method"
            Name         = $Matches[1]
            Signature    = "$($Matches[1])($($Matches[2].Trim()))"
            ReturnType   = ""
            Params       = $Matches[2].Trim()
            Modifiers    = ""
            Access       = $Access
            Comment      = $Comment
            UESpecifiers = $ueSpecs
        }
    }

    return $null
}

function Parse-PropertyDecl([string]$Decl, [string]$Access, [string]$Comment, [string]$Macro) {
    $ueSpecs = ""
    if ($Macro -match '^UPROPERTY\s*\(([^)]*)\)') { $ueSpecs = $Matches[1].Trim() }

    # Remove default value, bit-field size, trailing ;
    $clean = $Decl -replace '\s*=\s*[^;,]*', ''
    $clean = $clean -replace '\s*:\s*\d+', ''
    $clean = $clean -replace ';\s*$', ''
    $clean = $clean.Trim()

    # Last word is the property name; everything before is the type
    if ($clean -match '^(.*?)\s+(\w+)\s*$') {
        $propType = $Matches[1].Trim()
        $propName = $Matches[2]

        if (-not $propType -or -not $propName) { return $null }
        if ($propName -match '^(class|struct|enum|typename|friend)$') { return $null }

        return [PSCustomObject]@{
            Kind         = "property"
            Name         = $propName
            Type         = $propType
            Access       = $Access
            Comment      = $Comment
            UESpecifiers = $ueSpecs
        }
    }
    return $null
}

# ---------------------------------------------------------------------------
# Header parser
# ---------------------------------------------------------------------------

function Parse-Header([string]$Path) {
    $raw = Get-Content $Path -Encoding UTF8
    $n   = $raw.Count
    $types = [System.Collections.Generic.List[PSCustomObject]]::new()

    # State: "top" | "awaitingBrace" | "inType"
    $state         = "top"
    $depth         = 0
    $currentType   = $null
    $currentAccess = "private"

    $pendingComment      = [System.Collections.Generic.List[string]]::new()
    $pendingMacro        = ""
    $pendingTypeSpec     = ""
    $pendingTypeSpecArgs = ""

    $inBlockComment = $false
    $blockBuf       = [System.Collections.Generic.List[string]]::new()

    $i = 0
    while ($i -lt $n) {
        $line    = $raw[$i]
        $trimmed = $line.Trim()

        # -- Block comment (inside) ------------------------------------------
        if ($inBlockComment) {
            if ($trimmed -match '\*/') {
                $inBlockComment = $false
                $before = ($trimmed -split '\*/', 2)[0] -replace '^\*+\s*', ''
                if ($before.Trim()) { $pendingComment.Add($before.Trim()) | Out-Null }
                foreach ($bl in $blockBuf) { $pendingComment.Add($bl) | Out-Null }
                $blockBuf.Clear()
            } else {
                $content = $trimmed -replace '^\*+\s*', ''
                if ($content) { $blockBuf.Add($content) | Out-Null }
            }
            $i++; continue
        }

        # -- Block comment (open) -------------------------------------------
        if ($trimmed -match '^/\*') {
            if ($trimmed -match '^/\*.*\*/') {
                $content = $trimmed -replace '^/\*+\s*', '' -replace '\s*\*/.*$', ''
                if ($content.Trim()) { $pendingComment.Add($content.Trim()) | Out-Null }
            } else {
                $inBlockComment = $true
                $blockBuf.Clear()
                $content = $trimmed -replace '^/\*+\s*', ''
                if ($content.Trim()) { $blockBuf.Add($content.Trim()) | Out-Null }
            }
            $i++; continue
        }

        # -- Line comment ---------------------------------------------------
        if ($trimmed -match '^//') {
            # Section divider lines (// ---  or // ===) are decorative; skip
            if ($trimmed -match '^//\s*[-=]{3,}') { $i++; continue }
            $content = $trimmed -replace '^//\s*', ''
            $pendingComment.Add($content) | Out-Null
            $i++; continue
        }

        # -- Blank line -----------------------------------------------------
        if (-not $trimmed) {
            if (-not $pendingMacro) { $pendingComment.Clear() }
            $i++; continue
        }

        # -- Preprocessor ---------------------------------------------------
        if ($trimmed -match '^#') {
            $pendingComment.Clear(); $pendingMacro = ""
            $i++; continue
        }

        # ===================================================================
        #  TOP LEVEL
        # ===================================================================
        if ($state -eq "top") {

            # UCLASS / USTRUCT / UENUM / UINTERFACE (may span multiple lines)
            if ($trimmed -match '^(UCLASS|USTRUCT|UENUM|UINTERFACE)\s*\(') {
                $endIdx = $i
                $macro = Read-MacroBlock $raw $i ([ref]$endIdx)
                $i = $endIdx
                if ($macro -match '^(UCLASS|USTRUCT|UENUM|UINTERFACE)') {
                    $pendingTypeSpec     = $Matches[1]
                    $pendingTypeSpecArgs = Get-MacroArgs $macro
                }
                $i++; continue
            }

            # Forward declaration  class Foo;  or  struct Bar;
            if ($trimmed -match '^(class|struct)\s+\w+\s*;') {
                $pendingComment.Clear()
                $i++; continue
            }

            # class declaration
            if ($trimmed -match '^class\s+(\w+_API\s+)?(\w+)(?:\s*:\s*(?:public|protected|private)\s+([\w:<>, ]+?))?(?:\s*\{)?\s*$') {
                $apiMacro = if ($Matches[1]) { $Matches[1].Trim() } else { "" }
                $currentType = [PSCustomObject]@{
                    Kind        = "class"
                    SpecType    = if ($pendingTypeSpec) { $pendingTypeSpec } else { "class" }
                    SpecArgs    = $pendingTypeSpecArgs
                    ClassName   = $Matches[2]
                    ParentClass = if ($Matches[3]) { $Matches[3].Trim() } else { "" }
                    Module      = if ($apiMacro) { $apiMacro -replace '_API$', '' } else { "" }
                    Comment     = (Join-CommentLines $pendingComment)
                    Members     = [System.Collections.Generic.List[PSCustomObject]]::new()
                }
                $pendingComment.Clear(); $pendingMacro = ""
                $pendingTypeSpec = ""; $pendingTypeSpecArgs = ""
                $currentAccess = "private"
                $depth = 0
                $state = if ($trimmed -match '\{') { "inType" } else { "awaitingBrace" }
                $i++; continue
            }

            # struct declaration
            if ($trimmed -match '^struct\s+(\w+_API\s+)?(\w+)(?:\s*:\s*(?:public|protected|private)\s+([\w:<>, ]+?))?(?:\s*\{)?\s*$') {
                $apiMacro = if ($Matches[1]) { $Matches[1].Trim() } else { "" }
                $currentType = [PSCustomObject]@{
                    Kind        = "struct"
                    SpecType    = if ($pendingTypeSpec) { $pendingTypeSpec } else { "struct" }
                    SpecArgs    = $pendingTypeSpecArgs
                    ClassName   = $Matches[2]
                    ParentClass = if ($Matches[3]) { $Matches[3].Trim() } else { "" }
                    Module      = if ($apiMacro) { $apiMacro -replace '_API$', '' } else { "" }
                    Comment     = (Join-CommentLines $pendingComment)
                    Members     = [System.Collections.Generic.List[PSCustomObject]]::new()
                }
                $pendingComment.Clear(); $pendingMacro = ""
                $pendingTypeSpec = ""; $pendingTypeSpecArgs = ""
                $currentAccess = "public"
                $depth = 0
                $state = if ($trimmed -match '\{') { "inType" } else { "awaitingBrace" }
                $i++; continue
            }

            $pendingComment.Clear(); $pendingMacro = ""
        }

        # ===================================================================
        #  AWAITING OPENING BRACE
        # ===================================================================
        elseif ($state -eq "awaitingBrace") {
            if ($trimmed -eq '{') { $state = "inType" }
        }

        # ===================================================================
        #  INSIDE TYPE
        # ===================================================================
        elseif ($state -eq "inType") {

            # Closing brace
            if ($trimmed -match '^}\s*;?\s*$') {
                if ($depth -eq 0) {
                    $types.Add($currentType) | Out-Null
                    $currentType = $null
                    $state = "top"
                } else {
                    $depth--
                }
                $pendingComment.Clear(); $pendingMacro = ""
                $i++; continue
            }

            # Pure opening brace on its own line (nested scope)
            if ($trimmed -eq '{') {
                $depth++
                $pendingComment.Clear()
                $i++; continue
            }

            # Inside nested scope — track depth but skip parsing
            if ($depth -gt 0) {
                $opens  = Count-Char $trimmed '{'
                $closes = Count-Char $trimmed '}'
                $depth += $opens - $closes
                if ($depth -lt 0) { $depth = 0 }
                $pendingComment.Clear(); $pendingMacro = ""
                $i++; continue
            }

            # At depth 0 inside the type body:

            if ($trimmed -match '^GENERATED') {
                $pendingComment.Clear()
                $i++; continue
            }

            if ($trimmed -match '^(public|protected|private)\s*:') {
                $currentAccess = $Matches[1]
                $pendingComment.Clear()
                $i++; continue
            }

            # UE member macros (always on the line immediately before the decl)
            if ($trimmed -match '^(UPROPERTY|UFUNCTION|UMETA|UDELEGATE)\s*\(') {
                $endIdx = $i
                $pendingMacro = Read-MacroBlock $raw $i ([ref]$endIdx)
                $i = $endIdx
                $i++; continue
            }

            if ($trimmed -match '^(friend\b|using\b|typedef\b|DECLARE_|DEFINE_|static_assert)') {
                $pendingComment.Clear(); $pendingMacro = ""
                $i++; continue
            }

            # Collect a full declaration (may span multiple lines)
            $decl = $trimmed
            $j = $i

            $hasInlineBody = $decl -match '\{[^}]*\}'

            if (-not $hasInlineBody -and $decl -notmatch '[;{]') {
                while (($j + 1) -lt $n -and $decl -notmatch '[;{]') {
                    $j++
                    $decl += " " + $raw[$j].Trim()
                }
                if ($j -gt $i) { $i = $j }
            }

            # Bare opening brace at end = nested scope, not a member decl
            if ($decl -match '\{\s*$' -and $decl -notmatch '\{[^}]*\}') {
                $opens  = Count-Char $decl '{'
                $closes = Count-Char $decl '}'
                $depth += $opens - $closes
                $pendingComment.Clear(); $pendingMacro = ""
                $i++; continue
            }

            $comment = Join-CommentLines $pendingComment

            if ($decl -match '\(') {
                $m = Parse-MethodDecl $decl $currentAccess $comment $pendingMacro
                if ($m) { $currentType.Members.Add($m) | Out-Null }
            } elseif ($decl -match ';') {
                $m = Parse-PropertyDecl $decl $currentAccess $comment $pendingMacro
                if ($m) { $currentType.Members.Add($m) | Out-Null }
            }

            $pendingComment.Clear(); $pendingMacro = ""
        }

        $i++
    }

    return $types
}

# ---------------------------------------------------------------------------
# Markdown generator
# ---------------------------------------------------------------------------

function Generate-Markdown(
    [PSCustomObject[]]$Types,
    [string]$HeaderPath,
    [string[]]$CppLines,
    [string]$SourceRelPath = ""
) {
    $sb              = [System.Text.StringBuilder]::new()
    $fileName        = Split-Path -Leaf $HeaderPath
    $fileNameNoExt   = [System.IO.Path]::GetFileNameWithoutExtension($HeaderPath)

    # Index of implemented methods from .cpp
    $implemented = @{}
    if ($CppLines) {
        foreach ($cl in $CppLines) {
            if ($cl -match '::\s*(\w+)\s*\(') { $implemented[$Matches[1]] = $true }
        }
    }

    [void]$sb.AppendLine("# $fileNameNoExt")
    [void]$sb.AppendLine()
    [void]$sb.AppendLine("**File:** $BT$fileName$BT")
    if ($SourceRelPath) {
        [void]$sb.AppendLine("**Path:** $BT$SourceRelPath$BT")
    }
    [void]$sb.AppendLine()

    $typeCount = $Types.Count

    for ($ti = 0; $ti -lt $typeCount; $ti++) {
        $type = $Types[$ti]

        $typeLabel = switch ($type.SpecType) {
            'UCLASS'     { 'UObject Class' }
            'USTRUCT'    { 'UStruct' }
            'UENUM'      { 'UEnum' }
            'UINTERFACE' { 'UInterface' }
            'struct'     { 'Struct' }
            default      { 'Class' }
        }

        [void]$sb.AppendLine("---")
        [void]$sb.AppendLine()
        [void]$sb.AppendLine("## $($type.ClassName)")
        [void]$sb.AppendLine()

        $metaParts = [System.Collections.Generic.List[string]]::new()
        $metaParts.Add("**Type:** $typeLabel") | Out-Null
        if ($type.ParentClass) { $metaParts.Add("**Inherits:** $BT$($type.ParentClass)$BT") | Out-Null }
        if ($type.Module)      { $metaParts.Add("**Module:** $($type.Module)") | Out-Null }
        [void]$sb.AppendLine(($metaParts -join " | "))
        [void]$sb.AppendLine()

        if ($type.SpecArgs) {
            $specTokens = ($type.SpecArgs -split ',') |
                          ForEach-Object { $_.Trim() } |
                          Where-Object { $_ }
            if ($specTokens) {
                $specMd = ($specTokens | ForEach-Object { "$BT$_$BT" }) -join " "
                [void]$sb.AppendLine("**Specifiers:** $specMd")
                [void]$sb.AppendLine()
            }
        }

        if ($type.Comment) {
            [void]$sb.AppendLine("> $($type.Comment)")
            [void]$sb.AppendLine()
        }

        # Properties
        $props = @($type.Members | Where-Object { $_.Kind -eq 'property' })
        if ($props.Count -gt 0) {
            [void]$sb.AppendLine("### Properties")
            [void]$sb.AppendLine()

            foreach ($acc in @('public', 'protected', 'private')) {
                $grp = @($props | Where-Object { $_.Access -eq $acc })
                if ($grp.Count -eq 0) { continue }

                $accLabel = $acc.Substring(0,1).ToUpper() + $acc.Substring(1)
                [void]$sb.AppendLine("#### $accLabel")
                [void]$sb.AppendLine()
                [void]$sb.AppendLine("| Name | Type | Specifiers | Description |")
                [void]$sb.AppendLine("|------|------|------------|-------------|")

                foreach ($p in $grp) {
                    $spec = if ($p.UESpecifiers) { "$BT$($p.UESpecifiers)$BT" } else { "" }
                    $desc = $p.Comment -replace '\|', '\|'
                    [void]$sb.AppendLine("| $BT$($p.Name)$BT | $BT$($p.Type)$BT | $spec | $desc |")
                }
                [void]$sb.AppendLine()
            }
        }

        # Methods
        $methods = @($type.Members | Where-Object { $_.Kind -eq 'method' })
        if ($methods.Count -gt 0) {
            [void]$sb.AppendLine("### Methods")
            [void]$sb.AppendLine()

            foreach ($acc in @('public', 'protected', 'private')) {
                $grp = @($methods | Where-Object { $_.Access -eq $acc })
                if ($grp.Count -eq 0) { continue }

                $accLabel = $acc.Substring(0,1).ToUpper() + $acc.Substring(1)
                [void]$sb.AppendLine("#### $accLabel")
                [void]$sb.AppendLine()

                foreach ($m in $grp) {
                    [void]$sb.AppendLine("##### $BT$($m.Signature)$BT")
                    [void]$sb.AppendLine()

                    $badges = [System.Collections.Generic.List[string]]::new()
                    if ($m.Modifiers) { $badges.Add("_$($m.Modifiers)_") | Out-Null }
                    if ($m.UESpecifiers) {
                        $badges.Add("${BT}UFUNCTION($($m.UESpecifiers))${BT}") | Out-Null
                    }
                    if ($CppLines -and $implemented.ContainsKey($m.Name)) {
                        $badges.Add("_implemented in .cpp_") | Out-Null
                    }
                    if ($badges.Count -gt 0) {
                        [void]$sb.AppendLine(($badges -join " | "))
                        [void]$sb.AppendLine()
                    }

                    if ($m.Comment) {
                        [void]$sb.AppendLine($m.Comment)
                        [void]$sb.AppendLine()
                    }
                }
            }
        }
    }

    return $sb.ToString()
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Convert-SingleHeader([string]$HPath, [string]$OutPath, [string]$RelPath = "") {
    $cppFile  = [System.IO.Path]::ChangeExtension($HPath, ".cpp")
    $cppLines = $null
    if (Test-Path $cppFile) {
        Write-Host "  Found .cpp : $(Split-Path -Leaf $cppFile)" -ForegroundColor DarkGray
        $cppLines = Get-Content $cppFile -Encoding UTF8
    }

    Write-Host "Parsing    : $HPath" -ForegroundColor Cyan
    $types = @(Parse-Header $HPath)

    if ($types.Count -eq 0) {
        Write-Host "  [SKIP] No types found." -ForegroundColor DarkGray
        return
    }

    $names = ($types | ForEach-Object { $_.ClassName }) -join ", "
    Write-Host "  Found      : $($types.Count) type(s) -- $names" -ForegroundColor Green

    $dir = Split-Path -Parent $OutPath
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }

    $markdown = Generate-Markdown $types $HPath $cppLines $RelPath
    [System.IO.File]::WriteAllText($OutPath, $markdown, [System.Text.Encoding]::UTF8)
    Write-Host "  Written    : $OutPath" -ForegroundColor Green
}

function Find-ProjectRoot([string]$StartDir) {
    $dir = $StartDir
    while ($dir) {
        $uprojects = Get-ChildItem -Path $dir -Filter "*.uproject" -ErrorAction SilentlyContinue
        if ($uprojects) { return $dir }
        $parent = Split-Path -Parent $dir
        if ($parent -eq $dir) { break }
        $dir = $parent
    }
    return ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if ($ScanAll) {

    # Resolve project root
    if (-not $ProjectRoot) {
        $ProjectRoot = Find-ProjectRoot (Get-Location).Path
    }
    if (-not $ProjectRoot -or -not (Test-Path $ProjectRoot)) {
        Write-Host "[ERROR] Could not locate .uproject. Pass -ProjectRoot explicitly." -ForegroundColor Red
        exit 1
    }
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
    Write-Host "Project root : $ProjectRoot" -ForegroundColor Cyan

    # Scan roots: Source/ and all of Plugins/
    $scanRoots = @(
        (Join-Path $ProjectRoot "Source"),
        (Join-Path $ProjectRoot "Plugins")
    )

    # Segments that always disqualify a file path
    $alwaysExclude = @('Intermediate', 'Binaries', 'ThirdParty', 'PCGExtendedToolkit')
    $allExclude    = $alwaysExclude + $ExcludePlugins

    $headers = [System.Collections.Generic.List[string]]::new()
    foreach ($root in $scanRoots) {
        if (-not (Test-Path $root)) { continue }
        Get-ChildItem -Path $root -Filter "*.h" -Recurse -ErrorAction SilentlyContinue |
            Where-Object {
                $path = $_.FullName
                # Skip generated headers
                if ($_.Name -match '\.generated\.h$') { return $false }
                # Skip excluded path segments
                foreach ($seg in $allExclude) {
                    if ($path -match "\\$seg\\") { return $false }
                }
                return $true
            } |
            ForEach-Object { $headers.Add($_.FullName) | Out-Null }
    }

    if ($headers.Count -eq 0) {
        Write-Host "[WARN] No headers found in scan roots." -ForegroundColor Yellow
        exit 0
    }
    Write-Host "Found $($headers.Count) header(s) to convert." -ForegroundColor Cyan

    # Output directory
    if (-not $OutputDir) {
        $OutputDir = Join-Path $ProjectRoot "Documentation\generated-api"
    }
    Write-Host "Output dir   : $OutputDir`n" -ForegroundColor Cyan

    $ok = 0; $skipped = 0
    foreach ($h in $headers) {
        $rel    = $h.Substring($ProjectRoot.Length).TrimStart('\')
        $baseMd = [System.IO.Path]::GetFileNameWithoutExtension($h) + ".md"
        $outMd  = Join-Path $OutputDir $baseMd
        try {
            Convert-SingleHeader $h $outMd $rel
            $ok++
        } catch {
            Write-Host "  [ERROR] $($_.Exception.Message)" -ForegroundColor Red
            $skipped++
        }
        Write-Host ""
    }

    Write-Host "Done. Converted: $ok  Skipped: $skipped" -ForegroundColor Green

} else {

    # Single-file mode
    if (-not $HeaderFile) {
        Write-Host "Provide a .h file path or use -ScanAll to batch-convert." -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $HeaderFile)) {
        Write-Host "File not found: $HeaderFile" -ForegroundColor Red
        exit 1
    }
    if ($HeaderFile -notmatch '\.h$') {
        Write-Host "Expected a .h file." -ForegroundColor Red
        exit 1
    }

    $HeaderFile = (Resolve-Path $HeaderFile).Path

    if (-not $Output) {
        $baseName = [System.IO.Path]::GetFileNameWithoutExtension($HeaderFile)
        $Output   = Join-Path (Split-Path -Parent $HeaderFile) "$baseName.md"
    }

    Convert-SingleHeader $HeaderFile $Output
}
