<#
    Scan tools/ for .ps1 and .py scripts and emit the same JSON manifest shape as scan_tools.py.

    This is the pure-PowerShell counterpart to scan_tools.py, for a context with no Python
    available (or as a standalone check outside the Dev Tools UI). The Dev Tools UI server always
    uses scan_tools.py directly (no subprocess), since it needs Python's `ast` module to parse
    scripts precisely - this script gets the common cases right with regex instead, which is good
    enough to browse and run tools from a terminal, but python-editor entry-function detection is
    more limited here: it recognizes a zero-arg main(), an `if __name__ == "__main__": fn(args)`
    call, or a single function mentioned in the docstring, but does not fold references to
    module-level constants the way the AST-based scanner does.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\ui\Scan-Tools.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\ui\Scan-Tools.ps1 -OutputPath tools\ui\manifest.json
#>
param(
    [string]$ToolsRoot = '',
    [string]$OutputPath = ''
)

$ErrorActionPreference = 'Stop'

if (-not $ToolsRoot) {
    $ToolsRoot = Split-Path -Parent $PSScriptRoot
}
$ToolsRoot = (Resolve-Path -LiteralPath $ToolsRoot).Path

if (-not $OutputPath) {
    $OutputPath = Join-Path $PSScriptRoot 'manifest.json'
}

$ExcludedDirNames = @('ui', '__pycache__', '.git', 'lib')
$Acronyms = @{
    ue5 = 'UE5'; orm = 'ORM'; pdf = 'PDF'; html = 'HTML'; json = 'JSON'
    cpp = 'C++'; udn = 'UDN'; uasset = 'UAsset'; api = 'API'; id = 'ID'; url = 'URL'; cd = 'CD'
}

function Get-DisplayName {
    param([string]$Stem)
    $words = $Stem -split '[-_]+'
    $out = @()
    foreach ($w in $words) {
        if (-not $w) { continue }
        $lw = $w.ToLowerInvariant()
        if ($Acronyms.ContainsKey($lw)) {
            $out += $Acronyms[$lw]
        } elseif ($w -ceq $w.ToUpperInvariant()) {
            $out += $w
        } else {
            $out += ($w.Substring(0,1).ToUpperInvariant() + $w.Substring(1))
        }
    }
    if ($out.Count -eq 0) { return $Stem }
    return ($out -join ' ')
}

