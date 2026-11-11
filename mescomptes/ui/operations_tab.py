"""Page « Opérations » : liste filtrable + volet de classement ; panneau réutilisable."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QMenu, QPushButton, QVBoxLayout, QWidget

from .. import analytics as an
from ..db import AUTO, MANUAL, NONE, STATUS_LABELS
from ..exporters import DATE, MONEY, TEXT, TableData, export_excel
from ..money import fmt_eur
from . import theme as T
from .classify import ClassifyDialog, ClassifyPanel
from .common import (FlowLayout, Card, CategoryCombo, OperationsView, Page, PeriodSelector, button, confirm, info, label,
                     save_path, search_box)


def build_context_menu(parent, db, sel, classify_cb, validate_cb, release_cb, delete_cb):
    menu = QMenu(parent)
    menu.addAction(T.icon("tag"), "Classer…", classify_cb)
    quick = menu.addMenu("Classer dans")
    for top, subs in db.category_tree():
        if subs:
            sub_menu = quick.addMenu(top.name)
            sub_menu.addAction(f"{top.name} (général)", lambda c=top.id: classify_cb(c))
            sub_menu.addSeparator()
            for s in subs:
                sub_menu.addAction(s.name, lambda c=s.id: classify_cb(c))
        else:
            quick.addAction(top.name, lambda c=top.id: classify_cb(c))
    if any(r["status"] == AUTO for r in sel):
        menu.addAction(T.icon("check"), "Valider la suggestion", validate_cb)
    if any(r["status"] == MANUAL for r in sel):
        menu.addAction(T.icon("undo"), "Annuler la validation", release_cb)
    menu.addSeparator()
    menu.addAction(T.icon("trash", T.RED), "Supprimer l'opération…", delete_cb)
    return menu


class OperationsPanel(QWidget):
    """Table d'opérations avec classement par double-clic (utilisée dans les vues de détail)."""
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        bar = QHBoxLayout()
        self.footer = label("", "muted")
        bar.addWidget(self.footer)
        bar.addStretch()
        bar.addWidget(label("Double-clic pour classer · clic droit pour plus d'actions", "muted"))
        lay.addLayout(bar)
        self.view = OperationsView(db, self)
        self.view.doubleClicked.connect(self._double_click)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        lay.addWidget(self.view, 1)

    def set_rows(self, rows):
        self.view.set_rows(rows)
        self.footer.setText(f"{len(rows)} opération(s) · total {fmt_eur(sum(r['amount'] for r in rows))}")

    def _double_click(self, index):
        if index.column() != self.view.model_.COL_NOTE:
            self.classify_selected()

    def classify_selected(self, preset_category=None):
        sel = self.view.selected_rows()
        if sel and ClassifyDialog(self.db, sel, self, preset_category=preset_category).exec() == QDialog.Accepted:
            self.changed.emit()

    def validate_selected(self):
        ids = [r["id"] for r in self.view.selected_rows() if r["status"] == AUTO]
        if ids:
            self.db.validate(ids)
            self.changed.emit()

    def release_selected(self):
        ids = [r["id"] for r in self.view.selected_rows() if r["status"] == MANUAL]
        if ids:
            self.db.release(ids)
            self.changed.emit()

    def delete_selected(self):
        sel = self.view.selected_rows()
        if sel and confirm(self, f"Supprimer définitivement {len(sel)} opération(s) ?\n"
                                 "(Elles seront réimportées si vous réimportez le même relevé.)"):
            self.db.delete_operations([r["id"] for r in sel])
            self.changed.emit()

    def _context_menu(self, pos):
        sel = self.view.selected_rows()
        if sel:
            build_context_menu(self, self.db, sel, self.classify_selected, self.validate_selected,
                               self.release_selected, self.delete_selected).exec(self.view.viewport().mapToGlobal(pos))


