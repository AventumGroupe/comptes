"""Formatage des montants (stockés en centimes, entiers)."""

NBSP = " "  # espace fine insécable, séparateur de milliers en français


def fmt_eur(cents, signed=False, blank_zero=False, symbol=True):
    if cents is None:
        return ""
    cents = int(round(cents))
    if blank_zero and cents == 0:
        return ""
    euros, cts = divmod(abs(cents), 100)
    s = f"{euros:,}".replace(",", NBSP) + f",{cts:02d}"
    if symbol:
        s += " €"
    if cents < 0:
        s = "-" + s
    elif signed and cents > 0:
        s = "+" + s
    return s


def fmt_pct(ratio, signed=True):
    """ratio = 0.125 -> '+12,5 %'. None -> ''."""
    if ratio is None:
        return ""
    s = f"{ratio * 100:+.1f}" if signed else f"{ratio * 100:.1f}"
    return s.replace(".", ",") + " %"


def pct_change(new, old):
    if not old:
        return None
    return (new - old) / abs(old)


def parse_eur_input(text):
    """Saisie utilisateur '1 234,5' -> 123450 centimes. '' -> None. ValueError si invalide."""
    t = (text or "").strip().replace("€", "").replace(" ", "").replace(NBSP, "").replace(" ", "")
    if not t:
        return None
    t = t.replace(",", ".")
    return int(round(float(t) * 100))
