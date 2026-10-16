"""Primitivas binárias. Não executa Eberick, DLLs ou conteúdo do projeto."""

from __future__ import annotations

import bisect
import hashlib
import io
import math
import re
import struct
import zipfile
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path


class LayoutError(ValueError):
    pass


@dataclass(frozen=True)
class Header:
    serial_id: int
    offset: int
    class_name: str
    data_offset: int
    next_header_offset: int
    occurrence: int

    def as_dict(self):
        d = asdict(self)
        d["offset_hex"] = hex(self.offset)
        d["warning"] = (
            "next_header_offset não delimita o fim do objeto; pode iniciar um filho."
        )
        return d


def load_stream(path, member=None, max_bytes=256 * 1024 * 1024):
    """Detecta pelos bytes; lê ZIP em memória, sem extrair caminhos do arquivo."""
    p = Path(path)
    if p.stat().st_size > max_bytes:
        raise LayoutError("Arquivo excede o limite configurado de leitura.")
    container = p.read_bytes()
    info = {
        "filename": p.name,
        "container_size": len(container),
        "container_sha256": hashlib.sha256(container).hexdigest(),
    }
    if zipfile.is_zipfile(io.BytesIO(container)):
        with zipfile.ZipFile(io.BytesIO(container)) as z:
            entries = [e for e in z.infolist() if not e.is_dir()]
            info["zip_members"] = [
                {
                    "name": e.filename,
                    "size": e.file_size,
                    "compressed_size": e.compress_size,
                    "crc32": f"{e.CRC:08x}",
                }
                for e in entries
            ]
            candidates = (
                [e for e in entries if e.filename == member]
                if member
                else [e for e in entries if e.filename == "__DADOS__"]
            )
            if not candidates and not member and len(entries) == 1:
                candidates = entries
            if len(candidates) != 1:
                raise LayoutError("ZIP ambíguo: escolha o membro com --member.")
            e = candidates[0]
            if e.flag_bits & 1:
                raise LayoutError("ZIP protegido por senha não é suportado.")
            if e.file_size > max_bytes:
                raise LayoutError("Conteúdo descompactado excede o limite configurado.")
            try:
                data = z.read(e)  # zipfile confere CRC; não usa extract/extractall.
            except (zipfile.BadZipFile, RuntimeError, zlib.error) as err:
                raise LayoutError(
                    "Falha de integridade ou descompactação do membro ZIP."
                ) from err
            info.update(container="zip", member=e.filename)
    else:
        data = container
        info.update(container="binary", member=None)
    if data[:8] != b":\x01\x01\0\0\x1a\x1a\x1a":
        raise LayoutError(
            "Assinatura inicial não reconhecida como uma das amostras Eberick."
        )
    info.update(
        stream_size=len(data),
        stream_sha256=hashlib.sha256(data).hexdigest(),
        offsets_basis="fluxo descompactado; nunca offsets do ZIP",
    )
    return data, info