class OperationsTab(Page):
    changed = Signal()
    import_requested = Signal()

    STATUS_CHIPS = [("Toutes", None), ("À classer", NONE), ("À vérifier", AUTO), ("Validées", MANUAL)]

    def __init__(self, db, parent=None):
        super().__init__("Opérations", "Classez vos opérations : l'application mémorise vos choix pour les suivantes.",
                         parent)
        self.db = db
        self.add_action(button("Exporter", "download", tooltip="Exporter la liste affichée (Excel)",
                               slot=self.export_excel))
        self.add_action(button("Importer un relevé", "upload", "primary", slot=lambda: self.import_requested.emit()))

        # pastilles de statut
        chips = FlowLayout()
        chips.setSpacing(8)
        self.chips = []
        for text, status in self.STATUS_CHIPS:
            b = QPushButton(text)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, s=status: self.set_status_filter(s))
            chips.addWidget(b)
            self.chips.append((b, status, text))
        self.chips[0][0].setChecked(True)
        chips.addStretch()
        self.period = PeriodSelector(self, default="Tout l'historique")
        chips.addWidget(self.period)
        self.add(chips)

        # filtres
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = search_box("Rechercher un libellé, un fournisseur, une note…")
        filters.addWidget(self.search, 1)
        self.cat_filter = CategoryCombo(self, with_all=True, with_none=True)
        filters.addWidget(self.cat_filter)
        self.dir_filter = QComboBox()
        for text, val in (("Débits et crédits", None), ("Débits", "debit"), ("Crédits", "credit")):
            self.dir_filter.addItem(text, val)
        filters.addWidget(self.dir_filter)
        self.add(filters)

        # liste + volet
        body = QHBoxLayout()
        body.setSpacing(0)
        card = Card(margins=(0, 4, 0, 0), spacing=0)
        self.view = OperationsView(db, card)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.view.hideColumn(self.view.model_.COL_NOTE)  # la note se saisit dans le volet
        self.view.setColumnWidth(self.view.model_.COL_CAT, 210)
        self.view.setColumnWidth(self.view.model_.COL_STATUS, 100)
        card.add(self.view, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(14, 8, 14, 8)
        self.footer = label("", "muted")
        foot.addWidget(self.footer)
        foot.addStretch()
        self.progress = label("", "muted")
        foot.addWidget(self.progress)
        self.show_panel_btn = button("Afficher le volet de classement", "tag", "link", slot=self._show_panel)
        self.show_panel_btn.hide()
        foot.addWidget(self.show_panel_btn)
        card.add(foot)
        body.addWidget(card, 1)
        self.panel = ClassifyPanel(db, self)
        self.panel.setStyleSheet(f"QFrame#drawer {{ border: 1px solid {T.BORDER}; border-radius: 12px; }}")
        self.panel.applied.connect(self._applied)
        self.panel.close_requested.connect(self._hide_panel)
        body.addSpacing(14)
        body.addWidget(self.panel)
        self.add(body, 1)

        self.status = None
        self.period.changed.connect(self.reload)
        self.cat_filter.currentIndexChanged.connect(self.reload)
        self.dir_filter.currentIndexChanged.connect(self.reload)
        self.search.textChanged.connect(self.reload)

    # ------------------------------------------------------------------
    def on_resize(self, width):
        narrow = width < 1150
        m = self.view.model_
        self.view.setColumnHidden(m.COL_STATUS, narrow)   # le statut reste visible dans le volet
        self.view.setColumnWidth(m.COL_CAT, 170 if narrow else 210)
        self.view.setColumnWidth(m.COL_DATE, 86 if narrow else 96)

    def refresh(self):
        self.cat_filter.populate(self.db)
        self.panel.refresh_categories()
        self.period.set_bounds(*self.db.date_bounds())
        self.reload()

    def set_status_filter(self, status):
        self.status = status
        for b, s, _ in self.chips:
            b.setChecked(s == status)
        self.reload()

    def reload(self, *_, keep_ids=None):
        start, end = self.period.period()
        cat = self.cat_filter.currentData()
        kwargs = {}
        if cat == CategoryCombo.NONE:
            kwargs["uncategorized"] = True
        elif cat not in (None, CategoryCombo.ALL):
            kwargs["cat_ids"] = self.db.descendants(cat)
        rows = self.db.operations(start=an.month_first_day(start) if start else None,
                                  end=an.month_last_day(end) if end else None,
                                  status=self.status, direction=self.dir_filter.currentData(),
                                  text=self.search.text().strip() or None, **kwargs)
        self.view.set_rows(rows)
        self.footer.setText(f"{len(rows)} opération(s) · total {fmt_eur(sum(r['amount'] for r in rows))}")
        counts = self.db.count_by_status()
        total = sum(counts.values())
        for b, s, text in self.chips:
            n = total if s is None else counts.get(s, 0)
            b.setText(f"{text}  {n}")
        done = counts.get(MANUAL, 0) + counts.get(AUTO, 0)
        self.progress.setText(f"{done / total * 100:.0f} % des opérations classées" if total else "")
        if keep_ids:
            for op_id in keep_ids:
                self.view.select_id(op_id)
        if not self.view.selected_rows():
            self.panel.set_ops([])

    def show_todo(self):
        self._reset_filters()
        self.set_status_filter(NONE)
        if self.view.proxy.rowCount():
            self.view.selectRow(0)

    def show_auto(self):
        self._reset_filters()
        self.set_status_filter(AUTO)

    def _reset_filters(self):
        for w in (self.period, self.cat_filter, self.dir_filter, self.search):
            w.blockSignals(True)
        self.period.preset.setCurrentText("Tout l'historique")
        self.period._apply_preset("Tout l'historique", emit=False)
        self.cat_filter.setCurrentIndex(0)
        self.dir_filter.setCurrentIndex(0)
        self.search.clear()
        for w in (self.period, self.cat_filter, self.dir_filter, self.search):
            w.blockSignals(False)

    # ------------------------------------------------------------------ volet
    def _selection_changed(self, *_):
        sel = self.view.selected_rows()
        if sel and self.panel.isHidden():
            self.show_panel_btn.show()
        self.panel.set_ops(sel)

    def _show_panel(self):
        self.panel.show()
        self.show_panel_btn.hide()
        self.panel.set_ops(self.view.selected_rows())

    def _hide_panel(self):
        self.panel.hide()
        self.show_panel_btn.show()

    def _applied(self, ids):
        """Après classement : recharge et passe à l'opération suivante à traiter."""
        sel_rows = sorted(self.view.proxy_row_of(i) for i in ids)
        anchor = sel_rows[-1] if sel_rows else 0
        visible = self.view.visible_rows()
        following = [r["id"] for r in visible[anchor + 1:] if r["status"] == NONE and r["id"] not in ids]
        self.reload()
        self.changed.emit()
        target = following[0] if following else None
        if target is None or not self.view.select_id(target):
            if self.status is not None and self.view.proxy.rowCount():
                self.view.selectRow(min(max(sel_rows[0], 0) if sel_rows else 0, self.view.proxy.rowCount() - 1))
            else:
                for i in ids:
                    self.view.select_id(i)
        self.view.setFocus()

    # ------------------------------------------------------------- actions
    def _classify_cb(self, preset=None):
        sel = self.view.selected_rows()
        if not sel:
            return
        if preset is not None:
            self.panel.show()
            self.panel.set_ops(sel, preset_category=preset)
            self.panel.apply() if self.panel.btn_apply.isEnabled() else None
        else:
            self._show_panel()

    def _validate(self):
        ids = [r["id"] for r in self.view.selected_rows() if r["status"] == AUTO]
        if ids:
            self.db.validate(ids)
            self._applied(ids)

    def _release(self):
        ids = [r["id"] for r in self.view.selected_rows() if r["status"] == MANUAL]
        if ids:
            self.db.release(ids)
            self.reload(keep_ids=ids)
            self.changed.emit()

    def _delete(self):
        sel = self.view.selected_rows()
        if sel and confirm(self, f"Supprimer définitivement {len(sel)} opération(s) ?\n"
                                 "(Elles seront réimportées si vous réimportez le même relevé.)"):
            self.db.delete_operations([r["id"] for r in sel])
            self.reload()
            self.changed.emit()

    def _context_menu(self, pos):
        sel = self.view.selected_rows()
        if sel:
            build_context_menu(self, self.db, sel, self._classify_cb, self._validate, self._release,
                               self._delete).exec(self.view.viewport().mapToGlobal(pos))

    def export_excel(self):
        rows = self.view.visible_rows()
        if not rows:
            info(self, "Aucune opération à exporter.")
            return
        path = save_path(self, "Exporter les opérations", "operations.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        t = TableData("Opérations", f"{len(rows)} opérations", ["Date", "Libellé", "Fournisseur", "Montant",
                                                                 "Catégorie", "Sous-catégorie", "Statut", "Note"],
                      [DATE, TEXT, TEXT, MONEY, TEXT, TEXT, TEXT, TEXT])
        cats = self.db.categories()
        for r in rows:
            c = cats.get(r["category_id"])
            if c is None:
                top, sub = "", ""
            elif c.parent_id is None:
                top, sub = c.name, ""
            else:
                top, sub = cats[c.parent_id].name, c.name
            t.add([r["date"], r["label"], r["vendor"], r["amount"], top, sub, STATUS_LABELS[r["status"]], r["note"]])
        export_excel(path, [t])
        info(self, f"Export enregistré :\n{path}")


__all__ = ["OperationsTab", "OperationsPanel", "QLabel"]
