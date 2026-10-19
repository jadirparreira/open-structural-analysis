from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all


# O arquivo .spec fica em packaging/linux; o projeto fica dois níveis acima.
project_root = Path(SPEC).resolve().parents[2]
sys.path.insert(0, str(project_root))


def unique(items):
    """Remove entradas duplicadas preservando a ordem original."""

    return list(dict.fromkeys(items))


# O package-data declarado no pyproject.toml cobre instalações Python, mas os
# arquivos também precisam ser informados explicitamente ao PyInstaller.
data_files = [
    (str(path), "osa/data")
    for path in sorted((project_root / "osa/data").glob("*.json"))
]
data_files.extend(
    (str(path), "osa/resources/icons")
    for path in sorted((project_root / "osa/resources/icons").glob("*.svg"))
)
data_files.extend(
    (str(path), "osa/resources/icons")
    for path in sorted((project_root / "osa/resources/icons").glob("*.png"))
)

plugin_root = project_root / "plugins"
data_files.extend(
    (
        str(path),
        str(Path("plugins") / path.relative_to(plugin_root).parent),
    )
    for path in sorted(plugin_root.rglob("*"))
    if path.is_file()
)


# As coleções iniciais são intencionalmente amplas. PyVista e VTK usam
# imports dinâmicos e bibliotecas compartilhadas que nem sempre aparecem na
# análise estática. Depois do primeiro build funcional, podemos reduzir o
# conteúdo se o tamanho final justificar essa otimização.
pyvista_datas, pyvista_binaries, pyvista_hiddenimports = collect_all("pyvista")
pyvistaqt_datas, pyvistaqt_binaries, pyvistaqt_hiddenimports = collect_all("pyvistaqt")
vtk_datas, vtk_binaries, vtk_hiddenimports = collect_all("vtkmodules")
ezdxf_datas, ezdxf_binaries, ezdxf_hiddenimports = collect_all("ezdxf")

converter_dir = project_root / "build-tools" / "libredwg" / sys.platform
converter_name = "dwg2dxf.exe" if sys.platform == "win32" else "dwg2dxf"
if not (converter_dir / converter_name).is_file():
    raise RuntimeError("Prepare o leitor DWG com scripts/prepare-dwg-converter.py antes de empacotar.")
converter_binaries = []
for path in converter_dir.iterdir():
    entry = (str(path), "osa/resources/converters")
    if path.name == converter_name or path.suffix.lower() == ".dll":
        converter_binaries.append(entry)
    else:
        data_files.append(entry)

datas = unique(data_files + pyvista_datas + pyvistaqt_datas + vtk_datas + ezdxf_datas)
binaries = unique(converter_binaries + pyvista_binaries + pyvistaqt_binaries + vtk_binaries + ezdxf_binaries)
hiddenimports = unique(
    pyvista_hiddenimports
    + pyvistaqt_hiddenimports
    + vtk_hiddenimports
    + ezdxf_hiddenimports
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

splash = Splash(
    str(project_root / "build/startup-splash.png"),
    binaries=analysis.binaries,
    datas=analysis.datas,
    center="primary",
    always_on_top=True,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    splash,
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
)

coll = COLLECT(
    executable,
    splash.binaries,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="open-structural-analysis",
)
