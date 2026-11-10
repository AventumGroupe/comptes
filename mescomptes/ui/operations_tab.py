"""Onglet « Opérations » : liste filtrable, classement, validation, import."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
                               QVBoxLayout, QWidget)

from .. import analytics as an
from ..db import AUTO, MANUAL, NONE
from ..exporters import DATE, MONEY, TEXT, TableData, export_excel
from ..money import fmt_eur
from .common import CategoryCombo, OperationsView, PeriodSelector, confirm, info, save_path
from .dialogs import ClassifyDialog


class OperationsPanel(QWidget):
    """Table d'opérations + actions de classement. Réutilisée dans les vues de détail."""
    changed = Signal()

    def __init__(self, db, parent=None, compact=False):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = OperationsView(db, self)
        self.view.doubleClicked.connect(self._double_click)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)

        bar = QHBoxLayout()
        self.btn_classify = QPushButton("Classer…")
        self.btn_classify.setToolTip("Choisir la catégorie des opérations sélectionnées (double-clic ou Entrée)")
        self.btn_validate = QPushButton("✔ Valider le classement auto")
        self.btn_validate.setToolTip("Confirme la catégorie proposée automatiquement")
        self.btn_release = QPushButton("Annuler la validation")
        self.btn_release.setToolTip("L'opération repasse sous le contrôle des règles automatiques")
        self.btn_classify.clicked.connect(self.classify_selected)
        self.btn_validate.clicked.connect(self.validate_selected)
        self.btn_release.clicked.connect(self.release_selected)
        for b in (self.btn_classify, self.btn_validate, self.btn_release):
            bar.addWidget(b)
        bar.addStretch()
        self.footer = QLabel()
        bar.addWidget(self.footer)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)

        act = QAction(self)
        act.setShortcuts([QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)])
        act.setShortcutContext(Qt.WidgetShortcut)
        act.triggered.connect(self.classify_selected)
        self.view.addAction(act)
        self._selection_changed()

    def set_rows(self, rows):
        self.view.set_rows(rows)
        n = len(rows)
        total = sum(r["amount"] for r in rows)
        self.footer.setText(f"{n} opération(s) — total {fmt_eur(total)}")
        self._selection_changed()

    def _selection_changed(self, *_):
        sel = self.view.selected_rows() if self.view.model_.rows else []
        self.btn_classify.setEnabled(bool(sel))
        self.btn_validate.setEnabled(any(r["status"] == AUTO for r in sel))
        self.btn_release.setEnabled(any(r["status"] == MANUAL for r in sel))
        if len(sel) > 1:
            self.footer.setText(f"{len(sel)} sélectionnée(s) — total {fmt_eur(sum(r['amount'] for r in sel))}")
        elif self.view.model_.rows is not None:
            rows = self.view.model_.rows
            self.footer.setText(f"{len(rows)} opération(s) — total {fmt_eur(sum(r['amount'] for r in rows))}")

    def _double_click(self, index):
        if index.column() == self.view.model_.COL_NOTE:
            return
        self.classify_selected()

    def classify_selected(self, preset_category=None):
        sel = self.view.selected_rows()
        if not sel:
            return
        dlg = ClassifyDialog(self.db, sel, self, preset_category=preset_category)
        if dlg.exec() == QDialog.Accepted:
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
        if not sel:
            return
        menu = QMenu(self)
        menu.addAction("Classer…", self.classify_selected)
        quick = menu.addMenu("Classer dans")
        for top, subs in self.db.category_tree():
            if subs:
                sub_menu = quick.addMenu(top.name)
                sub_menu.addAction(f"{top.name} (général)", lambda c=top.id: self.classify_selected(c))
                sub_menu.addSeparator()
                for s in subs:
                    sub_menu.addAction(s.name, lambda c=s.id: self.classify_selected(c))
            else:
                quick.addAction(top.name, lambda c=top.id: self.classify_selected(c))
        if any(r["status"] == AUTO for r in sel):
            menu.addAction("Valider le classement auto", self.validate_selected)
        if any(r["status"] == MANUAL for r in sel):
            menu.addAction("Annuler la validation", self.release_selected)
        menu.addSeparator()
        menu.addAction("Supprimer l'opération…", self.delete_selected)
        menu.exec(self.view.viewport().mapToGlobal(pos))


