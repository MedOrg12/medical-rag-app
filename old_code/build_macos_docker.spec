# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the macOS Docker launcher.
Produces a .app bundle that manages Docker containers.
"""

APP_NAME = 'MedicalRAG-Docker'
VERSION = '1.0.0'

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
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)

app = BUNDLE(
    exe,
    name=f'{APP_NAME}.app',
    icon=None,
    bundle_identifier='com.medicalrag.docker',
    version=VERSION,
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
        'CFBundleName': 'Medical RAG Docker',
        'CFBundleDisplayName': 'Medical RAG Docker',
        'CFBundleGetInfoString': 'Medical Research RAG - Docker Launcher',
        'CFBundleIdentifier': 'com.medicalrag.docker',
        'CFBundleVersion': VERSION,
        'CFBundleShortVersionString': VERSION,
    },
)
