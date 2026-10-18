"""Prepare a pinned LibreDWG converter for source runs and PyInstaller packages.

Linux requires a C compiler and make. Windows uses the upstream 64-bit release.
Downloads are restricted to published upstream artifacts and verified by SHA-256.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

VERSION = "0.14"
SOURCE_URL = f"https://ftp.gnu.org/gnu/libredwg/libredwg-{VERSION}.tar.xz"
SOURCE_SHA256 = "62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275"
WINDOWS_URL = f"https://github.com/LibreDWG/libredwg/releases/download/{VERSION}/libredwg-{VERSION}-win64.zip"
WINDOWS_SHA256 = "1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8"
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


def prepare(source_archive=None, windows_archive=None, *, force=False):
    if sys.platform not in ("linux", "win32"):
        raise ValueError("O conversor empacotado é preparado para Linux e Windows.")
    cache = ROOT / "build-tools" / "libredwg"
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / sys.platform
    executable = "dwg2dxf.exe" if sys.platform == "win32" else "dwg2dxf"
    stamp = destination / "version.txt"
    if not force and (destination / executable).is_file() and stamp.is_file() and stamp.read_text() == VERSION:
        print(f"LibreDWG {VERSION} já preparado em {destination}")
        return
    source = verified_archive(SOURCE_URL, SOURCE_SHA256, cache, source_archive)
    with TemporaryDirectory(prefix="opensa-libredwg-") as temporary:
        build = Path(temporary)
        # Only extract regular members beneath the verified archive's root.
        with tarfile.open(source) as archive:
            for member in archive.getmembers():
                if member.issym() or member.islnk() or member.isdev():
                    continue
                target = (build / member.name).resolve()
                if not target.is_relative_to(build.resolve()):
                    raise ValueError("Caminho inválido no pacote LibreDWG.")
                archive.extract(member, build)
        sources = build / f"libredwg-{VERSION}"
        staging = build / "converter"
        staging.mkdir()
        if sys.platform == "win32":
            if sys.maxsize <= 2**32:
                raise ValueError("O conversor DWG requer Windows de 64 bits.")
            binary_archive = verified_archive(WINDOWS_URL, WINDOWS_SHA256, cache, windows_archive)
            with ZipFile(binary_archive) as archive:
                for name in archive.namelist():
                    path = Path(name)
                    if len(path.parts) == 1 and (name == executable or name.lower().endswith(".dll")):
                        (staging / name).write_bytes(archive.read(name))
        else:
            subprocess.run([
                str(sources / "configure"), "--disable-shared", "--enable-static", "--disable-bindings",
                "--disable-docs", "--disable-json", "--enable-release", "CFLAGS=-O1",
            ], cwd=sources, check=True)
            subprocess.run(["make", f"-j{min(2, os.cpu_count() or 1)}", "-C", "src", "libredwg.la"],
                           cwd=sources, check=True)
            subprocess.run(["make", "-C", "programs", "dwg2dxf"], cwd=sources, check=True)
            shutil.copy2(sources / "programs" / executable, staging / executable)
            if shutil.which("strip"):
                subprocess.run(["strip", str(staging / executable)], check=True)
        if not (staging / executable).is_file():
            raise ValueError("O pacote LibreDWG não contém o conversor DWG esperado.")
        subprocess.run([str(staging / executable), "--version"], check=True)
        shutil.copy2(sources / "COPYING", staging / "COPYING-LibreDWG.txt")
        # Distribute the corresponding upstream source alongside the native tool.
        shutil.copy2(source, staging / f"libredwg-{VERSION}-source.tar.xz")
        (staging / "NOTICE.txt").write_text(
            f"GNU LibreDWG {VERSION} — GPL-3.0-or-later\n"
            f"Source: {SOURCE_URL}\nSHA-256: {SOURCE_SHA256}\n"
            f"Windows binary: {WINDOWS_URL}\nSHA-256: {WINDOWS_SHA256}\n"
            "Upstream: https://www.gnu.org/software/libredwg/\n"
            "Windows runtime DLLs are provided by the same upstream release.\n",
            encoding="utf-8",
        )
        (staging / "version.txt").write_text(VERSION)
        destination.mkdir(parents=True, exist_ok=True)
        for file in staging.iterdir():
            shutil.copy2(file, destination / file.name)
    print(f"LibreDWG {VERSION} preparado em {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, help="Arquivo fonte oficial já baixado")
    parser.add_argument("--windows-archive", type=Path, help="Pacote Windows oficial já baixado")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    prepare(args.source_archive, args.windows_archive, force=args.force)
