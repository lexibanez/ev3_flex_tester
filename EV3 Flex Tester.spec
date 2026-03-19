# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['EV3 FLEX TESTER GUI.py'],
    pathex=[],
    binaries=[],
    datas=[('Marr Sans Cond Web Bold Regular.ttf', '.'), ('Zipline_Logo_Vertical_White.png', '.')],
    hiddenimports=['pkgutil', 'PyQt5.sip'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='EV3 Flex Tester',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
