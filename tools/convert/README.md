# Document Format Converters

This directory contains tools for converting documentation between formats.

## `generated-api` layout

The API doc tree keeps each format in its own folder, so a PDF render never gets mistaken for
a source document (and never gets fed back into a converter or a compaction pass):

```
Documentation/generated-api/
├── markdown/          # source of record
│   ├── source/        # from convert-cpp-to-markdown.ps1 -ScanAll
│   ├── content/       # from convert-cpp-to-markdown.ps1 -ScanContent
│   └── unreal/        # from convert-udn-to-markdown.ps1
└── pdf/               # derived output, mirrors markdown/ exactly
    ├── source/
    ├── content/
    └── unreal/
```

`pdf/` is git-ignored in that repo: it is reproducible from `markdown/`, and single compacted
chunks render to PDFs past GitHub's 100 MB per-file limit.

---

## `convert-markdown-to-pdf.ps1`

Converts a markdown tree to PDF, writing each `.pdf` at the same relative path under the output
root so the two trees stay parallel.

### Features
- **Mirrors the folder structure** of the input tree
- **Print-tuned CSS**: GFM tables with headers repeated across page breaks, wrapped code blocks,
  page numbers in the footer, long asset paths broken instead of clipped
- **One browser for the whole run** (`puppeteer-core` + installed Edge/Chrome), so thousands of
  files cost milliseconds each instead of a process launch apiece
- **Incremental**: a PDF at least as new as its `.md` is skipped unless `-Force`
- **Auto-installs dependencies** via npm (`marked`, `puppeteer-core`)

### Usage

```powershell
# Default: Documentation\generated-api\markdown -> Documentation\generated-api\pdf
.\convert-markdown-to-pdf.ps1

# Preview the file list without launching a browser
.\convert-markdown-to-pdf.ps1 -DryRun

# Smoke-test styling on a handful of files
.\convert-markdown-to-pdf.ps1 -Max 5 -Force

# One subtree, custom destination
.\convert-markdown-to-pdf.ps1 -InputDir "..\..\..\Documentation\generated-api\markdown\source" `
                              -OutputDir "..\..\..\Documentation\generated-api\pdf\source"

