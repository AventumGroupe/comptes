"""Test de fumée de l'interface : ouvre chaque onglet et chaque export sur un relevé fictif."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from fake_statement import generate  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_full_ui(app, tmp_path, monkeypatch):
    from mescomptes.db import Database
    from mescomptes.exporters import export_excel, export_pdf
    from mescomptes.settings import Settings
    from mescomptes.ui import main_window as mw
    from mescomptes.ui.dialogs import ClassifyDialog, ImportDialog

    monkeypatch.setattr(mw.MainWindow, "_welcome", lambda self: None)
    xlsx = str(tmp_path / "releve.xlsx")
    n = generate(xlsx)
    db = Database.create(str(tmp_path / "t.mcpt"), "1234")

    dlg = ImportDialog(db, xlsx)
    assert len(dlg.ops) == n
    dlg._import()
    assert dlg.result_counts == (n, 0)

    def cat(name):
        return next(c.id for c in db.categories().values() if c.name == name)

    # Classement via le dialogue, avec création de règle
    op = [dict(o) for o in db.operations() if "CARREFOUR" in o["label"]][0]
    cd = ClassifyDialog(db, [op])
    assert cd.r_rule.isChecked() and cd.pattern.text() == "CARREFOUR MARKET"
    cd.combo.set_value(cat("Supermarché"))
    cd._accept()
    assert db.operation(op["id"])["status"] == "manual"
    assert all(o["category_id"] == cat("Supermarché") for o in db.operations() if "CARREFOUR" in o["label"])

    # Correction d'une opération auto : aucun choix par défaut
    auto = [dict(o) for o in db.operations() if o["status"] == "auto"][0]
    cd2 = ClassifyDialog(db, [auto])
    assert cd2.group.checkedButton() is None and cd2.r_update is not None

    db.save_rule("EDF", cat("Électricité"))
    db.set_budget(cat("Courses"), 2026, 50000)

    win = mw.MainWindow(db, Settings(str(tmp_path / "prefs.json")))
    win.show()
    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        app.processEvents()
    for k in range(win.charts_tab.kind.count()):
        win.charts_tab.kind.setCurrentIndex(k)
    for k in range(win.summary_tab.mode.count()):
        win.summary_tab.mode.setCurrentIndex(k)
    for k in range(win.compare_tab.mode.count()):
        win.compare_tab.mode.setCurrentIndex(k)
    win.detail_tab.show_category(cat("Courses"))
    app.processEvents()

    export_excel(str(tmp_path / "s.xlsx"), [win.summary_tab.table()])
    export_pdf(str(tmp_path / "s.pdf"), [win.summary_tab.table()],
               images=[("g", win.charts_tab.canvas.png_bytes())])
    assert os.path.getsize(tmp_path / "s.pdf") > 1000
    win.close()
    assert len(Database.open(str(tmp_path / "t.mcpt"), "1234").operations()) == n