class OperationsTab(QWidget):
    changed = Signal()
    import_requested = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        btn_import = QPushButton("📥  Importer un relevé…")
        btn_import.setStyleSheet("font-weight:bold; padding:6px 14px")
        btn_import.clicked.connect(self.import_requested)
        top.addWidget(btn_import)
        self.btn_todo = QPushButton()
        self.btn_todo.setFlat(True)
        self.btn_todo.setCursor(Qt.PointingHandCursor)
        self.btn_todo.clicked.connect(self.show_todo)
        top.addWidget(self.btn_todo)
        self.btn_check = QPushButton()
        self.btn_check.setFlat(True)
        self.btn_check.setCursor(Qt.PointingHandCursor)
        self.btn_check.clicked.connect(self.show_auto)
        top.addWidget(self.btn_check)
        top.addStretch()
        btn_export = QPushButton("Exporter (Excel)…")
        btn_export.clicked.connect(self.export_excel)
        top.addWidget(btn_export)
        lay.addLayout(top)

        filters = QHBoxLayout()
        self.period = PeriodSelector(self, default="Tout l'historique")
        filters.addWidget(self.period)
        filters.addSpacing(10)
        self.cat_filter = CategoryCombo(self, with_all=True, with_none=True)
        filters.addWidget(self.cat_filter)
        self.status_filter = QComboBox()
        for label, val in (("Tous statuts", None), ("À classer", NONE), ("Auto (à vérifier)", AUTO),
                           ("Validées", MANUAL)):
            self.status_filter.addItem(label, val)
        filters.addWidget(self.status_filter)
        self.dir_filter = QComboBox()
        for label, val in (("Débits et crédits", None), ("Débits", "debit"), ("Crédits", "credit")):
            self.dir_filter.addItem(label, val)
        filters.addWidget(self.dir_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 Rechercher (libellé, fournisseur, note)")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 1)
        lay.addLayout(filters)

        self.panel = OperationsPanel(db, self)
        self.panel.changed.connect(self.changed)
        lay.addWidget(self.panel, 1)

        self.period.changed.connect(self.reload)
        self.cat_filter.currentIndexChanged.connect(self.reload)
        self.status_filter.currentIndexChanged.connect(self.reload)
        self.dir_filter.currentIndexChanged.connect(self.reload)
        self.search.textChanged.connect(self.reload)

    def refresh(self):
        self.cat_filter.populate(self.db)
        self.period.set_bounds(*self.db.date_bounds())
        self.reload()

    def reload(self, *_):
        start, end = self.period.period()
        cat = self.cat_filter.currentData()
        kwargs = {}
        if cat == CategoryCombo.NONE:
            kwargs["uncategorized"] = True
        elif cat not in (None, CategoryCombo.ALL):
            kwargs["cat_ids"] = self.db.descendants(cat)
        rows = self.db.operations(start=an.month_first_day(start) if start else None,
                                  end=an.month_last_day(end) if end else None,
                                  status=self.status_filter.currentData(),
                                  direction=self.dir_filter.currentData(),
                                  text=self.search.text().strip() or None, **kwargs)
        self.panel.set_rows(rows)
        counts = self.db.count_by_status()
        n_todo, n_auto = counts.get(NONE, 0), counts.get(AUTO, 0)
        self.btn_todo.setText(f"⚠ {n_todo} à classer" if n_todo else "✔ Tout est classé")
        self.btn_todo.setStyleSheet("color:#CA6F1E; font-weight:bold" if n_todo else "color:#1E8449")
        self.btn_check.setText(f"🔎 {n_auto} classée(s) automatiquement à vérifier" if n_auto else "")
        self.btn_check.setVisible(bool(n_auto))
        self.btn_check.setStyleSheet("color:#2471A3")

    def _reset_filters(self, status):
        for w in (self.period, self.cat_filter, self.status_filter, self.dir_filter, self.search):
            w.blockSignals(True)
        self.period.preset.setCurrentText("Tout l'historique")
        self.period._apply_preset("Tout l'historique", emit=False)
        self.cat_filter.setCurrentIndex(0)
        self.status_filter.setCurrentIndex(self.status_filter.findData(status))
        self.dir_filter.setCurrentIndex(0)
        self.search.clear()
        for w in (self.period, self.cat_filter, self.status_filter, self.dir_filter, self.search):
            w.blockSignals(False)
        self.reload()

    def show_todo(self):
        self._reset_filters(NONE)

    def show_auto(self):
        self._reset_filters(AUTO)

    def export_excel(self):
        rows = self.panel.view.visible_rows()
        if not rows:
            info(self, "Aucune opération à exporter.")
            return
        path = save_path(self, "Exporter les opérations", "operations.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        t = TableData("Opérations", f"{len(rows)} opérations", ["Date", "Libellé", "Fournisseur", "Montant",
                                                                 "Catégorie", "Sous-catégorie", "Statut", "Note"],
                      [DATE, TEXT, TEXT, MONEY, TEXT, TEXT, TEXT, TEXT])
        from ..db import STATUS_LABELS
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
