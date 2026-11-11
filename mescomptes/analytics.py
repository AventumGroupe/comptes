"""Calculs d'analyse : tableaux croisés catégories × mois, comparaisons, prévisionnel.

Convention d'affichage (« montant présenté ») :
- catégories de dépenses : montant dépensé en positif (un remboursement le diminue) ;
- catégories de revenus : montant reçu en positif ;
- mouvements internes et opérations à classer : montant signé du compte.
"""

import calendar
import datetime as dt
from dataclasses import dataclass, field

UNCATEGORIZED = None  # clé des opérations « à classer »


# ---------------------------------------------------------------------- mois
def ym(date_str):
    return date_str[:7]


def add_months(month, n):
    y, m = int(month[:4]), int(month[5:7])
    m += n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def month_range(start, end):
    out = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def month_first_day(month):
    return f"{month}-01"


def month_last_day(month):
    y, m = int(month[:4]), int(month[5:7])
    return f"{month}-{calendar.monthrange(y, m)[1]:02d}"


MONTH_NAMES = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MONTH_FULL = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
              "novembre", "décembre"]


def month_label(month, full=False):
    names = MONTH_FULL if full else MONTH_NAMES
    return f"{names[int(month[5:7]) - 1]} {month[:4]}"


def period_label(start, end):
    if start == end:
        return month_label(start, full=True)
    return f"{month_label(start, full=True)} – {month_label(end, full=True)}"


def current_month():
    return dt.date.today().strftime("%Y-%m")


# ------------------------------------------------------------------- données
def sign_for(kind):
    return -1 if kind == "depense" else 1


def raw_sums(db, start_month, end_month, by_month=True):
    """{catégorie (ou None)}: {mois: centimes signés} ou {catégorie: centimes}."""
    sql = ("SELECT category_id, substr(date,1,7) AS m, SUM(amount) FROM operations "
           "WHERE date >= ? AND date <= ? GROUP BY category_id, m")
    rows = db.conn.execute(sql, (month_first_day(start_month), month_last_day(end_month))).fetchall()
    out = {}
    for cat, m, s in rows:
        if by_month:
            out.setdefault(cat, {})[m] = out.get(cat, {}).get(m, 0) + s
        else:
            out[cat] = out.get(cat, 0) + s
    return out


@dataclass
class Node:
    label: str
    kind: str                       # revenu | depense | neutre | none | total
    cat_ids: list                   # catégories couvertes (None = à classer)
    values: dict = field(default_factory=dict)  # colonne -> montant présenté (centimes)
    children: list = field(default_factory=list)
    level: int = 1                  # 0 = section/total, 1 = catégorie, 2 = sous-catégorie
    cat_id: int = None

    def total(self, cols):
        return sum(self.values.get(c, 0) for c in cols)


