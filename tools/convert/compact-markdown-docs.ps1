#Requires -Version 5.1
<#
.SYNOPSIS
    Merges every leaf folder of loose .md files into one (or a few size-capped) sibling .md
    file(s), to keep large generated-doc trees under a manageable file count without producing
    single files too big to upload elsewhere (e.g. NotebookLM's per-source word-count cap).

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
    still becomes its own (oversized) chunk rather than being split mid-file.

    Intended as a post-processing pass over doc trees like the one convert-cpp-to-markdown.ps1
    produces (Documentation\generated-api\source and \content), where one file per class/asset
    is easy to generate but unwieldy to keep as thousands of loose files, and grouping by their
    natural subfolder (a UBT module, a content pack's subfolder, etc.) still isn't always small
    enough on its own for a single upload.

.PARAMETER RootDir
    Root directory to scan.  Defaults to <ProjectRoot>\Documentation\generated-api.

.PARAMETER MinFilesPerFolder
    Minimum file count in a leaf folder before it gets merged.  Defaults to 2 (a folder with
    only one file gains nothing from merging).

.PARAMETER MaxWordsPerFile
    Soft cap on words per merged output file, used to split an oversized folder into multiple
    chunks.  Defaults to 400000 (comfortably under NotebookLM's documented 500,000-word
    per-source limit).

.PARAMETER DryRun
    List what would be merged (including chunk counts) without writing or deleting anything.

.EXAMPLE
    .\compact-markdown-docs.ps1
    .\compact-markdown-docs.ps1 -RootDir "Documentation\generated-api\source" -DryRun
    .\compact-markdown-docs.ps1 -MinFilesPerFolder 5 -MaxWordsPerFile 250000
#>
param(
    [string]$RootDir = "",

    [int]$MinFilesPerFolder = 2,

    [int]$MaxWordsPerFile = 400000,

    [switch]$DryRun
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

if (-not $RootDir) {
    $projectRoot = Find-ProjectRoot (Get-Location).Path
    if (-not $projectRoot) {
        Write-Host "[ERROR] Could not locate .uproject. Pass -RootDir explicitly." -ForegroundColor Red
        exit 1
    }
    $RootDir = Join-Path $projectRoot "Documentation\generated-api"
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
        $entries.Add([PSCustomObject]@{
            Name    = [System.IO.Path]::GetFileNameWithoutExtension($f.Name)
            Content = $content
            Words   = Get-WordCount $content
        }) | Out-Null
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
Write-Host "Files before    : $beforeCount" -ForegroundColor Cyan
Write-Host "Files after     : $afterCount" -ForegroundColor Cyan
