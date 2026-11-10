# -*- mode: python ; coding: utf-8 -*-
# Fabrication de l'exécutable unique : pyinstaller --noconfirm MesComptes.spec

a = Analysis(
    ["lancer.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/icone.ico", "assets")],
    hiddenimports=["matplotlib.backends.backend_qtagg"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib.backends.backend_tkagg", "matplotlib.backends._backend_tk",
              "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql", "PySide6.QtTest",
              "PySide6.QtOpenGL", "PySide6.QtDBus", "PySide6.QtConcurrent", "PySide6.QtXml",
              "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MesComptes",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icone.ico",
)
