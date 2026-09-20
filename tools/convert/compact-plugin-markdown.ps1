#Requires -Version 5.1

<#
.SYNOPSIS
    Compacts every direct child folder of a documentation folder into one (or a
    few size-capped) sibling Markdown file(s).

.DESCRIPTION
    Each folder directly beneath -ParentFolder is recursively scanned for .md
    files. Every Markdown file belonging to that folder is merged into sibling
    file(s) named after the folder itself.

        Plugins\PoseSearch\Runtime\PoseSearchLibrary.md   ->   Plugins\PoseSearch.md

    If the combined word count exceeds -MaxWordsPerFile, the output is split:

        Plugins\PoseSearch_1.md
        Plugins\PoseSearch_2.md

    The source folder is deleted only after every output file has been written
    successfully. If a write fails, any partial outputs are removed and the
    source folder is left untouched.

    Nothing about this script is plugin-specific. -ParentFolder simply means
    "the folder whose direct children get compacted", so it works equally on
    markdown\source\Plugins and markdown\content\Animation.

.PARAMETER ParentFolder
    The folder containing the documentation directories to compact.
    Aliases: -PluginsRoot, -RootFolder

.PARAMETER MaxWordsPerFile
    Maximum approximate word count per output file. Default is 400000.

.PARAMETER FolderName
    Optional. Compacts only the named child folder.
    Alias: -PluginName

.PARAMETER DryRun
    Reports what would happen without writing or deleting anything.

.EXAMPLE
    .\compact-plugin-markdown.ps1 -ParentFolder "Documentation\generated-api\markdown\source\Plugins" -DryRun

.EXAMPLE
    .\compact-plugin-markdown.ps1 -ParentFolder "Documentation\generated-api\markdown\content\Animation"

.EXAMPLE
    .\compact-plugin-markdown.ps1 -ParentFolder "Documentation\generated-api\markdown\source\Plugins" -FolderName "PoseSearch" -DryRun
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [Alias('PluginsRoot', 'RootFolder')]
    [string]$ParentFolder,

    [ValidateRange(1, 2147483647)]
    [int]$MaxWordsPerFile = 400000,

    [Alias('PluginName')]
    [string]$FolderName = "",

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-WordCount {
    param(
        [AllowEmptyString()]
        [string]$Text
    )

    if (-not $Text) {
        return 0
    }

    $words = @(
        $Text -split '\s+' | Where-Object { $_.Trim().Length -gt 0 }
    )

    return $words.Count
}

function New-MarkdownDocument {
    param(
        [Parameter(Mandatory)]
        [string]$Title,

        [Parameter(Mandatory)]
        [System.Collections.IList]$Entries
    )

    $builder = New-Object System.Text.StringBuilder

    [void]$builder.AppendLine("# $Title")
    [void]$builder.AppendLine()
    [void]$builder.AppendLine("_Compacted from $($Entries.Count) Markdown entries._")
    [void]$builder.AppendLine()
    [void]$builder.AppendLine("## Contents")
    [void]$builder.AppendLine()

    foreach ($entry in $Entries) {
        [void]$builder.AppendLine("- $($entry.Name)")
    }

    [void]$builder.AppendLine()

    foreach ($entry in $Entries) {
        [void]$builder.AppendLine("---")
        [void]$builder.AppendLine()
        [void]$builder.AppendLine("## $($entry.Name)")
        [void]$builder.AppendLine()
        [void]$builder.AppendLine($entry.Content.TrimEnd())
        [void]$builder.AppendLine()
    }

    return $builder.ToString()
}

function Split-IntoChunks {
    param(
        [Parameter(Mandatory)]
        [System.Collections.IList]$Entries,

        [Parameter(Mandatory)]
        [int]$MaximumWords
    )

    $chunks       = New-Object System.Collections.ArrayList
    $currentChunk = New-Object System.Collections.ArrayList
    $currentWords = 0

    foreach ($entry in $Entries) {
        $wouldExceedLimit = (
            $currentChunk.Count -gt 0 -and
            ($currentWords + $entry.Words) -gt $MaximumWords
        )

        if ($wouldExceedLimit) {
            [void]$chunks.Add($currentChunk)
            $currentChunk = New-Object System.Collections.ArrayList
            $currentWords = 0
        }

        [void]$currentChunk.Add($entry)
        $currentWords += $entry.Words
    }

    if ($currentChunk.Count -gt 0) {
        [void]$chunks.Add($currentChunk)
    }

    # The unary comma keeps the outer list intact across the return boundary.
    # Without it, a single-chunk result unrolls into a flat list of entries.
    return ,$chunks
}

