"""Base de données (SQLite en mémoire, persistée chiffrée) et logique métier :
catégories, opérations, règles d'apprentissage, budgets."""

import datetime as dt
import glob
import os
import shutil
import sqlite3
from dataclasses import dataclass

from . import store
from .normalize import extract_vendor, key_matches, label_key
from .seed import seed_categories

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE categories(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'depense'
);
CREATE TABLE rules(
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,
    pattern_key TEXT NOT NULL UNIQUE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);
CREATE TABLE imports(
    id INTEGER PRIMARY KEY,
    filename TEXT, imported_at TEXT, nb_new INTEGER, nb_dup INTEGER
);
CREATE TABLE operations(
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    value_date TEXT,
    label TEXT NOT NULL,
    label_key TEXT NOT NULL,
    vendor TEXT NOT NULL DEFAULT '',
    amount INTEGER NOT NULL,
    balance INTEGER,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'none',
    rule_id INTEGER REFERENCES rules(id) ON DELETE SET NULL,
    note TEXT NOT NULL DEFAULT '',
    import_id INTEGER REFERENCES imports(id) ON DELETE SET NULL,
    fingerprint TEXT NOT NULL UNIQUE
);
CREATE INDEX idx_ops_date ON operations(date);
CREATE INDEX idx_ops_cat ON operations(category_id);
CREATE TABLE budgets(
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    monthly INTEGER NOT NULL,
    PRIMARY KEY(category_id, year)
);
"""

# Statuts d'une opération
NONE, AUTO, MANUAL = "none", "auto", "manual"
STATUS_LABELS = {NONE: "À classer", AUTO: "Auto (à vérifier)", MANUAL: "Validée"}

KINDS = {"revenu": "Revenu", "depense": "Dépense", "neutre": "Mouvement interne"}
KIND_ORDER = {"revenu": 0, "depense": 1, "neutre": 2}

MAX_BACKUPS = 10


@dataclass
class Category:
    id: int
    name: str
    parent_id: int
    kind: str


@dataclass
class Rule:
    id: int
    pattern: str
    pattern_key: str
    category_id: int
    created_at: str
    nb_ops: int = 0


@dataclass
class ParsedOperation:
    """Opération issue d'un relevé, avant enregistrement. Montants en centimes."""
    date: str
    label: str
    amount: int
    value_date: str = None
    balance: int = None


def now_iso():
    return dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