function Split-TopLevel {
    # Split $Text on $Sep only at bracket/quote depth 0 (mirrors scan_tools.py's _split_top_level).
    param([string]$Text, [char]$Sep = ',')
    $parts = New-Object System.Collections.Generic.List[string]
    $depth = 0
    $quote = [char]0
    $buf = New-Object System.Text.StringBuilder
    $i = 0
    while ($i -lt $Text.Length) {
        $ch = $Text[$i]
        if ($quote -ne [char]0) {
            [void]$buf.Append($ch)
            if ($ch -eq $quote) {
                if ($i + 1 -lt $Text.Length -and $Text[$i+1] -eq $quote) {
                    [void]$buf.Append($Text[$i+1]); $i++
                } else {
                    $quote = [char]0
                }
            }
        } elseif ($ch -eq "'" -or $ch -eq '"') {
            $quote = $ch; [void]$buf.Append($ch)
        } elseif ($ch -eq '(' -or $ch -eq '[' -or $ch -eq '{') {
            $depth++; [void]$buf.Append($ch)
        } elseif ($ch -eq ')' -or $ch -eq ']' -or $ch -eq '}') {
            $depth--; [void]$buf.Append($ch)
        } elseif ($ch -eq $Sep -and $depth -eq 0) {
            $parts.Add($buf.ToString()); $buf = New-Object System.Text.StringBuilder
        } else {
            [void]$buf.Append($ch)
        }
        $i++
    }
    if ($buf.Length -gt 0 -or $parts.Count -gt 0) { $parts.Add($buf.ToString()) }
    return @($parts | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
}

function Get-BalancedParen {
    # Given text and the index of an opening '(', returns @{Inner=...; After=<index after close>}
    param([string]$Text, [int]$OpenAt)
    $depth = 0; $quote = [char]0; $i = $OpenAt
    while ($i -lt $Text.Length) {
        $ch = $Text[$i]
        if ($quote -ne [char]0) {
            if ($ch -eq $quote) { $quote = [char]0 }
        } elseif ($ch -eq "'" -or $ch -eq '"') {
            $quote = $ch
        } elseif ($ch -eq '(') {
            $depth++
        } elseif ($ch -eq ')') {
            $depth--
            if ($depth -eq 0) {
                return @{ Inner = $Text.Substring($OpenAt + 1, $i - $OpenAt - 1); After = $i + 1 }
            }
        }
        $i++
    }
    return @{ Inner = $Text.Substring($OpenAt + 1); After = $Text.Length }
}

function Get-BalancedBracket {
    param([string]$Text, [int]$OpenAt)
    $depth = 0; $quote = [char]0; $i = $OpenAt
    while ($i -lt $Text.Length) {
        $ch = $Text[$i]
        if ($quote -ne [char]0) {
            if ($ch -eq $quote) { $quote = [char]0 }
        } elseif ($ch -eq "'" -or $ch -eq '"') {
            $quote = $ch
        } elseif ($ch -eq '[') {
            $depth++
        } elseif ($ch -eq ']') {
            $depth--
            if ($depth -eq 0) {
                return @{ Inner = $Text.Substring($OpenAt + 1, $i - $OpenAt - 1); After = $i + 1 }
            }
        }
        $i++
    }
    return @{ Inner = $Text.Substring($OpenAt + 1); After = $Text.Length }
}

function ConvertFrom-PSLiteral {
    param([string]$Raw)
    $r = $Raw.Trim()
    if ($r -eq '$true' -or $r -eq '$True') { return @{ Value = $true; IsLiteral = $true } }
    if ($r -eq '$false' -or $r -eq '$False') { return @{ Value = $false; IsLiteral = $true } }
    if ($r -eq '$null' -or $r -eq '$Null') { return @{ Value = $null; IsLiteral = $true } }
    if ($r.Length -ge 2 -and $r[0] -eq $r[-1] -and ($r[0] -eq "'" -or $r[0] -eq '"')) {
        $inner = $r.Substring(1, $r.Length - 2).Replace([string]$r[0] + [string]$r[0], [string]$r[0])
        return @{ Value = $inner; IsLiteral = $true }
    }
    if ($r -match '^-?\d+$') { return @{ Value = [int]$r; IsLiteral = $true } }
    if ($r -match '^-?\d+\.\d+$') { return @{ Value = [double]$r; IsLiteral = $true } }
    if ($r -match '^@\((.*)\)$') {
        $items = Split-TopLevel -Text $Matches[1]
        $values = @()
        $ok = $true
        foreach ($it in $items) {
            $lit = ConvertFrom-PSLiteral -Raw $it
            if (-not $lit.IsLiteral) { $ok = $false; break }
            $values += , $lit.Value
        }
        if ($ok) { return @{ Value = $values; IsLiteral = $true } }
    }
    return @{ Value = $r; IsLiteral = $false }
}

function ConvertFrom-PyLiteral {
    # Python-syntax counterpart to ConvertFrom-PSLiteral: True/False/None, quoted strings,
    # numbers, and (...)/[...] tuples/lists. Used when reading .py source, where defaults are
    # written in Python literal syntax rather than PowerShell's.
    param([string]$Raw)
    $r = $Raw.Trim()
    if ($r -eq 'True') { return @{ Value = $true; IsLiteral = $true } }
    if ($r -eq 'False') { return @{ Value = $false; IsLiteral = $true } }
    if ($r -eq 'None') { return @{ Value = $null; IsLiteral = $true } }
    if ($r.Length -ge 2 -and $r[0] -eq $r[-1] -and ($r[0] -eq "'" -or $r[0] -eq '"')) {
        $inner = $r.Substring(1, $r.Length - 2) -replace '\\n', "`n" -replace '\\t', "`t" -replace "\\(['`"])", '$1' -replace '\\\\', '\'
        return @{ Value = $inner; IsLiteral = $true }
    }
    if ($r -match '^-?\d+$') { return @{ Value = [int]$r; IsLiteral = $true } }
    if ($r -match '^-?\d+\.\d+$') { return @{ Value = [double]$r; IsLiteral = $true } }
    if ($r -match '^[\(\[](.*)[\)\]]$') {
        $items = Split-TopLevel -Text $Matches[1]
        $values = @()
        $ok = $true
        foreach ($it in $items) {
            $lit = ConvertFrom-PyLiteral -Raw $it
            if (-not $lit.IsLiteral) { $ok = $false; break }
            $values += , $lit.Value
        }
        if ($ok) { return @{ Value = $values; IsLiteral = $true } }
    }
    return @{ Value = $r; IsLiteral = $false }
}

