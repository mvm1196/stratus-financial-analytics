# Stratus Financial Analytics

A reusable tool that reads board-level financial reports (PDF) and generates clean, structured Markdown summaries using Claude AI.

## What it does

Takes a P&L or board report PDF, uploads it to Claude via the Anthropic Files API, and outputs a formatted Markdown summary with YAML frontmatter — ready for Obsidian, Notion, or any Markdown-based system.

## Requirements

- Python 3.8+
- `ANTHROPIC_API_KEY` environment variable set
- Dependencies: `pip install -r requirements.txt`

## Usage

```bash
python summarize_pdf_report.py [PDF_PATH] [OUTPUT_DIR]
```

Both arguments are optional. Defaults:
- `PDF_PATH` — configured in the script for the pilot client
- `OUTPUT_DIR` — `30 - Meetings/_Unfiled/` inside the Jarvis Obsidian vault

## Output format

Each summary is saved as a `.md` file with:
- YAML frontmatter (date, project, type, tags)
- Report period
- Revenue and expense line items with prior-year comparison and favorable/unfavorable flag
- Net income/loss (period + YTD)
- Key variances
- Notable items
- Open items / TBDs

## Architecture

- Language: Python
- AI: Claude Opus 4.8 via [Anthropic Files API](https://platform.claude.com/docs/en/build-with-claude/files)
- Input: Any board-level financial report PDF
- Output: Markdown (`.md`) with YAML frontmatter
