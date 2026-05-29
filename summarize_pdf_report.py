"""
summarize_pdf_report.py

Reads a PDF board/financial report, sends it to Claude via the Anthropic Files API,
and generates a structured Markdown summary following the Jarvis meeting/document
output conventions defined in CLAUDE.md.

Usage:
    python summarize_pdf_report.py [PDF_PATH] [OUTPUT_PATH]

    PDF_PATH defaults to the Apr 2026 P&L vs 2025 report.
    OUTPUT_PATH defaults to the _Unfiled folder in the Jarvis vault.
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

DEFAULT_PDF = r"/mnt/h/My Drive/WCGC/Board Reports/2026/04 - May 2026/Apr 2026 P&L vs 2025.pdf"
DEFAULT_OUTPUT_DIR = r"/mnt/g/My Drive/AI/Jarvis/30 - Meetings/_Unfiled"

SYSTEM_PROMPT = """You are a financial document assistant. Your job is to read board-level \
financial reports and produce a clean, structured Markdown summary suitable for an \
executive audience with no accounting background.

Rules:
- Write for a non-technical executive audience - clear, concise, no jargon
- Do not infer or speculate - only document what is explicitly stated in the document
- Mark anything still being determined as TBD
- Label scope numbers as estimates if they are presented as such
- Do not use M-dashes (—) inside body content. Use hyphens (-) or colons (:) instead
- Bullets should be tight - one idea per bullet
- No filler language or throat-clearing
- Numbers: include $ and relevant units; use "vs" for comparisons; round to nearest dollar
- If a line item is favorable vs prior year, note "(favorable)"; if unfavorable, note "(unfavorable)"

Output the summary using EXACTLY this Markdown structure (no deviations):

---
date: YYYY-MM-DD
project: [Organization Name]
type: financial-report
tags: [financial-report, board, pl]
---

# YYYY-MM-DD - [Organization] - [Report Title]

## Report Period
[Month/period covered, e.g. "April 2026 vs April 2025"]

## Summary
One or two sentences on what this report covers and the overall financial position.

## Revenue
- [Line item]: $X (vs $Y prior year) - (favorable/unfavorable)
- ...

## Expenses
- [Line item]: $X (vs $Y prior year) - (favorable/unfavorable)
- ...

## Net Income / Loss
- [Period]: $X (vs $Y prior year) - (favorable/unfavorable)
- YTD: $X (vs $Y prior year) - (favorable/unfavorable)

## Key Variances
- [Most significant items driving the difference from prior year]

## Notable Items
- [Anything flagged, one-time, or worth calling out]

## Open Items / TBDs
- [Any items marked TBD or requiring follow-up - write "None." if nothing flagged]
"""

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def resolve_paths(argv):
    pdf_path = Path(argv[1]) if len(argv) > 1 else Path(DEFAULT_PDF)
    out_dir = Path(argv[2]) if len(argv) > 2 else Path(DEFAULT_OUTPUT_DIR)
    return pdf_path, out_dir


def derive_output_filename(pdf_path: Path) -> str:
    """
    Try to extract YYYY-MM-DD and a clean title from the PDF filename.
    Falls back to today's date + stem.
    """
    stem = pdf_path.stem  # e.g. "Apr 2026 P&L vs 2025"

    # Look for a 4-digit year to anchor a date
    year_match = re.search(r"(20\d{2})", stem)
    month_map = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "may": "05", "jun": "06", "jul": "07", "aug": "08",
        "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    month_match = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b",
        stem, re.IGNORECASE
    )

    if year_match and month_match:
        year = year_match.group(1)
        month = month_map[month_match.group(1).lower()]
        date_str = f"{year}-{month}-01"
    else:
        date_str = datetime.today().strftime("%Y-%m-%d")

    # Sanitize stem for a filename
    clean = re.sub(r'[<>:"/\\|?*]', "-", stem)
    clean = re.sub(r"\s+", " ", clean).strip()

    return f"{date_str} - {clean}.md"


def upload_pdf(client: anthropic.Anthropic, pdf_path: Path) -> str:
    print(f"Uploading {pdf_path.name} to Files API...")
    with open(pdf_path, "rb") as f:
        file_id = upload_pdf_fileobj(client, pdf_path.name, f)
    print(f"  Uploaded. file_id={file_id}")
    return file_id


def upload_pdf_fileobj(client: anthropic.Anthropic, filename: str, fileobj: BinaryIO) -> str:
    """Upload PDF content from an open binary stream and return the file_id."""
    result = client.beta.files.upload(
        file=(filename, fileobj, "application/pdf"),
    )
    return result.id


def build_user_message(filename: str, file_id: str) -> list:
    return [
        {
            "type": "text",
            "text": (
                f"Please summarize the attached financial report '{filename}'. "
                "Follow the exact output structure specified in your instructions. "
                "Use only the data present in the document."
            ),
        },
        {
            "type": "document",
            "source": {"type": "file", "file_id": file_id},
        },
    ]


def summarize_file_id(client: anthropic.Anthropic, filename: str, file_id: str) -> str:
    """Generate the Markdown summary for an already-uploaded file (no console output)."""
    chunks = []
    with client.beta.messages.stream(
        model="claude-opus-4-8",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": build_user_message(filename, file_id),
            }
        ],
        betas=["files-api-2025-04-14"],
    ) as stream:
        for text in stream.text_stream:
            chunks.append(text)
    return "".join(chunks)


def generate_summary(client: anthropic.Anthropic, pdf_path: Path, file_id: str) -> str:
    print("Generating summary (streaming)...")
    summary = summarize_file_id(client, pdf_path.name, file_id)
    print(summary)
    return summary


def save_output(content: str, out_dir: Path, filename: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    out_path.write_text(content, encoding="utf-8")
    return out_path


def cleanup_file(client: anthropic.Anthropic, file_id: str):
    try:
        client.beta.files.delete(file_id)
        print(f"Deleted uploaded file {file_id} from Files API.")
    except Exception as e:
        print(f"Warning: could not delete file {file_id}: {e}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main():
    pdf_path, out_dir = resolve_paths(sys.argv)

    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}")
        print("Check that the drive is mounted (e.g. /mnt/h) and the path is correct.")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    file_id = None
    try:
        file_id = upload_pdf(client, pdf_path)
        summary = generate_summary(client, pdf_path, file_id)
        filename = derive_output_filename(pdf_path)
        out_path = save_output(summary, out_dir, filename)
        print(f"\nSummary saved to: {out_path}")
    finally:
        if file_id:
            cleanup_file(client, file_id)


if __name__ == "__main__":
    main()