$PsTypeMap = @{
    switch = 'bool'; bool = 'bool'; boolean = 'bool'
    int = 'int'; int32 = 'int'; int64 = 'int'; long = 'int'; uint32 = 'int'
    double = 'float'; float = 'float'; single = 'float'; decimal = 'float'
    string = 'string'
}

function ConvertTo-PSParam {
    param([string]$Decl)
    $brackets = New-Object System.Collections.Generic.List[string]
    $i = 0
    while ($i -lt $Decl.Length -and [char]::IsWhiteSpace($Decl[$i])) { $i++ }
    while ($i -lt $Decl.Length -and $Decl[$i] -eq '[') {
        $res = Get-BalancedBracket -Text $Decl -OpenAt $i
        $brackets.Add($res.Inner)
        $i = $res.After
        while ($i -lt $Decl.Length -and [char]::IsWhiteSpace($Decl[$i])) { $i++ }
    }
    $remainder = $Decl.Substring($i).Trim()
    $name = 'param'
    $defaultRaw = $null
    if ($remainder -match '^\$(?<name>\w+)\s*(=\s*(?<default>[\s\S]*))?$') {
        $name = $Matches['name']
        if ($Matches.ContainsKey('default') -and $Matches['default']) { $defaultRaw = $Matches['default'].Trim() }
    }

    $required = $false
    $choices = $null
    $typeToken = $null
    foreach ($g in $brackets) {
        $gt = $g.Trim()
        $gl = $gt.ToLowerInvariant()
        if ($gl.StartsWith('parameter')) {
            if ($gt -match 'Mandatory\s*=\s*\$true') { $required = $true }
            continue
        }
        if ($gl.StartsWith('validateset')) {
            if ($gt -match '(?is)^validateset\((.*)\)$') {
                $choices = @()
                foreach ($item in (Split-TopLevel -Text $Matches[1])) {
                    $lit = ConvertFrom-PSLiteral -Raw $item
                    if ($lit.IsLiteral) { $choices += , $lit.Value }
                }
            }
            continue
        }
        if ($gl.StartsWith('alias') -or $gl.StartsWith('validatenotnull') -or $gl.StartsWith('validaterange')) { continue }
        $typeToken = $gt
    }

    if (-not $typeToken) { $typeToken = 'string' }
    $isArray = $typeToken.EndsWith('[]')
    $baseType = if ($isArray) { $typeToken.Substring(0, $typeToken.Length - 2) } else { $typeToken }
    $uiType = if ($PsTypeMap.ContainsKey($baseType.ToLowerInvariant())) { $PsTypeMap[$baseType.ToLowerInvariant()] } else { 'string' }
    if ($isArray) { $uiType = 'string[]' }

    $defaultInfo = @{ Value = $null; IsLiteral = $true }
    if ($null -ne $defaultRaw) {
        $defaultInfo = ConvertFrom-PSLiteral -Raw $defaultRaw
    } elseif ($uiType -eq 'bool') {
        $defaultInfo = @{ Value = $false; IsLiteral = $true }
    }

    return [ordered]@{
        name = $name
        label = $name
        type = $uiType
        required = $required
        choices = $choices
        default = $defaultInfo.Value
        defaultIsLiteral = $defaultInfo.IsLiteral
        defaultRaw = $defaultRaw
        help = ''
    }
}

