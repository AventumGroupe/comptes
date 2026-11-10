"""Génère un relevé fictif au format proche du Crédit Mutuel (pour tests et démonstration)."""

import datetime as dt
import random
import sys

import openpyxl

VENDORS = [
    ("PAIEMENT CB {d} CARREFOUR MARKET CARTE 4974XXXXXXXX1234", (-120, -25), 6),
    ("PAIEMENT CB {d} LECLERC DRIVE CARTE 4974XXXXXXXX1234", (-160, -40), 2),
    ("PAIEMENT CB {d} BOULANGERIE DU CENTRE CARTE 4974XXXXXXXX1234", (-12, -3), 8),
    ("PAIEMENT CB {d} TOTALENERGIES STATION CARTE 4974XXXXXXXX1234", (-80, -40), 2),
    ("PAIEMENT CB {d} AMAZON PAYMENTS CARTE 4974XXXXXXXX1234", (-90, -10), 2),
    ("PAIEMENT CB {d} PHARMACIE DE LA GARE CARTE 4974XXXXXXXX1234", (-35, -6), 1),
    ("PAIEMENT CB {d} LE PETIT BISTROT CARTE 4974XXXXXXXX1234", (-70, -25), 2),
    ("PAIEMENT CB {d} SNCF INTERNET CARTE 4974XXXXXXXX1234", (-120, -30), 0.4),
    ("RETRAIT DAB {d} CM STRASBOURG", (-100, -40), 1),
]
MONTHLY = [
    (1, "VIR SEPA RECU /DE SOCIETE ACME SAS /MOTIF SALAIRE {m}", 2850),
    (5, "PRLV SEPA SCI LES TILLEULS LOYER", -890),
    (8, "PRLV SEPA EDF CLIENTS PARTICULIERS ECH/{m}", -95),
    (10, "PRLV SEPA FREE MOBILE", -19.99),
    (12, "PRLV SEPA BOUYGUES TELECOM FACT {m}", -39.99),
    (14, "PRLV SEPA NETFLIX.COM", -13.49),
    (15, "PRLV SEPA MAIF ASSURANCE HABITATION", -32.5),
    (20, "VIR SEPA EMIS VERS LIVRET BLEU", -200),
    (25, "FRAIS COTIS EUROCOMPTE", -10.4),
]


def generate(path, start=dt.date(2025, 9, 1), months=14, seed=42):
    rnd = random.Random(seed)
    ops = []
    for i in range(months):
        y, m = start.year + (start.month - 1 + i) // 12, (start.month - 1 + i) % 12 + 1
        for day, label, amount in MONTHLY:
            ops.append((dt.date(y, m, day), label.format(m=f"{m:02d}{y}"), amount))
        for label, (lo, hi), freq in VENDORS:
            n = int(freq) + (1 if rnd.random() < freq - int(freq) else 0)
            for _ in range(n):
                d = dt.date(y, m, rnd.randint(1, 28))
                ops.append((d, label.format(d=d.strftime("%d%m")), round(rnd.uniform(lo, hi), 2)))
    ops.sort(key=lambda o: o[0])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Compte cheque"
    ws.append(["CREDIT MUTUEL"])
    ws.append(["Compte de chèques n° 00000 000000 00 - M. EXEMPLE"])
    ws.append([])
    ws.append(["Date", "Date de valeur", "Débit", "Crédit", "Libellé", "Solde"])
    balance = 1500.0
    for d, label, amount in ops:
        balance += amount
        ws.append([d, d, amount if amount < 0 else None, amount if amount > 0 else None, label, round(balance, 2)])
    wb.save(path)
    return len(ops)


if __name__ == "__main__":
    print(generate(sys.argv[1]))
