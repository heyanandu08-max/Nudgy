# PyInstaller spec for the one-file Nudgy server (nudgy-server / nudgy-server.exe).
# Build from backend/:  pyinstaller nudgy-server.spec
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["server_main.py"],
    pathex=["."],
    datas=[
        ("prompts", "prompts"),
        ("config", "config"),
        ("../.env.example", "."),
    ],
    # Routers and providers import each other lazily; collect the whole app package.
    hiddenimports=collect_submodules("app"),
    excludes=["pytest", "ruff"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="nudgy-server",
    console=True,
    upx=False,
)
