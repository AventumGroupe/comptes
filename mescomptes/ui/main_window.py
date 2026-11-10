"""Fenêtre de connexion et fenêtre principale."""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPushButton, QTabWidget, QVBoxLayout)

from .. import APP_NAME, __version__, store
from ..db import Database
from ..importer import ImportError_
from ..settings import Settings, default_data_dir
from .charts_tab import ChartsTab, DetailTab
from .common import error, info, save_path
from .dialogs import ImportDialog, PasswordDialog
from .operations_tab import OperationsTab
from .report_tabs import BudgetTab, CompareTab, SummaryTab
from .settings_tabs import CategoriesTab, RulesTab


# ===================================================================== Connexion
class NewFileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Créer un dossier de comptes")
        self.setMinimumWidth(560)
        form = QFormLayout(self)
        intro = QLabel("Un dossier regroupe les opérations, catégories, règles et budgets d'un compte. Il est "
                       "enregistré dans un seul fichier chiffré, que vous pouvez sauvegarder ou copier. Chaque "
                       "personne peut avoir son propre dossier et son propre mot de passe.")
        intro.setWordWrap(True)
        form.addRow(intro)
        self.name = QLineEdit("Mes comptes")
        form.addRow("Nom du dossier :", self.name)
        row = QHBoxLayout()
        self.folder = QLineEdit(default_data_dir())
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        form.addRow("Emplacement :", row)
        self.p1 = QLineEdit()
        self.p1.setEchoMode(QLineEdit.Password)
        self.p2 = QLineEdit()
        self.p2.setEchoMode(QLineEdit.Password)
        form.addRow("Mot de passe :", self.p1)
        form.addRow("Confirmation :", self.p2)
        warn = QLabel("⚠ Le mot de passe chiffre vos données : s'il est perdu, elles ne pourront pas être "
                      "récupérées. Notez-le en lieu sûr.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#CA6F1E")
        form.addRow(warn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Créer")
        bb.button(QDialogButtonBox.Cancel).setText("Annuler")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.db = None

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Emplacement du dossier", self.folder.text())
        if d:
            self.folder.setText(d)

    def _accept(self):
        name = "".join(c for c in self.name.text().strip() if c not in '<>:"/\\|?*')
        if not name:
            error(self, "Indiquez un nom.")
            return
        if len(self.p1.text()) < 4:
            error(self, "Le mot de passe doit comporter au moins 4 caractères.")
            return
        if self.p1.text() != self.p2.text():
            error(self, "Les deux mots de passe ne correspondent pas.")
            return
        path = os.path.join(self.folder.text(), name + store.FILE_EXTENSION)
        if os.path.exists(path):
            error(self, f"Un dossier existe déjà à cet emplacement :\n{path}")
            return
        try:
            self.db = Database.create(path, self.p1.text())
        except OSError as e:
            error(self, f"Impossible de créer le fichier : {e}")
            return
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.db = None
        self.setWindowTitle(APP_NAME)
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        title = QLabel(f"<h2 style='color:#1F4E79'>{APP_NAME}</h2>"
                       "<p style='color:#555'>Classement et analyse de vos relevés bancaires — "
                       "vos données restent sur cet ordinateur, chiffrées.</p>")
        title.setWordWrap(True)
        lay.addWidget(title)
        form = QFormLayout()
        row = QHBoxLayout()
        self.files = QComboBox()
        self.files.setMinimumWidth(320)
        for p in settings.recent_files():
            self.files.addItem(os.path.splitext(os.path.basename(p))[0], p)
            self.files.setItemData(self.files.count() - 1, p, Qt.ToolTipRole)
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.files, 1)
        row.addWidget(browse)
        form.addRow("Dossier :", row)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.returnPressed.connect(self._open)
        form.addRow("Mot de passe :", self.password)
        lay.addLayout(form)
        self.msg = QLabel()
        self.msg.setStyleSheet("color:#C0392B")
        lay.addWidget(self.msg)
        buttons = QHBoxLayout()
        new_btn = QPushButton("Créer un nouveau dossier…")
        new_btn.clicked.connect(self._new)
        buttons.addWidget(new_btn)
        buttons.addStretch()
        quit_btn = QPushButton("Quitter")
        quit_btn.clicked.connect(self.reject)
        self.open_btn = QPushButton("Ouvrir")
        self.open_btn.setDefault(True)
        self.open_btn.clicked.connect(self._open)
        buttons.addWidget(quit_btn)
        buttons.addWidget(self.open_btn)
        lay.addLayout(buttons)
        if self.files.count() == 0:
            self.msg.setStyleSheet("color:#2471A3")
            self.msg.setText("Première utilisation : cliquez sur « Créer un nouveau dossier… ».")
        self.password.setFocus()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un dossier", default_data_dir(),
                                              f"Dossier Mes Comptes (*{store.FILE_EXTENSION})")
        if path:
            i = self.files.findData(path)
            if i < 0:
                self.files.insertItem(0, os.path.splitext(os.path.basename(path))[0], path)
                i = 0
            self.files.setCurrentIndex(i)
            self.password.setFocus()

    def _open(self):
        path = self.files.currentData()
        if not path:
            self.msg.setText("Choisissez un dossier ou créez-en un.")
            return
        self.msg.setStyleSheet("color:#C0392B")
        self.msg.setText("Ouverture…")
        self.repaint()
        try:
            self.db = Database.open(path, self.password.text())
        except store.WrongPassword:
            self.msg.setText("Mot de passe incorrect.")
            self.password.selectAll()
            return
        except (store.StoreError, OSError) as e:
            self.msg.setText(str(e))
            return
        self.settings.add_recent(path)
        self.accept()

    def _new(self):
        dlg = NewFileDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.db = dlg.db
            self.settings.add_recent(dlg.db.path)
            self.accept()


