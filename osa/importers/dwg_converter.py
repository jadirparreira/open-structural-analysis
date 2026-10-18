"""Read DWG through a local, isolated LibreDWG process without modifying the source."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import ezdxf

CONVERSION_TIMEOUT = 120


def converter_path() -> Path:
    executable = "dwg2dxf.exe" if sys.platform == "win32" else "dwg2dxf"
    configured = os.environ.get("OSA_DWG_CONVERTER")
    if configured:
        candidates = [Path(configured)]
    else:
        package = Path(__file__).resolve().parents[1]
        candidates = [
            package / "resources" / "converters" / executable,
            package.parent / "build-tools" / "libredwg" / sys.platform / executable,
        ]
        installed = shutil.which(executable)
        if installed:
            candidates.append(Path(installed))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise ValueError(
        "O conversor DWG não foi encontrado nesta instalação do OpenSA. "
        "Instale uma versão completa com suporte a DWG."
    )


def read_dwg(filename: Path):
    if not filename.is_file():
        raise ValueError("O arquivo DWG não foi encontrado.")
    converter = converter_path()
    with TemporaryDirectory(prefix="opensa-dwg-") as temporary:
        directory = Path(temporary)
        # An ASCII filename also accommodates CAD tools with legacy path handling.
        source = directory / "drawing.dwg"
        target = directory / "drawing.dxf"
        shutil.copyfile(filename, source)
        log_path = directory / "conversion.log"
        try:
            with log_path.open("wb") as log:
                result = subprocess.run(
                    [str(converter), "-o", str(target), str(source)],
                    cwd=directory, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    timeout=CONVERSION_TIMEOUT, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
        except subprocess.TimeoutExpired as error:
            raise ValueError("A leitura do DWG excedeu 120 segundos. Simplifique o desenho e tente novamente.") from error
        except OSError as error:
            raise ValueError("Não foi possível iniciar o leitor DWG desta instalação do OpenSA.") from error
        if result.returncode != 0 or not target.is_file():
            raise ValueError("Não foi possível ler o DWG. Verifique a integridade e a versão do arquivo.")
        try:
            document = ezdxf.readfile(target)
        except (OSError, ezdxf.DXFError) as error:
            raise ValueError("O leitor DWG não produziu um desenho válido para importação.") from error
        # The native tool reports recoverable/unsupported entities through its log.
        # Keep warnings bounded, including when a damaged CAD file is very noisy.
        diagnostics = []
        with log_path.open(encoding="utf-8", errors="replace") as log:
            for line in log:
                if re.search(r"\b(error|warn(?:ing)?|unsupported|unhandled|skipp(?:ed|ing))\b", line, re.IGNORECASE):
                    diagnostics.append(line.strip()[:300])
                    if len(diagnostics) == 10:
                        break
        warnings = ()
        if diagnostics:
            warnings = ("O leitor DWG relatou avisos; confira os detalhes do desenho:\n" + "\n".join(diagnostics),)
        return document, warnings