function Get-LeadingCommentBlock {
    # Returns @{ Text = <description text>; NextIndex = <first non-comment line index> }
    param([string[]]$Lines)
    $i = 0; $n = $Lines.Count
    while ($i -lt $n -and $Lines[$i].Trim() -eq '') { $i++ }
    if ($i -lt $n -and $Lines[$i].TrimStart().StartsWith('<#')) {
        $buf = New-Object System.Collections.Generic.List[string]
        $first = $Lines[$i].TrimStart()
        $buf.Add($first.Substring($first.IndexOf('<#') + 2))
        $i++
        while ($i -lt $n -and $Lines[$i] -notmatch '#>') {
            $buf.Add($Lines[$i]); $i++
        }
        if ($i -lt $n) {
            $closeIdx = $Lines[$i].IndexOf('#>')
            $buf.Add($Lines[$i].Substring(0, $closeIdx))
            $i++
        }
        $text = ($buf -join "`n")
        # dedent
        $bodyLines = $text -split "`n"
        $indents = @($bodyLines | Where-Object { $_.Trim() -ne '' } | ForEach-Object { $_.Length - $_.TrimStart(' ').Length })
        $pad = if ($indents.Count -gt 0) { ($indents | Measure-Object -Minimum).Minimum } else { 0 }
        $dedented = ($bodyLines | ForEach-Object { if ($_.Length -ge $pad) { $_.Substring($pad) } else { $_.Trim() } }) -join "`n"
        return @{ Text = $dedented.Trim(); NextIndex = $i }
    }
    $buf = New-Object System.Collections.Generic.List[string]
    while ($i -lt $n -and ($Lines[$i].Trim() -eq '' -or $Lines[$i].TrimStart().StartsWith('#'))) {
        $t = $Lines[$i].TrimStart()
        if ($t.StartsWith('#')) { $buf.Add($t.Substring(1).TrimStart(' ')) }
        elseif ($buf.Count -gt 0) { $buf.Add('') }
        $i++
    }
    return @{ Text = ($buf -join "`n").Trim(); NextIndex = $i }
}

function Split-DescriptionUsage {
    param([string]$Text)
    $usage = New-Object System.Collections.Generic.List[string]
    $descLines = New-Object System.Collections.Generic.List[string]
    $inUsage = $false
    foreach ($line in ($Text -split "`n")) {
        $stripped = $line.Trim()
        if ($stripped -match '^(?i)usage\s*:?\s*$') { $inUsage = $true; continue }
        if ($inUsage) {
            if ($stripped -eq '' -and $usage.Count -gt 0) { $inUsage = $false; continue }
            if ($stripped -ne '') { $usage.Add($stripped); continue }
        }
        if ($stripped -match '(?i)^(powershell|python)\b' -and ($line -match '-File' -or $line -match '\.py' -or $line -match '\.ps1')) {
            $usage.Add($stripped); continue
        }
        $descLines.Add($line)
    }
    $desc = ($descLines -join "`n").Trim() -replace '(\n){3,}', "`n`n"
    return @{ Description = $desc; Usage = @($usage) }
}

