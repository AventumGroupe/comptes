"""Boîtes de dialogue : classement d'opérations, import de relevé, saisie de catégorie."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QRadioButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from .. import importer
from ..db import AUTO, KINDS, MANUAL
from ..money import fmt_eur
from ..normalize import label_key
from .common import GREEN, RED, CategoryCombo, error


def _fmt_date(d):
    return f"{d[8:10]}/{d[5:7]}/{d[:4]}" if d else ""


# =================================================================== Classement
class ClassifyDialog(QDialog):
    """Classement manuel d'une ou plusieurs opérations, avec choix de l'apprentissage."""

    def __init__(self, db, ops, parent=None, preset_category=None):
        super().__init__(parent)
        self.db = db
        self.ops = ops
        self.setWindowTitle("Classer l'opération" if len(ops) == 1 else f"Classer {len(ops)} opérations")
        self.setMinimumWidth(720)
        lay = QVBoxLayout(self)

        # --- résumé
        if len(ops) == 1:
            o = ops[0]
            txt = (f"<b>{o['label']}</b><br>{_fmt_date(o['date'])} — "
                   f"<span style='color:{'#C0392B' if o['amount'] < 0 else '#1E8449'}'>{fmt_eur(o['amount'])}</span>")
            cur = db.category_label(o["category_id"])
            if cur:
                status = {AUTO: "classée automatiquement", MANUAL: "validée"}.get(o["status"], "")
                txt += f"<br>Catégorie actuelle : <b>{cur}</b> ({status})"
        else:
            total = sum(o["amount"] for o in ops)
            txt = f"<b>{len(ops)} opérations sélectionnées</b> — total {fmt_eur(total)}"
        summary = QLabel(txt)
        summary.setWordWrap(True)
        summary.setTextFormat(Qt.RichText)
        lay.addWidget(summary)

        # --- catégorie
        row = QHBoxLayout()
        row.addWidget(QLabel("Catégorie :"))
        self.combo = CategoryCombo(self)
        self.combo.populate(db)
        start_cat = preset_category if preset_category is not None else (
            ops[0]["category_id"] if len({o["category_id"] for o in ops}) == 1 else None)
        self.combo.insertItem(0, "— Choisir une catégorie —", None)
        self.combo.setCurrentIndex(0)
        if start_cat is not None:
            self.combo.set_value(start_cat)
        row.addWidget(self.combo, 1)
        new_btn = QPushButton("Nouvelle catégorie…")
        new_btn.clicked.connect(self._new_category)
        row.addWidget(new_btn)
        lay.addLayout(row)

        # --- apprentissage
        vendors = {o["vendor"] for o in ops}
        rule_ids = {o["rule_id"] for o in ops if o["status"] == AUTO}
        self.current_rule = db.rule(next(iter(rule_ids))) if len(rule_ids) == 1 and all(
            o["status"] == AUTO for o in ops) else None
        is_correction = self.current_rule is not None

        box = QGroupBox("Apprentissage : que faire pour les prochaines opérations de ce fournisseur ?")
        bl = QVBoxLayout(box)
        self.group = QButtonGroup(self)
        self.r_only = QRadioButton("Uniquement cette opération (exception, aucune règle créée ou modifiée)"
                                   if len(ops) == 1 else f"Uniquement ces {len(ops)} opérations (aucune règle)")
        self.group.addButton(self.r_only)
        bl.addWidget(self.r_only)
        self.r_update = None
        if is_correction:
            self.r_update = QRadioButton(
                f"Modifier la règle « {self.current_rule.pattern} » pour toutes les opérations de ce fournisseur")
            self.group.addButton(self.r_update)
            bl.addWidget(self.r_update)
        rule_row = QHBoxLayout()
        self.r_rule = QRadioButton("Créer une règle plus précise : libellé contenant" if is_correction
                                   else "Mémoriser : les libellés contenant")
        self.group.addButton(self.r_rule)
        rule_row.addWidget(self.r_rule)
        self.pattern = QLineEdit(next(iter(vendors)) if len(vendors) == 1 else "")
        self.pattern.setPlaceholderText("ex. CARREFOUR")
        rule_row.addWidget(self.pattern, 1)
        rule_row.addWidget(QLabel("→ cette catégorie"))
        bl.addLayout(rule_row)
        self.match_info = QLabel()
        self.match_info.setWordWrap(True)
        self.match_info.setStyleSheet("color:#555; margin-left:22px")
        bl.addWidget(self.match_info)
        lay.addWidget(box)

        if is_correction:
            hint = QLabel("Cette opération a été classée automatiquement : choisissez comment appliquer la correction.")
            hint.setStyleSheet("color:#CA6F1E")
            hint.setWordWrap(True)
            lay.addWidget(hint)
        elif all(o["status"] == MANUAL for o in ops):
            self.r_only.setChecked(True)
        else:
            self.r_rule.setChecked(True)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Classer")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self.pattern.textChanged.connect(self._update_info)
        self.pattern.textEdited.connect(lambda: self.r_rule.setChecked(True))
        self.group.buttonToggled.connect(self._update_info)
        self.combo.currentIndexChanged.connect(self._update_info)
        self._update_info()

    def _new_category(self):
        dlg = CategoryEditDialog(self.db, self, parent_id=self.db.top_category_id(self.combo.currentData()))
        if dlg.exec() == QDialog.Accepted:
            self.combo.populate(self.db)
            self.combo.set_value(dlg.created_id)

    def _update_info(self, *_):
        ok = self.group.checkedButton() is not None
        if self.r_rule.isChecked():
            pat = self.pattern.text()
            if not label_key(pat):
                self.match_info.setText("Saisissez un motif (au moins un mot, hors chiffres).")
                ok = False
            else:
                total, pending = self.db.matching_operations(pat)
                txt = (f"Ce motif correspond à {total} opération(s) déjà importée(s) ; {pending} non validée(s) "
                       f"seront classées automatiquement, ainsi que les prochaines importées.")
                existing = self.db.rule_by_pattern(pat)
                if existing:
                    txt += (f"<br><span style='color:#CA6F1E'>Une règle existe déjà pour ce motif "
                            f"(→ {self.db.category_label(existing.category_id)}) : elle sera mise à jour.</span>")
                missing = [o for o in self.ops if f" {label_key(pat)} " not in f" {o['label_key']} "]
                if missing:
                    txt += (f"<br><span style='color:#C0392B'>Attention : {len(missing)} opération(s) sélectionnée(s) "
                            f"ne contiennent pas ce motif.</span>")
                self.match_info.setText(txt)
        elif self.r_update is not None and self.r_update.isChecked():
            total, pending = self.db.matching_operations(self.current_rule.pattern)
            self.match_info.setText(
                f"La règle « {self.current_rule.pattern} » (actuellement → "
                f"{self.db.category_label(self.current_rule.category_id)}) pointera vers la nouvelle catégorie ; "
                f"{pending} opération(s) non validée(s) seront reclassées, ainsi que les prochaines importées. "
                f"Les opérations déjà validées ne changent pas.")
        else:
            self.match_info.setText("")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok and self.combo.currentData() is not None)

    def _accept(self):
        cat = self.combo.currentData()
        if cat is None:
            return
        ids = [o["id"] for o in self.ops]
        try:
            self.db.classify(ids, cat, save=False)
            if self.r_rule.isChecked():
                self.db.save_rule(self.pattern.text(), cat)
            elif self.r_update is not None and self.r_update.isChecked():
                self.db.save_rule(self.current_rule.pattern, cat, rule_id=self.current_rule.id)
            else:
                self.db.save()
        except ValueError as e:
            error(self, e)
            return
        self.accept()


# ==================================================================== Catégories
class CategoryEditDialog(QDialog):
    """Création d'une catégorie ou sous-catégorie."""

    def __init__(self, db, parent=None, parent_id=None):
        super().__init__(parent)
        self.db = db
        self.created_id = None
        self.setWindowTitle("Nouvelle catégorie")
        form = QFormLayout(self)
        self.name = QLineEdit()
        form.addRow("Nom :", self.name)
        self.parent_combo = QComboBox()
        self.parent_combo.addItem("(catégorie principale)", None)
        for top, _ in db.category_tree():
            self.parent_combo.addItem(f"Sous-catégorie de : {top.name}", top.id)
        if parent_id is not None:
            self.parent_combo.setCurrentIndex(max(0, self.parent_combo.findData(parent_id)))
        form.addRow("Emplacement :", self.parent_combo)
        self.kind = QComboBox()
        for k, label in KINDS.items():
            self.kind.addItem(label, k)
        self.kind.setCurrentIndex(1)
        form.addRow("Type :", self.kind)
        self.parent_combo.currentIndexChanged.connect(self._sync)
        self._sync()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _sync(self):
        pid = self.parent_combo.currentData()
        self.kind.setEnabled(pid is None)
        if pid is not None:
            self.kind.setCurrentIndex(self.kind.findData(self.db.categories()[pid].kind))

    def _accept(self):
        try:
            self.created_id = self.db.add_category(self.name.text(), self.parent_combo.currentData(),
                                                   self.kind.currentData())
        except ValueError as e:
            error(self, e)
            return
        self.accept()


