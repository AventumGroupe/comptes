"""Onglets « Détail catégorie » et « Graphiques »."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSplitter, QTreeWidget,
                               QVBoxLayout, QWidget)

from .. import analytics as an
from ..exporters import DATE, MONEY, PCT, TEXT, TableData, export_pdf
from ..money import fmt_eur, fmt_pct, pct_change
from .common import (CHART_COLORS, ChartCanvas, CategoryCombo, PeriodSelector, SortItem, euro_axis, error, info,
                     safe_filename, save_path, set_money, SORT_ROLE)
from .operations_tab import OperationsPanel


def _month_sums(db, cat_ids, start, end):
    """Montants présentés par mois pour un ensemble de catégories (ou [None] = à classer)."""
    if cat_ids == [None]:
        where, args, sign = "category_id IS NULL", [], 1
    else:
        where = f"category_id IN ({','.join('?' * len(cat_ids))})"
        args = list(cat_ids)
        sign = an.sign_for(db.categories()[cat_ids[0]].kind)
    rows = db.conn.execute(
        f"SELECT substr(date,1,7) m, SUM(amount), COUNT(*) FROM operations WHERE {where} "
        f"AND date >= ? AND date <= ? GROUP BY m", args + [an.month_first_day(start), an.month_last_day(end)]
    ).fetchall()
    sums = {m: s * sign for m, s, _ in rows}
    count = sum(c for _, _, c in rows)
    return sums, count


# ============================================================ Détail catégorie
class DetailTab(QWidget):
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Catégorie :"))
        self.cat = CategoryCombo(self, with_none=True)
        bar.addWidget(self.cat)
        bar.addSpacing(12)
        self.period = PeriodSelector(self, default="12 derniers mois")
        bar.addWidget(self.period)
        bar.addStretch()
        pdf = QPushButton("Exporter PDF…")
        pdf.clicked.connect(self.export_pdf)
        bar.addWidget(pdf)
        lay.addLayout(bar)

        self.stats = QLabel()
        self.stats.setTextFormat(Qt.RichText)
        self.stats.setStyleSheet("font-size:11pt; padding:4px")
        lay.addWidget(self.stats)

        split = QSplitter(Qt.Vertical)
        top = QSplitter(Qt.Horizontal)
        self.canvas = ChartCanvas(self, height=3.2)
        top.addWidget(self.canvas)
        self.months_tree = QTreeWidget()
        self.months_tree.setHeaderLabels(["Mois", "Montant", "Année précédente", "Écart"])
        self.months_tree.setRootIsDecorated(False)
        top.addWidget(self.months_tree)
        self.vendors = QTreeWidget()
        self.vendors.setHeaderLabels(["Fournisseur", "Nb", "Total"])
        self.vendors.setRootIsDecorated(False)
        self.vendors.setSortingEnabled(True)
        top.addWidget(self.vendors)
        top.setSizes([600, 360, 300])
        split.addWidget(top)
        self.panel = OperationsPanel(db, self)
        self.panel.changed.connect(self._ops_changed)
        split.addWidget(self.panel)
        split.setSizes([330, 330])
        lay.addWidget(split, 1)

        self.cat.currentIndexChanged.connect(self.reload)
        self.period.changed.connect(self.reload)

    def show_category(self, cat_id):
        self.cat.set_value(cat_id)

    def refresh(self):
        self.cat.populate(self.db)
        self.period.set_bounds(*self.db.date_bounds())
        self.reload()

    def _ops_changed(self):
        self.changed.emit()

    def _cat_ids(self):
        v = self.cat.currentData()
        if v == CategoryCombo.NONE:
            return [None], "Opérations à classer", "none"
        if v is None:
            return None, "", ""
        c = self.db.categories()[v]
        return self.db.descendants(v), self.db.category_label(v), c.kind

    def reload(self, *_):
        cat_ids, name, kind = self._cat_ids()
        if cat_ids is None:
            return
        start, end = self.period.period()
        months = an.month_range(start, end)
        sums, count = _month_sums(self.db, cat_ids, start, end)
        prev, _ = _month_sums(self.db, cat_ids, an.add_months(start, -12), an.add_months(end, -12))
        total = sum(sums.values())
        total_prev = sum(prev.values())
        self.data = (name, kind, months, sums, prev)
        verb = {"depense": "dépensé", "revenu": "reçu"}.get(kind, "net")
        p = pct_change(total, total_prev)
        covered = sum(1 for m in months if an.add_months(m, -12) in prev)
        partial = f", {covered} mois de données sur {len(months)}" if covered < len(months) else ""
        cmp_txt = f" — année précédente : {fmt_eur(total_prev)} ({fmt_pct(p)}{partial})" if total_prev else ""
        self.stats.setText(f"<b>{name}</b> — total {verb} : <b>{fmt_eur(total)}</b> sur {len(months)} mois, "
                           f"soit <b>{fmt_eur(round(total / max(len(months), 1)))}</b> / mois en moyenne — "
                           f"{count} opération(s){cmp_txt}")

        # graphique
        fig = self.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        x = list(range(len(months)))
        ax.bar(x, [sums.get(m, 0) / 100 for m in months], color=CHART_COLORS[0], label="Période")
        if any(prev.values()):
            ax.plot(x, [prev[an.add_months(m, -12)] / 100 if an.add_months(m, -12) in prev else float("nan")
                        for m in months], color=CHART_COLORS[1],
                    marker="o", linestyle="--", label="Année précédente")
            ax.legend(loc="upper left", fontsize=8, frameon=False)
        ax.set_xticks(x, [an.month_label(m) for m in months], rotation=45 if len(months) > 6 else 0,
                      ha="right" if len(months) > 6 else "center", fontsize=8)
        euro_axis(ax)
        ax.set_title(name, fontsize=10)
        self.canvas.draw_idle()

        # tableau par mois
        self.months_tree.clear()
        for m in months:
            it = SortItem(self.months_tree, [an.month_label(m, full=True)])
            v, pv = sums.get(m, 0), prev.get(an.add_months(m, -12), 0)
            set_money(it, 1, v, blank_zero=False)
            set_money(it, 2, pv)
            set_money(it, 3, v - pv if pv else 0, colorize=True, invert=(kind == "depense"), signed=True)
        for c in range(4):
            self.months_tree.resizeColumnToContents(c)

        # fournisseurs
        self.vendors.clear()
        sign = an.sign_for(kind) if kind in ("depense", "revenu") else 1
        for vendor, n, s in an.top_vendors(self.db, cat_ids, start, end, limit=50, uncategorized=cat_ids == [None]):
            it = SortItem(self.vendors, [vendor or "(inconnu)", str(n)])
            it.setData(1, SORT_ROLE, n)
            set_money(it, 2, s * sign)
        self.vendors.sortItems(2, Qt.DescendingOrder)
        for c in range(3):
            self.vendors.resizeColumnToContents(c)

        kw = {"uncategorized": True} if cat_ids == [None] else {"cat_ids": cat_ids}
        self.panel.set_rows(self.db.operations(start=an.month_first_day(start), end=an.month_last_day(end), **kw))

    def export_pdf(self):
        name, kind, months, sums, prev = self.data
        path = save_path(self, "Exporter", f"detail {safe_filename(name)}.pdf", "PDF (*.pdf)")
        if not path:
            return
        t = TableData(f"Détail : {name}", self.period.label(), ["Mois", "Montant", "Année précédente", "Écart %"],
                      [TEXT, MONEY, MONEY, PCT])
        for m in months:
            v, pv = sums.get(m, 0), prev.get(an.add_months(m, -12), 0)
            t.add([an.month_label(m, full=True), v, pv, pct_change(v, pv)])
        t.add(["Total", sum(sums.values()), sum(prev.get(an.add_months(m, -12), 0) for m in months),
               pct_change(sum(sums.values()), sum(prev.values()))], bold=True, shade=True)
        ops = TableData("Opérations", self.period.label(), ["Date", "Libellé", "Montant", "Catégorie"],
                        [DATE, TEXT, MONEY, TEXT])
        for r in self.panel.view.visible_rows():
            ops.add([r["date"], r["label"], r["amount"], self.db.category_label(r["category_id"])])
        try:
            export_pdf(path, [t, ops], images=[(name, self.canvas.png_bytes())], title=f"Détail : {name}",
                       landscape=False)
        except Exception as e:  # noqa: BLE001
            error(self, f"Export impossible : {e}")
            return
        info(self, f"Export enregistré :\n{path}")


# ================================================================= Graphiques
class ChartsTab(QWidget):
    CHARTS = ["Revenus et dépenses par mois", "Répartition des dépenses", "Évolution des dépenses par catégorie",
              "Solde du compte en fin de mois"]

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Graphique :"))
        self.kind = QComboBox()
        self.kind.addItems(self.CHARTS)
        bar.addWidget(self.kind)
        bar.addSpacing(12)
        self.period = PeriodSelector(self, default="12 derniers mois")
        bar.addWidget(self.period)
        bar.addStretch()
        png = QPushButton("Image PNG…")
        png.clicked.connect(self.export_png)
        pdf = QPushButton("PDF…")
        pdf.clicked.connect(self.export_pdf)
        bar.addWidget(QLabel("Exporter :"))
        bar.addWidget(png)
        bar.addWidget(pdf)
        lay.addLayout(bar)
        self.canvas = ChartCanvas(self, height=5)
        lay.addWidget(self.canvas, 1)
        self.kind.currentIndexChanged.connect(self.reload)
        self.period.changed.connect(self.reload)

    def refresh(self):
        self.period.set_bounds(*self.db.date_bounds())
        self.reload()

    def reload(self, *_):
        start, end = self.period.period()
        fig = self.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        k = self.kind.currentIndex()
        months = an.month_range(start, end)
        labels = [an.month_label(m) for m in months]
        x = list(range(len(months)))
        rot = dict(rotation=45, ha="right") if len(months) > 8 else {}
        if k == 0:
            data = an.monthly_totals(self.db, start, end)
            w = 0.4
            ax.bar([i - w / 2 for i in x], [r / 100 for _, r, _ in data], w, color="#27AE60", label="Revenus")
            ax.bar([i + w / 2 for i in x], [d / 100 for _, _, d in data], w, color="#C0392B", label="Dépenses")
            ax.plot(x, [(r - d) / 100 for _, r, d in data], color="#2E86C1", marker="o", label="Revenus − dépenses")
            ax.axhline(0, color="#999", linewidth=0.8)
            top = max([r / 100 for _, r, _ in data] + [d / 100 for _, _, d in data] + [1])
            ax.set_ylim(top=top * 1.2)
            ax.set_xticks(x, labels, fontsize=8, **rot)
            ax.legend(frameon=False, fontsize=9, loc="upper center", ncol=3)
            euro_axis(ax)
        elif k == 1:
            rep = an.pivot(self.db, start, end)
            nodes = [n for t, kind, ns in rep.sections if kind == "depense" for n in ns]
            vals = sorted(((n.label, n.total(months)) for n in nodes if n.total(months) > 0), key=lambda x: -x[1])
            if len(vals) > 10:
                vals = vals[:9] + [("Autres", sum(v for _, v in vals[9:]))]
            total = sum(v for _, v in vals)
            if total:
                wedges, _ = ax.pie([v for _, v in vals], colors=CHART_COLORS[:len(vals)], startangle=90,
                                   counterclock=False, wedgeprops=dict(width=0.42, edgecolor="white"))
                ax.legend(wedges, [f"{lbl} — {fmt_eur(v)} ({v / total * 100:.0f} %)" for lbl, v in vals],
                          loc="center left", bbox_to_anchor=(1, 0.5), frameon=False, fontsize=9)
                ax.text(0, 0, f"Total\n{fmt_eur(total)}", ha="center", va="center", fontsize=11, weight="bold")
                ax.set_aspect("equal")
            else:
                ax.text(0.5, 0.5, "Aucune dépense classée sur la période", ha="center", transform=ax.transAxes)
                ax.axis("off")
        elif k == 2:
            rep = an.pivot(self.db, start, end)
            nodes = [n for t, kind, ns in rep.sections if kind == "depense" for n in ns]
            nodes.sort(key=lambda n: -n.total(months))
            main, rest = nodes[:8], nodes[8:]
            bottom = [0] * len(months)
            series = [(n.label, [n.values.get(m, 0) / 100 for m in months]) for n in main]
            if rest:
                series.append(("Autres", [sum(n.values.get(m, 0) for n in rest) / 100 for m in months]))
            for i, (lbl, vals) in enumerate(series):
                ax.bar(x, vals, bottom=bottom, color=CHART_COLORS[i % len(CHART_COLORS)], label=lbl)
                bottom = [b + v for b, v in zip(bottom, vals)]
            ax.set_xticks(x, labels, fontsize=8, **rot)
            ax.legend(loc="center left", bbox_to_anchor=(1, 0.5), frameon=False, fontsize=9)
            euro_axis(ax)
        else:
            series = an.account_balance_series(self.db, start, end)
            vals = [(i, b / 100) for i, (_, b) in enumerate(series) if b is not None]
            if vals:
                ax.plot([i for i, _ in vals], [v for _, v in vals], color="#2E86C1", marker="o")
                ax.fill_between([i for i, _ in vals], [v for _, v in vals], alpha=0.1, color="#2E86C1")
                ax.set_xticks(x, labels, fontsize=8, **rot)
                euro_axis(ax)
            else:
                ax.text(0.5, 0.5, "Le relevé importé ne contient pas de colonne « Solde ».", ha="center",
                        transform=ax.transAxes)
                ax.axis("off")
        ax.set_title(f"{self.CHARTS[k]} — {self.period.label()}", fontsize=11)
        self.canvas.draw_idle()

    def export_png(self):
        path = save_path(self, "Exporter l'image", f"{safe_filename(self.kind.currentText())}.png", "Image PNG (*.png)")
        if path:
            with open(path, "wb") as f:
                f.write(self.canvas.png_bytes())
            info(self, f"Image enregistrée :\n{path}")

    def export_pdf(self):
        path = save_path(self, "Exporter", f"{safe_filename(self.kind.currentText())}.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            export_pdf(path, [], images=[(f"{self.kind.currentText()} — {self.period.label()}",
                                          self.canvas.png_bytes())], title="Graphique", landscape=True)
        except Exception as e:  # noqa: BLE001
            error(self, f"Export impossible : {e}")
            return
        info(self, f"Export enregistré :\n{path}")
