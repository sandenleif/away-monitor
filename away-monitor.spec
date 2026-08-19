# -*- mode: python ; coding: utf-8 -*-
"""Eine einzelne Exe: Modell eingebettet, kein Konsolenfenster.

Onefile statt Onedir, weil der Updater dann genau eine Datei tauschen muss.
Preis dafuer sind ein paar Sekunden Startzeit -- PyInstaller packt bei jedem
Start in ein Temp-Verzeichnis aus.
"""

a = Analysis(
    ['entry.py'],
    pathex=[],
    binaries=[],
    datas=[('models/face_detection_yunet_2023mar.onnx', 'models')],
    # pystray und PIL laden ihre Windows-Backends dynamisch nach; die findet
    # die statische Analyse nicht von allein.
    hiddenimports=['pystray._win32', 'PIL._tkinter_finder'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'scipy', 'pandas', 'pytest', 'IPython', 'notebook'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='away-monitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)
