"""
populate_wcgc_actuals.py

Reads monthly P&L source files for WCGC and writes actuals into the
"Copy of WCGC 2025 Budget" Google Sheet (tab: 2025 Budget vs Forecast - 12 Month - WIP).

Source files (G:\\My Drive\\Syck Stratus\\Stratus Financial Analytics\\2025\\):
  - P&L Detail xlsx  (Feb, Mar, Nov): transaction-level export from QuickBooks
  - P&L vs 2024 PDF  (Apr-Oct, Dec):  monthly comparison report

Auth:
  Requires ~/.config/gspread/credentials.json (OAuth Desktop client).
  First run will print a URL to paste into your browser for one-time auth.
  Token is cached at ~/.config/gspread/authorized_user.json for future runs.

Usage:
    python populate_wcgc_actuals.py
"""

import openpyxl
import pdfplumber
import re
import gspread
from gspread.utils import rowcol_to_a1

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

BASE = "/mnt/g/My Drive/Syck Stratus/Stratus Financial Analytics/2025"

SPREADSHEET_ID = "1R1ftAvLmNVrcgxP9Xmn971RFPCbAbneGCyc5IchNzP0"
TARGET_GID = 442715932  # "2025 Budget vs Forecast - 12 Month - WIP"

# (month_label, sheet_col, source_type, source_path)
MONTHS = [
    ("Jan", 6,  "xlsx", f"{BASE}/Jan 2025/Jan 2025 P&L Detail.xlsx"),
    ("Feb", 7,  "xlsx", f"{BASE}/Feb 2025/Feb 2025 P&L Detail[9].xlsx"),
    ("Mar", 8,  "xlsx", f"{BASE}/Mar 2025/Mar 2025 P&L Detail.xlsx"),
    ("Apr", 12, "pdf",  f"{BASE}/Apr 2025/Apr 2025 P&L vs 2024.pdf"),
    ("May", 13, "pdf",  f"{BASE}/May 2025/May 2025 P&L vs 2024.pdf"),
    ("Jun", 14, "pdf",  f"{BASE}/June 2025/Jun 2025 P&L vs 2024.pdf"),
    ("Jul", 18, "pdf",  f"{BASE}/July 2025/Jul 2025 P&L vs 2024.pdf"),
    ("Aug", 19, "pdf",  f"{BASE}/Aug 2025/Aug 2025 P&L vs 2024.pdf"),
    ("Sep", 20, "pdf",  f"{BASE}/Sept 2025/Sep 2025 P&L vs 2024.pdf"),
    ("Oct", 24, "pdf",  f"{BASE}/Oct 2025/Oct 2025 P&L vs 2024.pdf"),
    ("Nov", 25, "xlsx", f"{BASE}/Nov 2025/Nov 2025 P&L Detail.xlsx"),
    ("Dec", 26, "pdf",  f"{BASE}/Dec 2025/Dec 2025 P&L vs 2024.pdf"),
]

# ---------------------------------------------------------------------------
# ROW MAP — source account name → actuals section row in the Google Sheet
#
# Rows 104+ are the actuals/forecast input section.
# Multiple source names mapping to the same row are accumulated (summed).
# ---------------------------------------------------------------------------

ROW_MAP = {
    # ── Income ───────────────────────────────────────────────────────────────
    "1-Shotgun Income":                         104,
    "2-Rifle-Pistol Income":                    105,
    "3-Membership Income":                      106,
    "4-Merch-Snacks Income":                    107,
    "6000 - Donations Inc-Other (Sq)":          110,
    "6050 - Sponsor Income":                    111,
    "Other Income (Delta Defense/CPR Income)":  112,
    # ── Cost of Goods Sold ───────────────────────────────────────────────────
    "Ammunition":                               117,
    "Merchandise":                              118,
    "Clay Targets":                             119,
    "Paper / Steel Targets":                    120,
    "Water/Snacks":                             121,
    # ── 1-Ops Expenses ───────────────────────────────────────────────────────
    "Cash (Over)/ Short":                       128,
    "Equipment Purchase":                       129,
    "Equipment Rental":                         130,
    "Event":                                    131,
    "Kitchen Supplies":                         132,
    "Membership Management":                    133,
    "Permits & Licenses":                       134,
    "Prizes":                                   135,
    "Supplies (Equipment)":                     136,
    "Safety Training":                          137,
    "Safety Training/Security":                 137,
    "Security":                                 137,  # renamed in some months
    "Uniforms":                                 139,
    # ── 2-Other Expenses ─────────────────────────────────────────────────────
    "Accounting":                               143,
    "Tax / CPA Services":                       143,  # sub-line in PDF months; accumulates into Accounting
    "Fuel/Propane":                             144,
    "Liability Insurance":                      145,
    "Repairs & Maintenance":                    146,
    "Trash":                                    147,
    "Volunteer Expense":                        148,
    # ── 3-Payroll Expense ────────────────────────────────────────────────────
    "Direct Deposit Fees":                      152,  # accumulates with Payroll Processing
    "Payroll Processing":                       152,
    "Payroll Taxes":                            153,
    "Payroll Wages":                            154,
    "Sick Pay":                                 155,
    "Workers Comp":                             156,
    "Employee Expense Reimbursement":           157,
    "Stipends/Incentives":                      157,
    # ── 4-General & Admin Expense ────────────────────────────────────────────
    "Advertising/Marketing":                    161,
    "Auto/Mileage Reimb":                       162,
    "Bank Charges":                             163,  # direct charges only; CC fees go to row 171
    "Dues & Subs":                              164,
    "Conference Expenses":                      165,
    "Donations":                                167,  # expense (not income)
    "Legal":                                    168,
    "Inspection / Compliance Fees":             169,
    "Meals":                                    170,
    "Meals/Travel":                             170,
    "Travel":                                   170,  # accumulates with Meals
    "Merchant Fees CC":                         171,
    "Office Expense":                           172,
    "Postage & Shipping":                       173,
    "Printing":                                 174,
    "Telecommunication":                        176,
    "Unsecured Property Tax":                   177,
    # ── Other Expense ────────────────────────────────────────────────────────
    "Depreciation Expense":                     196,
    # ── Other Income ─────────────────────────────────────────────────────────
    "Dividend on MM Edward Jones":              189,
    "Interest":                                 191,
    "Misc Income":                              192,
}