# Skip the heaviest content, restyle, tune throughput
.\convert-markdown-to-pdf.ps1 -Exclude "content/Graph/**","**/Deprecated/**"
.\convert-markdown-to-pdf.ps1 -Css ".\my-print.css" -Concurrency 8
```

### Key parameters

| Parameter | Purpose |
|-----------|---------|
| `-InputDir` / `-OutputDir` | Markdown root / PDF root. Default to the `generated-api` split layout above |
| `-Force` | Re-render everything, ignoring up-to-date PDFs |
| `-DryRun` | List what would be written; no browser is launched |
| `-Max <n>` | Stop after n files — use it before committing to a full run |
| `-Exclude <globs>` | Input-relative path globs (forward slashes), e.g. `content/Graph/**` |
| `-Concurrency <n>` | Pages printed in parallel (default 4) |
| `-TimeoutMs <ms>` | Per-file layout/print budget (default 300000) |
| `-Css <path>` | Stylesheet appended after the built-in print CSS |
| `-BrowserPath <path>` | Override browser autodetection (Edge, then Chrome) |

### Scale

PDFs run roughly 10-20x the size of their markdown. Compacted chunks are the extreme case: a
4.9 MB merged `.md` prints in ~45s to a ~114 MB PDF. Converting **uncompacted** per-class
markdown gives far more usable documents, and `-Exclude` keeps the giant merged content chunks
out of a run.

### Requirements

- **Node.js** (https://nodejs.org/)
- **Microsoft Edge** or **Google Chrome** (any Chromium build; autodetected)
- **npm** packages: `marked`, `puppeteer-core` — auto-installed on first run

---

## `convert-udn-to-markdown.ps1`

Converts Unreal Engine's UDN documentation/tooltip source (`Engine\Documentation\Source`,
shipped with every engine install) to markdown, mirroring the source's folder structure under
`Documentation/generated-api/markdown/unreal/`.

UDN is Epic's bracket-tag markup that predates the current docs site - it's the same content
that backs in-editor tooltips. This is a pure-PowerShell parser (no Node/npm dependency): it
strips the `Key: Value` header block into YAML front matter, turns each named
`[EXCERPT:Name]`/`[VAR:Name]` fragment into its own heading, renders `[REGION:tip]`-style callout
boxes as blockquotes, drops author-only `[COMMENT:...]` blocks, and unwraps
`[PUBLISH:Rocket]`/`[PUBLISH:Licensee]` distribution-channel blocks in place. Everything else
(bold, bullets, `---` rules, images, links) is already valid markdown and passes through as-is.
Referenced local images are copied alongside their `.md` (including the `Images\` sibling-folder
convention most of the source screenshots use) so the generated tree has working image links on
its own.

### Features
- **Pure PowerShell** - no Node.js/npm dependency, unlike the other converters here
- **Mirrors the folder structure** of `Engine\Documentation\Source`
- **English by default**: only `*.INT.udn` is converted; `-Locales INT,CHN,...` adds Epic's
  parallel .CHN/.JPN/.KOR translations of the same content
- **Incremental**: markdown at least as new as its `.udn` is skipped unless `-Force`
- **Image handling**: copies referenced screenshots next to the generated `.md`, rewriting the
  link if the image was only found via the `Images\` sibling-folder convention

### Usage

```powershell
# Default: <EnginePath>\Engine\Documentation\Source -> Documentation\generated-api\markdown\unreal
.\convert-udn-to-markdown.ps1

# Preview the file list without writing anything
.\convert-udn-to-markdown.ps1 -DryRun

# Also pull the Chinese/Japanese/Korean translations
.\convert-udn-to-markdown.ps1 -Locales INT,CHN,JPN,KOR

# Point at a different engine install, re-convert everything
.\convert-udn-to-markdown.ps1 -EnginePath "D:\UE_5.4" -Force
```

### Key parameters

| Parameter | Purpose |
|-----------|---------|
| `-EnginePath` | Engine install root. Defaults to `A:\GE\UE_5.8` |
| `-SourceDir` | UDN source root. Defaults to `<EnginePath>\Engine\Documentation\Source` |
| `-OutputDir` | Markdown output root. Defaults to `Documentation\generated-api\markdown\unreal` |
| `-Locales` | Locale suffixes to convert. Defaults to `@('INT')` |
| `-Exclude <globs>` | Source-relative path globs to skip, e.g. `"Shared/Types/**"` |
| `-Max <n>` | Stop after n conversions - use it before committing to a full run |
| `-Force` | Re-convert everything, ignoring up-to-date markdown |
| `-DryRun` | List what would be written; nothing is read or copied |

### Requirements

- None beyond Windows PowerShell 5.1 and a local Unreal Engine install.

---

## `convert_html_to_markdown.ps1`

Converts HTML files to beautifully formatted Markdown using the Turndown library.

### Features
- **GitHub Flavored Markdown** support (tables, strikethrough, task lists)
- **Structured output** with YAML front matter metadata
- **Preserves formatting**: headings, links, images, code blocks, lists
- **Directory structure** mirrored in output
- **Auto-installs dependencies** via npm

### Usage

```powershell
# Default: converts from Documentation folder
.\convert_html_to_markdown.ps1

# Specify custom HTML directory
.\convert_html_to_markdown.ps1 -HtmlDirectory "C:\path\to\html\docs"

# Force conversion even if dependencies fail
.\convert_html_to_markdown.ps1 -Force
```

### Output

- **Location**: `<HtmlDirectory>/markdown/`
- **Format**: Markdown (.md) files with YAML front matter
- **Structure**: Mirrors the source HTML directory structure

### Example Output

```markdown
---
title: Getting Started
source: docs/getting-started.html
converted_at: 2026-06-21T14:30:00.000Z
---

# Getting Started

This is the converted content...
```

### Requirements

- **Node.js** (https://nodejs.org/)
- **npm** packages: `turndown`, `turndown-plugin-gfm`
  - Auto-installed on first run

---

## `convert_html_to_pdf.ps1`

Converts HTML files to PDF using Microsoft Edge headless mode.

### Usage

```powershell
# Default: converts from Documentation folder
.\convert_html_to_pdf.ps1

# Specify custom HTML directory
.\convert_html_to_pdf.ps1 -HtmlDirectory "C:\path\to\html\docs"

# Specify Edge location (if not in default path)
.\convert_html_to_pdf.ps1 -EdgePath "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

### Requirements

- **Microsoft Edge** (https://www.microsoft.com/en-us/edge)

---

## Quick Start

```powershell
cd C:\MyProject\WeekendWarriorDevTools\tools\convert

# Convert to Markdown
.\convert_html_to_markdown.ps1

# Convert to PDF
.\convert_html_to_pdf.ps1
```
