"""
clear_hardcoded_numbers.py

Clears all hard-coded numeric values from a Google Sheet while
preserving formulas, text labels, and empty cells.

Requires: ~/.config/gspread/credentials.json
  - OAuth Desktop client credentials from Google Cloud Console
  - Google Sheets API must be enabled on the project

First run will open a browser (or print a URL to paste) for one-time login.
Token is cached at ~/.config/gspread/authorized_user.json for future runs.

Usage:
    python clear_hardcoded_numbers.py
"""

import re
import gspread
from gspread.utils import rowcol_to_a1

SPREADSHEET_ID = "1BNZp084Obw688-4Z45nQ-DV08Hrdzh30z-H_lWSvCE0"

# Matches hard-coded numbers in common spreadsheet formats:
#   12,807.30   0.00   -500   (1,234.56)   (22,318.04)
NUMBER_RE = re.compile(
    r"^\s*-?[\d,]+(\.\d+)?\s*$"           # positive or negative: 12,807.30  -500
    r"|^\s*\([\d,]+(\.\d+)?\)\s*$"        # accounting negative: (1,234.56)
)


def is_hardcoded_number(value) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    if not s or s.startswith("="):
        return False
    return bool(NUMBER_RE.match(s))


def main():
    print("Authenticating with Google...")
    print("(On WSL: if no browser opens, copy the URL printed below into your Windows browser)\n")

    gc = gspread.oauth()
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    print(f"Opened: {spreadsheet.title}\n")

    total_cleared = 0

    for sheet in spreadsheet.worksheets():
        print(f"Sheet: '{sheet.title}'")

        # FORMULA render option returns raw =formulas so we don't mistake them for values
        all_values = sheet.get_all_values(value_render_option="FORMULA")

        cells_to_clear = []
        for row_idx, row in enumerate(all_values, start=1):
            for col_idx, cell_value in enumerate(row, start=1):
                if is_hardcoded_number(cell_value):
                    cells_to_clear.append(rowcol_to_a1(row_idx, col_idx))

        if cells_to_clear:
            # Send in chunks of 500 to stay within Sheets API limits
            chunk_size = 500
            for i in range(0, len(cells_to_clear), chunk_size):
                sheet.batch_clear(cells_to_clear[i : i + chunk_size])
            print(f"  Cleared {len(cells_to_clear)} cell(s)")
            total_cleared += len(cells_to_clear)
        else:
            print("  Nothing to clear")

    print(f"\nDone. Total cells cleared: {total_cleared}")


if __name__ == "__main__":
    main()
