"""Catégories proposées à la création d'un dossier (validées par l'utilisateur,
modifiables à tout moment dans l'application)."""

# (nom, type, [sous-catégories]) ; type : revenu | depense | neutre
DEFAULT_CATEGORIES = [
    ("Revenus", "revenu", ["Salaires", "Allocations & prestations sociales", "Pensions & retraites",
                           "Remboursements", "Revenus locatifs", "Autres revenus"]),
    ("Logement", "depense", ["Loyer / crédit immobilier", "Charges de copropriété",
                             "Travaux & entretien", "Ameublement & équipement"]),
    ("Énergie", "depense", ["Électricité", "Gaz", "Eau", "Chauffage / fioul"]),
    ("Courses", "depense", ["Supermarché", "Boulangerie / marché", "Hygiène & maison"]),
    ("Restaurants", "depense", ["Restaurant", "Fast-food / livraison", "Café / bar"]),
    ("Transport", "depense", ["Carburant", "Péage / parking", "Transports en commun", "Train / avion",
                              "Entretien véhicule", "Crédit / location véhicule"]),
    ("Santé", "depense", ["Médecin", "Pharmacie", "Optique / dentaire", "Mutuelle"]),
    ("Assurances", "depense", ["Habitation", "Automobile", "Prévoyance / vie"]),
    ("Abonnements", "depense", ["Téléphone / internet", "Streaming / TV", "Presse / logiciels",
                                "Sport / club"]),
    ("Loisirs", "depense", ["Sorties & culture", "Voyages & vacances", "Shopping & vêtements",
                            "Cadeaux", "Hobbies"]),
    ("Enfants", "depense", ["Garde / crèche", "École / cantine", "Activités", "Vêtements & fournitures"]),
    ("Impôts", "depense", ["Impôt sur le revenu", "Taxe foncière", "Taxe d'habitation", "Autres taxes"]),
    ("Épargne", "neutre", ["Livret", "Assurance-vie", "Placements"]),
    ("Virements internes", "neutre", ["Entre mes comptes"]),
    ("Divers", "depense", ["Retraits d'espèces", "Frais bancaires", "Dons", "Autres dépenses"]),
]


def seed_categories(conn):
    for name, kind, subs in DEFAULT_CATEGORIES:
        cur = conn.execute("INSERT INTO categories(name, parent_id, kind) VALUES (?, NULL, ?)", (name, kind))
        pid = cur.lastrowid
        for sub in subs:
            conn.execute("INSERT INTO categories(name, parent_id, kind) VALUES (?, ?, ?)", (sub, pid, kind))
