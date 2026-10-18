from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace

import ezdxf
import numpy as np
import pytest

from osa.importers import dwg_converter
from osa.importers.drawing_reference import import_drawing_reference
from osa.model import StructuralModel


@pytest.fixture
def dwg_setup(monkeypatch, tmp_path):
    source = tmp_path / "Planta com espaço – Térreo.DWG"
    source.write_bytes(b"AC1032-unchanged-source")
    converter = tmp_path / "dwg2dxf"
    converter.write_text("fake converter used by mocked subprocess")
    converter.chmod(0o755)
    monkeypatch.setenv("OSA_DWG_CONVERTER", str(converter))
    return source, converter


def test_dwg_import_uses_private_files_preserves_name_and_embeds_geometry(dwg_setup, monkeypatch, tmp_path):
    source, converter = dwg_setup
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert args[0] == str(converter)
        assert Path(args[-1]).read_bytes() == source.read_bytes()
        assert Path(args[-1]) != source
        assert kwargs["timeout"] == dwg_converter.CONVERSION_TIMEOUT
        assert kwargs["check"] is False
        assert not kwargs.get("shell")
        document = ezdxf.new()
        document.units = 4  # mm
        document.modelspace().add_line((1000, 2000), (3000, 4000))
        hatch = document.modelspace().add_hatch()
        hatch.paths.add_polyline_path([(0, 0), (100, 0), (100, 100), (0, 100)], is_closed=True)
        document.saveas(args[args.index("-o") + 1])
        kwargs["stdout"].write(b"Warning: unsupported custom CAD object\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dwg_converter.subprocess, "run", run)
    result = import_drawing_reference(source)
    assert result.reference.name == source.name
    assert result.reference.plane == "XY"
    assert result.reference.origin == (0, 0, 0)
    assert result.reference.geometry.triangles
    lines = np.frombuffer(result.reference.geometry.lines, dtype="<f8").reshape(-1, 2, 2)
    np.testing.assert_allclose(lines, [[[1, 2], [3, 4]]])
    assert "custom CAD object" in result.warnings[0]
    assert source.read_bytes() == b"AC1032-unchanged-source"
    assert not Path(calls[0][1]["cwd"]).exists()
    model = StructuralModel()
    model.add_reference(result.reference)
    saved = tmp_path / "dwg-reference.osa"
    model.save(saved)
    source.unlink()
    restored = StructuralModel()
    restored.load(saved)
    assert restored.references[result.reference.id].geometry.lines == result.reference.geometry.lines


@pytest.mark.parametrize("mode", ["nonzero", "missing_output", "corrupt_output", "timeout", "cannot_start"])
def test_failed_conversion_cleans_temporary_files_and_preserves_original(dwg_setup, monkeypatch, mode):
    source, _ = dwg_setup
    directories = []

    def run(args, **kwargs):
        directories.append(Path(kwargs["cwd"]))
        if mode == "timeout":
            raise TimeoutExpired(args, 120)
        if mode == "cannot_start":
            raise OSError("cannot start")
        if mode == "corrupt_output":
            Path(args[args.index("-o") + 1]).write_text("invalid output")
        return SimpleNamespace(returncode=1 if mode == "nonzero" else 0)

    monkeypatch.setattr(dwg_converter.subprocess, "run", run)
    with pytest.raises(ValueError):
        import_drawing_reference(source)
    assert source.read_bytes() == b"AC1032-unchanged-source"
    assert all(not directory.exists() for directory in directories)


def test_missing_converter_explains_installation_and_dxf_still_works(monkeypatch, tmp_path):
    monkeypatch.setenv("OSA_DWG_CONVERTER", str(tmp_path / "missing-converter"))
    dwg = tmp_path / "file.dwg"
    dwg.write_bytes(b"AC1032")
    with pytest.raises(ValueError, match="instalação do OpenSA"):
        import_drawing_reference(dwg)
    document = ezdxf.new()
    document.units = 6
    document.modelspace().add_line((0, 0), (1, 1))
    dxf = tmp_path / "file.dxf"
    document.saveas(dxf)
    assert import_drawing_reference(dxf).reference.geometry.lines


def test_bundled_converter_is_preferred_to_system_installation(monkeypatch, tmp_path):
    monkeypatch.delenv("OSA_DWG_CONVERTER", raising=False)
    monkeypatch.setattr(dwg_converter, "__file__", str(tmp_path / "osa" / "importers" / "dwg_converter.py"))
    name = "dwg2dxf.exe" if dwg_converter.sys.platform == "win32" else "dwg2dxf"
    bundled = tmp_path / "osa" / "resources" / "converters" / name
    bundled.parent.mkdir(parents=True)
    bundled.write_text("converter")
    bundled.chmod(0o755)
    monkeypatch.setattr(dwg_converter.shutil, "which", lambda _: str(tmp_path / "other-converter"))
    assert dwg_converter.converter_path() == bundled


def test_missing_dwg_does_not_start_converter(monkeypatch, tmp_path):
    monkeypatch.setattr(dwg_converter, "converter_path", lambda: pytest.fail("should not start converter"))
    with pytest.raises(ValueError, match="não foi encontrado"):
        import_drawing_reference(tmp_path / "missing.dwg")
