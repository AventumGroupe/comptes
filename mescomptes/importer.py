"""Lecture des relevés bancaires (Excel .xlsx/.xls, CSV) avec détection
automatique des colonnes (Crédit Mutuel et formats proches)."""

import csv
import datetime as dt
import os
import re
from html.parser import HTMLParser
from dataclasses import dataclass, field

from .db import ParsedOperation
from .normalize import strip_accents

HEADER_SCAN_ROWS = 40


class ImportError_(Exception):
    pass


@dataclass
class Mapping:
    """Correspondance des colonnes (indices à partir de 0, None = absente)."""
    header_row: int = 0
    date_col: int = None
    value_date_col: int = None
    label_cols: list = field(default_factory=list)
    amount_col: int = None
    debit_col: int = None
    credit_col: int = None
    balance_col: int = None

    def is_complete(self):
        return (self.date_col is not None and self.label_cols
                and (self.amount_col is not None or self.debit_col is not None or self.credit_col is not None))


@dataclass
class Sheet:
    name: str
    rows: list  # liste de listes de valeurs


# ------------------------------------------------------------------- lecture
def read_sheets(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    if ext == ".xls":
        return _read_xls(path)
    if ext in (".csv", ".txt"):
        return [_read_csv(path)]
    raise ImportError_(f"Format non pris en charge : {ext or 'inconnu'} (attendu : .xlsx, .xls ou .csv)")


def _read_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        sheets.append(Sheet(ws.title, _trim(rows)))
    wb.close()
    return sheets


def _read_xls(path):
    import xlrd
    try:
        book = xlrd.open_workbook(path)
    except xlrd.biffh.XLRDError:
        # Certaines banques exportent un « .xls » qui est en réalité du HTML ou du CSV.
        return [_read_csv(path)]
    sheets = []
    for sh in book.sheets():
        rows = []
        for i in range(sh.nrows):
            row = []
            for cell in sh.row(i):
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        row.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode))
                    except Exception:
                        row.append(cell.value)
                elif cell.ctype == xlrd.XL_CELL_EMPTY:
                    row.append(None)
                else:
                    row.append(cell.value)
            rows.append(row)
        sheets.append(Sheet(sh.name, _trim(rows)))
    return sheets


class _HtmlTable(HTMLParser):
    """Lecture des faux « .xls » qui sont en réalité des tableaux HTML."""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            text = " ".join("".join(self._cell).split())
            self._row.append(text or None)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _read_csv(path):
    raw = open(path, "rb").read()
    head = raw[:2000].lstrip().lower()
    if head.startswith(b"<") and b"<table" in raw[:200000].lower():
        parser = _HtmlTable()
        for enc in ("utf-8", "cp1252"):
            try:
                parser.feed(raw.decode(enc))
                break
            except UnicodeDecodeError:
                continue
        return Sheet(os.path.basename(path), _trim(parser.rows))
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") >= sample.count(",") else ","
    rows = [list(r) for r in csv.reader(text.splitlines(), delimiter=delim)]
    rows = [[(c.strip() if c.strip() != "" else None) for c in r] for r in rows]
    return Sheet(os.path.basename(path), _trim(rows))


def _trim(rows):
    """Supprime les lignes entièrement vides en fin de feuille."""
    while rows and all(v in (None, "") for v in rows[-1]):
        rows.pop()
    return rows


# ------------------------------------------------------------------ détection
def _norm_header(v):
    return re.sub(r"[^A-Z ]", " ", strip_accents(str(v or "")).upper()).strip()


def detect_mapping(rows):
    """Cherche la ligne d'en-tête et les colonnes. Retourne un Mapping (éventuellement incomplet)."""
    best = None
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        m = _mapping_from_header(row, i)
        score = sum(x is not None for x in (m.date_col, m.amount_col, m.debit_col, m.credit_col, m.balance_col))
        score += 1 if m.label_cols else 0
        if m.is_complete() and (best is None or score > best[0]):
            best = (score, m)
    if best:
        return best[1]
    return Mapping(header_row=0)


