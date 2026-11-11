"""Point d'entrée de l'application."""

import os
import sys


def main():
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QDialog

    from . import APP_NAME
    from .settings import Settings
    from .ui.main_window import LoginDialog, MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    from .ui.theme import apply_theme
    apply_theme(app)
    icon_path = _resource("assets/icone.ico")
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    settings = Settings()
    login = LoginDialog(settings)
    if login.exec() != QDialog.Accepted or login.db is None:
        return 0
    win = MainWindow(login.db, settings)
    win.showMaximized()
    code = app.exec()
    # Les données sont déjà enregistrées (fermeture de la fenêtre). Sortie directe pour éviter
    # un éventuel plantage de Qt pendant la destruction des objets à la fermeture de Python.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def _resource(rel):
    import os
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(base, rel)
    return path if os.path.exists(path) else None


if __name__ == "__main__":
    sys.exit(main())
