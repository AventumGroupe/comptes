"""Écran de connexion et fenêtre principale (navigation latérale)."""

import os
import sys

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout,
                               QWidget)

from .. import APP_NAME, __version__, store
from ..db import NONE, Database
from ..importer import ImportError_
from ..settings import Settings, default_data_dir
from . import theme as T
from .charts_tab import ChartsTab, DetailTab
from .common import Card, button, error, info, label, save_path
from .dashboard import DashboardPage
from .dialogs import ImportDialog, PasswordDialog
from .operations_tab import OperationsTab
from .report_tabs import BudgetTab, CompareTab, SummaryTab
from .settings_tabs import CategoriesTab, RulesTab


def caps_lock_on():
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.WinDLL("User32.dll").GetKeyState(0x14) & 1)
    except Exception:  # noqa: BLE001
        return False


class PasswordField(QWidget):
    """Champ mot de passe avec bouton « afficher » et alerte Verr. Maj."""

    def __init__(self, placeholder="Mot de passe", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText(placeholder)
        self.toggle = self.edit.addAction(T.icon("eye", T.SUBTLE), QLineEdit.TrailingPosition)
        self.toggle.setToolTip("Afficher / masquer le mot de passe")
        self.toggle.triggered.connect(self._toggle)
        lay.addWidget(self.edit)
        self.caps = label("⚠ Verr. Maj est activé", None)
        self.caps.setStyleSheet(f"color:{T.ORANGE}; font-size:9pt")
        self.caps.hide()
        lay.addWidget(self.caps)
        self.edit.textEdited.connect(self._check_caps)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check_caps)
        self._timer.start(700)

    def _toggle(self):
        show = self.edit.echoMode() == QLineEdit.Password
        self.edit.setEchoMode(QLineEdit.Normal if show else QLineEdit.Password)
        self.toggle.setIcon(T.icon("eye", T.ACCENT if show else T.SUBTLE))

    def _check_caps(self, *_):
        self.caps.setVisible(self.edit.hasFocus() and caps_lock_on())

    def text(self):
        return self.edit.text()