# ======================================================================== Import
class ImportDialog(QDialog):
    """Aperçu et import d'un relevé, avec correction possible des colonnes."""

    FIELDS = [("date_col", "Date d'opération *"), ("value_date_col", "Date de valeur"),
              ("label1", "Libellé *"), ("label2", "Libellé (complément)"),
              ("amount_col", "Montant (signé)"), ("debit_col", "Débit"), ("credit_col", "Crédit"),
              ("balance_col", "Solde")]

    def __init__(self, db, path, parent=None):
        super().__init__(parent)
        self.db = db
        self.path = path
        self.result_counts = None
        self.setWindowTitle(f"Importer un relevé — {os.path.basename(path)}")
        self.resize(1000, 680)
        self.sheets = importer.load_statement(path)
        if not self.sheets:
            raise importer.ImportError_("Le fichier ne contient aucune feuille.")
        # feuille par défaut : la première dont les colonnes sont reconnues
        start = next((i for i, (_, m) in enumerate(self.sheets) if m.is_complete()), 0)

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.sheet_combo = QComboBox()
        for s, _ in self.sheets:
            self.sheet_combo.addItem(s.name)
        top.addWidget(QLabel("Feuille :"))
        top.addWidget(self.sheet_combo)
        top.addSpacing(20)
        top.addWidget(QLabel("Ligne d'en-tête :"))
        self.header_spin = QSpinBox()
        self.header_spin.setMinimum(1)
        top.addWidget(self.header_spin)
        top.addStretch()
        lay.addLayout(top)

        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        box = QGroupBox("Colonnes du relevé")
        grid = QFormLayout(box)
        grid.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.combos = {}
        cols_layout = QHBoxLayout()
        left, right = QFormLayout(), QFormLayout()
        for i, (key, label) in enumerate(self.FIELDS):
            cb = QComboBox()
            cb.setMinimumWidth(200)
            self.combos[key] = cb
            (left if i < 4 else right).addRow(label + " :", cb)
            cb.currentIndexChanged.connect(self._reparse)
        cols_layout.addLayout(left)
        cols_layout.addSpacing(30)
        cols_layout.addLayout(right)
        grid.addRow(cols_layout)
        lay.addWidget(box)

        self.preview = QTableWidget(0, 4)
        self.preview.setHorizontalHeaderLabels(["Date", "Libellé", "Montant", "Solde"])
        self.preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.preview.verticalHeader().setVisible(False)
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.preview, 1)

        self.summary = QLabel()
        lay.addWidget(self.summary)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Importer")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        self.buttons.accepted.connect(self._import)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

        self._loading = False
        self.sheet_combo.currentIndexChanged.connect(self._load_sheet)
        self.header_spin.valueChanged.connect(self._header_changed)
        self.sheet_combo.setCurrentIndex(start)
        self._load_sheet(start)

    # -------------------------------------------------------------------
    def _load_sheet(self, idx, mapping=None):
        sheet, detected = self.sheets[idx]
        self.sheet = sheet
        m = mapping or detected
        self._loading = True
        self.header_spin.setMaximum(max(1, len(sheet.rows)))
        self.header_spin.setValue(m.header_row + 1)
        self._fill_combos(m)
        self._loading = False
        if detected.is_complete() and mapping is None:
            self.status.setText("<span style='color:#1E8449'>✔ Colonnes reconnues automatiquement. "
                                "Vérifiez l'aperçu puis cliquez sur « Importer ».</span>")
        elif mapping is None:
            self.status.setText("<span style='color:#CA6F1E'>Colonnes non reconnues : indiquez la ligne "
                                "d'en-tête et les colonnes ci-dessous.</span>")
        self._reparse()

    def _header_changed(self, value):
        if self._loading:
            return
        row = self.sheet.rows[value - 1] if value - 1 < len(self.sheet.rows) else []
        m = importer._mapping_from_header(row, value - 1)
        self._loading = True
        self._fill_combos(m)
        self._loading = False
        self._reparse()

    def _fill_combos(self, m):
        header = self.sheet.rows[m.header_row] if m.header_row < len(self.sheet.rows) else []
        width = max((len(r) for r in self.sheet.rows[:200]), default=0)
        values = {
            "date_col": m.date_col, "value_date_col": m.value_date_col,
            "label1": m.label_cols[0] if m.label_cols else None,
            "label2": m.label_cols[1] if len(m.label_cols) > 1 else None,
            "amount_col": m.amount_col, "debit_col": m.debit_col, "credit_col": m.credit_col,
            "balance_col": m.balance_col,
        }
        for key, cb in self.combos.items():
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("— aucune —", None)
            for j in range(width):
                name = header[j] if j < len(header) and header[j] not in (None, "") else ""
                cb.addItem(f"Colonne {_col_letter(j)}" + (f" : {name}" if name else ""), j)
            cb.setCurrentIndex(max(0, cb.findData(values[key])) if values[key] is not None else 0)
            cb.blockSignals(False)

    def _mapping(self):
        g = {k: cb.currentData() for k, cb in self.combos.items()}
        labels = [c for c in (g["label1"], g["label2"]) if c is not None]
        return importer.Mapping(header_row=self.header_spin.value() - 1, date_col=g["date_col"],
                                value_date_col=g["value_date_col"], label_cols=labels,
                                amount_col=g["amount_col"], debit_col=g["debit_col"],
                                credit_col=g["credit_col"], balance_col=g["balance_col"])

    def _reparse(self, *_):
        if self._loading:
            return
        m = self._mapping()
        self.ops = []
        ok_btn = self.buttons.button(QDialogButtonBox.Ok)
        if not m.is_complete():
            self.preview.setRowCount(0)
            self.summary.setText("<span style='color:#C0392B'>Il faut au minimum une date, un libellé et "
                                 "un montant (ou des colonnes débit/crédit).</span>")
            ok_btn.setEnabled(False)
            return
        if m.amount_col is not None and (m.debit_col is not None or m.credit_col is not None):
            m.amount_col = None
        try:
            self.ops, skipped = importer.parse_operations(self.sheet.rows, m)
        except Exception as e:  # noqa: BLE001
            self.summary.setText(f"<span style='color:#C0392B'>Erreur : {e}</span>")
            ok_btn.setEnabled(False)
            return
        self.preview.setRowCount(min(len(self.ops), 500))
        for i, o in enumerate(self.ops[:500]):
            self.preview.setItem(i, 0, QTableWidgetItem(_fmt_date(o.date)))
            self.preview.setItem(i, 1, QTableWidgetItem(o.label))
            it = QTableWidgetItem(fmt_eur(o.amount))
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            it.setForeground(RED if o.amount < 0 else GREEN)
            self.preview.setItem(i, 2, it)
            bal = QTableWidgetItem(fmt_eur(o.balance) if o.balance is not None else "")
            bal.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.preview.setItem(i, 3, bal)
        self.preview.resizeColumnToContents(0)
        if self.ops:
            dates = sorted(o.date for o in self.ops)
            deb = sum(o.amount for o in self.ops if o.amount < 0)
            cre = sum(o.amount for o in self.ops if o.amount > 0)
            txt = (f"<b>{len(self.ops)} opérations</b> du {_fmt_date(dates[0])} au {_fmt_date(dates[-1])} — "
                   f"débits : {fmt_eur(deb)}, crédits : {fmt_eur(cre)}")
            if skipped:
                txt += f" — {skipped} ligne(s) ignorée(s) (sans date, libellé ou montant)"
            self.summary.setText(txt)
        else:
            self.summary.setText("<span style='color:#C0392B'>Aucune opération lisible avec ces colonnes.</span>")
        ok_btn.setEnabled(bool(self.ops))

    def _import(self):
        if not self.ops:
            return
        new, dup = self.db.import_operations(self.ops, self.path)
        self.result_counts = (new, dup)
        self.accept()


