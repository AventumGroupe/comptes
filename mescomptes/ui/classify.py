"""Panneau de classement (volet latéral) et sa version en boîte de dialogue."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QScrollArea, QVBoxLayout, QWidget)

from ..db import AUTO, MANUAL, NONE
from ..money import fmt_eur
from ..normalize import label_key
from . import theme as T
from .common import CategoryPicker, button, error, hline, label


def _fmt_date(d):
    return f"{d[8:10]}/{d[5:7]}/{d[:4]}" if d else ""


class ClassifyPanel(QFrame):
    """Détail d'une (ou plusieurs) opération(s) et choix de la catégorie + apprentissage."""
    applied = Signal(list)   # identifiants des opérations modifiées
    close_requested = Signal()

    def __init__(self, db, parent=None, closable=True):
        super().__init__(parent)
        self.db = db
        self.ops = []
        self.current_rule = None
        self.setObjectName("drawer")
        self.setMinimumWidth(320)
        self.setMaximumWidth(420)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        head = QHBoxLayout()
        self.kicker = label("OPÉRATION", "kpiLabel")
        head.addWidget(self.kicker)
        head.addStretch()
        if closable:
            x = QPushButton()
            x.setObjectName("ghost")
            x.setIcon(T.icon("x", T.MUTED))
            x.setToolTip("Fermer le volet")
            x.setCursor(Qt.PointingHandCursor)
            x.clicked.connect(self.close_requested)
            head.addWidget(x)
        root.addLayout(head)

        # ---- état vide
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.addStretch()
        ic = QLabel()
        ic.setPixmap(T.pixmap("sparkle", T.ACCENT, 34))
        ic.setAlignment(Qt.AlignCenter)
        el.addWidget(ic)
        msg = label("Sélectionnez une opération dans la liste pour la classer.\n\n"
                    "Astuce : sélectionnez plusieurs lignes (Ctrl ou Maj) pour les classer d'un coup.", "muted", True)
        msg.setAlignment(Qt.AlignCenter)
        el.addWidget(msg)
        el.addStretch()
        root.addWidget(self.empty, 1)

        # ---- contenu (défilant si l'écran est petit)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self.content = QWidget()
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        self.amount = label("", "kpiValue")
        cl.addWidget(self.amount)
        self.title = label("", wrap=True)
        self.title.setStyleSheet("font-weight:600; font-size:10.5pt")
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cl.addWidget(self.title)
        self.meta = label("", "muted", True)
        cl.addWidget(self.meta)
        self.state = label("", wrap=True)
        self.state.setTextFormat(Qt.RichText)
        cl.addWidget(self.state)
        cl.addWidget(hline())

        cat_head = QHBoxLayout()
        cat_head.addWidget(label("Catégorie", "sectionTitle"))
        cat_head.addStretch()
        self.new_cat = button("Nouvelle", "plus", "link", slot=self._new_category)
        self.new_cat.setToolTip("Créer une catégorie ou sous-catégorie")
        cat_head.addWidget(self.new_cat)
        cl.addLayout(cat_head)
        self.picker = CategoryPicker(db)
        self.picker.setMinimumHeight(220)
        self.picker.selection_changed.connect(self._update)
        self.picker.chosen.connect(lambda _v: self.apply())
        cl.addWidget(self.picker, 1)

        cl.addWidget(label("Apprentissage", "sectionTitle"))
        self.group = QButtonGroup(self)
        self.r_rule = QRadioButton("Mémoriser ce fournisseur")
        self.r_rule.setToolTip("Les prochaines opérations de ce fournisseur seront classées automatiquement.")
        self.r_update = QRadioButton("Modifier la règle existante")
        self.r_only = QRadioButton("Exception (cette opération seulement)")
        for r in (self.r_rule, self.r_update, self.r_only):
            self.group.addButton(r)
            cl.addWidget(r)
        prow = QHBoxLayout()
        prow.setContentsMargins(26, 0, 0, 0)
        prow.addWidget(label("Motif", "muted"))
        self.pattern = QLineEdit()
        self.pattern.setPlaceholderText("ex. CARREFOUR")
        prow.addWidget(self.pattern, 1)
        cl.addLayout(prow)
        self.match_info = label("", "muted", True)
        self.match_info.setTextFormat(Qt.RichText)
        self.match_info.setContentsMargins(26, 0, 0, 0)
        cl.addWidget(self.match_info)

        nrow = QHBoxLayout()
        nrow.addWidget(label("Note", "muted"))
        self.note = QLineEdit()
        self.note.setPlaceholderText("Ajouter une note…")
        self.note.editingFinished.connect(self._save_note)
        nrow.addWidget(self.note, 1)
        cl.addLayout(nrow)

        buttons = QHBoxLayout()
        self.btn_validate = button("Valider la suggestion", "check", tooltip="Confirme la catégorie proposée",
                                   slot=self.validate)
        self.btn_apply = button("Enregistrer", None, "primary", tooltip="Ctrl+Entrée", slot=self.apply)
        buttons.addWidget(self.btn_validate)
        buttons.addStretch()
        buttons.addWidget(self.btn_apply)
        cl.addLayout(buttons)
        self.hint = label("", "muted", True)
        cl.addWidget(self.hint)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)

        self.pattern.textChanged.connect(self._update)
        self.pattern.textEdited.connect(lambda: self.r_rule.setChecked(True))
        self.group.buttonToggled.connect(self._update)
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(seq), self, self.apply, context=Qt.WidgetWithChildrenShortcut)
        self.set_ops([])

    # ------------------------------------------------------------------
    def refresh_categories(self):
        self.picker.populate()

    def set_ops(self, ops, preset_category=None):
        self.ops = [dict(o) for o in ops]
        has = bool(self.ops)
        self.empty.setVisible(not has)
        self.scroll.setVisible(has)
        if not has:
            self.kicker.setText("OPÉRATION")
            return
        ops = self.ops
        if len(ops) == 1:
            o = ops[0]
            self.kicker.setText("OPÉRATION")
            self.amount.setText(fmt_eur(o["amount"], signed=True))
            self.amount.setStyleSheet(f"color:{T.GREEN if o['amount'] > 0 else T.TEXT}")
            self.title.setText(o["label"])
            self.meta.setText(f"{_fmt_date(o['date'])}  ·  Fournisseur : {o['vendor'] or '—'}")
            self.note.setText(o["note"])
            self.note.setEnabled(True)
        else:
            total = sum(o["amount"] for o in ops)
            self.kicker.setText(f"{len(ops)} OPÉRATIONS")
            self.amount.setText(fmt_eur(total, signed=True))
            self.amount.setStyleSheet(f"color:{T.GREEN if total > 0 else T.TEXT}")
            vendors = sorted({o["vendor"] for o in ops})
            self.title.setText(", ".join(vendors[:4]) + ("…" if len(vendors) > 4 else ""))
            self.meta.setText(f"Du {_fmt_date(min(o['date'] for o in ops))} au {_fmt_date(max(o['date'] for o in ops))}")
            self.note.setText("")
            self.note.setEnabled(False)

        # état actuel
        statuses = {o["status"] for o in ops}
        rule_ids = {o["rule_id"] for o in ops if o["status"] == AUTO}
        self.current_rule = (self.db.rule(next(iter(rule_ids)))
                             if statuses == {AUTO} and len(rule_ids) == 1 else None)
        cats = {o["category_id"] for o in ops}
        cat_label = self.db.category_label(next(iter(cats))) if len(cats) == 1 else ""
        if statuses == {NONE}:
            self.state.setText(f"<span style='color:{T.ORANGE}'>● À classer</span>")
        elif statuses == {AUTO} and cat_label:
            rule = f" (règle « {self.current_rule.pattern} »)" if self.current_rule else ""
            self.state.setText(f"<span style='color:{T.BLUE}'>● Proposée automatiquement :</span> "
                               f"<b>{cat_label}</b>{rule}")
        elif statuses == {MANUAL} and cat_label:
            self.state.setText(f"<span style='color:{T.GREEN}'>● Validée :</span> <b>{cat_label}</b>")
        else:
            self.state.setText(f"<span style='color:{T.MUTED}'>Statuts et catégories variés</span>")

        start = preset_category if preset_category is not None else (next(iter(cats)) if len(cats) == 1 else None)
        self.picker.search.clear()
        self.picker.set_value(start)

        vendors = {o["vendor"] for o in ops}
        self.pattern.setText(next(iter(vendors)) if len(vendors) == 1 else "")
        self.r_update.setVisible(self.current_rule is not None)
        if self.current_rule:
            self.r_update.setText(f"Modifier la règle « {self.current_rule.pattern} »")
            self.r_update.setToolTip("La nouvelle catégorie s'appliquera à toutes les opérations non validées "
                                     "de ce fournisseur, et aux suivantes.")
        self.r_only.setText("Exception (cette opération seulement)" if len(ops) == 1
                            else f"Exception (ces {len(ops)} opérations seulement)")
        self.btn_validate.setVisible(statuses == {AUTO})

        # choix par défaut
        self.group.setExclusive(False)
        for r in (self.r_rule, self.r_update, self.r_only):
            r.setChecked(False)
        self.group.setExclusive(True)
        if statuses == {MANUAL}:
            self.r_only.setChecked(True)
        elif self.current_rule is None:
            self.r_rule.setChecked(True)
        # correction d'une proposition automatique : aucun choix imposé (au cas par cas)
        self._update()

    def _update(self, *_):
        if not self.ops:
            return
        cat = self.picker.value()
        rule_mode = self.r_rule.isChecked()
        self.pattern.setEnabled(rule_mode or not self.r_update.isChecked())
        ok = self.group.checkedButton() is not None and cat is not None
        txt = ""
        if rule_mode:
            pat = self.pattern.text()
            if not label_key(pat):
                txt = "Saisissez un mot du libellé (hors chiffres)."
                ok = False
            else:
                total, pending = self.db.matching_operations(pat)
                txt = f"{total} opération(s) concernée(s), dont {pending} non validée(s) qui seront classées."
                existing = self.db.rule_by_pattern(pat)
                if existing:
                    txt += (f"<br><span style='color:{T.ORANGE}'>Règle existante (→ "
                            f"{self.db.category_label(existing.category_id)}) : elle sera mise à jour.</span>")
                missing = sum(1 for o in self.ops if f" {label_key(pat)} " not in f" {o['label_key']} ")
                if missing:
                    txt += f"<br><span style='color:{T.RED}'>{missing} opération(s) sélectionnée(s) ne contiennent pas ce motif.</span>"
        elif self.r_update.isChecked() and self.current_rule:
            _, pending = self.db.matching_operations(self.current_rule.pattern)
            txt = (f"Actuellement → {self.db.category_label(self.current_rule.category_id)}. "
                   f"{pending} opération(s) non validée(s) suivront la nouvelle catégorie.")
        elif self.r_only.isChecked():
            txt = "Aucune règle créée ni modifiée."
        self.match_info.setText(txt)
        self.btn_apply.setEnabled(ok)
        if cat is None:
            self.hint.setText("Choisissez une catégorie (double-clic pour enregistrer directement).")
        elif self.group.checkedButton() is None:
            self.hint.setText("Opération classée automatiquement : choisissez comment appliquer la correction.")
        else:
            self.hint.setText("")

    # ------------------------------------------------------------------
    def apply(self):
        if not self.ops or not self.btn_apply.isEnabled():
            return
        cat = self.picker.value()
        ids = [o["id"] for o in self.ops]
        try:
            self.db.classify(ids, cat, save=False)
            if self.r_rule.isChecked():
                self.db.save_rule(self.pattern.text(), cat)
            elif self.r_update.isChecked() and self.current_rule:
                self.db.save_rule(self.current_rule.pattern, cat, rule_id=self.current_rule.id)
            else:
                self.db.save()
        except ValueError as e:
            error(self, e)
            return
        self.applied.emit(ids)

    def validate(self):
        ids = [o["id"] for o in self.ops if o["status"] == AUTO]
        if ids:
            self.db.validate(ids)
            self.applied.emit(ids)

    def _save_note(self):
        if len(self.ops) == 1 and self.note.text() != self.ops[0]["note"]:
            self.db.set_note(self.ops[0]["id"], self.note.text())
            self.ops[0]["note"] = self.note.text()

    def _new_category(self):
        from .dialogs import CategoryEditDialog
        dlg = CategoryEditDialog(self.db, self, parent_id=self.db.top_category_id(self.picker.value()))
        if dlg.exec() == QDialog.Accepted:
            self.picker.populate()
            self.picker.set_value(dlg.created_id)


class ClassifyDialog(QDialog):
    """Même panneau, en fenêtre (depuis les vues d'analyse)."""

    def __init__(self, db, ops, parent=None, preset_category=None):
        super().__init__(parent)
        self.setWindowTitle("Classer l'opération" if len(ops) == 1 else f"Classer {len(ops)} opérations")
        self.resize(460, 720)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.panel = ClassifyPanel(db, self, closable=False)
        self.panel.setMaximumWidth(16777215)
        self.panel.setStyleSheet("QFrame#drawer { border: none; }")
        lay.addWidget(self.panel)
        self.panel.set_ops(ops, preset_category)
        self.panel.applied.connect(lambda _ids: self.accept())

    # compatibilité avec les tests
    @property
    def r_rule(self):
        return self.panel.r_rule

    @property
    def r_update(self):
        return self.panel.r_update if self.panel.current_rule else None

    @property
    def group(self):
        return self.panel.group

    @property
    def pattern(self):
        return self.panel.pattern

    def _accept(self):
        self.panel.apply()


__all__ = ["ClassifyPanel", "ClassifyDialog", "QSize"]