# ===================================================================== Connexion
class NewFileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Créer un dossier de comptes")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 20)
        lay.setSpacing(10)
        lay.addWidget(label("Nouveau dossier", "title"))
        lay.addWidget(label("Un dossier regroupe les opérations, catégories, règles et budgets d'un compte, dans un "
                            "seul fichier chiffré que vous pouvez sauvegarder ou copier. Chaque personne peut avoir "
                            "son propre dossier et son propre mot de passe.", "subtitle", True))
        lay.addWidget(label("Nom du dossier", "kpiLabel"))
        self.name = QLineEdit("Mes comptes")
        lay.addWidget(self.name)
        lay.addWidget(label("Emplacement", "kpiLabel"))
        row = QHBoxLayout()
        self.folder = QLineEdit(default_data_dir())
        row.addWidget(self.folder, 1)
        row.addWidget(button("Parcourir…", slot=self._browse))
        lay.addLayout(row)
        lay.addWidget(label("Mot de passe", "kpiLabel"))
        self.p1 = PasswordField("Mot de passe (4 caractères minimum)")
        self.p2 = PasswordField("Confirmation")
        lay.addWidget(self.p1)
        lay.addWidget(self.p2)
        warn = label("Le mot de passe chiffre vos données : s'il est perdu, elles ne pourront pas être récupérées. "
                     "Notez-le en lieu sûr.", None, True)
        warn.setStyleSheet(f"color:{T.ORANGE}; background:{T.ORANGE_SOFT}; border-radius:8px; padding:8px")
        lay.addWidget(warn)
        row2 = QHBoxLayout()
        row2.addStretch()
        row2.addWidget(button("Annuler", slot=self.reject))
        row2.addWidget(button("Créer le dossier", None, "primary", slot=self._accept))
        lay.addLayout(row2)
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
        self.resize(520, 520)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(36, 30, 36, 26)
        card = Card(margins=(28, 26, 28, 22), spacing=10)
        logo = QLabel()
        logo.setPixmap(T.pixmap("chart", T.ACCENT, 34))
        card.add(logo)
        card.add(label(APP_NAME, "title"))
        card.add(label("Vos comptes classés et analysés automatiquement. Vos données restent sur cet "
                       "ordinateur, chiffrées.", "subtitle", True))
        card.layout_.addSpacing(6)
        card.add(label("DOSSIER", "kpiLabel"))
        row = QHBoxLayout()
        self.files = QComboBox()
        for p in settings.recent_files():
            self.files.addItem(T.icon("lock", T.MUTED), os.path.splitext(os.path.basename(p))[0], p)
            self.files.setItemData(self.files.count() - 1, p, Qt.ToolTipRole)
        row.addWidget(self.files, 1)
        row.addWidget(button("Parcourir…", slot=self._browse))
        card.add(row)
        card.add(label("MOT DE PASSE", "kpiLabel"))
        self.password = PasswordField()
        self.password.edit.returnPressed.connect(self._open)
        card.add(self.password)
        self.msg = label("", None, True)
        self.msg.setStyleSheet(f"color:{T.RED}")
        card.add(self.msg)
        self.open_btn = button("Ouvrir", "lock", "primary", slot=self._open)
        self.open_btn.setMinimumHeight(36)
        card.add(self.open_btn)
        card.add(hrow := QHBoxLayout())
        hrow.addWidget(button("Créer un nouveau dossier", "plus", "link", slot=self._new))
        hrow.addStretch()
        hrow.addWidget(button("Quitter", None, "ghost", slot=self.reject))
        outer.addWidget(card)
        if self.files.count() == 0:
            self.msg.setStyleSheet(f"color:{T.BLUE}")
            self.msg.setText("Première utilisation : cliquez sur « Créer un nouveau dossier ».")
        self.password.edit.setFocus()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un dossier", default_data_dir(),
                                              f"Dossier Mes Comptes (*{store.FILE_EXTENSION})")
        if path:
            i = self.files.findData(path)
            if i < 0:
                self.files.insertItem(0, T.icon("lock", T.MUTED), os.path.splitext(os.path.basename(path))[0], path)
                i = 0
            self.files.setCurrentIndex(i)
            self.password.edit.setFocus()

    def _open(self):
        path = self.files.currentData()
        if not path:
            self.msg.setText("Choisissez un dossier ou créez-en un.")
            return
        self.msg.setStyleSheet(f"color:{T.RED}")
        self.msg.setText("Ouverture…")
        self.repaint()
        try:
            self.db = Database.open(path, self.password.text())
        except store.WrongPassword:
            self.msg.setText("Mot de passe incorrect." + (" Attention : Verr. Maj est activé." if caps_lock_on() else ""))
            self.password.edit.selectAll()
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
    NAV = [
        (None, "PILOTAGE"),
        ("dashboard", "Tableau de bord"),
        ("list", "Opérations"),
        (None, "ANALYSES"),
        ("table", "Synthèse mensuelle"),
        ("compare", "Comparaison"),
        ("pie", "Détail par catégorie"),
        ("chart", "Graphiques"),
        ("target", "Budget"),
        (None, "PARAMÈTRES"),
        ("tag", "Catégories"),
        ("wand", "Règles"),
    ]

    def __init__(self, db, settings):
        super().__init__()
        self.db = db
        self.settings = settings
        self.name = os.path.splitext(os.path.basename(db.path))[0]
        self.setWindowTitle(f"{APP_NAME} — {self.name}")
        self.resize(1440, 900)

        self.dashboard = DashboardPage(db)
        self.ops_tab = OperationsTab(db)
        self.summary_tab = SummaryTab(db)
        self.compare_tab = CompareTab(db)
        self.detail_tab = DetailTab(db)
        self.charts_tab = ChartsTab(db)
        self.budget_tab = BudgetTab(db)
        self.cat_tab = CategoriesTab(db)
        self.rules_tab = RulesTab(db)
        self.pages = [self.dashboard, self.ops_tab, self.summary_tab, self.compare_tab, self.detail_tab,
                      self.charts_tab, self.budget_tab, self.cat_tab, self.rules_tab]
        self.stack = QStackedWidget()
        for p in self.pages:
            self.stack.addWidget(p)
            if hasattr(p, "changed"):
                p.changed.connect(self.data_changed)
        self.ops_tab.import_requested.connect(self.import_statement)
        self.dashboard.go_todo.connect(self.go_todo)
        self.dashboard.go_operations.connect(lambda: self.show_page(1))
        self.dashboard.open_category.connect(self.open_category)

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._sidebar())
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        QShortcut(QKeySequence("Ctrl+I"), self, self.import_statement)
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)
        self._stale = set(range(len(self.pages)))
        QTimer.singleShot(0, lambda: self.show_page(0 if db.operations() else 1))
        if not db.operations():
            QTimer.singleShot(300, self._welcome)

    # ----------------------------------------------------------------- barre
    def _sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(236)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(2)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(T.pixmap("chart", T.ACCENT, 24))
        brand.addWidget(logo)
        brand.addWidget(label(APP_NAME, "brand"))
        brand.addStretch()
        lay.addLayout(brand)
        lay.addSpacing(14)
        imp = button("Importer un relevé", "upload", "primary", slot=self.import_statement,
                     tooltip="Ctrl+I")
        imp.setMinimumHeight(34)
        lay.addWidget(imp)
        lay.addSpacing(8)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        page_index = 0
        for ic, text in self.NAV:
            if ic is None:
                lay.addWidget(label(text, "navSection"))
                continue
            b = QPushButton(text)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(T.icon(ic, T.MUTED, active_color=T.ACCENT))
            b.setIconSize(QSize(18, 18))
            if text == "Opérations":
                bl = QHBoxLayout(b)
                bl.setContentsMargins(0, 0, 8, 0)
                bl.addStretch()
                self.badge = label("", "badge")
                self.badge.setAttribute(Qt.WA_TransparentForMouseEvents)
                bl.addWidget(self.badge)
            idx = page_index
            b.clicked.connect(lambda _c=False, i=idx: self.show_page(i))
            self.nav_group.addButton(b)
            self.nav_buttons.append(b)
            lay.addWidget(b)
            page_index += 1
        lay.addStretch()
        foot = QFrame()
        foot.setStyleSheet(f"QFrame {{ background:{T.BG}; border-radius:10px; }}")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(10, 8, 6, 8)
        ic = QLabel()
        ic.setPixmap(T.pixmap("lock", T.MUTED, 16))
        fl.addWidget(ic)
        txt = QVBoxLayout()
        txt.setSpacing(0)
        txt.addWidget(label(self.name, None))
        sub = label("Dossier chiffré", "muted")
        sub.setStyleSheet("font-size:8.5pt")
        txt.addWidget(sub)
        fl.addLayout(txt, 1)
        more = QPushButton("⋯")
        more.setObjectName("ghost")
        more.setCursor(Qt.PointingHandCursor)
        more.setToolTip("Sauvegarde, mot de passe, aide")
        menu = QMenu(more)
        menu.addAction(T.icon("download"), "Enregistrer une copie de sauvegarde…", self.save_copy)
        menu.addAction(T.icon("file"), "Ouvrir le dossier des sauvegardes", self.open_backups)
        menu.addAction(T.icon("lock"), "Changer le mot de passe…", self.change_password)
        menu.addSeparator()
        menu.addAction(T.icon("sparkle"), "Comment ça marche ?", self._welcome)
        menu.addAction("À propos", lambda: info(self, f"{APP_NAME} {__version__}\n\nApplication locale : aucune "
                                                      f"donnée n'est envoyée sur internet.\nFichier : {self.db.path}"))
        menu.addSeparator()
        menu.addAction(T.icon("logout"), "Quitter", self.close)
        more.setMenu(menu)
        more.setStyleSheet("QPushButton::menu-indicator { image: none; width: 0; }")
        fl.addWidget(more)
        lay.addWidget(foot)
        return side

    def _update_badges(self):
        n = self.db.count_by_status().get(NONE, 0)
        self.badge.setText(str(n))
        self.badge.setVisible(n > 0)
        self.badge.setToolTip(f"{n} opération(s) à classer")

    def show_page(self, idx):
        self.nav_buttons[idx].setChecked(True)
        self.stack.setCurrentIndex(idx)
        if idx in self._stale:
            self._stale.discard(idx)
            self.pages[idx].refresh()
        self._update_badges()

    def _welcome(self):
        QMessageBox.information(self, "Bienvenue", (
            "<h3>Comment ça marche</h3>"
            "<ol>"
            "<li><b>Importez</b> votre relevé Excel du Crédit Mutuel (bouton « Importer un relevé », ou Ctrl+I).</li>"
            "<li>Dans <b>Opérations</b>, cliquez sur une ligne : le volet de droite permet de choisir la catégorie. "
            "L'application <b>mémorise le fournisseur</b> et passe automatiquement à l'opération suivante.</li>"
            "<li>Les opérations classées automatiquement sont « À vérifier » : validez-les ou corrigez-les "
            "(exception ponctuelle ou modification de la règle, au choix).</li>"
            "<li>Analysez : tableau de bord, synthèse mensuelle, comparaisons, détail par catégorie, graphiques, "
            "budget. Exports Excel et PDF.</li>"
            "</ol>"))

    # ------------------------------------------------------------- navigation
    def data_changed(self):
        self._stale = set(range(len(self.pages)))
        self._stale.discard(self.stack.currentIndex())
        self._update_badges()

    def go_todo(self):
        self.show_page(1)
        self.ops_tab.show_todo()

    def open_category(self, cat_id):
        self.show_page(4)
        self.detail_tab.show_category(cat_id)

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
            self._stale = set(range(len(self.pages)))
            if counts.get("none"):
                self.go_todo()
            else:
                self.show_page(1)

    def save_copy(self):
        base = os.path.splitext(os.path.basename(self.db.path))[0]
        path = save_path(self, "Enregistrer une copie", f"{base} (copie){store.FILE_EXTENSION}",
                         f"Dossier Mes Comptes (*{store.FILE_EXTENSION})")
        if path:
            self.db.save_copy(path)
            info(self, f"Copie enregistrée (même mot de passe) :\n{path}")

    def open_backups(self):
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


__all__ = ["Settings"]