def _col_letter(j):
    s = ""
    j += 1
    while j:
        j, r = divmod(j - 1, 26)
        s = chr(65 + r) + s
    return s


# ======================================================================= Divers
def ask_text(parent, title, label, text=""):
    value, ok = QInputDialog.getText(parent, title, label, QLineEdit.Normal, text)
    return value.strip() if ok else None


class RuleEditDialog(QDialog):
    def __init__(self, db, parent=None, rule=None):
        super().__init__(parent)
        self.db, self.rule = db, rule
        self.setWindowTitle("Modifier la règle" if rule else "Nouvelle règle")
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        self.pattern = QLineEdit(rule.pattern if rule else "")
        form.addRow("Le libellé contient :", self.pattern)
        self.combo = CategoryCombo(self)
        self.combo.populate(db)
        if rule:
            self.combo.set_value(rule.category_id)
        form.addRow("Catégorie :", self.combo)
        self.info = QLabel()
        self.info.setStyleSheet("color:#555")
        self.info.setWordWrap(True)
        form.addRow(self.info)
        self.pattern.textChanged.connect(self._info)
        self._info()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _info(self):
        total, pending = self.db.matching_operations(self.pattern.text())
        self.info.setText(f"{total} opération(s) correspondent, dont {pending} non validée(s) "
                          f"(les opérations validées à la main ne sont jamais modifiées).")

    def _accept(self):
        try:
            self.db.save_rule(self.pattern.text(), self.combo.currentData(),
                              rule_id=self.rule.id if self.rule else None)
        except ValueError as e:
            error(self, e)
            return
        self.accept()


class PasswordDialog(QDialog):
    """Saisie d'un nouveau mot de passe (avec confirmation)."""

    def __init__(self, parent=None, title="Nouveau mot de passe", ask_current=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout(self)
        self.current = None
        if ask_current:
            self.current = QLineEdit()
            self.current.setEchoMode(QLineEdit.Password)
            form.addRow("Mot de passe actuel :", self.current)
        self.p1 = QLineEdit()
        self.p1.setEchoMode(QLineEdit.Password)
        self.p2 = QLineEdit()
        self.p2.setEchoMode(QLineEdit.Password)
        form.addRow("Nouveau mot de passe :", self.p1)
        form.addRow("Confirmation :", self.p2)
        warn = QLabel("Important : ce mot de passe chiffre vos données. S'il est perdu, "
                      "elles ne pourront pas être récupérées.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#CA6F1E")
        form.addRow(warn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _accept(self):
        if len(self.p1.text()) < 4:
            QMessageBox.warning(self, "Mot de passe", "Le mot de passe doit comporter au moins 4 caractères.")
            return
        if self.p1.text() != self.p2.text():
            QMessageBox.warning(self, "Mot de passe", "Les deux saisies ne correspondent pas.")
            return
        self.accept()

    def password(self):
        return self.p1.text()
