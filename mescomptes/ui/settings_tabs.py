"""Onglets « Catégories » et « Règles »."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QPushButton, QTreeWidget, QVBoxLayout,
                               QWidget)

from ..db import KINDS
from .common import SECTION_BG, SORT_ROLE, CategoryCombo, SortItem, confirm, error, info, style_row
from .dialogs import CategoryEditDialog, RuleEditDialog

CAT_ROLE = Qt.UserRole + 20


class DeleteCategoryDialog(QDialog):
    def __init__(self, db, cat_id, nb_ops, nb_rules, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Supprimer la catégorie")
        form = QFormLayout(self)
        name = db.category_label(cat_id)
        msg = QLabel(f"Supprimer <b>{name}</b> et ses sous-catégories ?<br>"
                     f"Elle contient {nb_ops} opération(s) et {nb_rules} règle(s).")
        msg.setWordWrap(True)
        form.addRow(msg)
        self.target = CategoryCombo(self)
        self.target.populate(db)
        excluded = set(db.descendants(cat_id))
        for i in reversed(range(self.target.count())):
            if self.target.itemData(i) in excluded:
                self.target.removeItem(i)
        self.target.insertItem(0, "Ne pas transférer : opérations « à classer », règles supprimées", None)
        self.target.setCurrentIndex(0)
        if nb_ops or nb_rules:
            form.addRow("Transférer vers :", self.target)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Supprimer")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class CategoriesTab(QWidget):
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        intro = QLabel("Organisez vos catégories sur deux niveaux. Le type détermine où la catégorie apparaît dans "
                       "les analyses : revenus, dépenses ou mouvements internes (épargne, virements entre comptes : "
                       "exclus des dépenses).")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#555")
        lay.addWidget(intro)
        bar = QHBoxLayout()
        actions = [("Nouvelle catégorie…", self.add_top), ("Nouvelle sous-catégorie…", self.add_sub),
                   ("Renommer…", self.rename), ("Changer le type…", self.change_kind),
                   ("Déplacer…", self.move), ("Supprimer…", self.delete)]
        self.buttons = {}
        for label, cb in actions:
            b = QPushButton(label)
            b.clicked.connect(cb)
            bar.addWidget(b)
            self.buttons[label] = b
        bar.addStretch()
        lay.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Catégorie", "Type", "Opérations", "Règles"])
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.rename())
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(self.tree, 1)

    def refresh(self):
        selected = self._selected()
        self.tree.clear()
        ops = dict(self.db.conn.execute("SELECT category_id, COUNT(*) FROM operations GROUP BY category_id").fetchall())
        rules = dict(self.db.conn.execute("SELECT category_id, COUNT(*) FROM rules GROUP BY category_id").fetchall())
        for top, subs in self.db.category_tree():
            n_ops = ops.get(top.id, 0) + sum(ops.get(s.id, 0) for s in subs)
            n_rules = rules.get(top.id, 0) + sum(rules.get(s.id, 0) for s in subs)
            it = SortItem(self.tree, [top.name, KINDS[top.kind], str(n_ops), str(n_rules)])
            it.setData(0, CAT_ROLE, top.id)
            style_row(it, 4, bold=True, bg=SECTION_BG)
            for s in subs:
                c = SortItem(it, [s.name, "", str(ops.get(s.id, 0)), str(rules.get(s.id, 0))])
                c.setData(0, CAT_ROLE, s.id)
                if s.id == selected:
                    self.tree.setCurrentItem(c)
            if top.id == selected:
                self.tree.setCurrentItem(it)
            it.setExpanded(True)
        for c in (1, 2, 3):
            self.tree.resizeColumnToContents(c)

    def _selected(self):
        it = self.tree.currentItem()
        return it.data(0, CAT_ROLE) if it else None

    def _done(self):
        self.refresh()
        self.changed.emit()

    def add_top(self):
        if CategoryEditDialog(self.db, self).exec() == QDialog.Accepted:
            self._done()

    def add_sub(self):
        cid = self._selected()
        parent = self.db.top_category_id(cid) if cid else None
        dlg = CategoryEditDialog(self.db, self, parent_id=parent)
        if parent is None and dlg.parent_combo.count() > 1:
            dlg.parent_combo.setCurrentIndex(1)
        if dlg.exec() == QDialog.Accepted:
            self._done()

    def rename(self):
        cid = self._selected()
        if cid is None:
            return
        name, ok = QInputDialog.getText(self, "Renommer", "Nouveau nom :", QLineEdit.Normal,
                                        self.db.categories()[cid].name)
        if ok and name.strip():
            try:
                self.db.rename_category(cid, name)
            except ValueError as e:
                error(self, e)
                return
            self._done()

    def change_kind(self):
        cid = self._selected()
        if cid is None:
            return
        cid = self.db.top_category_id(cid)
        labels = list(KINDS.values())
        current = labels.index(KINDS[self.db.categories()[cid].kind])
        choice, ok = QInputDialog.getItem(self, "Type de catégorie",
                                          f"Type de « {self.db.categories()[cid].name} » (et de ses sous-catégories) :",
                                          labels, current, False)
        if ok:
            kind = next(k for k, v in KINDS.items() if v == choice)
            self.db.set_category_kind(cid, kind)
            self._done()

    def move(self):
        cid = self._selected()
        if cid is None:
            return
        cats = self.db.categories()
        options = [("(devenir une catégorie principale)", None)] + [
            (t.name, t.id) for t, _ in self.db.category_tree() if t.id != cid]
        labels = [o[0] for o in options]
        choice, ok = QInputDialog.getItem(self, "Déplacer", f"Placer « {cats[cid].name} » sous :", labels, 0, False)
        if not ok:
            return
        target = options[labels.index(choice)][1]
        try:
            self.db.move_category(cid, target)
        except ValueError as e:
            error(self, e)
            return
        self._done()

    def delete(self):
        cid = self._selected()
        if cid is None:
            return
        nb_ops, nb_rules = self.db.category_usage(cid)
        dlg = DeleteCategoryDialog(self.db, cid, nb_ops, nb_rules, self)
        if dlg.exec() == QDialog.Accepted:
            try:
                self.db.delete_category(cid, dlg.target.currentData())
            except ValueError as e:
                error(self, e)
                return
            self._done()


class RulesTab(QWidget):
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        intro = QLabel("Les règles sont créées quand vous classez une opération. Une règle s'applique à tout libellé "
                       "contenant son motif ; si plusieurs règles correspondent, la plus précise (motif le plus long) "
                       "l'emporte. Les opérations que vous avez validées ne sont jamais modifiées par une règle.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#555")
        lay.addWidget(intro)
        bar = QHBoxLayout()
        for label, cb in (("Nouvelle règle…", self.add), ("Modifier…", self.edit), ("Supprimer", self.delete),
                          ("Réappliquer toutes les règles", self.reapply)):
            b = QPushButton(label)
            b.clicked.connect(cb)
            bar.addWidget(b)
        bar.addSpacing(20)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 Filtrer")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.search, 1)
        lay.addLayout(bar)
        test_row = QHBoxLayout()
        test_row.addWidget(QLabel("Tester un libellé :"))
        self.test = QLineEdit()
        self.test.setPlaceholderText("Collez un libellé de relevé pour voir quelle règle s'appliquerait")
        self.test.textChanged.connect(self._test)
        test_row.addWidget(self.test, 1)
        self.test_result = QLabel()
        test_row.addWidget(self.test_result)
        lay.addLayout(test_row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Le libellé contient", "Catégorie", "Opérations classées", "Créée le"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit())
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        lay.addWidget(self.tree, 1)
        self.count = QLabel()
        lay.addWidget(self.count)

    def refresh(self, *_):
        q = self.search.text().strip().casefold()
        self.tree.clear()
        rules = self.db.rules()
        shown = 0
        for r in rules:
            cat = self.db.category_label(r.category_id)
            if q and q not in r.pattern.casefold() and q not in cat.casefold():
                continue
            it = SortItem(self.tree, [r.pattern, cat, str(r.nb_ops), r.created_at[:10]])
            it.setData(0, Qt.UserRole, r.id)
            it.setData(2, SORT_ROLE, r.nb_ops)
            it.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            shown += 1
        self.count.setText(f"{shown} règle(s) affichée(s) sur {len(rules)}")
        self._test()

    def _test(self, *_):
        text = self.test.text().strip()
        if not text:
            self.test_result.setText("")
            return
        m = self.db.find_rule(text)
        if m:
            rule = self.db.rule(m[0])
            self.test_result.setText(f"→ <b>{self.db.category_label(m[1])}</b> (règle « {rule.pattern} »)")
        else:
            self.test_result.setText("<span style='color:#CA6F1E'>Aucune règle : « à classer »</span>")

    def _selected_ids(self):
        return [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()]

    def _done(self):
        self.refresh()
        self.changed.emit()

    def add(self):
        if RuleEditDialog(self.db, self).exec() == QDialog.Accepted:
            self._done()

    def edit(self):
        ids = self._selected_ids()
        if len(ids) != 1:
            return
        if RuleEditDialog(self.db, self, rule=self.db.rule(ids[0])).exec() == QDialog.Accepted:
            self._done()

    def delete(self):
        ids = self._selected_ids()
        if not ids:
            return
        if confirm(self, f"Supprimer {len(ids)} règle(s) ?\nLes opérations classées automatiquement par ces règles "
                         f"(non validées) seront reclassées par les autres règles ou repasseront « à classer »."):
            for rid in ids:
                self.db.delete_rule(rid)
            self._done()

    def reapply(self):
        n = self.db.apply_rules()
        info(self, f"{n} opération(s) reclassée(s).")
        self._done()
