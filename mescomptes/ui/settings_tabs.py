"""Pages « Catégories » et « Règles »."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..db import KINDS
from . import theme as T
from .common import (COLOR_ROLE, GREY, SORT_ROLE, Card, CategoryCombo, DotDelegate, Page, SortItem, bold_font,
                     button, confirm, error, info, label, search_box, style_tree)
from .dialogs import CategoryEditDialog, RuleEditDialog

CAT_ROLE = Qt.UserRole + 20


class DeleteCategoryDialog(QDialog):
    def __init__(self, db, cat_id, nb_ops, nb_rules, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Supprimer la catégorie")
        form = QFormLayout(self)
        form.setContentsMargins(20, 18, 20, 16)
        msg = QLabel(f"Supprimer <b>{db.category_label(cat_id)}</b> et ses sous-catégories ?<br>"
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
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)


class CleanupDialog(QDialog):
    """Liste des catégories sans opération, cochées par défaut, à supprimer."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Supprimer les catégories vides")
        self.resize(620, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.addWidget(label("Catégories sans aucune opération", "sectionTitle"))
        lay.addWidget(label("Décochez celles que vous souhaitez garder. Les règles rattachées à une catégorie "
                            "supprimée sont supprimées aussi ; aucune opération n'est touchée.", "muted", True))
        self.tree = QTreeWidget()
        style_tree(self.tree)
        self.tree.setHeaderLabels(["CATÉGORIE", "RÈGLES", "BUDGET"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        cats = db.categories()
        self.items = []
        for c, nb_rules, has_budget in db.empty_categories():
            name = db.category_label(c.id)
            if c.parent_id is None:
                n_subs = sum(1 for x in cats.values() if x.parent_id == c.id)
                if n_subs:
                    name += f"  (et ses {n_subs} sous-catégories)"
            it = QTreeWidgetItem(self.tree, [name, str(nb_rules) if nb_rules else "", "oui" if has_budget else ""])
            it.setCheckState(0, Qt.Checked)
            it.setData(0, CAT_ROLE, c.id)
            if c.parent_id is None:
                it.setFont(0, bold_font())
            if nb_rules:
                it.setForeground(1, GREY)
            self.items.append(it)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        row.addWidget(button("Tout cocher", None, "ghost", slot=lambda: self._check_all(True)))
        row.addWidget(button("Tout décocher", None, "ghost", slot=lambda: self._check_all(False)))
        row.addStretch()
        self.count = label("", "muted")
        row.addWidget(self.count)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setObjectName("primary")
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.tree.itemChanged.connect(self._update)
        self._update()

    def _check_all(self, on):
        for it in self.items:
            it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)

    def _update(self, *_):
        n = len(self.selected())
        self.ok.setText(f"Supprimer {n} catégorie(s)")
        self.ok.setEnabled(n > 0)
        self.count.setText(f"{n} sélectionnée(s) sur {len(self.items)}")

    def selected(self):
        return [it.data(0, CAT_ROLE) for it in self.items if it.checkState(0) == Qt.Checked]


class CategoriesTab(Page):
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__("Catégories", "Deux niveaux : catégorie et sous-catégorie. Le type détermine la place "
                                       "dans les analyses (les mouvements internes sont exclus des dépenses).", parent)
        self.db = db
        self.add_action(button("Supprimer les catégories vides", "trash", slot=self.cleanup))
        self.add_action(button("Nouvelle catégorie", "plus", "primary", slot=self.add_top))
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = search_box("Rechercher une catégorie…")
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search, 1)
        for text, ic, cb in (("Sous-catégorie", "plus", self.add_sub), ("Renommer", "edit", self.rename),
                             ("Type", "tag", self.change_kind), ("Déplacer", "compare", self.move),
                             ("Supprimer", "trash", self.delete)):
            bar.addWidget(button(text, ic, slot=cb))
        self.add(bar)
        card = Card(margins=(0, 4, 0, 4))
        self.tree = QTreeWidget()
        style_tree(self.tree)
        self.tree.setItemDelegateForColumn(0, DotDelegate(self.tree))
        self.tree.setHeaderLabels(["CATÉGORIE", "TYPE", "OPÉRATIONS", "RÈGLES"])
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.rename())
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        card.add(self.tree, 1)
        self.add(card, 1)

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
            it.setData(0, COLOR_ROLE, T.category_color(self.db, top.id))
            for c in range(4):
                it.setFont(c, bold_font())
            for s in subs:
                n = ops.get(s.id, 0)
                c = SortItem(it, [s.name, "", str(n), str(rules.get(s.id, 0) or "")])
                c.setData(0, CAT_ROLE, s.id)
                if n == 0:
                    for col in range(4):
                        c.setForeground(col, GREY)
                if s.id == selected:
                    self.tree.setCurrentItem(c)
            if top.id == selected:
                self.tree.setCurrentItem(it)
            it.setExpanded(True)
        for c in (1, 2, 3):
            self.tree.resizeColumnToContents(c)
            self.tree.headerItem().setTextAlignment(c, Qt.AlignLeft | Qt.AlignVCenter)
        self._filter(self.search.text())

    def _filter(self, text):
        q = text.strip().casefold()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top_match = q in top.text(0).casefold()
            any_child = False
            for j in range(top.childCount()):
                ch = top.child(j)
                m = not q or top_match or q in ch.text(0).casefold()
                ch.setHidden(not m)
                any_child |= m
            top.setHidden(bool(q) and not (top_match or any_child))

    def _selected(self):
        it = self.tree.currentItem()
        return it.data(0, CAT_ROLE) if it else None

    def _done(self):
        self.refresh()
        self.changed.emit()

    def cleanup(self):
        if not self.db.empty_categories():
            info(self, "Toutes les catégories contiennent au moins une opération.")
            return
        dlg = CleanupDialog(self.db, self)
        if dlg.exec() == QDialog.Accepted and dlg.selected():
            self.db.delete_categories(dlg.selected())
            self._done()

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
            self.db.set_category_kind(cid, next(k for k, v in KINDS.items() if v == choice))
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
        try:
            self.db.move_category(cid, options[labels.index(choice)][1])
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


