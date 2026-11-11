import datetime as dt
import os

import openpyxl
import pytest

from mescomptes import analytics, store
from mescomptes.db import AUTO, MANUAL, NONE, Database, ParsedOperation
from mescomptes.importer import detect_mapping, load_statement, parse_amount, parse_date, parse_operations
from mescomptes.normalize import extract_vendor, key_matches, label_key


# ---------------------------------------------------------------- normalize
@pytest.mark.parametrize("label,vendor", [
    ("PAIEMENT CB 1210 AMAZON PAYMENTS CARTE 4974XXXXXXXX1234", "AMAZON PAYMENTS"),
    ("PRLV SEPA EDF CLIENTS PARTICULIERS REF 123456", "EDF CLIENTS PARTICULIERS"),
    ("VIR SEPA RECU /DE M. DUPONT JEAN /MOTIF SALAIRE OCT", "DUPONT JEAN"),
    ("RETRAIT DAB 0410 CM PARIS 15", "RETRAIT DAB"),
    ("CHEQUE 1234567", "CHEQUE"),
    ("FRAIS PAIE CB", "FRAIS PAIE CB"),
    ("CB CARREFOUR MARKET 05/10", "CARREFOUR MARKET"),
    ("PAIEMENT CB 0909 PHARMACIE DE LA GARE CARTE 4974XXXX", "PHARMACIE DE LA GARE"),
    ("VIR SEPA EMIS VERS LIVRET BLEU", "LIVRET BLEU"),
])
def test_extract_vendor(label, vendor):
    assert extract_vendor(label) == vendor


def test_label_key_and_match():
    assert label_key("Paiement CB 12/10 Café de l'Été") == "PAIEMENT CB CAFE DE ETE"
    assert key_matches("CARREFOUR MARKET", label_key("CB CARREFOUR 1234 MARKET"))
    assert not key_matches("EDF", label_key("PRLV CEDF SERVICES"))
    assert not key_matches("", "ANYTHING")


# ----------------------------------------------------------------- importer
def test_parse_amount():
    assert parse_amount("1 234,56") == 123456
    assert parse_amount("-12,5") == -1250
    assert parse_amount("1.234,56 €") == 123456
    assert parse_amount("1,234.56") == 123456
    assert parse_amount(-45.1) == -4510
    assert parse_amount("12,00-") == -1200
    assert parse_amount("abc") is None
    assert parse_amount(None) is None


def test_parse_date():
    assert parse_date("05/10/2026") == "2026-10-05"
    assert parse_date("05/10/26") == "2026-10-05"
    assert parse_date(dt.datetime(2026, 1, 2)) == "2026-01-02"
    assert parse_date(46000) == "2025-12-09"
    assert parse_date("Solde") is None


