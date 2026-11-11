"""Parse a Fidelity monthly "Investment Report" PDF into canonical rows.

Output is two lists of dicts matching the canonical CSV schema in schema.py:
one row per account per statement period, and one row per holding.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pdfplumber

ASSET_CLASSES = [
    "Core Account",
    "Mutual Funds",
    "Exchange Traded Products",
    "Stocks",
    "Bonds",
    "Options",
    "Other",
]
SUBCLASS_RE = re.compile(
    r"^(?:[A-Z][\w/&-]*\s){0,3}(?:Funds?|Stocks?|STOCKS?|Bonds|Securities|Deposit|Deposits)$"
)
PERIOD_RE = re.compile(
    r"([A-Z][a-z]+) (\d{1,2})(?:, (\d{4}))?\s*[–—-]\s*([A-Z][a-z]+) (\d{1,2}), (\d{4})"
)
ACCOUNT_RE = re.compile(r"Account (?:# )?([A-Z0-9]{1,4}-?\d{5,9})\b")
NUM_RE = re.compile(r"^[-−]?\$?[-−]?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?[A-Za-z]?$")
DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
SYMBOL_RE = re.compile(r"\(([A-Z][A-Z0-9.]{0,6})\)")
CUSIP_RE = re.compile(r"CUSIP:\s*([0-9A-Z]{9})")
DASHES = {"—", "–", "-", "--"}

SUMMARY_FIELDS = {
    "beginning_value": ("Beginning Account Value",),
    "additions": ("Additions", "Contributions"),
    "subtractions": ("Subtractions", "Distributions"),
    "change_in_investment_value": ("Change in Investment Value",),
    "ending_value": ("Ending Account Value",),
}


def _num(tok: str) -> float | None:
    """'$8,247.50t' -> 8247.5 ; non-numeric -> None."""
    if not NUM_RE.match(tok) or not any(c.isdigit() for c in tok):
        return None
    neg = tok.count("-") + tok.count("−") == 1
    digits = re.sub(r"[^\d.]", "", tok)
    return -float(digits) if neg else float(digits)


def _first_amount(rest: str) -> float | None:
    """First 'this period' amount after a summary label; a dash means zero."""
    for tok in rest.replace("*", " ").split():
        if tok in DASHES:
            return 0.0
        val = _num(tok)
        if val is not None:
            return val
    return None


def _parse_period(text: str) -> tuple[date, date]:
    m = PERIOD_RE.search(text)
    if not m:
        raise ValueError("could not find the statement period (e.g. 'July 1 – July 31, 2015')")
    m1, d1, y1, m2, d2, y2 = m.groups()
    end = datetime.strptime(f"{m2} {d2} {y2}", "%B %d %Y").date()
    start = datetime.strptime(f"{m1} {d1} {y1 or y2}", "%B %d %Y").date()
    return start, end


def _find_row(tokens: list[str], is_bond: bool):
    """Locate (quantity, price, value) as three consecutive numbers where
    quantity x price == value. That arithmetic check is what separates a real
    holding row from numbers that are part of the description."""
    nums = [None if "%" in t else _num(t) for t in tokens]
    for i in range(1, len(tokens) - 2):
        q, p, v = nums[i], nums[i + 1], nums[i + 2]
        if q is None or p is None or v is None or q == 0:
            continue
        tol = max(abs(v) * 0.01, 1.0)
        if abs(q * p - v) <= tol or (is_bond and abs(q * p / 100 - v) <= tol):
            return i, q, p, v
    return None


def parse_statement(pdf_path: str | Path) -> tuple[list[dict], list[dict], list[str]]:
    pdf_path = Path(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages]

    period_start, period_end = _parse_period("\n".join(pages[:2]))
    base = {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "source_file": pdf_path.name,
    }
    accounts: dict[str, dict] = {}
    holdings: list[dict] = []
    warnings: list[str] = []
    asset_class: dict[str, str | None] = {}   # persists across "(continued)" pages
    subclass: dict[str, str | None] = {}

    for text in pages:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        acct = None
        in_holdings = False
        current: dict | None = None

        for idx, line in enumerate(lines):
            m = ACCOUNT_RE.search(line)
            if m and (line.startswith(("Account", "Holdings", "Activity")) or "Account Value" in line
                      or "(continued)" in line or "Estimated Cash Flow" in line):
                acct = m.group(1)
                if acct not in accounts:
                    accounts[acct] = {**base, "account_number": acct, "account_name": ""}
                if "Account Value:" in line and idx + 1 < len(lines):
                    accounts[acct]["account_name"] = lines[idx + 1]
            if re.match(r"^Holdings\b", line):
                in_holdings = True
                continue
            if acct is None:
                continue

            # ---- account summary ("Account Value" page) ----
            if not in_holdings:
                for field, labels in SUMMARY_FIELDS.items():
                    for label in labels:
                        if line.startswith(label) and field not in accounts[acct]:
                            val = _first_amount(line[len(label):])
                            if val is not None:
                                accounts[acct][field] = val
                continue

            # ---- holdings tables ----
            if re.match(r"^Total (Holdings|Value|Market Value)\b", line):
                in_holdings = False
                current = None
                continue
            header = next((a for a in ASSET_CLASSES if line == a or line.startswith(a + " (")
                           or (a == "Exchange Traded Products" and line.startswith(a))), None)
            if header:
                asset_class[acct], subclass[acct], current = header, None, None
                continue
            if line.startswith("Total "):
                subclass[acct], current = None, None
                continue
            if line.startswith(("Description", "Price ", "Total Unrealized", "Percent of")):
                continue
            if SUBCLASS_RE.match(line) and "(" not in line:
                subclass[acct], current = line.title(), None
                continue

            tokens = line.split()
            is_bond = asset_class.get(acct) == "Bonds"
            hit = _find_row(tokens, is_bond) if len(tokens) >= 4 else None
            if hit:
                i, qty, price, value = hit
                desc_tokens = tokens[:i]
                maturity = ""
                if desc_tokens and DATE_RE.match(desc_tokens[-1]) and is_bond:
                    maturity = desc_tokens.pop()
                if desc_tokens and re.fullmatch(r"\d+%", desc_tokens[-1]):
                    desc_tokens.pop()  # 529 "percent of total value" column
                rest = [t for t in tokens[i + 3:] if not re.fullmatch(r"[A-Za-z]", t)]
                cost = _num(rest[0]) if rest else None
                gain = _num(rest[1]) if len(rest) > 1 and "%" not in rest[1] else None
                income = _num(rest[2]) if len(rest) > 2 and "%" not in rest[2] else None
                current = {
                    **base,
                    "account_number": acct,
                    "asset_class": asset_class.get(acct) or "Other",
                    "asset_subclass": subclass.get(acct) or "",
                    "symbol": "",
                    "cusip": "",
                    "description": " ".join(desc_tokens),
                    "maturity": maturity,
                    "quantity": qty,
                    "price": price,
                    "market_value": value,
                    "cost_basis": cost,
                    "unrealized_gain": gain,
                    "est_annual_income": income,
                }
                holdings.append(current)
            elif current is not None:
                cm = CUSIP_RE.search(line)
                if cm:
                    current["cusip"] = cm.group(1)
                elif not line.startswith(("—", "–", "ISIN", "SEDOL", "Int.", "Fixed", "Semi-", "Based on")) \
                        and len(line) > 1 and not re.search(r"\d+ of \d+$", line):
                    current["description"] += " " + line
            elif sum(_num(t) is not None for t in tokens) >= 4:
                warnings.append(f"unparsed holdings line ({acct}): {line}")

    for h in holdings:
        syms = SYMBOL_RE.findall(h["description"])
        if syms:
            h["symbol"] = syms[-1]
            h["description"] = SYMBOL_RE.sub("", h["description"])
        h["description"] = re.sub(r"\s+", " ", h["description"]).strip()
        h["account_name"] = accounts[h["account_number"]].get("account_name", "")

    account_rows = []
    for acct, row in accounts.items():
        missing = [f for f in ("beginning_value", "ending_value", "change_in_investment_value") if f not in row]
        if missing:
            warnings.append(f"account {acct}: missing {', '.join(missing)} - skipped")
            continue
        row.setdefault("additions", 0.0)
        row.setdefault("subtractions", 0.0)
        account_rows.append(row)
        total = sum(h["market_value"] for h in holdings if h["account_number"] == acct)
        if abs(total - row["ending_value"]) > max(1.0, 0.005 * abs(row["ending_value"])):
            warnings.append(
                f"account {acct}: holdings sum {total:,.2f} != ending value {row['ending_value']:,.2f}"
            )
    if not account_rows:
        warnings.append("no accounts found - is this a Fidelity Investment Report?")
    return account_rows, holdings, warnings
