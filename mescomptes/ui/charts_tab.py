"""Pages « Détail par catégorie » et « Graphiques »."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QTreeWidget

from .. import analytics as an
from ..exporters import DATE, MONEY, PCT, TEXT, TableData, export_pdf
from ..money import fmt_eur, fmt_pct, pct_change
from . import theme as T
from .common import (CHART_COLORS, SORT_ROLE, Card, CategoryCombo, ChartCanvas, Page, PeriodSelector, SortItem,
                     button, error, euro_axis, info, label, safe_filename, save_path, set_money, style_tree)
from .dashboard import KpiCard
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
    return {m: s * sign for m, s, _ in rows}, sum(c for _, _, c in rows)


# ============================================================ Détail catégorie
class DetailTab(Page):
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__("Détail par catégorie", "Évolution, comparaison avec l'année précédente et "
                                                 "principaux fournisseurs d'une catégorie.", parent, scroll=True)
        self.db = db
        self.add_action(button("PDF", "file", slot=self.export_pdf, tooltip="Exporter en PDF"))
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.cat = CategoryCombo(self, with_none=True)
        bar.addWidget(self.cat)
        bar.addSpacing(8)
        self.period = PeriodSelector(self, default="12 derniers mois")
        bar.addWidget(self.period)
        bar.addStretch()
        self.add(bar)

        kpis = QGridLayout()
        kpis.setSpacing(14)
        self.k_total = KpiCard("Total sur la période")
        self.k_avg = KpiCard("Moyenne mensuelle")
        self.k_count = KpiCard("Nombre d'opérations")
        for i, k in enumerate((self.k_total, self.k_avg, self.k_count)):
            kpis.addWidget(k, 0, i)
        self.add(kpis)

        row = QHBoxLayout()
        row.setSpacing(14)
        chart_card = Card()
        self.chart_title = label("", "sectionTitle")
        chart_card.add(self.chart_title)
        self.canvas = ChartCanvas(chart_card, height=2.8)
        chart_card.add(self.canvas, 1)
        row.addWidget(chart_card, 3)
        vcard = Card()
        vcard.add(label("Principaux fournisseurs", "sectionTitle"))
        self.vendors = QTreeWidget()
        style_tree(self.vendors)
        self.vendors.setHeaderLabels(["FOURNISSEUR", "NB", "TOTAL"])
        self.vendors.setRootIsDecorated(False)
        self.vendors.setSortingEnabled(True)
        vcard.add(self.vendors, 1)
        row.addWidget(vcard, 2)
        self.add(row, 3)

        ops_card = Card()
        ops_card.add(label("Opérations", "sectionTitle"))
        self.panel = OperationsPanel(db, ops_card)
        self.panel.changed.connect(self._ops_changed)
        ops_card.add(self.panel, 1)
        self.add(ops_card, 3)

        self.cat.currentIndexChanged.connect(self.reload)
        self.period.changed.connect(self.reload)
        self.data = None
        self._bars = {}
        self.canvas.mpl_connect("pick_event", self._on_pick)
        self.canvas.mpl_connect("motion_notify_event", lambda e: self.canvas.setCursor(
            Qt.PointingHandCursor if any(b.contains(e)[0] for b in self._bars) else Qt.ArrowCursor))

    def _on_pick(self, event):
        m = self._bars.get(event.artist)
        cat_ids, name, _kind = self._cat_ids()
        if m is None or cat_ids is None:
            return
        from .report_tabs import OperationsDialog
        dlg = OperationsDialog(self.db, name, cat_ids, m, m, self)
        dlg.exec()
        if dlg.dirty:
            self._ops_changed()

    def show_category(self, cat_id):
        self.cat.set_value(cat_id)

    def refresh(self):
        self.cat.populate(self.db)
        self.period.set_bounds(*self.db.date_bounds())
        self.reload()

    def _ops_changed(self):
        self.reload()
        self.changed.emit()

    def _cat_ids(self):
        v = self.cat.currentData()
        if v == CategoryCombo.NONE:
            return [None], "Opérations à classer", "none"
        if v is None:
            return None, "", ""
        return self.db.descendants(v), self.db.category_label(v), self.db.categories()[v].kind

    def reload(self, *_):
        cat_ids, name, kind = self._cat_ids()
        if cat_ids is None:
            return
        start, end = self.period.period()
        months = an.month_range(start, end)
        sums, count = _month_sums(self.db, cat_ids, start, end)
        prev, prev_count = _month_sums(self.db, cat_ids, an.add_months(start, -12), an.add_months(end, -12))
        total, total_prev = sum(sums.values()), sum(prev.values())
        self.data = (name, kind, months, sums, prev)
        good_up = kind in ("revenu", "revenu_autre")
        has_prev = bool(prev)
        ref = "vs même période N-1"
        self.k_total.set(total, total_prev if has_prev else 0, good_up, ref=ref)
        self.k_avg.set(round(total / max(len(months), 1)),
                       round(total_prev / max(len(months), 1)) if has_prev else 0, good_up, ref=ref)
        self.k_count.value.setText(str(count))
        self.k_count.delta.setText(f"<span style='color:{T.MUTED}'>{prev_count} l'année précédente</span>"
                                   if has_prev else "")
        covered = sum(1 for m in months if an.add_months(m, -12) in prev)
        if has_prev and covered < len(months):
            self.k_total.delta.setText(self.k_total.delta.text() +
                                       f"<br><span style='color:{T.SUBTLE}'>N-1 : {covered} mois de données "
                                       f"sur {len(months)}</span>")
        self.chart_title.setText(f"{name} — par mois (cliquez sur un mois pour voir ses opérations)")

        fig = self.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        x = list(range(len(months)))
        color = T.category_color(self.db, cat_ids[0]).name() if cat_ids != [None] else T.ORANGE
        bars = ax.bar(x, [sums.get(m, 0) / 100 for m in months], color=color, width=0.6, label="Période")
        self._bars = {}
        for m, rect in zip(months, bars):
            rect.set_picker(True)
            self._bars[rect] = m
        if has_prev:
            ax.plot(x, [prev[an.add_months(m, -12)] / 100 if an.add_months(m, -12) in prev else float("nan")
                        for m in months], color=T.TEXT, marker="o", markersize=3.5, linestyle="--",
                    linewidth=1.2, label="Année précédente")
            ax.legend(loc="upper left", fontsize=8)
        ax.set_xticks(x, [an.month_label(m) for m in months], rotation=45 if len(months) > 6 else 0,
                      ha="right" if len(months) > 6 else "center", fontsize=8)
        euro_axis(ax)
        self.canvas.draw_idle()

        self.vendors.clear()
        sign = an.sign_for(kind) if kind in ("depense", "revenu", "revenu_autre") else 1
        for vendor, n, s in an.top_vendors(self.db, cat_ids, start, end, limit=50, uncategorized=cat_ids == [None]):
            it = SortItem(self.vendors, [vendor or "(inconnu)", str(n)])
            it.setData(1, SORT_ROLE, n)
            set_money(it, 2, s * sign)
        self.vendors.sortItems(2, Qt.DescendingOrder)
        self.vendors.resizeColumnToContents(1)
        self.vendors.setColumnWidth(0, 200)

        kw = {"uncategorized": True} if cat_ids == [None] else {"cat_ids": cat_ids}
        self.panel.set_rows(self.db.operations(start=an.month_first_day(start), end=an.month_last_day(end), **kw))

    def export_pdf(self):
        if not self.data:
            return
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
class ChartsTab(Page):
    changed = Signal()
    CHARTS = ["Revenus et dépenses par mois", "Répartition des dépenses", "Évolution des dépenses par catégorie",
              "Solde du compte en fin de mois"]

    def __init__(self, db, parent=None):
        super().__init__("Graphiques", "Visualisez vos finances sous différents angles.", parent)
        self.db = db
        self.add_action(button("Image", "download", slot=self.export_png, tooltip="Exporter en image PNG"))
        self.add_action(button("PDF", "file", slot=self.export_pdf, tooltip="Exporter en PDF"))
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.kind = QComboBox()
        self.kind.addItems(self.CHARTS)
        bar.addWidget(self.kind)
        bar.addSpacing(8)
        self.period = PeriodSelector(self, default="12 derniers mois")
        bar.addWidget(self.period)
        bar.addStretch()
        self.add(bar)
        card = Card(margins=(18, 16, 18, 16))
        self.hint = label("Cliquez sur une catégorie, une barre ou une entrée de la légende pour voir les "
                          "opérations correspondantes.", "muted")
        card.add(self.hint)
        self.canvas = ChartCanvas(card, height=5)
        card.add(self.canvas, 1)
        self.add(card, 1)
        self.kind.currentIndexChanged.connect(self.reload)
        self.period.changed.connect(self.reload)
        self._targets = {}
        self._last_click = None
        self.canvas.mpl_connect("pick_event", self._on_pick)
        self.canvas.mpl_connect("motion_notify_event", self._on_move)

    # ------------------------------------------------------------- clics
    def _register(self, artist, title, cat_ids, start, end):
        artist.set_picker(True)
        self._targets[artist] = (title, cat_ids, start, end)

    def _on_move(self, event):
        hit = any(a.contains(event)[0] for a in self._targets if a.figure is not None)
        self.canvas.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)

    def _on_pick(self, event):
        target = self._targets.get(event.artist)
        if target is None or self._last_click is event.mouseevent:
            return
        self._last_click = event.mouseevent
        from .report_tabs import OperationsDialog
        title, cat_ids, start, end = target
        dlg = OperationsDialog(self.db, title, cat_ids, start, end, self)
        dlg.exec()
        if dlg.dirty:
            self.reload()
            self.changed.emit()

    def _kind_ids(self, kind):
        return [c.id for c in self.db.categories().values() if c.kind == kind]

    def refresh(self):
        self.period.set_bounds(*self.db.date_bounds())
        self.reload()

    def reload(self, *_):
        start, end = self.period.period()
        fig = self.canvas.figure
        fig.clear()
        self._targets = {}
        ax = fig.add_subplot(111)
        k = self.kind.currentIndex()
        months = an.month_range(start, end)
        labels = [an.month_label(m) for m in months]
        self.hint.setVisible(k != 3)
        x = list(range(len(months)))
        rot = dict(rotation=45, ha="right") if len(months) > 8 else {}
        if k == 0:
            data = an.monthly_totals(self.db, start, end)
            w = 0.38
            rb = ax.bar([i - w / 2 for i in x], [r / 100 for _, r, _ in data], w, color="#32D583", label="Revenus")
            db_ = ax.bar([i + w / 2 for i in x], [d / 100 for _, _, d in data], w, color=T.ACCENT, label="Dépenses")
            rev_ids = self._kind_ids("revenu") + self._kind_ids("revenu_autre")
            dep_ids = self._kind_ids("depense")
            for m, r1, r2 in zip(months, rb, db_):
                self._register(r1, f"Revenus — {an.month_label(m, full=True)}", rev_ids, m, m)
                self._register(r2, f"Dépenses — {an.month_label(m, full=True)}", dep_ids, m, m)
            ax.plot(x, [(r - d) / 100 for _, r, d in data], color=T.TEXT, marker="o", markersize=4,
                    label="Revenus − dépenses")
            ax.axhline(0, color=T.BORDER_STRONG, linewidth=0.8)
            top = max([r / 100 for _, r, _ in data] + [d / 100 for _, _, d in data] + [1])
            ax.set_ylim(top=top * 1.2)
            ax.set_xticks(x, labels, fontsize=8, **rot)
            ax.legend(fontsize=9, loc="upper left", ncol=3)
            euro_axis(ax)
        elif k == 1:
            rep = an.pivot(self.db, start, end)
            nodes = [n for _, kind, ns in rep.sections if kind == "depense" for n in ns]
            ranked = sorted((n for n in nodes if n.total(months) > 0), key=lambda n: -n.total(months))
            vals = [(n.label, n.total(months), n.cat_id) for n in ranked]
            ids = [n.cat_ids for n in ranked]
            if len(vals) > 10:
                vals = vals[:9] + [("Autres", sum(v for _, v, _ in vals[9:]), None)]
                ids = ids[:9] + [[c for n in ranked[9:] for c in n.cat_ids]]
            total = sum(v for _, v, _ in vals)
            if total:
                colors = [T.category_color(self.db, c).name() if c else T.SUBTLE for _, _, c in vals]
                wedges, _ = ax.pie([v for _, v, _ in vals], colors=colors, startangle=90, counterclock=False,
                                   wedgeprops=dict(width=0.38, edgecolor="white", linewidth=2))
                leg = ax.legend(wedges, [f"{lbl} — {fmt_eur(v)} ({v / total * 100:.0f} %)" for lbl, v, _ in vals],
                                loc="center left", bbox_to_anchor=(1, 0.5), fontsize=9)
                for wedge, patch, text, (lbl, _v, _c), cids in zip(wedges, leg.get_patches(), leg.get_texts(),
                                                                    vals, ids):
                    for artist in (wedge, patch, text):
                        self._register(artist, lbl, cids, start, end)
                ax.text(0, 0.06, fmt_eur(total), ha="center", va="center", fontsize=13, weight="bold", color=T.TEXT)
                ax.text(0, -0.12, "de dépenses", ha="center", va="center", fontsize=9, color=T.MUTED)
                ax.set_aspect("equal")
            else:
                ax.text(0.5, 0.5, "Aucune dépense classée sur la période", ha="center", transform=ax.transAxes,
                        color=T.MUTED)
                ax.axis("off")
        elif k == 2:
            rep = an.pivot(self.db, start, end)
            nodes = [n for _, kind, ns in rep.sections if kind == "depense" for n in ns]
            nodes.sort(key=lambda n: -n.total(months))
            main, rest = nodes[:8], nodes[8:]
            bottom = [0] * len(months)
            series = [(n.label, [n.values.get(m, 0) / 100 for m in months], T.category_color(self.db, n.cat_id).name(),
                       n.cat_ids) for n in main]
            if rest:
                series.append(("Autres", [sum(n.values.get(m, 0) for n in rest) / 100 for m in months], T.SUBTLE,
                               [c for n in rest for c in n.cat_ids]))
            for lbl, vals, col, cids in series:
                bars = ax.bar(x, vals, bottom=bottom, color=col, label=lbl, width=0.65, edgecolor="white",
                              linewidth=0.6)
                for m, rect in zip(months, bars):
                    self._register(rect, f"{lbl} — {an.month_label(m, full=True)}", cids, m, m)
                bottom = [b + v for b, v in zip(bottom, vals)]
            ax.set_xticks(x, labels, fontsize=8, **rot)
            leg = ax.legend(loc="center left", bbox_to_anchor=(1, 0.5), fontsize=9)
            for patch, text, (lbl, _v, _c, cids) in zip(leg.get_patches(), leg.get_texts(), series):
                self._register(patch, lbl, cids, start, end)
                self._register(text, lbl, cids, start, end)
            euro_axis(ax)
        else:
            series = an.account_balance_series(self.db, start, end)
            vals = [(i, b / 100) for i, (_, b) in enumerate(series) if b is not None]
            if vals:
                ax.plot([i for i, _ in vals], [v for _, v in vals], color=T.ACCENT, marker="o", markersize=4)
                ax.fill_between([i for i, _ in vals], [v for _, v in vals], alpha=0.08, color=T.ACCENT)
                ax.set_xticks(x, labels, fontsize=8, **rot)
                euro_axis(ax)
            else:
                ax.text(0.5, 0.5, "Le relevé importé ne contient pas de colonne « Solde ».", ha="center",
                        transform=ax.transAxes, color=T.MUTED)
                ax.axis("off")
        ax.set_title(f"{self.CHARTS[k]} — {self.period.label()}")
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


__all__ = ["CHART_COLORS", "fmt_pct"]
