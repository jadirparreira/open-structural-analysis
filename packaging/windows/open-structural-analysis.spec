from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPEC).resolve().parents[2]
sys.path.insert(0, str(project_root))


def unique(items):
    """Remove entradas duplicadas preservando a ordem original."""

    return list(dict.fromkeys(items))


data_files = [
    (str(path), "osa/data")
    for path in sorted((project_root / "osa/data").glob("*.json"))
]
data_files.extend(
    (str(path), "osa/resources/icons")
    for path in sorted((project_root / "osa/resources/icons").glob("*.svg"))
)


pyvista_datas, pyvista_binaries, pyvista_hiddenimports = collect_all("pyvista")
pyvistaqt_datas, pyvistaqt_binaries, pyvistaqt_hiddenimports = collect_all("pyvistaqt")
vtk_datas, vtk_binaries, vtk_hiddenimports = collect_all("vtkmodules")

datas = unique(data_files + pyvista_datas + pyvistaqt_datas + vtk_datas)
binaries = unique(pyvista_binaries + pyvistaqt_binaries + vtk_binaries)
hiddenimports = unique(
    pyvista_hiddenimports
    + pyvistaqt_hiddenimports
    + vtk_hiddenimports
    + ["PySide6.QtSvg", "PySide6.QtSvgWidgets"]
)


analysis = Analysis(
    [str(project_root / "osa/main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="open-structural-analysis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(project_root / "build/windows/openstructuralanalysis.ico"),
)

COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="open-structural-analysis",
)