function Get-RelParts {
    param([string]$FullPath, [string]$Root)
    $rel = $FullPath.Substring($Root.Length).TrimStart('\','/').Replace('\','/')
    $segs = $rel -split '/'
    $dirSegs = $segs[0..($segs.Count - 2)]
    $category = if ($dirSegs.Count -gt 0) { $dirSegs[0] } else { 'misc' }
    $subCategory = if ($dirSegs.Count -gt 1) { ($dirSegs[1..($dirSegs.Count - 1)] -join '/') } else { '' }
    return @{ Rel = $rel; Category = $category; SubCategory = $subCategory }
}

function ConvertTo-ToolId {
    param([string]$RelPosix)
    $dot = $RelPosix.LastIndexOf('.')
    if ($dot -lt 0) { return $RelPosix }
    return $RelPosix.Substring(0, $dot)
}

function Read-PowerShellTool {
    param([System.IO.FileInfo]$File, [string]$Root)
    $raw = Get-Content -LiteralPath $File.FullName -Raw -Encoding UTF8
    $lines = $raw -split "`r?`n"

    $block = Get-LeadingCommentBlock -Lines $lines
    $split = Split-DescriptionUsage -Text $block.Text

    $idx = $block.NextIndex
    while ($idx -lt $lines.Count) {
        $s = $lines[$idx].Trim()
        if ($s -eq '' -or $s.StartsWith('#') -or $s -match '(?i)^\[CmdletBinding' -or $s -match '(?i)^\[OutputType') {
            $idx++; continue
        }
        break
    }

    $params = @()
    if ($idx -lt $lines.Count -and $lines[$idx].Trim() -match '(?i)^param\s*\(') {
        $restText = ($lines[$idx..($lines.Count - 1)] -join "`n")
        $openAt = $restText.IndexOf('(')
        $res = Get-BalancedParen -Text $restText -OpenAt $openAt
        foreach ($decl in (Split-TopLevel -Text $res.Inner)) {
            $params += , (ConvertTo-PSParam -Decl $decl)
        }
    }

    $relInfo = Get-RelParts -FullPath $File.FullName -Root $Root
    $summary = if ($split.Description) { ($split.Description -split "`n")[0].Trim() } else { "Runs $($File.Name)." }
    $description = if ($split.Description) { $split.Description } else { "Runs $($File.Name). No description comment found in the script." }

    return [ordered]@{
        id = ConvertTo-ToolId -RelPosix $relInfo.Rel
        name = $File.BaseName
        displayName = Get-DisplayName -Stem $File.BaseName
        relPath = $relInfo.Rel
        category = $relInfo.Category
        subCategory = $relInfo.SubCategory
        kind = 'powershell'
        requiresEditor = $false
        summary = $summary
        description = $description
        usage = $split.Usage
        params = $params
        sourceMTime = [Math]::Floor((Get-Date $File.LastWriteTimeUtc -UFormat %s))
        sourceSize = $File.Length
    }
}

function Read-PythonTool {
    # Regex-based best-effort counterpart to scan_tools.py's ast-based parser.
    param([System.IO.FileInfo]$File, [string]$Root)
    $raw = Get-Content -LiteralPath $File.FullName -Raw -Encoding UTF8

    $doc = ''
    if ($raw -match '(?s)^\s*#!.*?\r?\n(?<rest>.*)$') { $body = $Matches['rest'] } else { $body = $raw }
    # Every script in this repo docstrings with triple-double-quotes; that's the only form handled.
    if ($body -match '(?s)^\s*"""(?<doc>.*?)"""') {
        $doc = $Matches['doc'].Trim()
    }
    $split = Split-DescriptionUsage -Text $doc

    $hasArgparse = $raw -match 'ArgumentParser\s*\('
    $importsUnreal = $raw -match '(?m)^\s*import\s+unreal\b'

    $relInfo = Get-RelParts -FullPath $File.FullName -Root $Root
    $summary = if ($split.Description) { ($split.Description -split "`n")[0].Trim() } else { "Runs $($File.Name)." }
    $description = if ($split.Description) { $split.Description } else { "Runs $($File.Name). No module docstring found in the script." }

    $base = [ordered]@{
        id = ConvertTo-ToolId -RelPosix $relInfo.Rel
        name = $File.BaseName
        displayName = Get-DisplayName -Stem $File.BaseName
        relPath = $relInfo.Rel
        category = $relInfo.Category
        subCategory = $relInfo.SubCategory
        summary = $summary
        description = $description
        usage = $split.Usage
        sourceMTime = [Math]::Floor((Get-Date $File.LastWriteTimeUtc -UFormat %s))
        sourceSize = $File.Length
    }

    # Top-level `def name(...):` signatures, in file order, skipping private (_-prefixed) names.
    # The argument list is extracted with paren-balancing, not a `[^)]*` regex, because a
    # multi-line signature with a nested-paren default (a tuple default, a Tuple[...] type hint)
    # is exactly the shape this repo's editor scripts use, and a naive regex truncates at the
    # first inner ')' - silently mis-detecting the entry function.
    $funcs = [ordered]@{}
    foreach ($fm in [regex]::Matches($raw, '(?m)^def\s+(?<name>[A-Za-z_]\w*)\s*\(')) {
        $fname = $fm.Groups['name'].Value
        if ($fname.StartsWith('_') -or $funcs.Contains($fname)) { continue }
        $openAt = $fm.Index + $fm.Length - 1
        $res = Get-BalancedParen -Text $raw -OpenAt $openAt
        $funcs[$fname] = $res.Inner
    }

    if ($hasArgparse) {
        # Regex-based add_argument() extraction: good enough for flags/help/defaults/action, but
        # does not resolve module-level constant references the way scan_tools.py's AST pass does.
        $params = @()
        $positionals = @()
        foreach ($am in [regex]::Matches($raw, '(?s)\.add_argument\((?<inner>.*?)\)\s*\r?\n')) {
            $inner = $am.Groups['inner'].Value
            $parts = Split-TopLevel -Text $inner
            if ($parts.Count -eq 0) { continue }
            $flagParts = @($parts | Where-Object { $_ -match '^[\x27\x22]' })
            if ($flagParts.Count -eq 0) { continue }
            $flags = @($flagParts | ForEach-Object { $_.Trim("'", '"') })
            $isPositional = -not $flags[0].StartsWith('-')
            $kw = @{}
            foreach ($p in $parts) {
                if ($p -match '^(?<k>\w+)\s*=\s*(?<v>[\s\S]+)$') { $kw[$Matches['k']] = $Matches['v'].Trim() }
            }
            $action = if ($kw.ContainsKey('action')) { $kw['action'].Trim("'", '"') } else { 'store' }
            $isBool = $action -in @('store_true', 'store_false')
            $uiType = if ($isBool) { 'bool' } elseif ($kw.ContainsKey('choices')) { 'choice' } elseif ($kw.ContainsKey('type') -and $kw['type'].Trim() -eq 'int') { 'int' } elseif ($kw.ContainsKey('type') -and $kw['type'].Trim() -eq 'float') { 'float' } else { 'string' }
            $longFlag = @($flags | Where-Object { $_.StartsWith('--') })
            $label = if ($isPositional) { $flags[0] } elseif ($longFlag.Count -gt 0) { $longFlag[0] } else { $flags[0] }
            $dest = if ($isPositional) { $flags[0] } else { $label.TrimStart('-').Replace('-', '_') }
            $default = $null
            if ($isBool) { $default = ($action -eq 'store_false') }
            elseif ($kw.ContainsKey('default')) {
                $dlit = ConvertFrom-PyLiteral -Raw $kw['default']
                $default = $dlit.Value
            }
            $help = ''
            if ($kw.ContainsKey('help')) {
                $h = $kw['help'].Trim()
                if ($h.Length -ge 2 -and ($h[0] -eq "'" -or $h[0] -eq '"')) { $help = $h.Substring(1, $h.Length - 2) }
            }
            $entry = [ordered]@{
                name = $dest; label = $label; flags = $flags; type = $uiType
                required = ($kw.ContainsKey('required') -and $kw['required'].Trim() -eq 'True') -or $isPositional
                choices = $null; default = $default; defaultIsLiteral = $true; defaultRaw = $null
                help = $help; positional = $isPositional; nargs = $(if ($kw.ContainsKey('nargs')) { $kw['nargs'].Trim("'", '"') } else { $null })
                group = $null
            }
            if ($isPositional) { $positionals += , $entry } else { $params += , $entry }
        }
        $base['kind'] = 'python-cli'
        $base['requiresEditor'] = $false
        $base['params'] = $params
        $base['positionals'] = $positionals
        $base['groups'] = @()
        return $base
    }

    if ($importsUnreal) {
        $mainCallFn = $null
        $mainCallArgs = $null
        if ($raw -match '(?s)if\s+__name__\s*==\s*[\x27\x22]__main__[\x27\x22]\s*:\s*\r?\n\s+(?<call>[A-Za-z_]\w*)\((?<args>[^\r\n]*)\)') {
            $cand = $Matches['call']
            if ($funcs.Contains($cand)) { $mainCallFn = $cand; $mainCallArgs = $Matches['args'] }
        }

        $order = @()
        $notes = @()
        if ($funcs.Contains('main') -and [string]::IsNullOrWhiteSpace($funcs['main'])) {
            $order = @('main')
            $notes += 'This script exposes a zero-argument main() that runs a built-in preview/apply flow. Check the script''s module-level constants (shown below) before running - flipping something like APPLY from False to True happens by editing the file, not from this UI.'
        } elseif ($mainCallFn) {
            $order = @($mainCallFn)
        } else {
            $mentioned = @()
            foreach ($m in [regex]::Matches($doc, '[.\s]([A-Za-z_]\w*)\s*\(')) {
                $n = $m.Groups[1].Value
                if ($funcs.Contains($n) -and ($mentioned -notcontains $n)) { $mentioned += $n }
            }
            if ($mentioned.Count -gt 0) {
                $order = $mentioned
            } elseif ($funcs.Count -gt 0) {
                $order = @($funcs.Keys | Select-Object -First 1)
                $notes += 'Could not tell which function is the intended entry point from the docstring or a __main__ block - guessed from its signature. Pick the right one from the dropdown if this looks wrong.'
            }
        }
        foreach ($k in $funcs.Keys) { if ($order -notcontains $k) { $order += $k } }

        $entryFunctions = @()
        for ($idx = 0; $idx -lt $order.Count; $idx++) {
            $fname = $order[$idx]
            if (-not $funcs.Contains($fname)) { continue }
            $argText = $funcs[$fname]
            $fparams = @()
            $exampleValues = @()
            if ($fname -eq $mainCallFn -and $mainCallArgs) {
                $exampleValues = @(Split-TopLevel -Text $mainCallArgs)
            }
            $argDecls = @(Split-TopLevel -Text $argText)
            for ($ai = 0; $ai -lt $argDecls.Count; $ai++) {
                $ad = $argDecls[$ai].Trim()
                if ($ad -eq 'self' -or $ad -eq 'cls' -or $ad -eq '') { continue }
                $pname = $ad; $ann = $null; $defRaw = $null
                if ($ad -match '^(?<n>\w+)\s*(:\s*(?<ann>[^=]+?))?\s*(=\s*(?<def>[\s\S]+))?$') {
                    $pname = $Matches['n']
                    if ($Matches['ann']) { $ann = $Matches['ann'].Trim() }
                    if ($Matches['def']) { $defRaw = $Matches['def'].Trim() }
                }
                $required = $true
                $defVal = $null
                $defSource = $null
                if ($defRaw) {
                    $lit = ConvertFrom-PyLiteral -Raw $defRaw
                    $defVal = $lit.Value; $required = $false; $defSource = 'signature'
                } elseif ($ai -lt $exampleValues.Count) {
                    $lit = ConvertFrom-PyLiteral -Raw $exampleValues[$ai]
                    $defVal = $lit.Value; $required = $false; $defSource = 'example'
                }
                $uiType = 'string'
                if ($ann) {
                    $al = $ann.ToLowerInvariant()
                    if ($al -match '^(tuple|list|dict|sequence|set)') { $uiType = 'json' }
                    elseif ($al -match 'bool') { $uiType = 'bool' }
                    elseif ($al -match 'float') { $uiType = 'float' }
                    elseif ($al -match '\bint\b') { $uiType = 'int' }
                } elseif ($defVal -is [bool]) { $uiType = 'bool' }
                elseif ($defVal -is [int]) { $uiType = 'int' }
                elseif ($defVal -is [double]) { $uiType = 'float' }
                elseif ($defVal -is [array]) { $uiType = 'json' }
                $fparams += , ([ordered]@{
                    name = $pname; label = $pname; type = $uiType; annotation = $ann
                    required = $required; choices = $null; default = $defVal
                    defaultIsLiteral = $true; defaultRaw = $defRaw; defaultSource = $defSource; help = ''
                })
            }
            $entryFunctions += , ([ordered]@{
                name = $fname; isPrimary = ($idx -eq 0); docSummary = ''; params = $fparams
            })
        }

        $constants = @()
        foreach ($cm in [regex]::Matches($raw, '(?m)^(?<name>[A-Z][A-Z0-9_]*)\s*=\s*(?<val>.+)$')) {
            $cname = $cm.Groups['name'].Value
            if ($cname.StartsWith('_')) { continue }
            $cval = $cm.Groups['val'].Value.Trim()
            $lit = ConvertFrom-PyLiteral -Raw $cval
            if (-not $lit.IsLiteral) { continue }
            $text = if ($cval.Length -gt 300) { $cval.Substring(0, 300) + '…' } else { $cval }
            $constants += , ([ordered]@{ name = $cname; value = $text })
        }

        $base['kind'] = 'python-editor'
        $base['requiresEditor'] = $true
        $base['entryFunctions'] = $entryFunctions
        $base['scriptConstants'] = $constants
        $base['notes'] = $notes
        $base['params'] = if ($entryFunctions.Count -gt 0) { $entryFunctions[0]['params'] } else { @() }
        return $base
    }

    $base['kind'] = 'python-cli'
    $base['requiresEditor'] = $false
    $base['params'] = @()
    $base['positionals'] = @()
    $base['groups'] = @()
    return $base
}

# --------------------------------------------------------------------------------------
# Discovery + top-level scan
# --------------------------------------------------------------------------------------

# -Include with -Recurse is unreliable unless -Path itself ends in a wildcard (a well-known
# PowerShell gotcha), so filter the extension ourselves rather than trust -Include here.
$allFiles = Get-ChildItem -LiteralPath $ToolsRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.Extension -eq '.ps1' -or $_.Extension -eq '.py') -and
        ($_.FullName -notmatch '__pycache__') -and
        -not (
            @($_.DirectoryName.Substring($ToolsRoot.Length).TrimStart('\', '/') -split '[\\/]' |
                Where-Object { $_ -ne '' }) |
            Where-Object { $ExcludedDirNames -contains $_ }
        )
    } |
    Sort-Object FullName

$tools = @()
$errors = @()
foreach ($file in $allFiles) {
    try {
        if ($file.Extension -eq '.ps1') {
            $tools += , (Read-PowerShellTool -File $file -Root $ToolsRoot)
        } else {
            $tools += , (Read-PythonTool -File $file -Root $ToolsRoot)
        }
    } catch {
        $errors += , [ordered]@{ relPath = $file.FullName.Substring($ToolsRoot.Length).TrimStart('\','/').Replace('\','/'); error = "$_" }
    }
}

$tools = @($tools | Sort-Object category, subCategory, name)

$manifest = [ordered]@{
    generatedAt = (Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')
    toolsRoot = $ToolsRoot
    toolCount = $tools.Count
    tools = $tools
    errors = $errors
}

$json = $manifest | ConvertTo-Json -Depth 12
Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8
Write-Host "Scanned $($tools.Count) tool(s), $($errors.Count) error(s). Wrote $OutputPath"
