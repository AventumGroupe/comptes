"""Nettoyage des libellés bancaires et extraction du « fournisseur ».

Deux notions :
- ``label_key(libellé)`` : forme canonique servant à la comparaison (majuscules,
  sans accents, sans ponctuation, sans les mots contenant des chiffres - dates,
  numéros de carte, références - ni les lettres isolées).
- ``extract_vendor(libellé)`` : proposition de nom de fournisseur, débarrassée
  des préfixes bancaires (PAIEMENT CB, PRLV SEPA, VIR...), proposée à
  l'utilisateur comme motif de règle.

Une règle « motif -> catégorie » s'applique à une opération quand la clé du motif
apparaît, mot pour mot, dans la clé du libellé.
"""

import re
import unicodedata

# Préfixes bancaires, exprimés sous forme de clé (cf. label_key). Les plus longs d'abord.
_PREFIXES = sorted(
    [
        "PAIEMENT PAR CARTE", "PAIEMENT CARTE", "PAIEMENT CB", "PAIEMENT PSC", "PAIEMENT",
        "ACHAT CB", "ACHAT CARTE", "FACTURE CARTE", "CARTE", "CB",
        "PRLV SEPA", "PRELEVEMENT SEPA", "PRELEVEMENT EUROPEEN", "PRELEVEMENT", "PRLV",
        "VIR SEPA RECU", "VIR SEPA EMIS", "VIR SEPA", "VIR INST RECU", "VIR INST EMIS", "VIR INST",
        "VIR RECU", "VIR EMIS", "VIREMENT SEPA RECU", "VIREMENT SEPA EMIS", "VIREMENT SEPA",
        "VIREMENT INSTANTANE", "VIREMENT RECU", "VIREMENT EMIS", "VIREMENT", "VIR",
        "ECHEANCE PRET", "ECH PRET",
        "SEPA", "RECU", "EMIS", "INST",
    ],
    key=len,
    reverse=True,
)

# Mots en tête de nom à retirer (articles, civilités).
_LEADING_NOISE = {"DE", "DU", "DES", "A", "AU", "AUX", "LA", "LE", "LES", "MR", "MME", "MLLE",
                  "MONSIEUR", "MADAME", "MLE", "ET", "POUR", "PAR", "SOC", "STE", "VERS", "CHEZ"}

# Petits mots qui ne comptent pas dans la limite de longueur du nom.
_SMALL_WORDS = {"DE", "DU", "DES", "LA", "LE", "LES", "ET", "A", "AU", "AUX", "EN", "SUR", "SA", "SAS", "SARL"}

# Mots à partir desquels le reste du libellé n'est que de la référence.
_CUT_WORDS = {"MOTIF", "REF", "REFERENCE", "REFERENCES", "ECH", "MDT", "MANDAT", "ID", "LIB",
              "LIBELLE", "DATE", "NUM", "NUMERO", "CARTE", "ICS", "RUM", "FACTURE", "FACT",
              "COMMANDE", "CMDE", "INFO", "INFOS", "NOTPROVIDED"}

_MAX_VENDOR_WORDS = 3


def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def label_key(text):
    """Clé de comparaison d'un libellé ou d'un motif."""
    s = strip_accents(str(text or "")).upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    tokens = [t for t in s.split() if len(t) > 1 and not any(ch.isdigit() for ch in t)]
    return " ".join(tokens)


def key_matches(pattern_key, label_k):
    """Vrai si la clé du motif apparaît mot pour mot dans la clé du libellé."""
    if not pattern_key:
        return False
    return f" {pattern_key} " in f" {label_k} "


def extract_vendor(text):
    """Propose un nom de fournisseur à partir du libellé brut."""
    key = label_key(text)
    if not key:
        return ""
    tokens = key.split()

    first = tokens[0]
    if first in ("RETRAIT", "RET") or key.startswith("RETRAIT DAB"):
        return "RETRAIT DAB" if "DAB" in tokens[:3] else "RETRAIT"
    if first in ("CHEQUE", "CHQ") or key.startswith("REMISE CHEQUE"):
        return " ".join(tokens[:2]) if first == "REMISE" else "CHEQUE"

    # Retrait des préfixes bancaires (éventuellement enchaînés : "PAIEMENT CB ...").
    changed = True
    while changed and tokens:
        changed = False
        joined = " ".join(tokens)
        for p in _PREFIXES:
            if joined == p:
                break  # le libellé n'est qu'un préfixe : on le garde tel quel
            if joined.startswith(p + " "):
                tokens = tokens[len(p.split()):]
                changed = True
                break
        while tokens and tokens[0] in _LEADING_NOISE and len(tokens) > 1:
            tokens = tokens[1:]
            changed = True

    # Coupure à la première référence.
    for i, t in enumerate(tokens):
        if t in _CUT_WORDS and i > 0:
            tokens = tokens[:i]
            break

    if not tokens:
        tokens = key.split()
    out, significant = [], 0
    for t in tokens:
        if significant >= _MAX_VENDOR_WORDS:
            break
        out.append(t)
        if t not in _SMALL_WORDS:
            significant += 1
    while len(out) > 1 and out[-1] in _SMALL_WORDS:
        out.pop()
    return " ".join(out)
