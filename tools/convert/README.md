# HTML to Markdown/PDF Converters

This directory contains tools for converting HTML documentation to other formats.

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
cd a:\Projects\ColossusRising\WeekendWarriorDevTools\tools\convert

# Convert to Markdown
.\convert_html_to_markdown.ps1

# Convert to PDF
.\convert_html_to_pdf.ps1
```
