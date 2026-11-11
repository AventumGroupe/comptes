"""Page « Tableau de bord » : indicateurs clés, évolution, principales dépenses."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractItemView, QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import analytics as an
from ..db import NONE
from ..money import fmt_eur, fmt_pct, pct_change
from . import theme as T
from .common import Card, ChartCanvas, OperationsView, Page, PeriodSelector, button, euro_axis, label


class KpiCard(Card):
    def __init__(self, title, parent=None):
        super().__init__(parent, margins=(18, 14, 18, 14), spacing=4)
        self.title = label(title.upper(), "kpiLabel")
        self.value = label("—", "kpiValue")
        self.delta = label("", "muted")
        self.delta.setTextFormat(Qt.RichText)
        self.extra = label("", "muted")
        self.extra.setStyleSheet("font-size:8.5pt")
        self.extra.hide()
        self.add(self.title)
        self.add(self.value)
        self.add(self.extra)
        self.add(self.delta)

    def set(self, cents, previous, good_when_up=True, color=None, ref="vs période précédente"):
        self.value.setText(fmt_eur(cents))
        self.value.setStyleSheet(f"color:{color}" if color else "")
        p = pct_change(cents, previous)
        if p is None:
            self.delta.setText("<span style='color:%s'>pas de point de comparaison</span>" % T.SUBTLE)
            return
        up = p > 0
        good = up == good_when_up
        col = T.GREEN if good else T.RED
        arrow = "▲" if up else "▼"
        self.delta.setText(f"<span style='color:{col}; font-weight:600'>{arrow} {fmt_pct(p)}</span>"
                           f"<span style='color:{T.MUTED}'>  {ref}</span>")


class CategoryBar(QWidget):
    """Ligne « pastille · nom · montant » avec barre de proportion."""
    clicked = Signal(int)

    def __init__(self, name, color, amount, ratio, delta, cat_id, parent=None):
        super().__init__(parent)
        self.name, self.color, self.amount, self.ratio, self.delta, self.cat_id = (
            name, QColor(color), amount, ratio, delta, cat_id)
        self.setMinimumHeight(42)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Voir le détail de la catégorie")

    def mousePressEvent(self, e):
        self.clicked.emit(self.cat_id)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(2, 2, -2, -2)
        fm = p.fontMetrics()
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(QRectF(r.left(), r.top() + 6, 9, 9))
        p.setPen(QColor(T.TEXT))
        f = p.font()
        f.setBold(True)
        p.setFont(f)
        p.drawText(r.left() + 18, r.top() + 15, self.name)
        amount = fmt_eur(self.amount)
        p.drawText(r.right() - fm.horizontalAdvance(amount) - 70, r.top() + 15, amount)
        f.setBold(False)
        p.setFont(f)
        if self.delta is not None:
            col = QColor(T.RED if self.delta > 0 else T.GREEN)
            p.setPen(col)
            txt = fmt_pct(self.delta)
            p.drawText(r.right() - fm.horizontalAdvance(txt), r.top() + 15, txt)
        track = QRectF(r.left() + 18, r.top() + 24, r.width() - 18, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T.HOVER))
        p.drawRoundedRect(track, 3, 3)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(track.left(), track.top(), max(6, track.width() * self.ratio), 6), 3, 3)


class DashboardPage(Page):
    go_todo = Signal()
    go_operations = Signal()
    open_category = Signal(int)
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__("Tableau de bord", "Vue d'ensemble de vos finances.", parent, scroll=True)
        self.db = db
        self.period = PeriodSelector(self, default="Dernier mois")
        self.add_action(self.period)

        # bandeau « à classer »
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 10, 14, 10)
        ic = QLabel()
        ic.setPixmap(T.pixmap("alert", T.ORANGE, 20))
        bl.addWidget(ic)
        self.banner_text = label("")
        self.banner_text.setStyleSheet(f"color:{T.ORANGE}; font-weight:600")
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(button("Classer maintenant", None, "primary", slot=lambda: self.go_todo.emit()))
        self.add(self.banner)

        self.grid = QGridLayout()
        self.grid.setSpacing(14)
        self.k_rev = KpiCard("Revenus")
        self.k_dep = KpiCard("Dépenses")
        self.k_net = KpiCard("Revenus − dépenses")
        self.k_sav = KpiCard("Épargne et virements")
        self.kpis = (self.k_rev, self.k_dep, self.k_net, self.k_sav)
        self._kpi_cols = None
        self._place_kpis(4)
        self.add(self.grid)

        row = QBoxLayout(QBoxLayout.LeftToRight)
        row.setSpacing(14)
        self.row = row
        chart_card = Card()
        self.chart_card = chart_card
        chart_card.add(label("Évolution sur 12 mois", "sectionTitle"))
        self.canvas = ChartCanvas(chart_card, height=3.2)
        chart_card.add(self.canvas, 1)
        row.addWidget(chart_card, 3)
        top_card = Card()
        th = QHBoxLayout()
        th.addWidget(label("Principales dépenses", "sectionTitle"))
        th.addStretch()
        self.top_period = label("", "muted")
        th.addWidget(self.top_period)
        top_card.add(th)
        self.top_box = QVBoxLayout()
        self.top_box.setSpacing(2)
        top_card.add(self.top_box)
        top_card.layout_.addStretch()
        row.addWidget(top_card, 2)
        self.add(row, 3)

        last_card = Card(margins=(16, 12, 16, 8))
        last_card.setMinimumHeight(230)
        lh = QHBoxLayout()
        lh.addWidget(label("Dernières opérations", "sectionTitle"))
        lh.addStretch()
        lh.addWidget(button("Tout voir", None, "link", slot=lambda: self.go_operations.emit()))
        last_card.add(lh)
        self.last = OperationsView(db, last_card)
        self.last.setSortingEnabled(False)
        self.last.setSelectionMode(QAbstractItemView.NoSelection)
        self.last.hideColumn(5)
        last_card.add(self.last, 1)
        self.add(last_card, 2)

        self.period.changed.connect(self.reload)

    # ------------------------------------------------------------ adaptatif
    def _place_kpis(self, cols):
        if cols == self._kpi_cols:
            return
        self._kpi_cols = cols
        for k in self.kpis:
            self.grid.removeWidget(k)
        for i, k in enumerate(self.kpis):
            self.grid.addWidget(k, i // cols, i % cols)
        for c in range(4):
            self.grid.setColumnStretch(c, 1 if c < cols else 0)

    def on_resize(self, width):
        # 4 cartes côte à côte seulement si elles tiennent sans être tronquées
        need = 4 * max(k.minimumSizeHint().width() for k in self.kpis) + 3 * 14 + 70
        self._place_kpis(4 if width >= need else 2)
        stacked = width < 1050
        self.row.setDirection(QBoxLayout.TopToBottom if stacked else QBoxLayout.LeftToRight)
        self.chart_card.setMinimumHeight(300 if stacked else 0)

    def refresh(self):
        self.period.set_bounds(*self.db.date_bounds())
        self.reload()

    def reload(self, *_):
        start, end = self.period.period()
        n = len(an.month_range(start, end))
        pstart, pend = an.add_months(start, -n), an.add_months(end, -n)
        cur = an.pivot(self.db, start, end)
        prev = an.pivot(self.db, pstart, pend)
        months, pmonths = cur.columns, prev.columns

        def tot(rep, key, cols):
            return rep.total(key).total(cols)

        def neutral(rep, cols):
            return sum(nd.total(cols) for _, k, ns in rep.sections if k == "neutre" for nd in ns)

        self.k_rev.set(tot(cur, "rev", months), tot(prev, "rev", pmonths), True, T.GREEN)
        self.k_rev.extra.setText(f"dont travail {fmt_eur(tot(cur, 'work', months))} · "
                                 f"autres {fmt_eur(tot(cur, 'other', months))}")
        self.k_rev.extra.show()
        self.k_dep.set(tot(cur, "dep", months), tot(prev, "dep", pmonths), False)
        net = tot(cur, "net", months)
        self.k_net.set(net, tot(prev, "net", pmonths), True, T.GREEN if net >= 0 else T.RED)
        self.k_sav.set(neutral(cur, months), neutral(prev, pmonths), True)

        counts = self.db.count_by_status()
        todo = counts.get(NONE, 0)
        self.banner.setVisible(todo > 0)
        self.banner_text.setText(f"{todo} opération(s) en attente de classement : vos analyses seront plus justes "
                                 f"une fois tout classé.")

        # principales dépenses
        while self.top_box.count():
            w = self.top_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        prev_by_cat = {nd.cat_id: nd.total(pmonths) for _, k, ns in prev.sections if k == "depense" for nd in ns}
        nodes = [nd for _, k, ns in cur.sections if k == "depense" for nd in ns if nd.total(months) > 0]
        nodes.sort(key=lambda nd: -nd.total(months))
        biggest = nodes[0].total(months) if nodes else 1
        self.top_period.setText(an.period_label(start, end))
        for nd in nodes[:7]:
            v = nd.total(months)
            bar = CategoryBar(nd.label, T.category_color(self.db, nd.cat_id), v, v / biggest,
                              pct_change(v, prev_by_cat.get(nd.cat_id, 0)), nd.cat_id)
            bar.clicked.connect(self.open_category.emit)
            self.top_box.addWidget(bar)
        if not nodes:
            self.top_box.addWidget(label("Aucune dépense classée sur la période.", "muted"))

        # graphique 12 mois
        e = end
        s = an.add_months(e, -11)
        data = an.monthly_totals(self.db, s, e)
        fig = self.canvas.figure
        fig.clear()
        ax = fig.add_subplot(111)
        x = list(range(len(data)))
        w = 0.36
        rep12 = an.pivot(self.db, s, e)
        work = [rep12.total("work").values.get(m, 0) / 100 for m, _, _ in data]
        other = [rep12.total("other").values.get(m, 0) / 100 for m, _, _ in data]
        ax.bar([i - w / 2 for i in x], work, w, color="#32D583", label="Revenus du travail")
        if any(other):
            ax.bar([i - w / 2 for i in x], other, w, bottom=work, color="#A6F4C5", label="Autres revenus")
        ax.bar([i + w / 2 for i in x], [d / 100 for _, _, d in data], w, color=T.ACCENT, label="Dépenses")
        ax.plot(x, [(r - d) / 100 for _, r, d in data], color=T.TEXT, marker="o", markersize=3.5, linewidth=1.4,
                label="Revenus − dépenses")
        ax.axhline(0, color=T.BORDER_STRONG, linewidth=0.8)
        ax.set_xticks(x, [an.month_label(m).split()[0].capitalize() for m, _, _ in data])
        top = max([r / 100 for _, r, _ in data] + [d / 100 for _, _, d in data] + [1])
        ax.set_ylim(top=top * 1.05)
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.01), ncol=4, fontsize=7.5, borderaxespad=0,
                  handlelength=1.2, columnspacing=1.2)
        euro_axis(ax)
        self.canvas.draw_idle()

        rows = self.db.operations()[:8]
        self.last.set_rows(rows)
