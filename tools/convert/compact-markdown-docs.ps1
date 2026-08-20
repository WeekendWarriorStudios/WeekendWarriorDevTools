#Requires -Version 5.1
<#
.SYNOPSIS
    Merges every leaf folder of loose .md files into one (or a few size-capped) sibling .md
    file(s), then de-nests any folder left holding only a single item, to keep large
    generated-doc trees under a manageable file count without producing single files too big to
    upload elsewhere (e.g. NotebookLM's per-source word-count cap).

.DESCRIPTION
    Walks -RootDir looking for "leaf" directories (directories with no subdirectories of their
    own) that contain -MinFilesPerFolder or more .md files. Each qualifying leaf directory's
    files are concatenated (sorted by filename, each section separated by a rule) into merged
    file(s) written next to the directory, then the original directory is deleted. Directories
    with fewer files than -MinFilesPerFolder are left as-is.

    If a leaf folder's combined word count exceeds -MaxWordsPerFile, its files are packed into
    multiple chunks instead of one file, each kept under the cap: "<LeafDirName>_1.md",
    "<LeafDirName>_2.md", etc. A folder that fits in one chunk keeps the plain
    "<LeafDirName>.md" name (no numeric suffix). A single source file that alone exceeds the cap
    is itself split along its own top-level "---" section rules (e.g. the per-graph sections in
    one Blueprint's export) before chunking, so even one huge asset doesn't blow past the cap;
    only a section that still can't be split further becomes its own oversized chunk.

    After merging, a second de-nesting pass walks -RootDir bottom-up: any folder that (still, or
    now that its own subfolders were merged/de-nested away) contains exactly one item - one file
    or one subfolder - has that item moved up into its parent and the now-empty folder deleted.
    This repeats up the tree, so a chain of single-item folders collapses fully in one pass. A
    folder with more than one item is always left nested, no matter how it got there. Use
    -SkipDenest to disable this pass and keep only the merge behavior.

    Intended as a post-processing pass over doc trees like the one convert-cpp-to-markdown.ps1
    produces (Documentation\generated-api\markdown\source and \content), where one file per class/asset
    is easy to generate but unwieldy to keep as thousands of loose files, and grouping by their
    natural subfolder (a UBT module, a content pack's subfolder, etc.) still isn't always small
    enough on its own for a single upload. It's also common for such trees to nest a single
    file one folder deep (e.g. "MyClass/MyClass.md") - the de-nesting pass flattens that too.

.PARAMETER RootDir
    Root directory to scan.  Defaults to <ProjectRoot>\Documentation\generated-api\markdown
    (the markdown half of the split layout; the sibling \pdf tree is generated output and must
    not be merged).

.PARAMETER MinFilesPerFolder
    Minimum file count in a leaf folder before it gets merged.  Defaults to 2 (a folder with
    only one file gains nothing from merging).

.PARAMETER MaxWordsPerFile
    Soft cap on words per merged output file, used to split an oversized folder into multiple
    chunks.  Defaults to 400000 (comfortably under NotebookLM's documented 500,000-word
    per-source limit).

.PARAMETER DryRun
    List what would be merged and de-nested (including chunk counts) without writing or
    deleting anything.

.PARAMETER SkipDenest
    Skip the post-merge de-nesting pass; leave single-item folders nested.

.EXAMPLE
    .\compact-markdown-docs.ps1
    .\compact-markdown-docs.ps1 -RootDir "Documentation\generated-api\markdown\source" -DryRun
    .\compact-markdown-docs.ps1 -MinFilesPerFolder 5 -MaxWordsPerFile 250000
    .\compact-markdown-docs.ps1 -SkipDenest
#>
param(
    [string]$RootDir = "",

    [int]$MinFilesPerFolder = 2,

    [int]$MaxWordsPerFile = 400000,

    [switch]$DryRun,

    [switch]$SkipDenest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

function Get-WordCount([string]$Text) {
    if (-not $Text) { return 0 }
    return (@($Text -split '\s+' | Where-Object { $_ })).Count
}

# A single source file can itself be too large for MaxWords (e.g. one Blueprint with hundreds of
# internal graphs). Rather than accept it whole as one oversized chunk, split it along its own
# top-level "---" section rules (the same separator these generators already put between graphs/
# entries), recursing in case a single section is still too big on its own. Each PSCustomObject
# emitted here is a plain (non-enumerable) object, so - unlike Group-IntoChunks below - this can
# safely emit results one at a time through the normal output stream without any pipeline-
# flattening risk; callers just `foreach` over however many pieces come back.
function Split-OversizedEntry([PSCustomObject]$Entry, [int]$MaxWords) {
    if ($Entry.Words -le $MaxWords) {
        $Entry
        return
    }

    $rawParts = @($Entry.Content -split '(?m)^---\s*$')
    if ($rawParts.Count -le 1) {
        # No further natural split point - accept it as an oversized leaf.
        $Entry
        return
    }

    for ($i = 0; $i -lt $rawParts.Count; $i++) {
        $partContent = $rawParts[$i].Trim()
        if (-not $partContent) { continue }

        $headingLine = @($partContent -split "`r?`n" | Where-Object { $_.Trim() -match '^#+\s*\S' }) | Select-Object -First 1
        $label = if ($headingLine) { ($headingLine.Trim() -replace '^#+\s*', '') } else { "section $($i + 1)" }

        $subEntry = [PSCustomObject]@{
            Name    = "$($Entry.Name) - $label"
            Content = $partContent
            Words   = Get-WordCount $partContent
        }

        Split-OversizedEntry $subEntry $MaxWords
    }
}

# Packs pre-read file entries (Name/Content/Words) into word-count-capped chunks. A single entry
# that alone exceeds MaxWords still becomes (or starts) its own chunk rather than being split.
function Group-IntoChunks([System.Collections.Generic.List[PSCustomObject]]$Entries, [int]$MaxWords) {
    $chunks  = [System.Collections.Generic.List[System.Collections.Generic.List[PSCustomObject]]]::new()
    $current = [System.Collections.Generic.List[PSCustomObject]]::new()
    $currentWords = 0

    foreach ($entry in $Entries) {
        if ($current.Count -gt 0 -and ($currentWords + $entry.Words) -gt $MaxWords) {
            $chunks.Add($current) | Out-Null
            $current = [System.Collections.Generic.List[PSCustomObject]]::new()
            $currentWords = 0
        }
        $current.Add($entry) | Out-Null
        $currentWords += $entry.Words
    }
    if ($current.Count -gt 0) { $chunks.Add($current) | Out-Null }

    # The unary comma forces this to cross the function-return pipeline boundary as exactly one
    # object. Without it, when there's only one chunk, PowerShell's automatic pipeline unrolling
    # collapses the (single-item) outer list down to that one chunk's own contents, so the caller
    # would silently receive a flat list of file-entries instead of a one-chunk list of chunks.
    return ,$chunks
}

function New-ChunkMarkdown([string]$Title, [System.Collections.Generic.List[PSCustomObject]]$Chunk) {
    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine("# $Title")
    [void]$sb.AppendLine()
    [void]$sb.AppendLine("_Compacted from $($Chunk.Count) files._")
    [void]$sb.AppendLine()
    [void]$sb.AppendLine("## Contents")
    [void]$sb.AppendLine()
    foreach ($entry in $Chunk) {
        [void]$sb.AppendLine("- $($entry.Name)")
    }
    [void]$sb.AppendLine()

    foreach ($entry in $Chunk) {
        [void]$sb.AppendLine("---")
        [void]$sb.AppendLine()
        [void]$sb.Append($entry.Content)
        [void]$sb.AppendLine()
        [void]$sb.AppendLine()
    }

    return $sb.ToString()
}

# Recursively collapses any directory under (but not including) $RootDir that ends up holding
# exactly one item - a single file or a single subdirectory - by moving that item up into the
# parent and deleting the now-empty directory. Recurses into subdirectories *before* checking
# this directory's own item count, so a chain of single-item folders (A/B/C/only.md) fully
# collapses bottom-up in one pass: C's content moves into B, which then itself holds one item
# and moves into A, and so on. A directory holding more than one item is always left nested,
# no matter how it got there - only the exactly-one-item case ever de-nests.
#
# Besides {Moved; Skipped} stats, the returned PSCustomObject tells $Dir's *caller* what $Dir
# itself resolves to: Collapsed=$false means $Dir stands as a real directory (0, 2+ items, or a
# would-be collision blocked its collapse); Collapsed=$true means $Dir's sole item takes $Dir's
# place, named by ResolvedName/ResolvedIsDir. This is tracked in memory - rather than by
# re-reading $Dir's children off disk after recursing - specifically so a DryRun preview of a
# multi-level chain reports each level's true original source path instead of re-querying a
# folder a real run would already have deleted by that point (DryRun never touches disk, so nothing
# actually moves between recursive calls). On a real run this doubles as the item's current
# actual path, since by the time a directory checks its own contents every subdirectory that was
# going to collapse already has, for real.
function Remove-SingleItemNesting {
    param(
        [Parameter(Mandatory)] [string]$Dir,
        [Parameter(Mandatory)] [string]$RootDir,
        [switch]$DryRun
    )

    $result = [PSCustomObject]@{
        Moved         = 0
        Skipped       = 0
        Collapsed     = $false
        ResolvedName  = $null
        ResolvedIsDir = $false
        SourcePath    = $null
    }

    # $Dir's contents as its parent will see them, once every subdirectory's own collapse (if
    # any) is folded in.
    $virtualItems = [System.Collections.Generic.List[PSCustomObject]]::new()
    foreach ($f in @(Get-ChildItem -LiteralPath $Dir -File -ErrorAction SilentlyContinue)) {
        $virtualItems.Add([PSCustomObject]@{ Name = $f.Name; IsDir = $false; SourcePath = $f.FullName })
    }
    foreach ($sub in @(Get-ChildItem -LiteralPath $Dir -Directory -ErrorAction SilentlyContinue)) {
        $childResult = Remove-SingleItemNesting -Dir $sub.FullName -RootDir $RootDir -DryRun:$DryRun
        $result.Moved   += $childResult.Moved
        $result.Skipped += $childResult.Skipped
        if ($childResult.Collapsed) {
            $virtualItems.Add([PSCustomObject]@{ Name = $childResult.ResolvedName; IsDir = $childResult.ResolvedIsDir; SourcePath = $childResult.SourcePath })
        } else {
            $virtualItems.Add([PSCustomObject]@{ Name = $sub.Name; IsDir = $true; SourcePath = $sub.FullName })
        }
    }

    # Never collapse the scan root itself - it has no meaningful "parent" to push into.
    if ($Dir -eq $RootDir) { return $result }
    if ($virtualItems.Count -ne 1) { return $result }

    $only = $virtualItems[0]
    $parentDir = Split-Path -Parent $Dir
    $destination = Join-Path $parentDir $only.Name

    if (Test-Path -LiteralPath $destination) {
        Write-Host "[WARN] Skipping de-nest of $Dir; $destination already exists." -ForegroundColor Yellow
        $result.Skipped++
        return $result
    }

    if ($DryRun) {
        Write-Host "[DRY RUN] Would de-nest $($only.SourcePath) -> $destination (removing $Dir)" -ForegroundColor Yellow
    } else {
        Move-Item -LiteralPath $only.SourcePath -Destination $destination
        Remove-Item -LiteralPath $Dir -Recurse -Force
        Write-Host "De-nested -> $destination" -ForegroundColor Green
    }
    $result.Moved++
    $result.Collapsed     = $true
    $result.ResolvedName  = $only.Name
    $result.ResolvedIsDir = $only.IsDir
    # DryRun: nothing really moved, so the item's real path is still its original one - keep
    # reporting that all the way up the chain. Real run: it just landed at $destination for real.
    $result.SourcePath    = if ($DryRun) { $only.SourcePath } else { $destination }
    return $result
}

if (-not $RootDir) {
    $projectRoot = Find-ProjectRoot (Get-Location).Path
    if (-not $projectRoot) {
        Write-Host "[ERROR] Could not locate .uproject. Pass -RootDir explicitly." -ForegroundColor Red
        exit 1
    }
    $RootDir = Join-Path $projectRoot "Documentation\generated-api\markdown"
}

if (-not (Test-Path $RootDir)) {
    Write-Host "[ERROR] RootDir not found: $RootDir" -ForegroundColor Red
    exit 1
}
$RootDir = (Resolve-Path $RootDir).Path

# Leaf directories: no subdirectories of their own.
$allDirs = @(Get-ChildItem -Path $RootDir -Directory -Recurse |
    Sort-Object { $_.FullName.Split([System.IO.Path]::DirectorySeparatorChar).Count } -Descending)
$leafDirs = @($allDirs | Where-Object {
    (@(Get-ChildItem -Path $_.FullName -Directory -ErrorAction SilentlyContinue)).Count -eq 0
})

Write-Host "Root              : $RootDir" -ForegroundColor Cyan
Write-Host "Leaf folders      : $($leafDirs.Count)" -ForegroundColor Cyan
Write-Host "Max words/file    : $MaxWordsPerFile" -ForegroundColor Cyan
Write-Host ""

$beforeCount = @(Get-ChildItem -Path $RootDir -Filter "*.md" -Recurse -File).Count
$mergedFolders   = 0
$chunkedFolders  = 0
$skippedExisting = 0
$qualifyingCount = 0

foreach ($dir in $leafDirs) {
    $mdFiles = @(Get-ChildItem -Path $dir.FullName -Filter "*.md" -File | Sort-Object Name)
    if ($mdFiles.Count -lt $MinFilesPerFolder) { continue }
    $qualifyingCount++

    $parentDir = Split-Path -Parent $dir.FullName

    $entries = [System.Collections.Generic.List[PSCustomObject]]::new()
    foreach ($f in $mdFiles) {
        $content = (Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8).TrimEnd()
        $rawEntry = [PSCustomObject]@{
            Name    = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
            Content = $content
            Words   = Get-WordCount $content
        }
        foreach ($piece in (Split-OversizedEntry $rawEntry $MaxWordsPerFile)) {
            $entries.Add($piece) | Out-Null
        }
    }

    $chunks = Group-IntoChunks $entries $MaxWordsPerFile
    $useSuffix = $chunks.Count -gt 1

    if ($DryRun) {
        $totalWords = ($entries | Measure-Object -Property Words -Sum).Sum
        if ($useSuffix) {
            Write-Host "[DRY RUN] Would split $($mdFiles.Count) file(s) ($totalWords words) in $($dir.FullName) into $($chunks.Count) chunk(s):" -ForegroundColor Yellow
            for ($i = 0; $i -lt $chunks.Count; $i++) {
                Write-Host "           -> $(Join-Path $parentDir "$($dir.Name)_$($i + 1).md")" -ForegroundColor Yellow
            }
        } else {
            Write-Host "[DRY RUN] Would merge $($mdFiles.Count) file(s) ($totalWords words) in $($dir.FullName)" -ForegroundColor Yellow
            Write-Host "           -> $(Join-Path $parentDir "$($dir.Name).md")" -ForegroundColor Yellow
        }
        continue
    }

    # Check every target path up front so a mid-loop collision can't leave a partial merge.
    # @(...) keeps this a true array even when $chunks.Count -eq 1 (a bare `for` expression
    # assigned to a variable otherwise collapses a single result down to a plain string, and
    # $targetPaths[0] on a string indexes its characters instead of the path).
    $targetPaths = @(for ($i = 0; $i -lt $chunks.Count; $i++) {
        $name = if ($useSuffix) { "$($dir.Name)_$($i + 1).md" } else { "$($dir.Name).md" }
        Join-Path $parentDir $name
    })
    $collisions = @($targetPaths | Where-Object { Test-Path $_ })
    if ($collisions.Count -gt 0) {
        Write-Host "[WARN] $($collisions -join ', ') already exist; skipping merge for $($dir.FullName)." -ForegroundColor Yellow
        $skippedExisting++
        continue
    }

    for ($i = 0; $i -lt $chunks.Count; $i++) {
        $title = if ($useSuffix) { "$($dir.Name) (part $($i + 1) of $($chunks.Count))" } else { $dir.Name }
        $markdown = New-ChunkMarkdown $title $chunks[$i]
        [System.IO.File]::WriteAllText($targetPaths[$i], $markdown, [System.Text.Encoding]::UTF8)
        Write-Host "Merged $($chunks[$i].Count) file(s) -> $($targetPaths[$i])" -ForegroundColor Green
    }
    Remove-Item -LiteralPath $dir.FullName -Recurse -Force

    $mergedFolders++
    if ($useSuffix) { $chunkedFolders++ }
}

if ($DryRun) {
    Write-Host ""
    Write-Host "[DRY RUN] Would merge $qualifyingCount qualifying folder(s) (of $($leafDirs.Count) leaf folder(s))." -ForegroundColor Yellow
}

$denestResult = [PSCustomObject]@{ Moved = 0; Skipped = 0 }
if (-not $SkipDenest) {
    Write-Host ""
    $denestResult = Remove-SingleItemNesting -Dir $RootDir -RootDir $RootDir -DryRun:$DryRun
}

if ($DryRun) {
    Write-Host ""
    if (-not $SkipDenest) {
        Write-Host "[DRY RUN] Would de-nest $($denestResult.Moved) folder(s) down to their single remaining item." -ForegroundColor Yellow
        if ($denestResult.Skipped -gt 0) {
            Write-Host "[DRY RUN] $($denestResult.Skipped) folder(s) would be skipped (name collision)." -ForegroundColor Yellow
        }
    }
    exit 0
}

$afterCount = @(Get-ChildItem -Path $RootDir -Filter "*.md" -Recurse -File).Count
Write-Host ""
Write-Host "Merged folders  : $mergedFolders" -ForegroundColor Green
if ($chunkedFolders -gt 0) {
    Write-Host "  ...split into multiple chunks : $chunkedFolders" -ForegroundColor Green
}
if ($skippedExisting -gt 0) {
    Write-Host "Skipped (name collision) : $skippedExisting" -ForegroundColor Yellow
}
if (-not $SkipDenest) {
    Write-Host "De-nested folders : $($denestResult.Moved)" -ForegroundColor Green
    if ($denestResult.Skipped -gt 0) {
        Write-Host "De-nest skipped (name collision) : $($denestResult.Skipped)" -ForegroundColor Yellow
    }
}
Write-Host "Files before    : $beforeCount" -ForegroundColor Cyan
Write-Host "Files after     : $afterCount" -ForegroundColor Cyan
