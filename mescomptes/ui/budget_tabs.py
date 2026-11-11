"""Pages « Prévisionnel » (saisie mois par mois) et « Prévu / réalisé » (écarts)."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QMenu,
                               QStyledItemDelegate, QTreeWidget)

from .. import analytics as an
from ..db import KIND_ORDER
from ..exporters import MONEY, PCT, TEXT, TableData, report_to_rows
from ..money import fmt_eur, fmt_pct, parse_eur_input
from . import theme as T
from .common import (FlowLayout, COLOR_ROLE, GREEN, GREY, RED, SECTION_BG, SORT_ROLE, TEXT as TEXT_COLOR, TOTAL_BG, Card,
                     ChartCanvas, DotDelegate, MonthCombo, Page, PeriodSelector, SortItem, bold_font, button,
                     confirm, error, euro_axis, info, label, style_row, style_tree)
from .report_tabs import NODE_ROLE, OperationsDialog, ReportTree, do_export, export_buttons

CAT_ROLE = Qt.UserRole + 30
SECTION_TITLES = {"revenu": "Revenus du travail et de substitution", "revenu_autre": "Autres revenus", "depense": "Dépenses",
                  "neutre": "Épargne et mouvements internes"}


class _ReadOnlyDot(DotDelegate):
    def createEditor(self, *_):
        return None


class _ReadOnly(QStyledItemDelegate):
    def createEditor(self, *_):
        return None


def _italic():
    f = QFont()
    f.setItalic(True)
    return f


# ================================================================ Prévisionnel
class ForecastPage(Page):
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__("Prévisionnel", "Saisissez vos montants prévus mois par mois (double-clic ou frappe directe "
                                         "dans une cellule). Recopiez n'importe quel mois vers la droite, puis ajustez les mois suivants.",
                         parent)
        self.db = db
        export_buttons(self, lambda: self.export("excel"), lambda: self.export("pdf"))

        row = FlowLayout()
        row.setSpacing(8)
        row.addWidget(label("À partir de", "muted"))
        self.start = MonthCombo()
        cur = an.current_month()
        self.start.set_months(an.month_range(an.add_months(cur, -36), an.add_months(cur, 24)))
        self.start.set_month(cur)
        row.addWidget(self.start)
        row.addWidget(label("sur", "muted"))
        self.length = QComboBox()
        for n in (12, 18, 24):
            self.length.addItem(f"{n} mois", n)
        row.addWidget(self.length)
        row.addSpacing(12)
        self.autocopy = QCheckBox("Recopier chaque saisie sur les mois suivants")
        self.autocopy.setToolTip("Quand vous saisissez un montant, il est reporté automatiquement sur tous les "
                                 "mois à droite (vous pouvez ensuite modifier un mois en particulier).")
        row.addWidget(self.autocopy)
        row.addStretch()
        self.add(row)

        row2 = FlowLayout()
        row2.setSpacing(8)
        self.copy_btn = button("Recopier vers la droite", "compare", "primary", slot=self.copy_selection_right,
                               tooltip="Reporte la ou les cellules sélectionnées sur tous les mois suivants (Ctrl+R)")
        row2.addWidget(self.copy_btn)
        row2.addWidget(button("Recopier la 1ʳᵉ colonne sur tous les mois", "compare", slot=self.copy_first_column,
                              tooltip="Chaque montant du premier mois est reporté sur les mois suivants"))
        row2.addWidget(button("Pré-remplir avec le réalisé moyen", "sparkle", slot=self.prefill,
                              tooltip="Propose, pour les cases vides, la moyenne mensuelle réalisée des 12 derniers mois"))
        row2.addStretch()
        row2.addWidget(button("Tout effacer", "trash", "danger", slot=self.clear_all))
        self.add(row2)
        self.sel_hint = label("Cliquez sur une cellule (n'importe quel mois), puis « Recopier vers la droite » ou "
                              "Ctrl+R. Vous pourrez ensuite modifier un mois suivant et recopier à nouveau à partir "
                              "de lui en cas d'évolution.", "muted", True)
        self.sel_hint.setTextFormat(Qt.RichText)
        self.add(self.sel_hint)

        card = Card(margins=(0, 4, 0, 4))
        self.tree = QTreeWidget()
        style_tree(self.tree)
        self.tree.setItemDelegateForColumn(0, _ReadOnlyDot(self.tree))
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
                                  QAbstractItemView.AnyKeyPressed)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.header().setStretchLastSection(False)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        card.add(self.tree, 1)
        self.add(card, 1)

        self.months = []
        self._filling = False
        self._expanded = {}
        self._restore = None   # (catégorie, colonne) à resélectionner après rechargement
        QShortcut(QKeySequence("Ctrl+R"), self, self.copy_selection_right, context=Qt.WidgetWithChildrenShortcut)
        self.tree.itemSelectionChanged.connect(self._selection_hint)
        self.start.currentIndexChanged.connect(self.reload)
        self.length.currentIndexChanged.connect(self.reload)

    def refresh(self):
        self.reload()

    # ------------------------------------------------------------------ affichage
    def reload(self, *_):
        m0 = self.start.month()
        if not m0:
            return
        self.months = an.month_range(m0, an.add_months(m0, self.length.currentData() - 1))
        months = self.months
        fc = self.db.forecasts(months[0], months[-1])
        self.fc = fc
        # mémorise l'état d'affichage
        for i in range(self.tree.topLevelItemCount()):
            sec = self.tree.topLevelItem(i)
            for j in range(sec.childCount()):
                it = sec.child(j)
                if it.data(0, CAT_ROLE) is not None:
                    self._expanded[it.data(0, CAT_ROLE)] = it.isExpanded()
        scroll = self.tree.verticalScrollBar().value()

        self._filling = True
        self.tree.clear()
        n = len(months) + 2
        self.tree.setColumnCount(n)
        self.tree.setHeaderLabels(["CATÉGORIE"] + [an.month_label(m).upper() for m in months] + ["TOTAL"])
        for c in range(1, n):
            self.tree.headerItem().setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)

        totals = {k: {m: 0 for m in months} for k in SECTION_TITLES}
        tree = self.db.category_tree()
        for kind in sorted(SECTION_TITLES, key=lambda k: KIND_ORDER[k]):
            tops = [(t, subs) for t, subs in tree if t.kind == kind]
            if not tops:
                continue
            sec = SortItem(self.tree, [SECTION_TITLES[kind].upper()])
            style_row(sec, n, bold=True, bg=SECTION_BG, fg=GREY)
            sec.setFlags(sec.flags() & ~Qt.ItemIsEditable)
            for top, subs in tops:
                it = SortItem(sec, [top.name])
                it.setData(0, CAT_ROLE, top.id)
                it.setData(0, COLOR_ROLE, T.category_color(self.db, top.id))
                it.setFlags(it.flags() | Qt.ItemIsEditable)
                own = fc.get(top.id, {})
                row_total = 0
                for c, m in enumerate(months, start=1):
                    child_sum = sum(fc.get(s.id, {}).get(m, 0) for s in subs)
                    if m in own:
                        v, computed = own[m], False
                    elif child_sum:
                        v, computed = child_sum, True
                    else:
                        v, computed = None, False
                    self._set_cell(it, c, v, bold=True, computed=computed)
                    row_total += v or 0
                    totals[kind][m] += v or 0
                self._set_cell(it, n - 1, row_total or None, bold=True, computed=True)
                for s in subs:
                    ch = SortItem(it, [s.name])
                    ch.setData(0, CAT_ROLE, s.id)
                    ch.setFlags(ch.flags() | Qt.ItemIsEditable)
                    vals = fc.get(s.id, {})
                    for c, m in enumerate(months, start=1):
                        self._set_cell(ch, c, vals.get(m))
                    self._set_cell(ch, n - 1, sum(vals.values()) or None, computed=True)
                it.setExpanded(self._expanded.get(top.id, False))
            sec.setExpanded(True)

        work, other = totals["revenu"], totals["revenu_autre"]
        rev = {m: work[m] + other[m] for m in months}
        dep, neu = totals["depense"], totals["neutre"]
        for title, vals, signed in (("Revenus prévus", rev, False), ("dont travail et substitution", work, False),
                                    ("dont autres revenus", other, False), ("Dépenses prévues", dep, False),
                                    ("Épargne prévue", neu, False),
                                    ("Solde prévisionnel", {m: rev[m] - dep[m] - neu[m] for m in months}, True)):
            t = SortItem(self.tree, [title])
            t.setFlags(t.flags() & ~Qt.ItemIsEditable)
            for c, m in enumerate(months, start=1):
                self._set_cell(t, c, vals[m] if vals[m] or signed else None, signed=signed)
            self._set_cell(t, n - 1, sum(vals.values()), signed=signed)
            style_row(t, n, bold=True, bg=TOTAL_BG)
            if signed:
                for c in range(1, n):
                    v = t.data(c, SORT_ROLE) or 0
                    t.setForeground(c, GREEN if v >= 0 else RED)
        self.tree.setItemDelegateForColumn(n - 1, _ReadOnly(self.tree))
        self.tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree.setColumnWidth(0, 330)
        for c in range(1, n):
            self.tree.setColumnWidth(c, 96)
        self.tree.verticalScrollBar().setValue(scroll)
        self._filling = False
        if self._restore:
            cat, col = self._restore
            it = self._find_item(cat)
            if it is not None and col < self.tree.columnCount():
                self.tree.setCurrentItem(it, col)
        self._selection_hint()

    def _set_cell(self, item, col, cents, bold=False, computed=False, signed=False):
        item.setText(col, fmt_eur(cents, signed=signed) if cents is not None else "")
        item.setData(col, SORT_ROLE, cents or 0)
        item.setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)
        f = QFont()
        f.setBold(bold)
        f.setItalic(computed and col <= len(self.months))
        item.setFont(col, f)
        if computed:
            item.setForeground(col, QBrush(GREY))
            if col <= len(self.months):
                item.setToolTip(col, "Somme des sous-catégories (saisissez un montant pour le remplacer)")

    # --------------------------------------------------------------------- saisie
    def _item_changed(self, item, col):
        if self._filling or col < 1 or col > len(self.months):
            return
        cat = item.data(0, CAT_ROLE)
        if cat is None:
            return
        try:
            cents = parse_eur_input(item.text(col))
        except ValueError:
            error(self, "Montant invalide. Exemples : 350 · 1 250,50")
            QTimer.singleShot(0, self.reload)
            return
        cents = abs(cents) if cents is not None else None
        targets = self.months[col - 1:] if self.autocopy.isChecked() else [self.months[col - 1]]
        self.db.set_forecasts([(cat, m, cents) for m in targets])
        self._restore = (cat, col)
        # rechargement différé : l'élément modifié ne doit pas être détruit pendant son propre signal
        QTimer.singleShot(0, self._after_edit)

    def _after_edit(self):
        self.reload()
        self.changed.emit()

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None or item.data(0, CAT_ROLE) is None:
            return
        col = self.tree.columnAt(pos.x())
        cat = item.data(0, CAT_ROLE)
        name = self.db.category_label(cat)
        menu = QMenu(self)
        if 1 <= col <= len(self.months):
            m = self.months[col - 1]
            value, _computed = self._value_at(cat, m)
            act = menu.addAction(T.icon("compare"), f"Recopier {fmt_eur(value) if value else 'cette valeur'} "
                                                    f"sur les mois suivants (Ctrl+R)",
                                 lambda: self._copy_right(cat, col))
            act.setEnabled(value is not None and col < len(self.months))
            menu.addAction(T.icon("edit"), "Modifier…", lambda: self.tree.editItem(item, col))
            menu.addAction(T.icon("x"), f"Effacer {an.month_label(m)}", lambda: self._set(cat, [m], None))
        menu.addAction(T.icon("trash", T.RED), f"Effacer toute la ligne « {name} »",
                       lambda: self._set(cat, self.months, None))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _find_item(self, cat):
        def walk(item):
            if item.data(0, CAT_ROLE) == cat:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None
        for i in range(self.tree.topLevelItemCount()):
            found = walk(self.tree.topLevelItem(i))
            if found is not None:
                return found
        return None

    def _value_at(self, cat, month):
        """Valeur affichée d'une cellule : montant propre, sinon somme des sous-catégories."""
        own = self.fc.get(cat, {}).get(month)
        if own is not None:
            return own, False
        kids = [c.id for c in self.db.categories().values() if c.parent_id == cat]
        total = sum(self.fc.get(k, {}).get(month, 0) for k in kids)
        return (total, True) if total else (None, False)

    def _selected_cells(self):
        cells = []
        for idx in self.tree.selectedIndexes():
            item = self.tree.itemFromIndex(idx)
            col = idx.column()
            if item is not None and item.data(0, CAT_ROLE) is not None and 1 <= col <= len(self.months):
                cells.append((item.data(0, CAT_ROLE), col))
        if not cells:
            item, col = self.tree.currentItem(), self.tree.currentColumn()
            if item is not None and item.data(0, CAT_ROLE) is not None and 1 <= col <= len(self.months):
                cells.append((item.data(0, CAT_ROLE), col))
        return sorted(set(cells))

    def _selection_hint(self):
        cells = self._selected_cells()
        if not cells:
            self.copy_btn.setEnabled(False)
            self.sel_hint.setText("Cliquez sur une cellule (n'importe quel mois), puis « Recopier vers la droite » ou "
                                  "Ctrl+R. Vous pourrez ensuite modifier un mois suivant et recopier à nouveau à "
                                  "partir de lui en cas d'évolution.")
            return
        self.copy_btn.setEnabled(any(c < len(self.months) for _, c in cells))
        if len(cells) == 1:
            cat, col = cells[0]
            m = self.months[col - 1]
            v, computed = self._value_at(cat, m)
            what = fmt_eur(v) if v is not None else "case vide"
            extra = " (somme des sous-catégories : chacune sera recopiée)" if computed else ""
            if col < len(self.months):
                target = (f"recopier sur <b>{an.month_label(self.months[col])} → "
                          f"{an.month_label(self.months[-1])}</b>")
            else:
                target = "dernier mois affiché, rien à recopier"
            self.sel_hint.setText(f"Sélection : <b>{self.db.category_label(cat)}</b>, {an.month_label(m, full=True)} "
                                  f"= <b>{what}</b>{extra} — Ctrl+R pour {target}.")
        else:
            self.sel_hint.setText(f"{len(cells)} cellules sélectionnées — Ctrl+R pour recopier chacune sur les mois "
                                  f"suivants.")

    def copy_selection_right(self):
        self.copy_right_cells(self._selected_cells())

    def copy_right_cells(self, cells):
        """Recopie chaque cellule (catégorie, colonne) sur tous les mois suivants du tableau."""
        entries = []
        for cat, col in cells:
            m = self.months[col - 1]
            following = self.months[col:]
            if not following:
                continue
            own = self.fc.get(cat, {}).get(m)
            if own is not None:
                entries += [(cat, f, own) for f in following]
            else:
                for c in self.db.categories().values():
                    if c.parent_id == cat:
                        v = self.fc.get(c.id, {}).get(m)
                        if v is not None:
                            entries += [(c.id, f, v) for f in following]
        if not entries:
            info(self, "Rien à recopier : sélectionnez une cellule contenant un montant (avant le dernier mois).")
            return
        if cells:
            self._restore = cells[0]
        self.db.set_forecasts(entries)
        self.reload()
        self.changed.emit()

    def _copy_right(self, cat, col):
        self.copy_right_cells([(cat, col)])

    def _set(self, cat, months, cents):
        self.db.set_forecasts([(cat, m, cents) for m in months])
        self.reload()
        self.changed.emit()

    def copy_first_column(self):
        first = self.months[0]
        entries = [(cat, m, vals[first]) for cat, vals in self.fc.items() if first in vals for m in self.months[1:]]
        if not entries:
            info(self, f"Aucun montant saisi en {an.month_label(first, full=True)}.")
            return
        if not confirm(self, f"Reporter les montants de {an.month_label(first, full=True)} sur les "
                             f"{len(self.months) - 1} mois suivants ?\nLes montants déjà saisis sur ces mois "
                             f"seront remplacés."):
            return
        self.db.set_forecasts(entries)
        self.reload()
        self.changed.emit()

    def prefill(self):
        lo, hi = self.db.date_bounds()
        if not hi:
            info(self, "Importez d'abord un relevé : le pré-remplissage s'appuie sur vos dépenses réelles.")
            return
        end = min(an.add_months(self.months[0], -1), an.ym(hi))
        start = max(an.add_months(end, -11), an.ym(lo))
        avg = self.db.monthly_average(start, end)
        cats = self.db.categories()
        has_children = {c.parent_id for c in cats.values() if c.parent_id is not None}
        entries = []
        for cat, v in avg.items():
            if cat in has_children or v <= 0:
                continue  # catégorie principale détaillée : on remplit ses sous-catégories
            v = round(v / 100) * 100  # à l'euro près
            for m in self.months:
                if m not in self.fc.get(cat, {}):
                    entries.append((cat, m, v))
        if not entries:
            info(self, "Rien à pré-remplir : les cases concernées sont déjà renseignées.")
            return
        if not confirm(self, f"Remplir les cases vides avec la moyenne mensuelle réalisée de "
                             f"{an.period_label(start, end)} ?\nVous pourrez ensuite ajuster chaque montant."):
            return
        self.db.set_forecasts(entries)
        self.reload()
        self.changed.emit()

    def clear_all(self):
        if not confirm(self, f"Effacer tout le prévisionnel de {an.period_label(self.months[0], self.months[-1])} ?"):
            return
        self.db.set_forecasts([(cat, m, None) for cat, vals in self.fc.items() for m in vals])
        self.reload()
        self.changed.emit()

    def export(self, kind):
        months = self.months
        t = TableData("Prévisionnel", an.period_label(months[0], months[-1]),
                      ["Catégorie"] + [an.month_label(m) for m in months] + ["Total"],
                      [TEXT] + [MONEY] * (len(months) + 1))

        def walk(item, depth):
            if item.data(0, CAT_ROLE) is None and depth == 0 and item.childCount():
                t.add([item.text(0)] + [None] * (len(months) + 1), bold=True, shade=True)
            else:
                cells = [item.text(0)] + [item.data(c, SORT_ROLE) or None for c in range(1, len(months) + 2)]
                t.add(cells, bold=depth <= 1, indent=depth, shade=depth == 0)
            for i in range(item.childCount()):
                walk(item.child(i), depth + 1)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i), 0)
        do_export(self, kind, t, f"previsionnel {an.period_label(months[0], months[-1])}")