function Invoke-CompactFolder {
    param(
        [Parameter(Mandatory)]
        [System.IO.DirectoryInfo]$Folder,

        [Parameter(Mandatory)]
        [int]$MaximumWords,

        [switch]$Preview
    )

    # Captured once and never reassigned. This is the fix for the original bug:
    # PoseSearch always yields PoseSearch.md, never a nested folder's name.
    $sourceName      = $Folder.Name
    $sourcePath      = $Folder.FullName
    $outputDirectory = $Folder.Parent.FullName

    $markdownFiles = @(
        Get-ChildItem -LiteralPath $sourcePath -Filter "*.md" -File -Recurse |
        Sort-Object FullName
    )

    if ($markdownFiles.Count -eq 0) {
        Write-Host "[SKIP] No Markdown files found: $sourcePath" -ForegroundColor DarkYellow

        return [PSCustomObject]@{
            Folder  = $sourceName
            Status  = "No Markdown files"
            Files   = 0
            Outputs = 0
        }
    }

    $entries = New-Object System.Collections.ArrayList

    foreach ($file in $markdownFiles) {
        $content = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8

        if ($null -eq $content) {
            $content = ""
        }

        # Name each entry by its path relative to the source folder so that
        # same-named files in different subfolders stay distinguishable.
        $relativePath = $file.FullName.Substring($sourcePath.Length).TrimStart('\', '/')
        $relativeName = $relativePath -replace '\.md$', ''

        $entry = [PSCustomObject]@{
            Name    = $relativeName
            Content = $content
            Words   = Get-WordCount -Text $content
        }

        [void]$entries.Add($entry)
    }

    $chunks           = Split-IntoChunks -Entries $entries -MaximumWords $MaximumWords
    $useNumberedNames = $chunks.Count -gt 1

    $outputPaths = @(
        for ($index = 0; $index -lt $chunks.Count; $index++) {
            $outputFileName = if ($useNumberedNames) {
                "{0}_{1}.md" -f $sourceName, ($index + 1)
            }
            else {
                "{0}.md" -f $sourceName
            }

            Join-Path $outputDirectory $outputFileName
        }
    )

    $existingOutputs = @(
        $outputPaths | Where-Object { Test-Path -LiteralPath $_ }
    )

    if ($existingOutputs.Count -gt 0) {
        Write-Host "[SKIP] Output already exists for $sourceName" -ForegroundColor Yellow

        foreach ($existingOutput in $existingOutputs) {
            Write-Host "       $existingOutput" -ForegroundColor Yellow
        }

        return [PSCustomObject]@{
            Folder  = $sourceName
            Status  = "Output exists"
            Files   = $markdownFiles.Count
            Outputs = $chunks.Count
        }
    }

    $totalWords = ($entries | Measure-Object -Property Words -Sum).Sum

    if ($Preview) {
        Write-Host "[DRY RUN] $sourceName" -ForegroundColor Cyan
        Write-Host "  Source files : $($markdownFiles.Count)"
        Write-Host "  Words        : $totalWords"
        Write-Host "  Output files : $($outputPaths.Count)"

        foreach ($outputPath in $outputPaths) {
            Write-Host "  -> $outputPath" -ForegroundColor Yellow
        }

        Write-Host "  Would remove : $sourcePath" -ForegroundColor DarkYellow
        Write-Host ""

        return [PSCustomObject]@{
            Folder  = $sourceName
            Status  = "Dry run"
            Files   = $markdownFiles.Count
            Outputs = $chunks.Count
        }
    }

    $writtenFiles = New-Object System.Collections.ArrayList
    $utf8NoBom    = New-Object System.Text.UTF8Encoding($false)

    try {
        for ($index = 0; $index -lt $chunks.Count; $index++) {
            $title = if ($useNumberedNames) {
                "{0} (part {1} of {2})" -f $sourceName, ($index + 1), $chunks.Count
            }
            else {
                $sourceName
            }

            $markdown = New-MarkdownDocument -Title $title -Entries $chunks[$index]

            [System.IO.File]::WriteAllText($outputPaths[$index], $markdown, $utf8NoBom)

            [void]$writtenFiles.Add($outputPaths[$index])

            Write-Host "Created: $($outputPaths[$index])" -ForegroundColor Green
        }

        Remove-Item -LiteralPath $sourcePath -Recurse -Force

        Write-Host "Removed: $sourcePath" -ForegroundColor DarkGreen
        Write-Host ""

        return [PSCustomObject]@{
            Folder  = $sourceName
            Status  = "Compacted"
            Files   = $markdownFiles.Count
            Outputs = $chunks.Count
        }
    }
    catch {
        Write-Host "[ERROR] Failed to compact $sourceName" -ForegroundColor Red
        Write-Host $_.Exception.Message -ForegroundColor Red

        # Roll back partial outputs; the source folder is never touched here.
        foreach ($writtenFile in $writtenFiles) {
            if (Test-Path -LiteralPath $writtenFile) {
                Remove-Item -LiteralPath $writtenFile -Force
            }
        }

        return [PSCustomObject]@{
            Folder  = $sourceName
            Status  = "Failed"
            Files   = $markdownFiles.Count
            Outputs = 0
        }
    }
}

if (-not (Test-Path -LiteralPath $ParentFolder -PathType Container)) {
    throw "ParentFolder does not exist or is not a directory: $ParentFolder"
}

$ParentFolder = (Resolve-Path -LiteralPath $ParentFolder).Path

if ($FolderName) {
    $selectedPath = Join-Path $ParentFolder $FolderName

    if (-not (Test-Path -LiteralPath $selectedPath -PathType Container)) {
        throw "Folder not found: $selectedPath"
    }

    $targetFolders = @(Get-Item -LiteralPath $selectedPath)
}
else {
    $targetFolders = @(
        Get-ChildItem -LiteralPath $ParentFolder -Directory | Sort-Object Name
    )
}

if ($targetFolders.Count -eq 0) {
    Write-Host "[WARN] No child folders found under $ParentFolder" -ForegroundColor Yellow
    return
}

Write-Host ""
Write-Host "Parent folder      : $ParentFolder" -ForegroundColor Cyan
Write-Host "Child folders      : $($targetFolders.Count)" -ForegroundColor Cyan
Write-Host "Maximum words/file : $MaxWordsPerFile" -ForegroundColor Cyan
Write-Host "Dry run            : $([bool]$DryRun)" -ForegroundColor Cyan
Write-Host ""

$results = @(
    foreach ($targetFolder in $targetFolders) {
        Invoke-CompactFolder `
            -Folder $targetFolder `
            -MaximumWords $MaxWordsPerFile `
            -Preview:$DryRun
    }
)

Write-Host ""
Write-Host "Summary" -ForegroundColor Cyan
Write-Host "-------" -ForegroundColor Cyan

$results | Format-Table Folder, Status, Files, Outputs -AutoSize
