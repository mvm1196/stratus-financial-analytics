"""
clear_rows_104_down.py

Clears all hard-coded numeric values from row 104 downward in a specific
Google Sheet tab, while preserving formulas, text labels, and empty cells.

Target:
    Spreadsheet ID : 1R1ftAvLmNVrcgxP9Xmn971RFPCbAbneGCyc5IchNzP0
    Sheet gid      : 442715932
    Rows cleared   : 104 and below

Requires: ~/.config/gspread/credentials.json
First run will print a URL to paste into your Windows browser for one-time auth.
Token is cached at ~/.config/gspread/authorized_user.json for future runs.
"""

import re
import gspread
from gspread.utils import rowcol_to_a1

SPREADSHEET_ID = "1R1ftAvLmNVrcgxP9Xmn971RFPCbAbneGCyc5IchNzP0"
TARGET_GID = 442715932
START_ROW = 104  # first row to process (1-based)

NUMBER_RE = re.compile(
    r"^\s*-?[\d,]+(\.\d+)?\s*$"
    r"|^\s*\([\d,]+(\.\d+)?\)\s*$"
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
    print("(On WSL: if no browser opens, copy the URL into your Windows browser)\n")

    gc = gspread.oauth()
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    print(f"Opened: {spreadsheet.title}\n")

    # Find the target worksheet by gid
    target_sheet = None
    for ws in spreadsheet.worksheets():
        if ws.id == TARGET_GID:
            target_sheet = ws
            break

    if target_sheet is None:
        print(f"ERROR: No worksheet found with gid {TARGET_GID}")
        return

    print(f"Sheet: '{target_sheet.title}' (gid={TARGET_GID})")
    print(f"Scanning from row {START_ROW} downward...\n")

    all_values = target_sheet.get_all_values(value_render_option="FORMULA")

    cells_to_clear = []
    for row_idx, row in enumerate(all_values, start=1):
        if row_idx < START_ROW:
            continue
        for col_idx, cell_value in enumerate(row, start=1):
            if is_hardcoded_number(cell_value):
                cells_to_clear.append(rowcol_to_a1(row_idx, col_idx))

    if cells_to_clear:
        chunk_size = 500
        for i in range(0, len(cells_to_clear), chunk_size):
            target_sheet.batch_clear(cells_to_clear[i : i + chunk_size])
        print(f"Cleared {len(cells_to_clear)} cell(s).")
    else:
        print("Nothing to clear — no hard-coded numbers found in row 104+.")

    print("\nDone.")


if __name__ == "__main__":
    main()
