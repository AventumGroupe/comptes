"""Détail chiffré derrière un graphique : répartition par catégorie / sous-catégorie et opérations.

``ChartClicks`` rend les éléments d'un graphique matplotlib cliquables (et affiche le montant au
survol) ; un clic ouvre ``BreakdownDialog``."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QSplitter, QStyle,
                               QStyledItemDelegate, QToolTip, QTreeWidget, QVBoxLayout)

from .. import analytics as an
from ..db import KIND_ORDER
from ..money import fmt_eur
from . import theme as T
from .common import (COLOR_ROLE, GREY, SECTION_BG, SORT_ROLE, Card, DotDelegate, SortItem, bold_font, button,
                     label, set_money, style_row, style_tree)

IDS_ROLE = Qt.UserRole + 40
RATIO_ROLE = Qt.UserRole + 41
SECTION_NAMES = {"revenu": "Revenus du travail et de substitution", "revenu_autre": "Autres revenus",
                 "depense": "Dépenses", "neutre": "Épargne et mouvements internes"}


class RatioDelegate(QStyledItemDelegate):
    """Pourcentage avec une petite barre de proportion."""

    def paint(self, painter, option, index):
        ratio = index.data(RATIO_ROLE)
        self.initStyleOption(option, index)
        text = option.text
        option.text = ""
        option.widget.style().drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        if ratio is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect.adjusted(8, 0, -8, 0)
        bar_w = max(r.width() - 52, 20)
        track = QRectF(r.left(), r.center().y() - 3, bar_w, 6)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(T.HOVER))
        painter.drawRoundedRect(track, 3, 3)
        painter.setBrush(QColor(index.data(COLOR_ROLE) or T.ACCENT))
        painter.drawRoundedRect(QRectF(track.left(), track.top(), max(4, bar_w * min(ratio, 1)), 6), 3, 3)
        painter.setPen(QColor(T.MUTED))
        painter.drawText(r.adjusted(bar_w + 6, 0, 0, 0), Qt.AlignVCenter | Qt.AlignRight, text)
        painter.restore()


class BreakdownDialog(QDialog):
    """Répartition par catégorie du périmètre (cat_ids) sur la période, puis les opérations."""

    def __init__(self, db, title, cat_ids, start, end, parent=None):
        super().__init__(parent)
        from .operations_tab import OperationsPanel
        self.db, self.title, self.start, self.end = db, title, start, end
        self.scope = set(cat_ids or [])
        self.dirty = False
        self.setWindowTitle(title)
        self.resize(1000, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(title, "title"))
        titles.addWidget(label(an.period_label(start, end), "subtitle"))
        head.addLayout(titles, 1)
        self.total_label = label("", "kpiValue")
        head.addWidget(self.total_label, 0, Qt.AlignRight | Qt.AlignVCenter)
        lay.addLayout(head)

        split = QSplitter(Qt.Vertical)
        top = Card(margins=(0, 6, 0, 4))
        th = QHBoxLayout()
        th.setContentsMargins(16, 0, 16, 0)
        th.addWidget(label("Répartition par catégorie", "sectionTitle"))
        th.addStretch()
        th.addWidget(label("Cliquez sur une ligne pour filtrer les opérations", "muted"))
        top.add(th)
        self.tree = QTreeWidget()
        style_tree(self.tree)
        self.tree.setHeaderLabels(["CATÉGORIE", "MONTANT", "PART DU TOTAL", "OPÉRATIONS"])
        self.tree.setItemDelegateForColumn(0, DotDelegate(self.tree))
        self.tree.setItemDelegateForColumn(2, RatioDelegate(self.tree))
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.setColumnWidth(2, 220)
        for c in (1, 3):
            self.tree.headerItem().setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
        self.tree.currentItemChanged.connect(self._filter_ops)
        top.add(self.tree, 1)
        split.addWidget(top)

        bottom = Card()
        bh = QHBoxLayout()
        self.ops_title = label("Opérations", "sectionTitle")
        bh.addWidget(self.ops_title)
        bh.addStretch()
        self.all_btn = button("Toutes les catégories", None, "link", slot=self._show_all)
        bh.addWidget(self.all_btn)
        bottom.add(bh)
        self.panel = OperationsPanel(db, bottom)
        self.panel.changed.connect(self._ops_changed)
        bottom.add(self.panel, 1)
        split.addWidget(bottom)
        split.setSizes([330, 330])
        lay.addWidget(split, 1)
        self.reload()

    # ------------------------------------------------------------------
    def reload(self):
        cats = self.db.categories()
        raw = an.raw_sums(self.db, self.start, self.end, by_month=False)
        counts = dict(self.db.conn.execute(
            "SELECT category_id, COUNT(*) FROM operations WHERE date >= ? AND date <= ? GROUP BY category_id",
            (an.month_first_day(self.start), an.month_last_day(self.end))).fetchall())
        groups = {}
        for top, subs in self.db.category_tree():
            if top.id not in self.scope and not any(s.id in self.scope for s in subs):
                continue
            sign = an.sign_for(top.kind)
            own = raw.get(top.id, 0) * sign if top.id in self.scope else 0
            rows = [(s, raw.get(s.id, 0) * sign, counts.get(s.id, 0)) for s in subs if s.id in self.scope]
            rows = [r for r in rows if r[1] or r[2]]
            total = own + sum(v for _, v, _ in rows)
            n = (counts.get(top.id, 0) if top.id in self.scope else 0) + sum(c for _, _, c in rows)
            if not total and not n:
                continue
            groups.setdefault(top.kind, []).append((top, total, n, own, rows))
        uncategorized = None in self.scope
        unc_val = raw.get(None, 0) if uncategorized else 0

        grand = sum(t for g in groups.values() for _, t, _, _, _ in g) + unc_val
        self.total_label.setText(fmt_eur(grand))
        self.tree.clear()
        multi = len(groups) > 1
        for kind in sorted(groups, key=lambda k: KIND_ORDER.get(k, 9)):
            entries = sorted(groups[kind], key=lambda e: -abs(e[1]))
            parent = self.tree
            if multi:
                sec_total = sum(e[1] for e in entries)
                sec = SortItem(self.tree, [SECTION_NAMES.get(kind, kind).upper()])
                set_money(sec, 1, sec_total)
                self._ratio(sec, sec_total, grand, None)
                sec.setText(3, str(sum(e[2] for e in entries)))
                sec.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
                sec.setData(0, IDS_ROLE, [c for e in entries for c in self._ids(e)])
                sec.setData(0, Qt.UserRole, SECTION_NAMES.get(kind, kind))
                style_row(sec, 4, bold=True, bg=SECTION_BG, fg=GREY)
                sec.setExpanded(True)
                parent = sec
            for top, total, n, own, rows in entries:
                color = T.category_color(self.db, top.id)
                it = SortItem(parent, [top.name])
                it.setData(0, COLOR_ROLE, color)
                it.setData(0, IDS_ROLE, self._ids((top, total, n, own, rows)))
                it.setData(0, Qt.UserRole, top.name)
                set_money(it, 1, total)
                self._ratio(it, total, grand, color)
                it.setText(3, str(n))
                it.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
                for c in range(4):
                    it.setFont(c, bold_font())
                if own and rows:
                    ch = SortItem(it, [f"{top.name} (sans sous-catégorie)"])
                    ch.setData(0, IDS_ROLE, [top.id])
                    ch.setData(0, Qt.UserRole, top.name)
                    set_money(ch, 1, own)
                    self._ratio(ch, own, grand, color)
                    ch.setText(3, str(counts.get(top.id, 0)))
                    ch.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
                for s, v, c in sorted(rows, key=lambda r: -abs(r[1])):
                    ch = SortItem(it, [s.name])
                    ch.setData(0, IDS_ROLE, [s.id])
                    ch.setData(0, Qt.UserRole, f"{top.name} › {s.name}")
                    set_money(ch, 1, v)
                    self._ratio(ch, v, grand, color)
                    ch.setText(3, str(c))
                    ch.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
                it.setExpanded(True)
        if uncategorized and unc_val:
            it = SortItem(self.tree, ["Opérations à classer"])
            it.setData(0, COLOR_ROLE, QColor(T.ORANGE))
            it.setData(0, IDS_ROLE, [None])
            it.setData(0, Qt.UserRole, "Opérations à classer")
            set_money(it, 1, unc_val)
            self._ratio(it, unc_val, grand, QColor(T.ORANGE))
            it.setText(3, str(counts.get(None, 0)))
            it.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
        self._show_all()

    def _ids(self, entry):
        top, _t, _n, own, rows = entry
        return ([top.id] if top.id in self.scope else []) + [s.id for s, _, _ in rows]

    @staticmethod
    def _ratio(item, value, grand, color):
        ratio = (value / grand) if grand else None
        item.setText(2, f"{ratio * 100:.0f} %" if ratio is not None else "")
        item.setData(2, RATIO_ROLE, abs(ratio) if ratio is not None else None)
        item.setData(2, SORT_ROLE, ratio or 0)
        if color is not None:
            item.setData(2, COLOR_ROLE, color)

    # ------------------------------------------------------------------
    def _rows_for(self, ids, name):
        if ids == [None]:
            rows = self.db.operations(start=an.month_first_day(self.start), end=an.month_last_day(self.end),
                                      uncategorized=True)
        else:
            real = [i for i in ids if i is not None]
            rows = self.db.operations(start=an.month_first_day(self.start), end=an.month_last_day(self.end),
                                      cat_ids=real) if real else []
            if None in ids:
                rows = list(rows) + list(self.db.operations(start=an.month_first_day(self.start),
                                                            end=an.month_last_day(self.end), uncategorized=True))
        self.panel.set_rows(rows)
        self.ops_title.setText(f"Opérations — {name}")

    def _filter_ops(self, item, _prev=None):
        if item is None:
            return
        self._rows_for(item.data(0, IDS_ROLE) or [], item.data(0, Qt.UserRole) or item.text(0))
        self.all_btn.setVisible(True)

    def _show_all(self):
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(None)
        self.tree.clearSelection()
        self.tree.blockSignals(False)
        self._rows_for(sorted(self.scope, key=lambda x: (x is None, x or 0)), self.title)
        self.all_btn.setVisible(False)

    def _ops_changed(self):
        self.dirty = True
        self.reload()


class ChartClicks:
    """Rend des éléments de graphique cliquables (détail) et affiche leur montant au survol."""

    def __init__(self, canvas, db, owner, on_change=None):
        self.canvas, self.db, self.owner, self.on_change = canvas, db, owner, on_change
        self.targets = {}
        self._last_click = None
        self._last_hover = None
        canvas.mpl_connect("pick_event", self._on_pick)
        canvas.mpl_connect("motion_notify_event", self._on_move)

    def clear(self):
        self.targets = {}
        self._last_hover = None

    def register(self, artist, title, cat_ids, start, end, amount=None):
        artist.set_picker(True)
        self.targets[artist] = (title, list(cat_ids), start, end, amount)

    def _hit(self, event):
        for a in self.targets:
            if a.figure is not None and a.contains(event)[0]:
                return a
        return None

    def _on_move(self, event):
        a = self._hit(event)
        self.canvas.setCursor(Qt.PointingHandCursor if a is not None else Qt.ArrowCursor)
        if a is None:
            if self._last_hover is not None:
                QToolTip.hideText()
            self._last_hover = None
            return
        if a is self._last_hover:
            return
        self._last_hover = a
        title, _ids, _s, _e, amount = self.targets[a]
        text = f"<b>{title}</b>"
        if amount is not None:
            text += f"<br>{fmt_eur(amount)}"
        text += f"<br><span style='color:{T.SUBTLE}'>Cliquez pour le détail</span>"
        QToolTip.showText(QCursor.pos(), text, self.canvas)

    def _on_pick(self, event):
        target = self.targets.get(event.artist)
        if target is None or self._last_click is event.mouseevent:
            return
        self._last_click = event.mouseevent
        QToolTip.hideText()
        title, cat_ids, start, end, _amount = target
        dlg = BreakdownDialog(self.db, title, cat_ids, start, end, self.owner)
        dlg.exec()
        if dlg.dirty and self.on_change:
            self.on_change()