def _mapping_from_header(row, idx):
    m = Mapping(header_row=idx)
    for j, v in enumerate(row):
        h = _norm_header(v)
        if not h:
            continue
        words = h.split()
        if "VALEUR" in words and m.value_date_col is None:
            m.value_date_col = j
        elif h.startswith("DATE") and m.date_col is None:
            m.date_col = j
        elif h in ("DEBIT", "DEBITS", "MONTANT DEBIT", "DEBIT EUR", "DEBIT EUROS", "SORTIES"):
            m.debit_col = j
        elif h in ("CREDIT", "CREDITS", "MONTANT CREDIT", "CREDIT EUR", "CREDIT EUROS", "ENTREES"):
            m.credit_col = j
        elif h.startswith("MONTANT") and m.amount_col is None:
            m.amount_col = j
        elif h.startswith("SOLDE") and m.balance_col is None:
            m.balance_col = j
        elif any(h.startswith(k) for k in ("LIBELLE", "OPERATION", "DESIGNATION", "DESCRIPTION", "NATURE",
                                           "INTITULE", "DETAIL", "COMPLEMENT")):
            m.label_cols.append(j)
    if m.amount_col is not None and (m.debit_col is not None or m.credit_col is not None):
        m.amount_col = None  # débit/crédit séparés prioritaires
    return m


# ----------------------------------------------------------------- conversion
_DATE_PATTERNS = [
    (re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})"), "dmy"),
    (re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2})\b"), "dmy2"),
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})"), "ymd"),
]


def parse_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (int, float)) and 20000 < v < 80000:  # numéro de série Excel
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    for rx, kind in _DATE_PATTERNS:
        m = rx.match(s)
        if not m:
            continue
        a, b, c = (int(x) for x in m.groups())
        try:
            if kind == "dmy":
                return dt.date(c, b, a).isoformat()
            if kind == "dmy2":
                return dt.date(2000 + c, b, a).isoformat()
            return dt.date(a, b, c).isoformat()
        except ValueError:
            return None
    return None


def parse_amount(v):
    """Valeur de cellule -> centimes (int) ou None."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(round(v * 100))
    s = str(v).strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = s.replace("€", "").replace("EUR", "").replace(" ", "").replace(" ", "").replace(" ", "")
    if s.endswith("-"):
        neg, s = True, s[:-1]
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("-"):
        neg, s = not neg, s[1:]
    if not s:
        return None
    if "," in s and "." in s:
        # le dernier séparateur est le séparateur décimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    cents = int(round(float(s) * 100))
    return -cents if neg else cents


def _cell(row, j):
    return row[j] if j is not None and j < len(row) else None


def parse_operations(rows, mapping):
    """Convertit les lignes en opérations. Retourne (opérations, lignes ignorées)."""
    if not mapping.is_complete():
        raise ImportError_("Colonnes incomplètes : il faut au moins une date, un libellé et un montant.")
    ops, skipped = [], 0
    for row in rows[mapping.header_row + 1:]:
        if not row or all(v in (None, "") for v in row):
            continue
        date = parse_date(_cell(row, mapping.date_col))
        label = " ".join(str(_cell(row, j)).strip() for j in mapping.label_cols
                         if _cell(row, j) not in (None, "")).strip()
        if mapping.amount_col is not None:
            amount = parse_amount(_cell(row, mapping.amount_col))
        else:
            debit = parse_amount(_cell(row, mapping.debit_col))
            credit = parse_amount(_cell(row, mapping.credit_col))
            if debit is None and credit is None:
                amount = None
            else:
                amount = abs(credit or 0) - abs(debit or 0)
        if not date or not label or amount is None:
            skipped += 1
            continue
        ops.append(ParsedOperation(
            date=date,
            label=re.sub(r"\s+", " ", label),
            amount=amount,
            value_date=parse_date(_cell(row, mapping.value_date_col)),
            balance=parse_amount(_cell(row, mapping.balance_col)),
        ))
    return ops, skipped


def load_statement(path):
    """Lecture + détection automatique. Retourne [(Sheet, Mapping)] pour chaque feuille."""
    return [(s, detect_mapping(s.rows)) for s in read_sheets(path)]