# xlsx "Total for X" entries that are parent-level roll-ups already captured
# by a more granular child entry in ROW_MAP — skip to avoid double-counting.
XLSX_SKIP = {
    "Tax / CPA Services",   # included in "Total for Accounting"
}

SORTED_ACCOUNTS = sorted(ROW_MAP.keys(), key=len, reverse=True)

# ---------------------------------------------------------------------------
# XLSX EXTRACTOR — transaction-level P&L Detail export
# ---------------------------------------------------------------------------

def extract_xlsx(path: str) -> dict[int, float]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    results: dict[int, float] = {}
    for row in ws.iter_rows(values_only=True):
        a = row[0]
        if not a:
            continue
        s = str(a).strip()
        if s.startswith("Total for "):
            name = s[len("Total for "):]
            if name in ROW_MAP and name not in XLSX_SKIP:
                amt = row[9]
                if amt is not None:
                    r = ROW_MAP[name]
                    results[r] = results.get(r, 0) + float(amt)
    return results


# ---------------------------------------------------------------------------
# PDF EXTRACTOR — "P&L vs Prior Year" single-month report
# ---------------------------------------------------------------------------

# Lines that start with these strings are section headers or totals — skip.
_SKIP_STARTS = (
    "Total", "NET", "GROSS", "$", "Winchester", "Profit and Loss",
    "Cash Basis", "TOTAL", "APR", "JAN", "FEB", "MAR", "MAY",
    "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "CHANGE",
    "Income", "Expenses", "Cost of Goods", "1-Ops", "2-Other",
    "3-Payroll", "4-General", "Other Income", "Other Expense", "Expense",
    # NOTE: "Bank Charges" intentionally omitted so data lines are captured
)


def _parse_current_amount(line: str, acc_len: int) -> float | None:
    """
    Extract the current-period dollar value from a P&L vs PY PDF line.

    Column layout: | Current | PY | Change | % Change |

    When current = 0:  line shows "Account PY_amt  (PY_amt)  (100%)"
                       → first two amounts are equal and opposite → return 0
    When PY = 0:       line shows "Account cur_amt  cur_amt"
                       → two equal positive amounts → return first
    Normal case:       return first amount (current period)
    """
    remainder = line[acc_len:].strip()

    # Strip percentage values so they don't pollute the number list
    remainder = re.sub(r"\([\d,]+\.?\d*\s*%\)", "", remainder)
    remainder = re.sub(r"[\d,]+\.?\d*\s*%", "", remainder)

    nums: list[float] = []
    for m in re.finditer(r"\(([\d,]+\.?\d*)\)|([\d,]+\.?\d*)", remainder):
        if m.group(1):
            nums.append(-float(m.group(1).replace(",", "")))
        else:
            v = m.group(2).replace(",", "")
            if v:
                nums.append(float(v))

    if not nums:
        return None                        # no data on this line (section header)
    if len(nums) == 1:
        return nums[0]
    if abs(nums[1] + nums[0]) < 0.02:     # second ≈ -(first) → current period = 0
        return 0.0
    return nums[0]                         # first number is always current period


def extract_pdf(path: str) -> dict[int, float]:
    all_lines: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                all_lines.extend(t.split("\n"))

    results: dict[int, float] = {}
    for line in all_lines:
        ls = line.strip()
        if not ls or any(ls.startswith(p) for p in _SKIP_STARTS):
            continue

        for acc in SORTED_ACCOUNTS:
            if not ls.startswith(acc):
                continue
            rest = ls[len(acc):]
            if rest and rest[0].isalpha():
                continue  # partial match — keep searching

            amt = _parse_current_amount(ls, len(acc))
            if amt is not None and amt != 0.0:
                r = ROW_MAP[acc]
                results[r] = results.get(r, 0) + amt
            break

    return results


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("Authenticating with Google...")
    gc = gspread.oauth()
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    target_sheet = next(
        ws for ws in spreadsheet.worksheets() if ws.id == TARGET_GID
    )
    print(f"Opened: {spreadsheet.title} → {target_sheet.title}\n")

    all_updates: list[dict] = []

    for month, col, src_type, path in MONTHS:
        extractor = extract_xlsx if src_type == "xlsx" else extract_pdf
        data = extractor(path)

        print(f"{'='*8} {month} ({src_type.upper()}) — {len(data)} cells {'='*8}")
        for row in sorted(data.keys()):
            cell = rowcol_to_a1(row, col)
            val = round(data[row], 2)
            print(f"  {cell}  row {row:3d}  {val:>12,.2f}")
            all_updates.append({"range": cell, "values": [[val]]})
        print()

    print(f"Total cells to write: {len(all_updates)}")
    print("Writing to sheet...")

    chunk_size = 500
    for i in range(0, len(all_updates), chunk_size):
        target_sheet.batch_update(
            all_updates[i : i + chunk_size],
            value_input_option="USER_ENTERED",
        )

    print(f"\nDone. {len(all_updates)} cells written.")


if __name__ == "__main__":
    main()
