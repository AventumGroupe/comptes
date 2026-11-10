"""Fichier de données chiffré.

Format : MAGIC | sel (16 o) | nonce (12 o) | AES-256-GCM( zlib( base SQLite ) )
La clé est dérivée du mot de passe par scrypt. Sans le mot de passe, le fichier
est illisible ; un mot de passe oublié ne peut pas être récupéré.
"""

import os
import zlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"MESCOMPTES\x01"
SALT_LEN = 16
NONCE_LEN = 12
FILE_EXTENSION = ".mcpt"


class StoreError(Exception):
    pass


class WrongPassword(StoreError):
    pass


class InvalidFile(StoreError):
    pass


def new_salt():
    return os.urandom(SALT_LEN)


def derive_key(password, salt):
    kdf = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1)
    return kdf.derive(password.encode("utf-8"))


def encrypt(data, key, salt):
    nonce = os.urandom(NONCE_LEN)
    payload = AESGCM(key).encrypt(nonce, zlib.compress(data, 6), MAGIC)
    return MAGIC + salt + nonce + payload


def read_file(path, password):
    """Retourne (données SQLite, clé, sel)."""
    with open(path, "rb") as f:
        blob = f.read()
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + SALT_LEN + NONCE_LEN + 16:
        raise InvalidFile("Ce fichier n'est pas un dossier Mes Comptes valide.")
    pos = len(MAGIC)
    salt = blob[pos:pos + SALT_LEN]
    pos += SALT_LEN
    nonce = blob[pos:pos + NONCE_LEN]
    pos += NONCE_LEN
    key = derive_key(password, salt)
    try:
        data = zlib.decompress(AESGCM(key).decrypt(nonce, blob[pos:], MAGIC))
    except InvalidTag:
        raise WrongPassword("Mot de passe incorrect.") from None
    return data, key, salt


def write_file(path, data, key, salt):
    """Écriture atomique : fichier temporaire puis remplacement."""
    blob = encrypt(data, key, salt)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