class Reader:
    """Índice de assinaturas + decodificadores explícitos, com rastreabilidade por campo.

    O índice é heurístico. Cada decodificador confere seus delimitadores e relações.
    O fluxo original permanece integralmente disponível para campos desconhecidos.
    """

    def __init__(self, data, source=None):
        self.data = data
        self.source = source or {}
        self.fields = []
        self.errors = []
        self.checks = []
        found = []
        counts = {}
        for m in re.finditer(rb"\[", data):
            p = m.end()
            if p + 4 > len(data):
                continue
            n = struct.unpack_from("<I", data, p)[0]
            e = p + 4 + n
            if (
                1 <= n <= 100
                and e <= len(data)
                and re.fullmatch(rb"[A-Za-z_][A-Za-z_0-9:]*", data[p + 4 : e])
            ):
                name = data[p + 4 : e].decode("ascii")
                counts[name] = counts.get(name, 0) + 1
                found.append((m.start(), name, e, counts[name]))
        self.headers = [
            Header(
                i + 1,
                off,
                name,
                end,
                found[i + 1][0] if i + 1 < len(found) else len(data),
                occ,
            )
            for i, (off, name, end, occ) in enumerate(found)
        ]
        self.by_id = {h.serial_id: h for h in self.headers}
        self.by_offset = {h.offset: h for h in self.headers}
        self.offsets = [h.offset for h in self.headers]
        self.classes = {}
        for h in self.headers:
            self.classes.setdefault(h.class_name, []).append(h)
        self.version = (
            self.u32(self.classes["Projeto"][0].data_offset)
            if self.classes.get("Projeto")
            else None
        )

    def require(self, ok, message):
        if not ok:
            raise LayoutError(message)

    def bytes(self, p, n):
        self.require(
            0 <= p <= len(self.data) and 0 <= n <= len(self.data) - p,
            f"Leitura fora dos limites em {p:#x}, n={n}",
        )
        return self.data[p : p + n]

    def unpack(self, fmt, p):
        return struct.unpack("<" + fmt, self.bytes(p, struct.calcsize("<" + fmt)))

    def u32(self, p):
        return self.unpack("I", p)[0]

    def string(self, p, max_length=100000):
        n = self.u32(p)
        self.require(n <= max_length, f"Texto excessivo em {p:#x}")
        try:
            value = self.bytes(p + 4, n).decode("cp1252")
        except UnicodeDecodeError as e:
            raise LayoutError(f"Texto inválido em {p:#x}") from e
        return value, p + 4 + n

    def close(self, p):
        self.require(self.bytes(p, 1) == b"]", f"Fechamento esperado em {p:#x}")
        return p + 1

    def header_at(self, p, name=None):
        h = self.by_offset.get(p)
        self.require(
            h is not None and (name is None or h.class_name == name),
            f"Classe {name!r} esperada em {p:#x}",
        )
        return h

    def after(self, h, name, limit=10000):
        """Busca uma âncora local, não implica relação de propriedade por si só."""
        for x in self.headers[h.serial_id :]:
            if x.offset > h.data_offset + limit:
                break
            if x.class_name == name:
                return x
        raise LayoutError(f"Âncora {name} ausente após {h.class_name}@{h.offset:#x}")

    def between(self, start, end, name=None):
        i = bisect.bisect_left(self.offsets, start)
        j = bisect.bisect_left(self.offsets, end)
        return [h for h in self.headers[i:j] if name is None or h.class_name == name]

    def field(
        self,
        h,
        name,
        p,
        fmt=None,
        value=None,
        size=None,
        status="decoded",
        interpretation=None,
        unit="raw",
    ):
        """decoded = bytes/tipo lidos; inferred = significado proposto; raw = sem semântica."""
        if fmt:
            vals = self.unpack(fmt, p)
            self.require(
                all(not isinstance(v, float) or math.isfinite(v) for v in vals),
                f"Número não finito em {p:#x}",
            )
            value = vals[0] if len(vals) == 1 else list(vals)
            size = struct.calcsize("<" + fmt)
        self.require(size is not None, "Campo deve ter tamanho conhecido.")
        self.bytes(p, size)
        self.fields.append(
            {
                "object_id": h.serial_id,
                "class_name": h.class_name,
                "occurrence": h.occurrence,
                "field": name,
                "offset": p,
                "offset_hex": hex(p),
                "relative_to_payload": p - h.data_offset,
                "size": size,
                "storage": ("<" + fmt) if fmt else "bytes/string",
                "value": value,
                "status": status,
                "interpretation": interpretation,
                "unit": unit,
            }
        )
        return value

    def text_field(self, h, name, p):
        value, end = self.string(p)
        self.field(h, name, p, value=value, size=end - p)
        return value, end

    def raw(self, h, name, start, end):
        return self.field(
            h,
            name,
            start,
            value=self.bytes(start, end - start).hex(),
            size=end - start,
            status="raw",
        )

    def ref(self, h, name, p, expected=None):
        self.require(self.bytes(p, 1) == b"\1", f"Referência esperada em {p:#x}")
        ident = self.u32(p + 1)
        target = self.by_id.get(ident)
        self.require(target is not None, f"Referência {ident} não resolvida em {p:#x}")
        if expected:
            names = {expected} if isinstance(expected, str) else set(expected)
            self.require(
                target.class_name in names,
                f"Referência {ident} resolve para {target.class_name}, esperado {names}",
            )
        self.field(
            h,
            name,
            p,
            value={"target_id": ident, "target_class": target.class_name},
            size=5,
        )
        return target, p + 5

    def run(self, h, fn):
        start = len(self.fields)
        try:
            return fn(h)
        except (LayoutError, struct.error, UnicodeError, OverflowError) as e:
            del self.fields[start:]
            self.errors.append(
                {
                    "object_id": h.serial_id,
                    "class_name": h.class_name,
                    "offset_hex": hex(h.offset),
                    "error": str(e),
                }
            )
            return None

    def identity(self, h):
        return {
            "object_id": h.serial_id,
            "class_name": h.class_name,
            "offset": h.offset,
            "offset_hex": hex(h.offset),
        }

    def hexdump(self, start, size):
        end = min(start + size, len(self.data))
        self.bytes(start, end - start)
        lines = []
        for p in range(start, end, 16):
            raw = self.data[p : min(p + 16, end)]
            lines.append(
                f"{p:08x}  {raw.hex(' '):47}  "
                + "".join(chr(c) if 32 <= c < 127 else "." for c in raw)
            )
        return "\n".join(lines)
