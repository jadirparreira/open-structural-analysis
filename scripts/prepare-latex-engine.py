"""Prepara o compilador LaTeX Tectonic fixado para execução local e pacotes PyInstaller.

O Tectonic é um compilador LaTeX completo em um único executável. Ele baixa
sob demanda, na primeira compilação, apenas os pacotes LaTeX usados pelo
documento (cache do usuário). Assim o laudo em PDF funciona sem MiKTeX ou
TeX Live instalados. Os downloads se limitam aos pacotes oficiais publicados
no GitHub e são conferidos por SHA-256.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

VERSION = "0.17.0"
_BASE_URL = f"https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40{VERSION}"
ARCHIVES = {
    "win32": (
        f"{_BASE_URL}/tectonic-{VERSION}-x86_64-pc-windows-msvc.zip",
        "f61ce51f0b0ade1015b7de7ef368541c5424e9756ecbd0d7af97d6d48030845f",
    ),
    "linux": (
        f"{_BASE_URL}/tectonic-{VERSION}-x86_64-unknown-linux-musl.tar.gz",
        "8533d07f9ccbd7a65824b9e0459041bca34af1eb33daba48f59215593753a3b7",
    ),
}
ROOT = Path(__file__).resolve().parents[1]


def verified_archive(url, checksum, cache, supplied=None):
    archive = Path(supplied) if supplied else cache / url.rsplit("/", 1)[-1]
    if not archive.is_file():
        if supplied:
            raise ValueError(f"Arquivo não encontrado: {archive}")
        temporary = archive.with_suffix(archive.suffix + ".tmp")
        try:
            with urlopen(url, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
        raise ValueError(f"SHA-256 inválido: {archive}. Remova o arquivo e tente novamente.")
    return archive


def prepare(supplied_archive=None, *, force=False):
    if sys.platform not in ARCHIVES:
        raise ValueError("O Tectonic empacotado é preparado para Linux e Windows (x86_64).")
    if sys.maxsize <= 2**32:
        raise ValueError("O Tectonic empacotado requer sistema de 64 bits.")
    cache = ROOT / "build-tools" / "tectonic"
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / sys.platform
    executable = "tectonic.exe" if sys.platform == "win32" else "tectonic"
    stamp = destination / "version.txt"
    if not force and (destination / executable).is_file() and stamp.is_file() and stamp.read_text() == VERSION:
        print(f"Tectonic {VERSION} já preparado em {destination}")
        return
    url, checksum = ARCHIVES[sys.platform]
    archive = verified_archive(url, checksum, cache, supplied_archive)
    with TemporaryDirectory(prefix="opensa-tectonic-") as temporary:
        staging = Path(temporary)
        # Extrai somente o executável na raiz do pacote verificado.
        if archive.suffix == ".zip":
            with ZipFile(archive) as package:
                (staging / executable).write_bytes(package.read(executable))
        else:
            with tarfile.open(archive) as package:
                member = package.getmember(executable)
                if not member.isfile():
                    raise ValueError("O pacote Tectonic não contém o executável esperado.")
                source = package.extractfile(member)
                (staging / executable).write_bytes(source.read())
            (staging / executable).chmod(0o755)
        subprocess.run([str(staging / executable), "--version"], check=True)
        (staging / "NOTICE.txt").write_text(
            f"Tectonic {VERSION} — MIT License\n"
            f"Binary: {url}\nSHA-256: {checksum}\n"
            "Upstream: https://tectonic-typesetting.github.io/\n"
            "Source: https://github.com/tectonic-typesetting/tectonic\n",
            encoding="utf-8",
        )
        (staging / "version.txt").write_text(VERSION)
        destination.mkdir(parents=True, exist_ok=True)
        for file in staging.iterdir():
            shutil.copy2(file, destination / file.name)
    print(f"Tectonic {VERSION} preparado em {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Pacote oficial do Tectonic já baixado")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    prepare(args.archive, force=args.force)
