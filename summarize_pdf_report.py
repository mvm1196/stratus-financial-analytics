"""
summarize_pdf_report.py

Reads one or more board-level financial report PDFs (P&L, Balance Sheet, etc.),
uploads them to Claude via the Anthropic Files API, and generates a structured
analytical Markdown summary.

Usage:
    # Pass a directory — all PDFs in the folder are processed together
    python summarize_pdf_report.py "/path/to/folder"

    # Pass one or more explicit file paths
    python summarize_pdf_report.py file1.pdf file2.pdf file3.pdf

    # Optional: add output directory as the last argument (must end in / or be an
    # existing directory that contains no .pdf extension)
    python summarize_pdf_report.py "/path/to/folder" "/path/to/output/"
"""

import sys
import os
import re
from pathlib import Path
from datetime import datetime
from typing import BinaryIO
import anthropic

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

DEFAULT_INPUT = r"/mnt/h/My Drive/WCGC/Board Reports/2026/04 - May 2026"
DEFAULT_OUTPUT_DIR = r"/mnt/g/My Drive/AI/Jarvis/30 - Meetings/_Unfiled"

SYSTEM_PROMPT = """You are a financial analyst producing board-level financial summaries \
for nonprofit organizations. You will receive one or more financial report PDFs for the \
same organization and reporting period. Produce a single unified summary.

---

ANALYTICAL STYLE REQUIREMENTS

- Write for a non-technical board audience - clear, direct, no jargon
- Every significant variance must include: dollar amount, percentage change vs prior year, \
and one sentence of analytical context (what likely drove it, or why it warrants attention)
- Express dollar variances in $K (e.g. $8.4K, -$2.0K). Use + for favorable, - for unfavorable
- Use "vs PY" for prior year comparisons
- Flag items that "warrant monitoring" or "merit review" when there is a meaningful trend or risk
- Do not speculate beyond what the data supports - use "likely", "may reflect", or "timing" \
language when the cause is inferred rather than stated
- Bullets should be tight - one item per bullet
- Do not use M-dashes in body text. Use hyphens (-) or colons (:) instead
- No filler language

---

OUTPUT STRUCTURE

Use exactly this structure. Omit any section for which no source document was provided.

[Organization Name] - Financial Summary
As of [Reporting Date]

## Section 1: FY[YY] vs FY[YY] Actuals ([Month Range] YTD)
[One opening sentence: headline Gross Profit or Net Income result and primary driver]

**Income** - $[total] ([+/-$X.XK / +/-X.X%] vs PY)
- [Line item]: [+/-$X.XK / +/-X.X%] - [one-line context]
- ...

**COGS** - $[total] ([+/-$X.XK / +/-X.X%] vs PY)
- [Line item]: [+/-$X.XK / +/-X.X%] - [one-line context]
- ...

**Expenses** - $[total] ([+/-$X.XK / +/-X.X%] vs PY)
- [Category]: [+/-$X.XK / +/-X.X%] - [one-line context]
  - [Sub-item driving the variance, if material]
- ...

**YTD Closing Line:** [One sentence bottom-line summary tying the drivers together]

---

## Section 2: Current Month Actuals ([Month Year] vs [Month Year])
[One opening sentence: headline Gross Profit or Net Income result and primary driver]

**Income** - $[total] ([+/-$X.XK / +/-X.X%] vs PY)
- [same structure as Section 1]

**COGS** - $[total] ([+/-$X.XK / +/-X.X%] vs PY)
- [same structure]

**Expenses** - $[total] ([+/-$X.XK / +/-X.X%] vs PY)
- [same structure]

**Month Closing Line:** [One sentence bottom-line summary]

---

## Section 3: Financial Position (Balance Sheet - [Date])
[One opening sentence: overall balance sheet health and direction vs PY]

**Assets** - Total Assets $[total] ([+/-$X.XK / +/-X.X%] vs PY)
- [Category]: $[total], [+/-$X.XK vs PY] - [context]
  - [Material sub-items]
- ...

**Liabilities** - Total Liabilities $[total] ([+/-$X.XK / +/-X.X%] vs PY)
- [same structure]

**Equity** - Total Equity $[total] ([+/-$X.XK vs PY])
- [Key equity line items]

---

## Section 4: Summary
[4-6 standalone paragraphs, one per major theme. Each paragraph: bold topic label, \
then 2-4 sentences of narrative. Cover: revenue trend, COGS/margin, expense discipline, \
net income position, balance sheet health. Call out any watch items or anomalies.]

**[Topic].** [Narrative.]

**[Topic].** [Narrative.]
"""

# ---------------------------------------------------------------------------
# INPUT RESOLUTION
# ---------------------------------------------------------------------------


