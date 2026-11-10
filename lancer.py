"""Lance l'application Mes Comptes (point d'entrée utilisé aussi pour fabriquer le .exe)."""
import sys

from mescomptes.main import main

if __name__ == "__main__":
    sys.exit(main())