class RulesTab(Page):
    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__("Règles d'apprentissage", "Créées quand vous classez une opération. Une règle s'applique à "
                                                   "tout libellé contenant son motif ; la plus précise l'emporte. Les "
                                                   "opérations validées ne sont jamais modifiées.", parent)
        self.db = db
        self.add_action(button("Réappliquer toutes les règles", "wand", slot=self.reapply))
        self.add_action(button("Nouvelle règle", "plus", "primary", slot=self.new_rule))
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = search_box("Filtrer les règles…")
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.search, 1)
        bar.addWidget(button("Modifier", "edit", slot=self.edit))
        bar.addWidget(button("Supprimer", "trash", slot=self.delete))
        self.add(bar)
        test_card = Card(margins=(16, 10, 16, 10))
        tr = QHBoxLayout()
        tr.addWidget(label("Tester un libellé", "sectionTitle"))
        self.test = QLineEdit()
        self.test.setPlaceholderText("Collez un libellé de relevé pour voir quelle règle s'appliquerait")
        self.test.textChanged.connect(self._test)
        tr.addWidget(self.test, 1)
        self.test_result = label("")
        self.test_result.setTextFormat(Qt.RichText)
        tr.addWidget(self.test_result)
        test_card.add(tr)
        self.add(test_card)
        card = Card(margins=(0, 4, 0, 4))
        self.tree = QTreeWidget()
        style_tree(self.tree)
        self.tree.setItemDelegateForColumn(1, DotDelegate(self.tree))
        self.tree.setHeaderLabels(["LE LIBELLÉ CONTIENT", "CATÉGORIE", "OPÉRATIONS", "CRÉÉE LE"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSortingEnabled(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit())
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        card.add(self.tree, 1)
        self.count = label("", "muted")
        self.count.setContentsMargins(14, 4, 14, 6)
        card.add(self.count)
        self.add(card, 1)

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
            it.setData(1, COLOR_ROLE, T.category_color(self.db, r.category_id))
            it.setData(2, SORT_ROLE, r.nb_ops)
            it.setFont(0, bold_font())
            if r.nb_ops == 0:
                it.setForeground(2, GREY)
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
            self.test_result.setText(f"→ <b>{self.db.category_label(m[1])}</b> "
                                     f"<span style='color:{T.MUTED}'>(règle « {rule.pattern} »)</span>")
        else:
            self.test_result.setText(f"<span style='color:{T.ORANGE}'>Aucune règle : « à classer »</span>")

    def _selected_ids(self):
        return [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()]

    def _done(self):
        self.refresh()
        self.changed.emit()

    def new_rule(self):
        if RuleEditDialog(self.db, self).exec() == QDialog.Accepted:
            self._done()

    def edit(self):
        ids = self._selected_ids()
        if len(ids) == 1 and RuleEditDialog(self.db, self, rule=self.db.rule(ids[0])).exec() == QDialog.Accepted:
            self._done()

    def delete(self):
        ids = self._selected_ids()
        if ids and confirm(self, f"Supprimer {len(ids)} règle(s) ?\nLes opérations classées automatiquement par ces "
                                 f"règles (non validées) seront reclassées ou repasseront « à classer »."):
            for rid in ids:
                self.db.delete_rule(rid)
            self._done()

    def reapply(self):
        n = self.db.apply_rules()
        info(self, f"{n} opération(s) reclassée(s).")
        self._done()
