"""Scénario complet de l'interface, exécuté dans un processus séparé par test_ui.py.
Affiche UI-OK à la fin si tout s'est bien passé."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import pathlib  # noqa: E402

from PySide6 import QtWidgets  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from fake_statement import generate  # noqa: E402


def run(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from mescomptes.db import Database
    from mescomptes.exporters import export_excel, export_pdf
    from mescomptes.settings import Settings
    from mescomptes.ui import main_window as mw
    from mescomptes.ui.classify import ClassifyDialog
    from mescomptes.ui.dialogs import ImportDialog
    from mescomptes.ui.theme import apply_theme
    apply_theme(app)

    mw.MainWindow._welcome = lambda self: None
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
    cd.panel.picker.set_value(cat("Supermarché"))
    cd._accept()
    assert db.operation(op["id"])["status"] == "manual"
    assert all(o["category_id"] == cat("Supermarché") for o in db.operations() if "CARREFOUR" in o["label"])

    # Correction d'une opération auto : aucun choix par défaut
    auto = [dict(o) for o in db.operations() if o["status"] == "auto"][0]
    cd2 = ClassifyDialog(db, [auto])
    assert cd2.group.checkedButton() is None and cd2.r_update is not None

    db.save_rule("EDF", cat("Électricité"))
    db.set_forecasts([(cat("Courses"), f"2026-{m:02d}", 50000) for m in range(1, 13)])

    win = mw.MainWindow(db, Settings(str(tmp_path / "prefs.json")))
    win.show()
    for i in range(len(win.pages)):
        win.show_page(i)
        app.processEvents()
    for k in range(win.charts_tab.kind.count()):
        win.charts_tab.kind.setCurrentIndex(k)
    for k in range(win.summary_tab.mode.count()):
        win.summary_tab.mode.setCurrentIndex(k)
    for k in range(win.compare_tab.mode.count()):
        win.compare_tab.mode.setCurrentIndex(k)
    win.detail_tab.show_category(cat("Courses"))

    # Volet de classement : sélection d'une opération à classer puis enregistrement -> passe à la suivante
    win.go_todo()
    app.processEvents()
    todo_before = db.count_by_status().get("none", 0)
    first = win.ops_tab.view.selected_rows()
    assert first and first[0]["status"] == "none"
    panel = win.ops_tab.panel
    panel.picker.set_value(cat("Divers"))
    assert panel.r_rule.isChecked() and panel.btn_apply.isEnabled()
    panel.apply()
    app.processEvents()
    assert db.count_by_status().get("none", 0) < todo_before
    nxt = win.ops_tab.view.selected_rows()
    assert nxt and nxt[0]["status"] == "none" and nxt[0]["id"] != first[0]["id"]

    # Comparaison : la période B est modifiable et bascule en « période libre »
    ct = win.compare_tab
    win.show_page(3)
    ct.mode.setCurrentIndex(0)
    ct.pb.set_period("2025-10", "2025-11")
    assert ct.mode.currentIndex() == ct.FREE and ct.pb.period() == ("2025-10", "2025-11")
    assert "oct. 2025" in ct.headers[2] or "octobre 2025" in ct.headers[2]

    # Graphiques cliquables : chaque part / barre / légende est reliée à des opérations
    win.show_page(5)
    for k in (0, 1, 2):
        win.charts_tab.kind.setCurrentIndex(k)
        app.processEvents()
        assert win.charts_tab._targets, k
        title, cat_ids, s_, e_ = next(iter(win.charts_tab._targets.values()))
        assert cat_ids and s_ <= e_

    # Prévisionnel : saisie avec recopie automatique sur les mois suivants
    fp = win.forecast_tab
    win.show_page(6)
    fp.start.set_month("2026-01")
    fp.autocopy.setChecked(True)
    sup = cat("Supermarché")

    def find(tree, cid):
        def walk(item):
            if item.data(0, Qt.UserRole + 30) == cid:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None
        for i in range(tree.topLevelItemCount()):
            found = walk(tree.topLevelItem(i))
            if found is not None:
                return found

    find(fp.tree, sup).setText(3, "450")       # mars 2026 -> recopié jusqu'en décembre
    app.processEvents()
    fc = db.forecasts("2026-01", "2026-12")[sup]
    assert "2026-02" not in fc and fc["2026-03"] == 45000 and fc["2026-12"] == 45000
    fp.autocopy.setChecked(False)
    find(fp.tree, sup).setText(5, "300")       # mai uniquement
    app.processEvents()
    fc = db.forecasts("2026-01", "2026-12")[sup]
    assert fc["2026-05"] == 30000 and fc["2026-06"] == 45000
    fp._copy_right(sup, 5)                     # recopie de mai vers la droite
    assert db.forecasts("2026-06", "2026-12")[sup]["2026-12"] == 30000

    # Recopie depuis n'importe quel mois via la sélection (Ctrl+R), puis évolution en cours d'année
    find(fp.tree, sup).setText(8, "320")       # août : nouvelle valeur (sans recopie automatique)
    app.processEvents()
    fp.tree.setCurrentItem(find(fp.tree, sup), 8)
    assert fp._selected_cells() == [(sup, 8)] and fp.copy_btn.isEnabled()
    fp.copy_selection_right()
    fc = db.forecasts("2026-01", "2026-12")[sup]
    assert fc["2026-07"] == 30000 and fc["2026-08"] == 32000 and fc["2026-12"] == 32000
    assert fp.tree.currentColumn() == 8        # la sélection est conservée après rechargement

    # Catégorie qui totalise ses sous-catégories : chaque sous-catégorie est recopiée
    resto, resto_top = cat("Restaurant"), cat("Restaurants")
    db.set_forecast(resto, "2026-04", 9000)
    fp.reload()
    fp.copy_right_cells([(resto_top, 4)])
    fcr = db.forecasts("2026-01", "2026-12")
    assert fcr[resto]["2026-12"] == 9000 and resto_top not in fcr

    # Prévu / réalisé
    pp = win.plan_tab
    win.show_page(7)
    pp.period.set_period("2026-01", "2026-10")
    for k in range(pp.mode.count()):
        pp.mode.setCurrentIndex(k)
        app.processEvents()
    courses = next(n for _, kd, ns in pp.report.sections if kd == "depense" for n in ns if n.label == "Courses")
    assert courses.plan["2026-03"] == 50000  # valeur propre de Courses prioritaire sur ses sous-catégories

    # Nettoyage des catégories vides
    from mescomptes.ui.settings_tabs import CleanupDialog
    dlg_c = CleanupDialog(db)
    ids = dlg_c.selected()
    assert ids
    db.delete_categories(ids)
    assert not db.empty_categories()
    win.data_changed()
    win.show_page(0)
    app.processEvents()

    export_excel(str(tmp_path / "s.xlsx"), [win.summary_tab.table()])
    export_pdf(str(tmp_path / "s.pdf"), [win.summary_tab.table()],
               images=[("g", win.charts_tab.canvas.png_bytes())])
    assert os.path.getsize(tmp_path / "s.pdf") > 1000
    win.close()
    assert len(Database.open(str(tmp_path / "t.mcpt"), "1234").operations()) == n


if __name__ == "__main__":
    run(pathlib.Path(sys.argv[1]))
    print("UI-OK", flush=True)