# ============================================================== Prévu / réalisé
class PlanActualPage(Page):
    changed = Signal()

    MODES = ["Synthèse de la période", "Écarts mois par mois", "Réalisé / prévu mois par mois"]

    def __init__(self, db, parent=None):
        super().__init__("Prévu / réalisé", "Comparez votre prévisionnel à la réalité. Les écarts sont orientés : "
                                            "positif (vert) = favorable (moins dépensé, plus reçu ou épargné).",
                         parent)
        self.db = db
        export_buttons(self, lambda: self.export("excel"), lambda: self.export("pdf"))
        row = FlowLayout()
        row.setSpacing(8)
        self.period = PeriodSelector(self, default="Année en cours")
        row.addWidget(self.period)
        row.addSpacing(10)
        self.mode = QComboBox()
        self.mode.addItems(self.MODES)
        row.addWidget(self.mode)
        row.addStretch()
        self.add(row)

        chart_card = Card(margins=(16, 10, 16, 8))
        chart_card.add(label("Dépenses et revenus : prévu (pointillés) et réalisé (barres)", "sectionTitle"))
        self.canvas = ChartCanvas(chart_card, height=2.2)
        self.canvas.setMinimumHeight(170)
        chart_card.add(self.canvas, 1)
        self.add(chart_card, 2)

        card = Card(margins=(0, 4, 0, 4))
        self.tree = ReportTree(db, card)
        self.tree.itemDoubleClicked.connect(self._open)
        card.add(self.tree, 1)
        self.add(card, 5)
        self.period.changed.connect(self.reload)
        self.mode.currentIndexChanged.connect(self.reload)
        self.report = None

    def refresh(self):
        lo, hi = self.db.date_bounds()
        self.period.set_bounds(lo, hi)
        self.reload()

    def reload(self, *_):
        start, end = self.period.period()
        if not start:
            return
        months = an.month_range(start, end)
        self.months = months
        rep = an.plan_vs_actual(self.db, start, end)
        self.report = rep
        mode = self.mode.currentIndex()

        if mode == 0:
            headers = ["Catégorie", "Prévu", "Réalisé", "Écart", "% du prévu"]

            def writer(item, node):
                p, r = sum(node.plan.values()), node.total(months)
                self._money(item, 1, p)
                self._money(item, 2, r)
                if (p or r) and node.kind != "none":
                    gap = an.favorable_gap(node.kind, p, r, node.label)
                    self._money(item, 3, gap, signed=True, color=GREEN if gap >= 0 else RED)
                if p:
                    ratio = r / p
                    item.setText(4, f"{ratio * 100:.0f} %")
                    item.setData(4, SORT_ROLE, ratio)
                    item.setTextAlignment(4, Qt.AlignRight | Qt.AlignVCenter)
                    if node.kind == "depense" or node.label == "Total dépenses":
                        item.setForeground(4, RED if ratio > 1 else (QBrush_(T.ORANGE) if ratio > 0.9 else GREEN))
        elif mode == 1:
            headers = ["Catégorie"] + [an.month_label(m) for m in months] + ["Total"]

            def writer(item, node):
                tp = tr = 0
                for c, m in enumerate(months, start=1):
                    p, r = node.plan.get(m, 0), node.values.get(m, 0)
                    tp, tr = tp + p, tr + r
                    if node.kind == "none":
                        if r:
                            self._money(item, c, r)
                        continue
                    if p or r:
                        gap = an.favorable_gap(node.kind, p, r, node.label)
                        self._money(item, c, gap, signed=True, color=GREEN if gap >= 0 else RED)
                        item.setToolTip(c, f"Prévu : {fmt_eur(p)}\nRéalisé : {fmt_eur(r)}")
                if (tp or tr) and node.kind != "none":
                    gap = an.favorable_gap(node.kind, tp, tr, node.label)
                    self._money(item, len(months) + 1, gap, signed=True, color=GREEN if gap >= 0 else RED)
                    item.setToolTip(len(months) + 1, f"Prévu : {fmt_eur(tp)}\nRéalisé : {fmt_eur(tr)}")
        else:
            headers = ["Catégorie"] + [an.month_label(m) for m in months]

            def writer(item, node):
                for c, m in enumerate(months, start=1):
                    p, r = node.plan.get(m, 0), node.values.get(m, 0)
                    if not (p or r):
                        continue
                    item.setText(c, f"{fmt_eur(r, symbol=False)} / {fmt_eur(p, symbol=False) if p else '—'}")
                    item.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
                    item.setToolTip(c, f"Réalisé : {fmt_eur(r)}\nPrévu : {fmt_eur(p)}")
                    if p:
                        gap = an.favorable_gap(node.kind, p, r, node.label)
                        item.setForeground(c, GREEN if gap >= 0 else RED)

        self.headers = headers
        self.tree.fill(rep, headers, writer)
        self._draw_chart(rep, months)

    @staticmethod
    def _money(item, col, cents, signed=False, color=None):
        item.setText(col, fmt_eur(cents, signed=signed, blank_zero=not signed))
        item.setData(col, SORT_ROLE, cents or 0)
        item.setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)
        if color is not None:
            item.setForeground(col, color)

    def _draw_chart(self, rep, months):
        rev, dep = rep.total("rev"), rep.total("dep")
        fig = self.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        x = list(range(len(months)))
        w = 0.36
        ax.bar([i - w / 2 for i in x], [rev.values.get(m, 0) / 100 for m in months], w, color="#32D583",
               label="Revenus réalisés")
        ax.bar([i + w / 2 for i in x], [dep.values.get(m, 0) / 100 for m in months], w, color=T.ACCENT,
               label="Dépenses réalisées")
        if any(rev.plan.values()):
            ax.plot([i - w / 2 for i in x], [rev.plan.get(m, 0) / 100 for m in months], color="#067647",
                    linestyle="--", marker="_", markersize=14, linewidth=1.2, label="Revenus prévus")
        if any(dep.plan.values()):
            ax.plot([i + w / 2 for i in x], [dep.plan.get(m, 0) / 100 for m in months], color=T.TEXT,
                    linestyle="--", marker="_", markersize=14, linewidth=1.2, label="Dépenses prévues")
        ax.set_xticks(x, [an.month_label(m).split()[0].capitalize() for m in months], fontsize=8)
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), borderaxespad=0, handlelength=1.2, columnspacing=1.2, ncol=4, fontsize=7.5)
        top = max([v / 100 for t in (rev, dep) for v in list(t.values.values()) + list(t.plan.values())] + [1])
        ax.set_ylim(top=top * 1.05)
        euro_axis(ax)
        self.canvas.draw_idle()

    def _open(self, item, col):
        node = item.data(0, NODE_ROLE)
        if node is None or not node.cat_ids:
            return
        mode = self.mode.currentIndex()
        if mode in (1, 2) and 1 <= col <= len(self.months):
            start = end = self.months[col - 1]
        else:
            start, end = self.months[0], self.months[-1]
        dlg = OperationsDialog(self.db, node.label, node.cat_ids, start, end, self)
        dlg.exec()
        if dlg.dirty:
            self.reload()
            self.changed.emit()

    def export(self, kind):
        months = self.months
        mode = self.mode.currentIndex()
        if mode == 0:
            t = TableData("Prévu / réalisé", self.period.label(), self.headers, [TEXT, MONEY, MONEY, MONEY, PCT])

            def values(n):
                p, r = sum(n.plan.values()), n.total(months)
                return [p, r, an.favorable_gap(n.kind, p, r, n.label) if (p or r) else None,
                        (r / p - 1) if p else None]
        elif mode == 1:
            t = TableData("Écarts prévu / réalisé", f"{self.period.label()} — positif = favorable", self.headers,
                          [TEXT] + [MONEY] * (len(months) + 1))

            def values(n):
                out = [an.favorable_gap(n.kind, n.plan.get(m, 0), n.values.get(m, 0), n.label)
                       if (n.plan.get(m) or n.values.get(m)) else None for m in months]
                tp, tr = sum(n.plan.values()), n.total(months)
                return out + [an.favorable_gap(n.kind, tp, tr, n.label) if (tp or tr) else None]
        else:
            headers = ["Catégorie"]
            for m in months:
                headers += [f"{an.month_label(m)} prévu", f"{an.month_label(m)} réalisé"]
            t = TableData("Prévu / réalisé par mois", self.period.label(), headers,
                          [TEXT] + [MONEY] * (2 * len(months)))

            def values(n):
                out = []
                for m in months:
                    out += [n.plan.get(m) or None, n.values.get(m) or None]
                return out
        report_to_rows(t, self.report, values)
        do_export(self, kind, t, f"prevu realise {self.period.label()}")


def QBrush_(color):
    from PySide6.QtGui import QColor
    return QBrush(QColor(color))


__all__ = ["ForecastPage", "PlanActualPage", "TEXT_COLOR", "fmt_pct"]