# =============================================================== Fenêtre principale
class MainWindow(QMainWindow):
    def __init__(self, db, settings):
        super().__init__()
        self.db = db
        self.settings = settings
        name = os.path.splitext(os.path.basename(db.path))[0]
        self.setWindowTitle(f"{APP_NAME} — {name}")
        self.resize(1360, 860)

        self.tabs = QTabWidget()
        self.ops_tab = OperationsTab(db)
        self.summary_tab = SummaryTab(db)
        self.compare_tab = CompareTab(db)
        self.detail_tab = DetailTab(db)
        self.charts_tab = ChartsTab(db)
        self.budget_tab = BudgetTab(db)
        self.cat_tab = CategoriesTab(db)
        self.rules_tab = RulesTab(db)
        self.all_tabs = [(self.ops_tab, "Opérations"), (self.summary_tab, "Synthèse mensuelle"),
                         (self.compare_tab, "Comparaison"), (self.detail_tab, "Détail par catégorie"),
                         (self.charts_tab, "Graphiques"), (self.budget_tab, "Budget"),
                         (self.cat_tab, "Catégories"), (self.rules_tab, "Règles")]
        for w, label in self.all_tabs:
            self.tabs.addTab(w, label)
            if hasattr(w, "changed"):
                w.changed.connect(self.data_changed)
        self.ops_tab.import_requested.connect(self.import_statement)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)
        self._stale = set(range(len(self.all_tabs)))
        self._build_menu()
        self.statusBar().showMessage(f"Dossier : {db.path}")
        QTimer.singleShot(0, lambda: self._tab_changed(0))
        if not db.operations():
            QTimer.singleShot(300, self._welcome)

    def _build_menu(self):
        m = self.menuBar().addMenu("&Fichier")
        a = QAction("Importer un relevé…", self)
        a.setShortcut(QKeySequence("Ctrl+I"))
        a.triggered.connect(self.import_statement)
        m.addAction(a)
        m.addSeparator()
        m.addAction("Enregistrer une copie de sauvegarde…", self.save_copy)
        m.addAction("Ouvrir le dossier des sauvegardes automatiques", self.open_backups)
        m.addAction("Changer le mot de passe…", self.change_password)
        m.addSeparator()
        q = QAction("Quitter", self)
        q.setShortcut(QKeySequence("Ctrl+Q"))
        q.triggered.connect(self.close)
        m.addAction(q)
        h = self.menuBar().addMenu("&Aide")
        h.addAction("Comment ça marche ?", self._welcome)
        h.addAction("À propos", lambda: info(self, f"{APP_NAME} {__version__}\n\nApplication locale : aucune donnée "
                                                   f"n'est envoyée sur internet.\nFichier : {self.db.path}"))

    def _welcome(self):
        QMessageBox.information(self, "Bienvenue", (
            "<h3>Comment ça marche</h3>"
            "<ol>"
            "<li><b>Importez</b> votre relevé Excel du Crédit Mutuel (Fichier › Importer, ou le bouton 📥).</li>"
            "<li><b>Classez</b> les opérations « à classer » : double-cliquez sur une ligne, choisissez la catégorie. "
            "L'application <b>mémorise le fournisseur</b> et classera automatiquement ses prochaines opérations.</li>"
            "<li>Les opérations classées automatiquement apparaissent en <span style='color:#2471A3'>bleu</span> : "
            "validez-les ou corrigez-les. En cas de correction, vous choisissez : exception ponctuelle ou "
            "modification de la règle.</li>"
            "<li>Analysez : synthèse mensuelle, comparaisons (mois précédent, N-1), détail par catégorie, "
            "graphiques, budget. Exports Excel et PDF.</li>"
            "</ol>"
            "<p>Les catégories proposées sont modifiables dans l'onglet « Catégories », les règles apprises dans "
            "l'onglet « Règles ».</p>"))

    # ------------------------------------------------------------- rafraîchissement
    def data_changed(self):
        self._stale = set(range(len(self.all_tabs)))
        self._tab_changed(self.tabs.currentIndex())

    def _tab_changed(self, idx):
        if idx in self._stale:
            self._stale.discard(idx)
            self.all_tabs[idx][0].refresh()

    # ------------------------------------------------------------------- actions
    def import_statement(self):
        start = self.settings.get("import_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, "Importer un relevé", start,
                                              "Relevés (*.xlsx *.xls *.xlsm *.csv);;Tous les fichiers (*)")
        if not path:
            return
        self.settings.set("import_dir", os.path.dirname(path))
        try:
            dlg = ImportDialog(self.db, path, self)
        except (ImportError_, Exception) as e:  # noqa: BLE001
            error(self, f"Lecture du fichier impossible :\n{e}")
            return
        if dlg.exec() == QDialog.Accepted and dlg.result_counts:
            new, dup = dlg.result_counts
            counts = self.db.count_by_status()
            msg = f"{new} opération(s) importée(s)."
            if dup:
                msg += f"\n{dup} opération(s) déjà présente(s) ignorée(s)."
            msg += (f"\n\n{counts.get('auto', 0)} classée(s) automatiquement (à vérifier), "
                    f"{counts.get('none', 0)} à classer.")
            info(self, msg, "Import terminé")
            self.data_changed()
            self.tabs.setCurrentWidget(self.ops_tab)
            if counts.get("none"):
                self.ops_tab.show_todo()

    def save_copy(self):
        base = os.path.splitext(os.path.basename(self.db.path))[0]
        path = save_path(self, "Enregistrer une copie", f"{base} (copie){store.FILE_EXTENSION}",
                         f"Dossier Mes Comptes (*{store.FILE_EXTENSION})")
        if path:
            self.db.save_copy(path)
            info(self, f"Copie enregistrée (même mot de passe) :\n{path}")

    def open_backups(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        folder = os.path.join(os.path.dirname(os.path.abspath(self.db.path)), "sauvegardes")
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def change_password(self):
        dlg = PasswordDialog(self, "Changer le mot de passe", ask_current=True)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            store.read_file(self.db.path, dlg.current.text())
        except store.WrongPassword:
            error(self, "Le mot de passe actuel est incorrect.")
            return
        self.db.change_password(dlg.password())
        info(self, "Mot de passe modifié.")

    def closeEvent(self, event):
        try:
            self.db.close()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Erreur", f"Enregistrement impossible : {e}")
        event.accept()