def make_cm_xlsx(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Compte courant"
    ws.append(["Crédit Mutuel - Relevé"])
    ws.append(["Compte : 0000 000000 00"])
    ws.append([])
    ws.append(["Date", "Date de valeur", "Débit", "Crédit", "Libellé", "Solde"])
    ws.append([dt.datetime(2026, 9, 2), dt.datetime(2026, 9, 2), -54.20, None,
               "PAIEMENT CB 0109 CARREFOUR MARKET CARTE 4974XXXX1234", 1945.80])
    ws.append(["03/09/2026", "03/09/2026", None, "2 500,00", "VIR SEPA RECU /DE SOCIETE ACME /MOTIF SALAIRE", 4445.80])
    ws.append(["10/09/2026", "10/09/2026", "-89,90", None, "PRLV SEPA EDF CLIENTS PARTICULIERS", 4355.90])
    ws.append([dt.datetime(2026, 10, 2), None, -61.00, None, "PAIEMENT CB 0110 CARREFOUR MARKET CARTE 4974XXXX1234", 4294.90])
    ws.append([dt.datetime(2026, 10, 5), None, -12.00, None, "PAIEMENT CB 0510 AMAZON PAYMENTS CARTE 4974XXXX1234", 4282.90])
    ws.append([None, None, None, None, "Solde au 31/10/2026", 4282.90])
    wb.save(path)


def test_import_credit_mutuel_like(tmp_path):
    p = tmp_path / "releve.xlsx"
    make_cm_xlsx(p)
    (sheet, mapping), = load_statement(str(p))
    assert mapping.header_row == 3
    assert mapping.date_col == 0 and mapping.value_date_col == 1
    assert mapping.debit_col == 2 and mapping.credit_col == 3 and mapping.label_cols == [4]
    assert mapping.balance_col == 5
    ops, skipped = parse_operations(sheet.rows, mapping)
    assert len(ops) == 5 and skipped == 1
    assert ops[0].amount == -5420 and ops[1].amount == 250000 and ops[2].amount == -8990
    assert ops[0].balance == 194580


def test_import_csv_single_amount(tmp_path):
    p = tmp_path / "releve.csv"
    p.write_text("Date;Libellé;Montant\n01/02/2026;CB BOULANGERIE;-3,20\n02/02/2026;VIR RECU;100,00\n",
                 encoding="cp1252")
    (sheet, mapping), = load_statement(str(p))
    ops, _ = parse_operations(sheet.rows, mapping)
    assert [o.amount for o in ops] == [-320, 10000]


def test_import_html_disguised_as_xls(tmp_path):
    p = tmp_path / "releve.xls"
    p.write_text("<html><table><tr><th>Date</th><th>Libellé</th><th>Débit</th><th>Crédit</th></tr>"
                 "<tr><td>01/02/2026</td><td>CB BOULANGERIE</td><td>3,20</td><td></td></tr>"
                 "<tr><td>02/02/2026</td><td>VIR RECU</td><td></td><td>100,00</td></tr></table></html>",
                 encoding="utf-8")
    (sheet, mapping), = load_statement(str(p))
    ops, _ = parse_operations(sheet.rows, mapping)
    assert [o.amount for o in ops] == [-320, 10000]


# ----------------------------------------------------------------- database
@pytest.fixture
def db(tmp_path):
    return Database.create(str(tmp_path / "test.mcpt"), "secret")


def cat(db, name):
    return next(c.id for c in db.categories().values() if c.name == name)


def sample_ops():
    return [
        ParsedOperation("2026-09-02", "PAIEMENT CB 0109 CARREFOUR MARKET CARTE 4974XXXX1234", -5420),
        ParsedOperation("2026-09-03", "VIR SEPA RECU /DE SOCIETE ACME /MOTIF SALAIRE", 250000),
        ParsedOperation("2026-09-10", "PRLV SEPA EDF CLIENTS PARTICULIERS", -8990),
        ParsedOperation("2026-10-02", "PAIEMENT CB 0110 CARREFOUR MARKET CARTE 4974XXXX1234", -6100),
        ParsedOperation("2026-10-05", "PAIEMENT CB 0510 AMAZON PAYMENTS CARTE 4974XXXX1234", -1200),
        ParsedOperation("2026-10-05", "PAIEMENT CB 0510 AMAZON PAYMENTS CARTE 4974XXXX1234", -1200),
    ]


def test_encryption_roundtrip(tmp_path):
    path = str(tmp_path / "d.mcpt")
    d = Database.create(path, "pass1")
    d.import_operations(sample_ops())
    d.close()
    with pytest.raises(store.WrongPassword):
        Database.open(path, "bad")
    d2 = Database.open(path, "pass1")
    assert len(d2.operations()) == 6
    d2.change_password("pass2")
    d2.close()
    assert len(Database.open(path, "pass2").operations()) == 6
    assert b"CARREFOUR" not in open(path, "rb").read()
    assert os.path.isdir(tmp_path / "sauvegardes")


def test_import_dedup(db):
    assert db.import_operations(sample_ops()) == (6, 0)  # deux AMAZON identiques le même jour : gardées
    assert db.import_operations(sample_ops()) == (0, 6)


def test_learning_flow(db):
    db.import_operations(sample_ops()[:3])
    first = [o for o in db.operations() if "CARREFOUR" in o["label"]][0]
    assert first["vendor"] == "CARREFOUR MARKET"
    supermarche = cat(db, "Supermarché")
    db.classify([first["id"]], supermarche)
    db.save_rule("CARREFOUR MARKET", supermarche)
    # Nouvel import : classement automatique
    db.import_operations(sample_ops()[3:])
    later = [o for o in db.operations() if "CARREFOUR" in o["label"] and o["date"] == "2026-10-02"][0]
    assert later["category_id"] == supermarche and later["status"] == AUTO
    assert db.operation(first["id"])["status"] == MANUAL

    # Correction ponctuelle : uniquement cette opération
    restaurant = cat(db, "Restaurant")
    db.classify([later["id"]], restaurant)
    db.apply_rules()
    assert db.operation(later["id"])["category_id"] == restaurant

    # Modification de la règle : s'applique aux opérations auto, pas aux validées
    db.release([later["id"]])
    assert db.operation(later["id"])["status"] == AUTO
    rule = db.rule_by_pattern("carrefour market")
    db.save_rule(rule.pattern, cat(db, "Hygiène & maison"), rule_id=rule.id)
    assert db.operation(later["id"])["category_id"] == cat(db, "Hygiène & maison")
    assert db.operation(first["id"])["category_id"] == supermarche

    # Le motif le plus précis l'emporte
    db.save_rule("CARREFOUR", cat(db, "Courses"))
    assert db.operation(later["id"])["category_id"] == cat(db, "Hygiène & maison")

    # Suppression de règle -> la règle plus générale prend le relais
    db.delete_rule(rule.id)
    assert db.operation(later["id"])["category_id"] == cat(db, "Courses")
    assert db.matching_operations("carrefour") == (2, 1)


def test_delete_category_reassign(db):
    db.import_operations(sample_ops())
    edf = [o for o in db.operations() if "EDF" in o["label"]][0]
    elec = cat(db, "Électricité")
    db.save_rule("EDF", elec)
    assert db.operation(edf["id"])["category_id"] == elec
    db.delete_category(cat(db, "Énergie"))
    assert db.operation(edf["id"])["status"] == NONE
    assert db.rules() == []


def test_analytics(db):
    db.import_operations(sample_ops())
    db.save_rule("CARREFOUR MARKET", cat(db, "Supermarché"))
    db.save_rule("ACME", cat(db, "Salaires"))
    db.save_rule("EDF", cat(db, "Électricité"))
    rep = analytics.pivot(db, "2026-09", "2026-10")
    assert rep.columns == ["2026-09", "2026-10"]
    titles = [s[0] for s in rep.sections]
    assert titles == ["Revenus", "Dépenses", "À classer"]
    courses = next(n for n in rep.sections[1][2] if n.label == "Courses")
    assert courses.values == {"2026-09": 5420, "2026-10": 6100}
    rev, dep, net, var = rep.totals
    assert rev.values["2026-09"] == 250000 and dep.values["2026-09"] == 5420 + 8990
    assert var.values["2026-10"] == -6100 - 2400

    cmp = analytics.compare(db, ("2026-10", "2026-10"), ("2026-09", "2026-09"))
    courses = next(n for n in cmp.sections[1][2] if n.label == "Courses")
    assert courses.values == {"A": 6100, "B": 5420}

    db.set_budget(cat(db, "Supermarché"), 2026, 6000)
    db.set_budget(cat(db, "Pharmacie"), 2026, 1000)
    b = analytics.budget_report(db, "2026-09", "2026-10")
    courses = next(n for n in b.sections[1][2] if n.label == "Courses")
    assert courses.values["budget"] == 12000 and courses.values["reel"] == 11520
    sante = next(n for n in b.sections[1][2] if n.label == "Santé")
    assert sante.values["budget"] == 2000
    db.copy_budgets(2026, 2027)
    assert db.budgets(2027) == db.budgets(2026)


def test_months():
    assert analytics.add_months("2026-11", 3) == "2027-02"
    assert analytics.add_months("2026-01", -1) == "2025-12"
    assert analytics.month_range("2026-11", "2027-01") == ["2026-11", "2026-12", "2027-01"]
    assert analytics.month_last_day("2028-02") == "2028-02-29"


def test_empty_categories(db):
    db.import_operations(sample_ops())
    db.save_rule("EDF", cat(db, "Électricité"))
    empty = db.empty_categories()
    names = {c.name for c, _, _ in empty}
    assert "Électricité" not in names and "Énergie" not in names
    assert "Gaz" in names and "Enfants" in names
    assert "Garde / crèche" not in names  # couverte par sa catégorie principale vide
    db.delete_categories([c.id for c, _, _ in empty])
    remaining = {c.name for c in db.categories().values()}
    assert remaining == {"Énergie", "Électricité"}
    assert len(db.operations()) == 6
