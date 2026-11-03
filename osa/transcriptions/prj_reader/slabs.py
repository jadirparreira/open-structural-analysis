"""Evidências de lajes para a futura transcrição como placas.

O prefixo conhecido fornece nome e referências do contorno. A região binária
é preservada com limites explícitos; não é declarada como o fim do objeto.
"""

from __future__ import annotations

import base64
import hashlib
import struct
import zlib

from .core import LayoutError


def is_slab_element_class(name):
    # TLajePreFabricada, CfgPavLaje e grupos de continuidade são cadastros ou
    # configurações e não devem ser contados como lajes lançadas.
    return name in {"Laje", "ElementoLaje"} or name.startswith("TElementoLaje")


def collect_slabs(reader, decoder, croquis):
    r = reader
    headers = [h for h in r.headers if is_slab_element_class(h.class_name)]
    records = []
    for index, h in enumerate(headers):
        context = next(
            (c for c in croquis if c["offset"] <= h.offset < c["region_end"]), None
        )
        limit = context["region_end"] if context else len(r.data)
        if index + 1 < len(headers):
            limit = min(limit, headers[index + 1].offset)
        raw = r.bytes(h.offset, limit - h.offset)
        record = {
            **r.identity(h),
            "floor_id": context["floor_id"] if context else None,
            "floor_name": context["floor_name"] if context else None,
            "name": None,
            "boundary_element_ids": [],
            "decoding_status": "unmapped",
            "source_region": {
                "offset": h.offset,
                "end_offset": limit,
                "object_end_known": False,
                "boundary": "next_slab_or_croqui_region_end",
                "encoding": "zlib+base64",
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "data": base64.b64encode(zlib.compress(raw)).decode("ascii"),
            },
        }
        start = len(r.fields)
        try:
            r.require(
                h.class_name == "TElementoLajeContornoComPilar",
                "Prefixo desta classe de laje ainda não mapeado",
            )
            common = decoder.basic_cad(h, 4)
            q = common["common_offset"]
            r.ref(h, "slab_text_level", q + 38, "TNivel")
            r.raw(h, "slab_prefix_codes_raw", q + 43, q + 55)
            count, capacity = r.field(h, "slab_boundary_count_capacity", q + 55, "2I")
            r.require(
                count <= capacity and count <= 10000,
                "Lista de contorno de laje inválida",
            )
            p = q + 63
            refs = []
            for number in range(count):
                target, p = r.ref(
                    h, f"slab_boundary_{number}", p, ("ElementoTrecho", "ElementoViga")
                )
                refs.append(target.serial_id)
            r.field(h, "slab_code_before_name_raw", p, "I", status="raw")
            name, _ = r.text_field(h, "slab_name", p + 4)
            record.update(
                name=name,
                uuid=common["uuid"],
                boundary_element_ids=refs,
                decoding_status="prefix_only",
            )
        except (LayoutError, struct.error, UnicodeError, OverflowError) as error:
            del r.fields[start:]
            record["decode_warning"] = str(error)
        records.append(record)
    return records
