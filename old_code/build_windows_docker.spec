# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the Windows Docker launcher.
Produces a lightweight .exe that manages Docker containers.
"""

a = Analysis(
    ['docker_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest', 'black', 'ruff', 'mypy',
        'IPython', 'jupyter', 'notebook',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'tkinter', '_tkinter',
        'numpy', 'pandas', 'scipy',
        'chromadb', 'ollama', 'fastapi', 'uvicorn',
        'pydantic', 'starlette', 'httpx',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MedicalRAG-Docker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)