def resolve_inputs(argv: list[str]) -> tuple[list[Path], Path]:
    """
    Returns (list_of_pdf_paths, output_dir).

    Rules:
    - If the last argument is an existing directory with no .pdf extension,
      treat it as output_dir.
    - Everything else is treated as input: a directory to scan, or explicit PDF files.
    """
    args = argv[1:]

    if not args:
        return _collect_pdfs(Path(DEFAULT_INPUT)), Path(DEFAULT_OUTPUT_DIR)

    out_dir = Path(DEFAULT_OUTPUT_DIR)
    input_args = args

    if len(args) >= 2:
        last = Path(args[-1])
        if last.suffix.lower() != ".pdf" and (last.is_dir() or str(args[-1]).endswith(("/", "\\"))):
            out_dir = last
            input_args = args[:-1]

    pdfs: list[Path] = []
    for arg in input_args:
        p = Path(arg)
        if p.is_dir():
            pdfs.extend(_collect_pdfs(p))
        elif p.suffix.lower() == ".pdf":
            pdfs.append(p)
        else:
            print(f"WARNING: Skipping '{arg}' - not a PDF or directory.")

    return pdfs, out_dir


def _collect_pdfs(directory: Path) -> list[Path]:
    pdfs = sorted(directory.glob("*.pdf"))
    if not pdfs:
        print(f"WARNING: No PDFs found in {directory}")
    return pdfs


# ---------------------------------------------------------------------------
# OUTPUT FILENAME
# ---------------------------------------------------------------------------


def derive_output_filename(pdf_paths: list[Path]) -> str:
    parents = {p.parent for p in pdf_paths}
    base = parents.pop().name if len(parents) == 1 else pdf_paths[0].stem

    year_match = re.search(r"(20\d{2})", base)
    month_map = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "may": "05", "jun": "06", "jul": "07", "aug": "08",
        "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    month_match = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b",
        base, re.IGNORECASE,
    )

    if year_match and month_match:
        date_str = f"{year_match.group(1)}-{month_map[month_match.group(1).lower()]}-01"
    else:
        date_str = datetime.today().strftime("%Y-%m-%d")

    clean = re.sub(r'[<>:"/\\|?*]', "-", base)
    clean = re.sub(r"\s+", " ", clean).strip()
    return f"{date_str} - {clean} - Financial Summary.md"


# ---------------------------------------------------------------------------
# FILES API
# ---------------------------------------------------------------------------


def upload_pdfs(client: anthropic.Anthropic, pdf_paths: list[Path]) -> list[str]:
    file_ids = []
    for path in pdf_paths:
        print(f"Uploading {path.name}...")
        with open(path, "rb") as f:
            result = client.beta.files.upload(
                file=(path.name, f, "application/pdf"),
            )
        print(f"  file_id={result.id}")
        file_ids.append(result.id)
    return file_ids


def cleanup_files(client: anthropic.Anthropic, file_ids: list[str]):
    for fid in file_ids:
        try:
            client.beta.files.delete(fid)
            print(f"Deleted {fid} from Files API.")
        except Exception as e:
            print(f"Warning: could not delete {fid}: {e}")


# ---------------------------------------------------------------------------
# GENERATION
# ---------------------------------------------------------------------------


def build_user_message(pdf_paths: list[Path], file_ids: list[str]) -> list:
    filenames = ", ".join(p.name for p in pdf_paths)
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"The following {len(pdf_paths)} financial report(s) are attached: {filenames}. "
                "Identify what each document contains (YTD P&L, current month P&L, "
                "Balance Sheet, etc.) and produce a single unified summary following "
                "the exact output structure in your instructions. "
                "Use only data present in the documents."
            ),
        }
    ]
    for fid in file_ids:
        content.append({
            "type": "document",
            "source": {"type": "file", "file_id": fid},
        })
    return content


def generate_summary(
    client: anthropic.Anthropic,
    pdf_paths: list[Path],
    file_ids: list[str],
) -> str:
    print(f"\nGenerating summary for {len(pdf_paths)} file(s) (streaming)...\n")
    chunks = []
    with client.beta.messages.stream(
        model="claude-opus-4-8",
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": build_user_message(pdf_paths, file_ids),
            }
        ],
        betas=["files-api-2025-04-14"],
    ) as stream:
        for text in stream.text_stream:
            chunks.append(text)

    print()
    return "".join(chunks)


# ---------------------------------------------------------------------------
# SAVE
# ---------------------------------------------------------------------------


def save_output(content: str, out_dir: Path, filename: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_text(content, encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main():
    pdf_paths, out_dir = resolve_inputs(sys.argv)

    if not pdf_paths:
        print("ERROR: No PDF files found. Provide a directory or explicit file paths.")
        sys.exit(1)

    missing = [p for p in pdf_paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERROR: File not found: {p}")
        print("Check that the drive is mounted (e.g. /mnt/h) and paths are correct.")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    print(f"Files to process ({len(pdf_paths)}):")
    for p in pdf_paths:
        print(f"  {p.name}")
    print(f"Output directory: {out_dir}\n")

    client = anthropic.Anthropic(api_key=api_key)
    file_ids: list[str] = []

    try:
        file_ids = upload_pdfs(client, pdf_paths)
        summary = generate_summary(client, pdf_paths, file_ids)
        filename = derive_output_filename(pdf_paths)
        out_path = save_output(summary, out_dir, filename)
        print(f"\nSummary saved to: {out_path}")
    finally:
        if file_ids:
            cleanup_files(client, file_ids)


if __name__ == "__main__":
    main()
