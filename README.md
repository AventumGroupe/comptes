# Mes Comptes

Application Windows autonome pour classer et analyser les opérations d'un relevé bancaire
(Crédit Mutuel et formats proches), avec apprentissage automatique des fournisseurs.

- **100 % local** : aucune connexion internet, aucune donnée envoyée.
- **Chiffré** : chaque dossier de comptes est un fichier unique (`.mcpt`) chiffré par mot de passe
  (AES-256, clé dérivée par scrypt). Un mot de passe perdu ne peut pas être récupéré.
- **Un seul fichier `MesComptes.exe`**, sans installation ni droits administrateur.

## Fonctionnalités

| Onglet | Rôle |
|---|---|
| Opérations | Import du relevé Excel (.xlsx/.xls) ou CSV, liste filtrable, classement, validation, notes |
| Synthèse mensuelle | Tableau catégories × mois, total, moyenne, écarts vs mois précédent (€ ou %) |
| Comparaison | Mois vs mois précédent, vs même mois N-1, période vs N-1, deux périodes libres |
| Détail par catégorie | Graphique mensuel avec N-1, principaux fournisseurs, liste des opérations |
| Graphiques | Revenus/dépenses, répartition, évolution par catégorie, solde du compte |
| Budget | Budget mensuel par catégorie et par année, suivi budget/réalisé |
| Catégories | Deux niveaux, type (revenu, dépense, mouvement interne), ajout, renommage, déplacement, suppression |
| Règles | Règles apprises « le libellé contient… → catégorie », modifiables, testables |

Exports **Excel** et **PDF** depuis chaque vue d'analyse.

## Apprentissage

1. Le libellé est nettoyé (dates, numéros de carte, références retirés) et un nom de fournisseur est proposé.
2. Quand vous classez une opération, vous choisissez de **mémoriser** le fournisseur (création d'une règle) ou de
   faire une **exception ponctuelle**.
3. Les opérations classées par une règle sont marquées « Auto (à vérifier) » ; celles que vous classez ou validez
   sont « Validées » et ne sont **jamais** modifiées automatiquement.
4. En corrigeant une opération auto, vous choisissez au cas par cas : exception, modification de la règle, ou
   nouvelle règle plus précise. Quand plusieurs règles correspondent, la plus précise (motif le plus long) l'emporte.

## Obtenir l'exécutable Windows

Le fichier `MesComptes.exe` est fabriqué automatiquement par GitHub à chaque envoi de code :
onglet **Actions** du dépôt › dernière exécution « Fabrication Windows » › section *Artifacts* ›
**MesComptes-Windows** (fichier zip contenant l'exe).

Pour une version publiée : créer une étiquette `v1.0.0` ; l'exe est alors joint à la page **Releases**.

Au premier lancement, Windows SmartScreen peut afficher « Windows a protégé votre ordinateur » (exécutable non
signé) : cliquer sur **Informations complémentaires › Exécuter quand même**.

## Développement

```bash
python -m venv venv
venv\Scripts\pip install -r requirements-dev.txt
venv\Scripts\python lancer.py          # lancer l'application
venv\Scripts\python -m pytest -q       # tests
venv\Scripts\pyinstaller MesComptes.spec   # fabriquer dist\MesComptes.exe
```

Structure : `mescomptes/` (moteur : `db.py`, `importer.py`, `normalize.py`, `analytics.py`, `exporters.py`,
`store.py`) et `mescomptes/ui/` (interface PySide6).
