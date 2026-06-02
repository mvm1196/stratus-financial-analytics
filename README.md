# Stratus Financial Analytics

A collection of Python tools for financial reporting automation at Stratus BPM. Reads QuickBooks exports and board-level financial PDFs, writes actuals into Google Sheets, and generates structured Markdown summaries using Claude AI.

## Scripts

### `populate_wcgc_actuals.py`

Reads Jan–Dec monthly P&L source files and writes actuals into the WCGC 2025 Budget Google Sheet.

- **xlsx months** (Jan, Feb, Mar, Nov): reads transaction-level P&L Detail exports from QuickBooks, sums by account category
- **PDF months** (Apr–Oct, Dec): parses the monthly "P&L vs Prior Year" PDF, disambiguates current-period vs prior-year columns
- Handles split accounts across months (e.g. Direct Deposit Fees + Payroll Processing, Accounting + Tax/CPA Services, Meals + Travel)
- Writes via gspread with batch updates

**Auth:** requires `~/.config/gspread/credentials.json` (OAuth Desktop client, Google Sheets API). First run prints a URL for one-time browser auth; token is cached afterward.

```bash
python populate_wcgc_actuals.py
```

---

### `summarize_pdf_report.py`

Reads one or more board-level financial PDFs, uploads them to Claude via the Anthropic Files API, and generates a structured analytical Markdown summary.

```bash
# Process all PDFs in a folder
python summarize_pdf_report.py "/path/to/folder"

# Pass explicit files
python summarize_pdf_report.py file1.pdf file2.pdf file3.pdf

# Specify output directory as last argument
python summarize_pdf_report.py "/path/to/folder" "/path/to/output/"
```

Output is a `.md` file covering: YTD and current-month P&L vs prior year, balance sheet snapshot, and a narrative summary with variance context. Saved to the configured output directory (default: Jarvis Obsidian vault `_Unfiled` folder).

**Requires:** `ANTHROPIC_API_KEY` environment variable.

---

### `clear_hardcoded_numbers.py`

Clears all hard-coded numeric values from every sheet in a Google Sheets workbook, preserving formulas, text labels, and formatting. Used to reset a budget template before re-use.

```bash
python clear_hardcoded_numbers.py
```

---

### `clear_rows_104_down.py`

Targeted variant of the above — clears hard-coded numbers only from row 104 downward in a specific worksheet tab (the actuals input section of the WCGC budget template).

```bash
python clear_rows_104_down.py
```

---

## Requirements

```bash
pip install -r requirements.txt
```

- Python 3.11+
- `anthropic` — Claude API client (for `summarize_pdf_report.py`)
- `gspread` — Google Sheets API client (for `populate_wcgc_actuals.py`, `clear_*.py`)
- `openpyxl` — reads QuickBooks xlsx exports
- `pdfplumber` — extracts text from financial PDFs

## Architecture

| Script | Input | Output | AI |
|---|---|---|---|
| `populate_wcgc_actuals.py` | QB xlsx + P&L PDFs | Google Sheet (gspread) | None |
| `summarize_pdf_report.py` | Board report PDFs | Markdown `.md` file | Claude Opus 4.8 |
| `clear_hardcoded_numbers.py` | Google Sheet | Google Sheet | None |
| `clear_rows_104_down.py` | Google Sheet | Google Sheet | None |
