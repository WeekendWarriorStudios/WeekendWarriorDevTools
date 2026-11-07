param(
    [Parameter(Mandatory = $true)]
    [string]$Query,

    [ValidateSet('All', 'Transcripts', 'UnrealPointers')]
    [string]$Source = 'All',

    [ValidateRange(0, 10)]
    [int]$Context = 1,

    [ValidateRange(1, 200)]
    [int]$MaxResults = 40
)

$transcriptRoot = 'C:\Users\pruss\My Drive\Documentation\YouTubeTranscripts\markdowns'
$unrealRoot = 'C:\Users\pruss\My Drive\Documentation\Unreal Engine\Markdowns'
$patterns = $Query -split '\s+' | Where-Object { $_.Length -ge 2 } | ForEach-Object { [regex]::Escape($_) }

if ($patterns.Count -eq 0) {
    throw 'Query must contain at least one searchable term.'
}

$regex = $patterns -join '|'
$results = [System.Collections.Generic.List[object]]::new()

if ($Source -in @('All', 'Transcripts')) {
    Get-ChildItem -LiteralPath $transcriptRoot -Filter '*.md' -File |
        Select-String -Pattern $regex -CaseSensitive:$false -Context $Context, $Context |
        ForEach-Object {
            $results.Add([pscustomobject]@{
                Source = 'Transcript'
                Title = [System.IO.Path]::GetFileNameWithoutExtension($_.Path)
                Path = $_.Path
                Line = $_.LineNumber
                Match = $_.Line.Trim()
                Context = (($_.Context.PreContext + $_.Context.PostContext) -join ' ').Trim()
            })
        }
}

if ($Source -in @('All', 'UnrealPointers')) {
    Get-ChildItem -LiteralPath $unrealRoot -Filter '*.gdoc' -File |
        Where-Object { $_.BaseName -match $regex } |
        ForEach-Object {
            $pointer = Get-Content -Raw -LiteralPath $_.FullName | ConvertFrom-Json -AsHashTable
            $results.Add([pscustomobject]@{
                Source = 'UnrealPointer'
                Title = $_.BaseName
                Path = $_.FullName
                Line = $null
                Match = $_.BaseName
                Context = "Google Doc ID: $($pointer['doc_id'])"
            })
        }
}

$results |
    Sort-Object Source, Title, Line -Unique |
    Select-Object -First $MaxResults |
    Format-Table Source, Title, Line, Match, Context -Wrap