def _add(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out


def _scale(d, factor):
    return {k: v * factor for k, v in d.items()}


@dataclass
class Report:
    """Structure commune aux vues : sections de catégories + lignes de total."""
    sections: list          # [(titre, kind, [Node])]
    totals: list            # [Node]
    columns: list


def build_report(db, raw, columns, include_empty=False):
    """raw : {cat_id ou None: {colonne: centimes signés}}.
    Retourne un Report avec montants présentés, agrégés par catégorie principale."""
    cats = db.categories()
    tree = db.category_tree()
    sections = {"revenu": [], "depense": [], "neutre": []}
    for top, subs in tree:
        sgn = sign_for(top.kind)
        top_vals = _scale(raw.get(top.id, {}), sgn)
        node = Node(top.name, top.kind, [top.id] + [s.id for s in subs], level=1, cat_id=top.id)
        children = []
        for s in subs:
            vals = _scale(raw.get(s.id, {}), sgn)
            if include_empty or any(vals.values()) or s.id in raw:
                children.append(Node(s.name, s.kind, [s.id], vals, level=2, cat_id=s.id))
        if top.id in raw and subs and any(top_vals.values()):
            children.insert(0, Node(f"{top.name} (sans sous-catégorie)", top.kind, [top.id], top_vals,
                                    level=2, cat_id=top.id))
        total = dict(top_vals)
        for ch in children:
            if ch.cat_id != top.id:
                total = _add(total, ch.values)
        node.values = total
        node.children = children
        if include_empty or children or any(total.values()) or top.id in raw:
            sections.setdefault(top.kind, []).append(node)

    out_sections = [("Revenus", "revenu", sections["revenu"]),
                    ("Dépenses", "depense", sections["depense"]),
                    ("Mouvements internes", "neutre", sections["neutre"])]
    uncategorized = raw.get(UNCATEGORIZED, {})
    if any(uncategorized.values()):
        out_sections.append(("À classer", "none",
                             [Node("Opérations à classer", "none", [UNCATEGORIZED], dict(uncategorized))]))

    def section_sum(kind):
        acc = {}
        for _, k, nodes in out_sections:
            if k == kind:
                for n in nodes:
                    acc = _add(acc, n.values)
        return acc

    rev, dep, neu = section_sum("revenu"), section_sum("depense"), section_sum("neutre")
    unc = dict(uncategorized)
    balance = {c: rev.get(c, 0) - dep.get(c, 0) + neu.get(c, 0) + unc.get(c, 0) for c in columns}
    totals = [
        Node("Total revenus", "total", [], rev, level=0),
        Node("Total dépenses", "total", [], dep, level=0),
        Node("Revenus − dépenses", "total", [], {c: rev.get(c, 0) - dep.get(c, 0) for c in columns}, level=0),
        Node("Variation du compte (toutes opérations)", "total", [], balance, level=0),
    ]
    return Report([s for s in out_sections if s[2]], totals, columns)


def pivot(db, start_month, end_month):
    """Tableau croisé catégories × mois."""
    months = month_range(start_month, end_month)
    return build_report(db, raw_sums(db, start_month, end_month), months)


def compare(db, period_a, period_b):
    """Compare deux périodes (tuples (mois début, mois fin)). Colonnes 'A' et 'B'."""
    a = raw_sums(db, *period_a, by_month=False)
    b = raw_sums(db, *period_b, by_month=False)
    raw = {}
    for cat in set(a) | set(b):
        raw[cat] = {"A": a.get(cat, 0), "B": b.get(cat, 0)}
    return build_report(db, raw, ["A", "B"])


def plan_vs_actual(db, start_month, end_month):
    """Prévisionnel et réalisé par catégorie et par mois.

    node.values[mois] = réalisé présenté ; node.plan[mois] = prévu.
    Pour les mouvements internes (épargne…), le montant présenté est la somme sortie du compte,
    comparable à un objectif d'épargne saisi en positif. Le prévu d'une catégorie principale est,
    pour chaque mois, sa propre valeur si elle est saisie, sinon la somme de ses sous-catégories."""
    months = month_range(start_month, end_month)
    cats = db.categories()
    raw = raw_sums(db, start_month, end_month)
    for cat, vals in raw.items():
        if cat is not None and cats.get(cat) and cats[cat].kind == "neutre":
            raw[cat] = {m: -v for m, v in vals.items()}
    report = build_report(db, raw, months, include_empty=True)
    fc = db.forecasts(start_month, end_month)

    for _, kind, nodes in report.sections:
        for node in nodes:
            node.plan = {}
            for ch in node.children:
                ch.plan = dict(fc.get(ch.cat_id, {})) if ch.cat_id != node.cat_id else {}
            own = fc.get(node.cat_id, {})
            for m in months:
                if m in own:
                    node.plan[m] = own[m]
                else:
                    s_ = sum(ch.plan.get(m, 0) for ch in node.children)
                    if s_:
                        node.plan[m] = s_
        # on retire les lignes sans prévu ni réalisé
        kept = []
        for node in nodes:
            node.children = [ch for ch in node.children if any(ch.values.values()) or any(ch.plan.values())]
            if node.children or any(node.values.values()) or any(node.plan.values()):
                kept.append(node)
        nodes[:] = kept
    report.sections = [s_ for s_ in report.sections if s_[2]]

    def total(kind, attr):
        acc = {}
        for _, k, nodes in report.sections:
            if k == kind:
                for n in nodes:
                    for m, v in getattr(n, attr).items():
                        acc[m] = acc.get(m, 0) + v
        return acc

    rev_r, dep_r, neu_r, unc = (total("revenu", "values"), total("depense", "values"), total("neutre", "values"),
                                total("none", "values"))
    rev_p, dep_p, neu_p = total("revenu", "plan"), total("depense", "plan"), total("neutre", "plan")

    def node(label, real, plan):
        n = Node(label, "total", [], real, level=0)
        n.plan = plan
        return n

    def solde(r, d, nn, u=None):
        u = u or {}
        return {m: r.get(m, 0) - d.get(m, 0) - nn.get(m, 0) + u.get(m, 0) for m in months}

    report.totals = [
        node("Total revenus", rev_r, rev_p),
        node("Total dépenses", dep_r, dep_p),
        node("Épargne et mouvements internes", neu_r, neu_p),
        node("Solde (revenus − dépenses − épargne)", solde(rev_r, dep_r, neu_r, unc), solde(rev_p, dep_p, neu_p)),
    ]
    for _, _k, nodes in report.sections:
        for n in nodes:
            if not hasattr(n, "plan"):
                n.plan = {}
    return report


def favorable_gap(kind, plan, real, label=""):
    """Écart orienté : positif = favorable (moins dépensé, plus reçu, solde meilleur)."""
    if kind in ("revenu", "neutre") or label in ("Total revenus", "Épargne et mouvements internes") \
            or label.startswith("Solde"):
        return real - plan
    return plan - real


def monthly_totals(db, start_month, end_month):
    """Par mois : revenus, dépenses (positives), solde net (revenus − dépenses)."""
    rep = pivot(db, start_month, end_month)
    rev, dep = rep.totals[0].values, rep.totals[1].values
    return [(m, rev.get(m, 0), dep.get(m, 0)) for m in rep.columns]


def account_balance_series(db, start_month, end_month):
    """Solde de fin de mois d'après la colonne « solde » du relevé (si disponible)."""
    out = []
    for m in month_range(start_month, end_month):
        r = db.conn.execute(
            "SELECT balance FROM operations WHERE date <= ? AND balance IS NOT NULL "
            "ORDER BY date DESC, id ASC LIMIT 1", (month_last_day(m),)).fetchone()
        out.append((m, r[0] if r else None))
    return out


def top_vendors(db, cat_ids, start_month, end_month, limit=15, uncategorized=False):
    if uncategorized:
        where, args = "category_id IS NULL", []
    else:
        where, args = f"category_id IN ({','.join('?' * len(cat_ids))})", list(cat_ids)
    sql = (f"SELECT vendor, COUNT(*), SUM(amount) FROM operations WHERE {where} AND date >= ? AND date <= ? "
           f"GROUP BY vendor ORDER BY ABS(SUM(amount)) DESC LIMIT ?")
    return db.conn.execute(sql, args + [month_first_day(start_month), month_last_day(end_month), limit]).fetchall()
