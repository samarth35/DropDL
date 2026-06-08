# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_dir = Path(SPECPATH)

ffmpeg_files = [
    (str(path), "ffmpeg")
    for path in (project_dir / "vendor" / "ffmpeg").glob("*")
    if path.is_file()
]

a = Analysis(
    ["desktop.py"],
    pathex=[str(project_dir)],
    binaries=ffmpeg_files,
    datas=[
        (str(project_dir / "static"), "static"),
        (str(project_dir / "THIRD_PARTY_NOTICES.txt"), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "webview", "pythonnet", "clr", "clr_loader"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DropDL",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DropDL",
)
