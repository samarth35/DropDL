# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_dir = Path(SPECPATH)
webview_datas, webview_binaries, webview_hiddenimports = collect_all("webview")

ffmpeg_files = [
    (str(path), "ffmpeg")
    for path in (project_dir / "vendor" / "ffmpeg").glob("*")
    if path.is_file()
]

a = Analysis(
    ["desktop.py"],
    pathex=[str(project_dir)],
    binaries=webview_binaries + ffmpeg_files,
    datas=webview_datas + [
        (str(project_dir / "static"), "static"),
        (str(project_dir / "THIRD_PARTY_NOTICES.txt"), "."),
    ],
    hiddenimports=webview_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
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