class Database:
    def __init__(self, path, key, salt, conn):
        self.path = path
        self._key = key
        self._salt = salt
        self.conn = conn
        conn.row_factory = sqlite3.Row
        self._cat_cache = None

    # ------------------------------------------------------------------ fichier
    @classmethod
    def create(cls, path, password, seed=True):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.execute("INSERT INTO meta VALUES('created_at', ?)", (now_iso(),))
        if seed:
            seed_categories(conn)
        salt = store.new_salt()
        db = cls(path, store.derive_key(password, salt), salt, conn)
        db.save()
        return db

    @classmethod
    def open(cls, path, password):
        data, key, salt = store.read_file(path, password)
        conn = sqlite3.connect(":memory:")
        conn.deserialize(data)
        conn.execute("PRAGMA foreign_keys=ON")
        db = cls(path, key, salt, conn)
        db._backup()
        return db

    def save(self):
        self.conn.commit()
        store.write_file(self.path, self.conn.serialize(), self._key, self._salt)

    def change_password(self, new_password):
        self._salt = store.new_salt()
        self._key = store.derive_key(new_password, self._salt)
        self.save()

    def save_copy(self, path):
        self.conn.commit()
        store.write_file(path, self.conn.serialize(), self._key, self._salt)

    def close(self):
        try:
            self.save()
        finally:
            self.conn.close()

    def _backup(self):
        """Copie de sécurité à l'ouverture (dossier « sauvegardes » à côté du fichier)."""
        try:
            folder = os.path.join(os.path.dirname(os.path.abspath(self.path)), "sauvegardes")
            os.makedirs(folder, exist_ok=True)
            base = os.path.splitext(os.path.basename(self.path))[0]
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(self.path, os.path.join(folder, f"{base}_{stamp}{store.FILE_EXTENSION}"))
            backups = sorted(glob.glob(os.path.join(folder, f"{base}_*{store.FILE_EXTENSION}")))
            for old in backups[:-MAX_BACKUPS]:
                os.remove(old)
        except OSError:
            pass  # une sauvegarde ratée ne doit pas empêcher l'ouverture

    def get_meta(self, key, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES(?, ?)", (key, str(value)))
        self.save()

    # --------------------------------------------------------------- catégories
    def _invalidate(self):
        self._cat_cache = None

    def categories(self):
        """Toutes les catégories, dict id -> Category."""
        if self._cat_cache is None:
            rows = self.conn.execute("SELECT id, name, parent_id, kind FROM categories").fetchall()
            self._cat_cache = {r["id"]: Category(*r) for r in rows}
        return self._cat_cache

    def category_tree(self):
        """[(catégorie principale, [sous-catégories])], triés par type puis nom."""
        cats = self.categories()
        tops = [c for c in cats.values() if c.parent_id is None]
        sort_key = lambda c: (KIND_ORDER.get(c.kind, 9), c.name.casefold())
        tops.sort(key=sort_key)
        tree = []
        for t in tops:
            subs = sorted((c for c in cats.values() if c.parent_id == t.id), key=lambda c: c.name.casefold())
            tree.append((t, subs))
        return tree

    def category_label(self, cat_id, sep=" › "):
        if cat_id is None:
            return ""
        cats = self.categories()
        c = cats.get(cat_id)
        if c is None:
            return ""
        if c.parent_id is not None and c.parent_id in cats:
            return f"{cats[c.parent_id].name}{sep}{c.name}"
        return c.name

    def top_category_id(self, cat_id):
        c = self.categories().get(cat_id)
        if c is None:
            return None
        return c.parent_id if c.parent_id is not None else c.id

    def descendants(self, cat_id):
        """L'identifiant donné et ceux de ses sous-catégories."""
        return [cat_id] + [c.id for c in self.categories().values() if c.parent_id == cat_id]

    def add_category(self, name, parent_id=None, kind="depense"):
        name = name.strip()
        if not name:
            raise ValueError("Le nom ne peut pas être vide.")
        if parent_id is not None:
            parent = self.categories()[parent_id]
            if parent.parent_id is not None:
                raise ValueError("Seuls deux niveaux sont possibles (catégorie › sous-catégorie).")
            kind = parent.kind
        self._check_unique_name(name, parent_id)
        cur = self.conn.execute("INSERT INTO categories(name, parent_id, kind) VALUES (?, ?, ?)",
                                (name, parent_id, kind))
        self._invalidate()
        self.save()
        return cur.lastrowid

    def _check_unique_name(self, name, parent_id, exclude_id=None):
        for c in self.categories().values():
            if c.parent_id == parent_id and c.name.casefold() == name.casefold() and c.id != exclude_id:
                raise ValueError(f"La catégorie « {name} » existe déjà à cet endroit.")

    def rename_category(self, cat_id, name):
        name = name.strip()
        if not name:
            raise ValueError("Le nom ne peut pas être vide.")
        self._check_unique_name(name, self.categories()[cat_id].parent_id, exclude_id=cat_id)
        self.conn.execute("UPDATE categories SET name=? WHERE id=?", (name, cat_id))
        self._invalidate()
        self.save()

    def set_category_kind(self, cat_id, kind):
        if kind not in KINDS:
            raise ValueError(kind)
        top = self.top_category_id(cat_id)
        self.conn.execute("UPDATE categories SET kind=? WHERE id=? OR parent_id=?", (kind, top, top))
        self._invalidate()
        self.save()

    def move_category(self, cat_id, new_parent_id):
        """Déplace une sous-catégorie sous une autre catégorie (ou la promeut si None)."""
        cats = self.categories()
        c = cats[cat_id]
        if new_parent_id is not None:
            if new_parent_id == cat_id or cats[new_parent_id].parent_id is not None:
                raise ValueError("Destination invalide.")
            if any(x.parent_id == cat_id for x in cats.values()):
                raise ValueError("Une catégorie qui a des sous-catégories ne peut pas devenir sous-catégorie.")
            kind = cats[new_parent_id].kind
        else:
            kind = c.kind
        self._check_unique_name(c.name, new_parent_id, exclude_id=cat_id)
        self.conn.execute("UPDATE categories SET parent_id=?, kind=? WHERE id=?", (new_parent_id, kind, cat_id))
        self._invalidate()
        self.save()

    def category_usage(self, cat_id):
        ids = self.descendants(cat_id)
        q = ",".join("?" * len(ids))
        nb_ops = self.conn.execute(f"SELECT COUNT(*) FROM operations WHERE category_id IN ({q})", ids).fetchone()[0]
        nb_rules = self.conn.execute(f"SELECT COUNT(*) FROM rules WHERE category_id IN ({q})", ids).fetchone()[0]
        return nb_ops, nb_rules

    def delete_category(self, cat_id, reassign_to=None):
        """Supprime une catégorie et ses sous-catégories. Les opérations et règles
        concernées sont transférées vers ``reassign_to`` ou, à défaut, les opérations
        repassent « à classer » et les règles sont supprimées."""
        ids = self.descendants(cat_id)
        if reassign_to in ids:
            raise ValueError("Impossible de transférer vers la catégorie supprimée.")
        q = ",".join("?" * len(ids))
        if reassign_to is not None:
            self.conn.execute(f"UPDATE operations SET category_id=? WHERE category_id IN ({q})", [reassign_to] + ids)
            self.conn.execute(f"UPDATE rules SET category_id=? WHERE category_id IN ({q})", [reassign_to] + ids)
        else:
            self.conn.execute(f"UPDATE operations SET category_id=NULL, status='none', rule_id=NULL "
                              f"WHERE category_id IN ({q})", ids)
        self.conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        self._invalidate()
        self.apply_rules(save=False)
        self.save()

    # --------------------------------------------------------------- opérations
    def import_operations(self, parsed, filename=""):
        """Enregistre les opérations, ignore les doublons, applique les règles.
        Retourne (nb_nouvelles, nb_doublons)."""
        cur = self.conn.execute("INSERT INTO imports(filename, imported_at, nb_new, nb_dup) VALUES (?,?,0,0)",
                                (os.path.basename(filename), now_iso()))
        import_id = cur.lastrowid
        seen = {}
        new_ids, dup = [], 0
        for op in parsed:
            base = f"{op.date}|{op.amount}|{label_key(op.label)}"
            seen[base] = seen.get(base, 0) + 1
            fingerprint = f"{base}|{seen[base]}"
            try:
                c = self.conn.execute(
                    "INSERT INTO operations(date, value_date, label, label_key, vendor, amount, balance, "
                    "import_id, fingerprint) VALUES (?,?,?,?,?,?,?,?,?)",
                    (op.date, op.value_date, op.label.strip(), label_key(op.label), extract_vendor(op.label),
                     op.amount, op.balance, import_id, fingerprint))
                new_ids.append(c.lastrowid)
            except sqlite3.IntegrityError:
                dup += 1
        self.conn.execute("UPDATE imports SET nb_new=?, nb_dup=? WHERE id=?", (len(new_ids), dup, import_id))
        self.apply_rules(save=False)
        self.save()
        return len(new_ids), dup

    def operations(self, start=None, end=None, cat_ids=None, uncategorized=False, status=None,
                   text=None, direction=None):
        """Recherche d'opérations. start/end : 'AAAA-MM-JJ' inclus.
        cat_ids : liste d'identifiants ; uncategorized : uniquement « à classer »."""
        sql = "SELECT * FROM operations WHERE 1=1"
        args = []
        if start:
            sql += " AND date >= ?"
            args.append(start)
        if end:
            sql += " AND date <= ?"
            args.append(end)
        if uncategorized:
            sql += " AND category_id IS NULL"
        elif cat_ids is not None:
            sql += f" AND category_id IN ({','.join('?' * len(cat_ids))})"
            args += list(cat_ids)
        if status:
            sql += " AND status = ?"
            args.append(status)
        if direction == "debit":
            sql += " AND amount < 0"
        elif direction == "credit":
            sql += " AND amount > 0"
        if text:
            sql += " AND (label LIKE ? OR vendor LIKE ? OR note LIKE ?)"
            like = f"%{text}%"
            args += [like, like, like]
        sql += " ORDER BY date DESC, id DESC"
        return self.conn.execute(sql, args).fetchall()

    def operation(self, op_id):
        return self.conn.execute("SELECT * FROM operations WHERE id=?", (op_id,)).fetchone()

    def date_bounds(self):
        r = self.conn.execute("SELECT MIN(date), MAX(date) FROM operations").fetchone()
        return r[0], r[1]

    def count_by_status(self):
        rows = self.conn.execute("SELECT status, COUNT(*) FROM operations GROUP BY status").fetchall()
        return {r[0]: r[1] for r in rows}

    def classify(self, op_ids, category_id, save=True):
        """Classement manuel (validé par l'utilisateur) : jamais modifié par les règles."""
        q = ",".join("?" * len(op_ids))
        self.conn.execute(f"UPDATE operations SET category_id=?, status='manual', rule_id=NULL WHERE id IN ({q})",
                          [category_id] + list(op_ids))
        if save:
            self.save()

    def validate(self, op_ids):
        """Valide le classement automatique proposé."""
        q = ",".join("?" * len(op_ids))
        self.conn.execute(f"UPDATE operations SET status='manual' WHERE status='auto' AND id IN ({q})", list(op_ids))
        self.save()

    def release(self, op_ids):
        """Annule la validation : l'opération repasse sous le contrôle des règles."""
        q = ",".join("?" * len(op_ids))
        self.conn.execute(f"UPDATE operations SET status='none', category_id=NULL, rule_id=NULL WHERE id IN ({q})",
                          list(op_ids))
        self.apply_rules(save=False)
        self.save()

    def set_note(self, op_id, note):
        self.conn.execute("UPDATE operations SET note=? WHERE id=?", (note or "", op_id))
        self.save()

    def delete_operations(self, op_ids):
        q = ",".join("?" * len(op_ids))
        self.conn.execute(f"DELETE FROM operations WHERE id IN ({q})", list(op_ids))
        self.save()

    # ------------------------------------------------------------------- règles
    def rules(self):
        rows = self.conn.execute(
            "SELECT r.*, (SELECT COUNT(*) FROM operations o WHERE o.rule_id = r.id) AS nb "
            "FROM rules r ORDER BY r.pattern_key").fetchall()
        return [Rule(r["id"], r["pattern"], r["pattern_key"], r["category_id"], r["created_at"], r["nb"])
                for r in rows]

    def rule(self, rule_id):
        r = self.conn.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
        return Rule(r["id"], r["pattern"], r["pattern_key"], r["category_id"], r["created_at"]) if r else None

    def rule_by_pattern(self, pattern):
        r = self.conn.execute("SELECT id FROM rules WHERE pattern_key=?", (label_key(pattern),)).fetchone()
        return self.rule(r[0]) if r else None

    def save_rule(self, pattern, category_id, rule_id=None, apply=True):
        """Crée ou met à jour une règle « libellé contient motif -> catégorie ».
        Si une règle de même motif existe déjà, elle est mise à jour."""
        key = label_key(pattern)
        if not key:
            raise ValueError("Le motif doit contenir au moins un mot (hors chiffres et lettres isolées).")
        existing = self.conn.execute("SELECT id FROM rules WHERE pattern_key=?", (key,)).fetchone()
        if existing and existing[0] != rule_id:
            if rule_id is not None:
                self.conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
            rule_id = existing[0]
        if rule_id is None:
            cur = self.conn.execute("INSERT INTO rules(pattern, pattern_key, category_id, created_at) VALUES (?,?,?,?)",
                                    (pattern.strip(), key, category_id, now_iso()))
            rule_id = cur.lastrowid
        else:
            self.conn.execute("UPDATE rules SET pattern=?, pattern_key=?, category_id=? WHERE id=?",
                              (pattern.strip(), key, category_id, rule_id))
        if apply:
            self.apply_rules(save=False)
        self.save()
        return rule_id

    def delete_rule(self, rule_id):
        self.conn.execute("UPDATE operations SET status='none', category_id=NULL WHERE rule_id=? AND status='auto'",
                          (rule_id,))
        self.conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        self.apply_rules(save=False)
        self.save()

    def _compiled_rules(self):
        rows = self.conn.execute("SELECT id, pattern_key, category_id FROM rules").fetchall()
        # Le motif le plus long (le plus précis) l'emporte ; à égalité, la règle la plus récente.
        return sorted(((r[1], r[0], r[2]) for r in rows), key=lambda x: (-len(x[0]), -x[1]))

    def find_rule(self, label, compiled=None):
        compiled = compiled if compiled is not None else self._compiled_rules()
        lk = label_key(label)
        for pkey, rid, cid in compiled:
            if key_matches(pkey, lk):
                return rid, cid
        return None

    def apply_rules(self, save=True):
        """Applique les règles à toutes les opérations non validées. Retourne le nombre de changements."""
        compiled = self._compiled_rules()
        changed = 0
        rows = self.conn.execute(
            "SELECT id, label_key, category_id, rule_id, status FROM operations WHERE status != 'manual'").fetchall()
        for r in rows:
            match = None
            for pkey, rid, cid in compiled:
                if key_matches(pkey, r["label_key"]):
                    match = (rid, cid)
                    break
            new = (match[1], match[0], AUTO) if match else (None, None, NONE)
            if new != (r["category_id"], r["rule_id"], r["status"]):
                self.conn.execute("UPDATE operations SET category_id=?, rule_id=?, status=? WHERE id=?",
                                  (*new, r["id"]))
                changed += 1
        if save:
            self.save()
        return changed

    def matching_operations(self, pattern):
        """Opérations dont le libellé correspond au motif : (total, non validées)."""
        key = label_key(pattern)
        total = pending = 0
        if not key:
            return 0, 0
        for r in self.conn.execute("SELECT label_key, status FROM operations"):
            if key_matches(key, r[0]):
                total += 1
                if r[1] != MANUAL:
                    pending += 1
        return total, pending

    # ------------------------------------------------------------------ budgets
    def budgets(self, year):
        rows = self.conn.execute("SELECT category_id, monthly FROM budgets WHERE year=?", (year,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def set_budget(self, category_id, year, monthly_cents):
        if monthly_cents is None:
            self.conn.execute("DELETE FROM budgets WHERE category_id=? AND year=?", (category_id, year))
        else:
            self.conn.execute("INSERT OR REPLACE INTO budgets VALUES (?,?,?)", (category_id, year, monthly_cents))
        self.save()

    def copy_budgets(self, from_year, to_year):
        self.conn.execute("DELETE FROM budgets WHERE year=?", (to_year,))
        self.conn.execute("INSERT INTO budgets SELECT category_id, ?, monthly FROM budgets WHERE year=?",
                          (to_year, from_year))
        self.save()

    def budget_years(self):
        return [r[0] for r in self.conn.execute("SELECT DISTINCT year FROM budgets ORDER BY year")]
