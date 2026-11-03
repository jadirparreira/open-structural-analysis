"""Layouts observados: dados comuns 3028/3419 e lançamento 3419.

O código 3219 tem reconhecimento estrutural parcial; a barra de fundação em
bloco é reconhecida no perfil observado, sem importar a geometria do bloco.

Não se atribui significado estrutural a um enum só porque seu valor é 0 ou 1.
Os códigos de serialização são registrados; a compatibilidade é verificada
pelas posições, delimitadores, referências e relações entre os registros.
Não gera automaticamente modelo de cálculo nem escreve PRJ.
"""

from __future__ import annotations

import collections
import math
import struct
import sys
import uuid

from .core import LayoutError
from .slabs import collect_slabs


class Decoder:
    def __init__(self, reader):
        self.r = reader
        self.cache = {}

    def cached(self, name, h, fn):
        key = (name, h.serial_id)
        if key not in self.cache:
            self.cache[key] = fn(h)
        return self.cache[key]

    def uuid(self, h):
        def parse(h):
            r = self.r
            p = h.data_offset
            r.field(h, "serialization_code_raw", p, "I", status="raw")
            r.close(p + 20)
            raw = r.bytes(p + 4, 16)
            value = r.field(h, "uuid_bytes", p + 4, value=raw.hex(), size=16)
            return dict(
                **r.identity(h),
                bytes_hex=value,
                uuid_le_candidate=str(uuid.UUID(bytes_le=raw)),
                end=p + 21,
            )

        return self.cached("uuid", h, parse)

    def load_key(self, h):
        def parse(h):
            r = self.r
            p = h.data_offset
            val = r.field(h, "version_type_subtype", p, "3I")
            r.close(p + 12)
            return dict(**r.identity(h), key=val[1:], end=p + 13)

        return self.cached("load_key", h, parse)

    def action(self, h):
        r = self.r
        p = h.data_offset
        r.field(h, "serialization_code_raw", p, "I", status="raw")
        name, q = r.text_field(h, "name", p + 8)
        symbol, q = r.text_field(h, "symbol", q)
        flags = r.field(h, "three_flags_raw", q, "3I", status="raw")
        factors = r.field(h, "five_factors_raw", q + 12, "5d", status="raw")
        key = self.load_key(r.header_at(q + 52, "TIdCarregamento"))
        return dict(
            **r.identity(h),
            name=name,
            symbol=symbol,
            key=key["key"],
            flags_raw=flags,
            factors_raw=factors,
        )

    def combination(self, h):
        r = self.r
        p = h.data_offset
        name, q = r.text_field(h, "name", p + 4)
        count = r.field(h, "term_count", q, "I")
        q += 4
        r.require(count <= 1000, "Combinação com quantidade excessiva")
        terms = []
        for _ in range(count):
            key = self.load_key(r.header_at(q, "TIdCarregamento"))
            q = key["end"]
            factor = r.field(h, "factor_" + str(len(terms)), q, "d")
            q += 8
            terms.append(
                {"key": key["key"], "factor": factor, "key_object_id": key["object_id"]}
            )
        r.close(q)
        return dict(**r.identity(h), name=name, terms=terms, end=q + 1)

    def section(self, h):
        def parse(h):
            r = self.r
            p = h.data_offset
            r.field(h, "serialization_codes_raw", p, "2I", status="raw")
            r.close(p + 105)
            dims = r.field(h, "seven_geometric_values_raw", p + 8, "7d", status="raw")
            code = r.field(h, "shape_code_raw", p + 64, "I", status="raw")
            angle = r.field(
                h, "angle_candidate_rad", p + 68, "d", status="inferred", unit="rad"
            )
            tail = r.raw(h, "section_tail_raw", p + 76, p + 105)
            return dict(
                **r.identity(h),
                geometric_values_raw=dims,
                shape_code_raw=code,
                angle_candidate_rad=angle,
                tail_raw=tail,
                end=p + 106,
            )

        return self.cached("section", h, parse)

    def concrete(self, h):
        r = self.r
        p = h.data_offset
        name, q = r.text_field(h, "name", p + 4)
        strength = r.field(
            h, "compressive_strength_candidate", q, "d", status="inferred"
        )
        modulus = r.field(h, "elastic_modulus_candidate", q + 8, "d", status="inferred")
        flag = r.field(h, "flag_raw", q + 16, "I", status="raw")
        density = r.field(
            h, "specific_weight_candidate", q + 20, "d", status="inferred"
        )
        # O prefixo é comum às duas amostras; o restante é preservado como fragmento.
        tail = r.raw(h, "interheader_tail_raw", q + 28, h.next_header_offset)
        return dict(
            **r.identity(h),
            name=name,
            compressive_strength_raw=strength,
            elastic_modulus_raw=modulus,
            specific_weight_raw=density,
            flag_raw=flag,
            tail_raw=tail,
            unit_status="não há unidade explícita decodificada",
        )

    def floor(self, h):
        r = self.r
        p = h.data_offset
        raw = r.field(h, "version_and_three_codes", p, "4I", status="raw")
        name, q = r.text_field(h, "name", p + 16)
        height = r.field(h, "height_candidate", q, "d", status="inferred")
        return dict(**r.identity(h), floor_id=raw[2], name=name, height_raw=height)

    def croqui(self, h):
        r = self.r
        p = h.data_offset
        uid = self.uuid(r.header_at(p + 4, "QiUUID"))
        q = uid["end"]
        vals = r.field(h, "floor_id_list_version_count_capacity", q, "4I")
        r.require(vals[2] <= vals[3], "Contagem do croqui excede a capacidade da lista")
        return dict(
            **r.identity(h),
            floor_id=vals[0],
            uuid=uid["bytes_hex"],
            beam_count=vals[2],
            capacity=vals[3],
        )

    def basic_cad(self, h, version_count):
        r = self.r
        p = h.data_offset
        r.field(h, "serialization_codes_raw", p, f"{version_count}I", status="raw")
        uid = self.uuid(r.header_at(p + 4 * version_count, "QiUUID"))
        q = uid["end"]
        level, q2 = r.ref(h, "drawing_level_reference", q, "TNivel")
        xy = r.field(h, "insertion_xy", q2, "2d")
        # Estes bytes são atributos gráficos; não são apoios estruturais.
        r.raw(h, "cad_attributes_raw", q + 21, q + 38)
        return {
            "uuid": uid["bytes_hex"],
            "drawing_level_id": level.serial_id,
            "xy_raw": xy,
            "common_offset": q,
        }

    def line(self, h):
        def parse(h):
            r = self.r
            common = self.basic_cad(h, 2)
            q = common["common_offset"]
            # O PRJ Bruno usa cinco bytes de atributos nas linhas; os layouts
            # já mapeados usam um ou nove.
            sizes = [
                size
                for size in (1, 5, 9)
                if r.bytes(q + 38 + size + 16, 1) == b"]"
            ]
            r.require(len(sizes) == 1, "Formato da linha não reconhecido ou ambíguo")
            p = q + 38 + sizes[0]
            r.raw(h, "line_attributes_raw", q + 38, p)
            xy2 = r.field(h, "endpoint_xy", p, "2d")
            end = r.close(p + 16)
            return dict(
                **r.identity(h),
                **common,
                xy_i_raw=common["xy_raw"],
                xy_j_raw=xy2,
                end=end,
            )

        return self.cached("line", h, parse)

    def temperature(self, h):
        def parse(h):
            r = self.r
            p = h.data_offset
            if h.class_name == "TVariacaoDeTemperatura":
                vals = r.field(h, "two_values_raw", p + 4, "2d", status="raw")
                end = r.close(p + 20)
                return dict(**r.identity(h), values_raw=vals, end=end)
            if h.class_name == "TRetracao":
                flag = r.field(h, "flag_raw", p + 4, "I", status="raw")
                vals = r.field(h, "four_values_raw", p + 8, "4d", status="raw")
                end = r.close(p + 40)
                return dict(**r.identity(h), flag_raw=flag, values_raw=vals, end=end)
            r.require(
                h.class_name == "TDadosTemperatura", "Classe de temperatura inesperada"
            )
            vals = r.field(h, "list_header_raw", p + 4, "2I", status="raw")
            r.require(vals == [1, 2], "Lista de temperaturas diferente da amostra")
            a = self.temperature(r.header_at(p + 12, "TVariacaoDeTemperatura"))
            c = self.temperature(r.header_at(a["end"], "TVariacaoDeTemperatura"))
            t = self.temperature(r.header_at(c["end"], "TRetracao"))
            end = r.close(t["end"])
            return dict(
                **r.identity(h),
                variation_ids=[a["object_id"], c["object_id"]],
                shrinkage_id=t["object_id"],
                end=end,
            )

        return self.cached("temperature", h, parse)

    def font_end(self, h):
        r = self.r
        p = h.data_offset
        _, q = r.string(p + 4)
        # Após o nome da fonte: cinco bytes; fechamento da fonte e do texto.
        return r.close(q + 5)

    def scalar_map(self, h, p, name):
        r = self.r
        _cfg, q = r.ref(h, name + "_config_reference", p, "ConfigAcoes")
        count = r.field(h, name + "_count", q, "I")
        q += 4
        r.require(count < 1000, "Mapa escalar excessivo")
        entries = []
        for i in range(count):
            key = self.load_key(r.header_at(q, "TIdCarregamento"))
            q = key["end"]
            val = r.field(
                h,
                name + f"_value_{i}",
                q,
                "d",
                status="inferred",
                interpretation="Escalar associado a uma ação; dimensão física depende do contexto.",
            )
            q += 8
            entries.append(
                {
                    "key": key["key"],
                    "value_raw": val,
                    "value_offset": q - 8,
                    "key_object_id": key["object_id"],
                }
            )
        return entries, q

    def wall(self, h):
        def parse(h):
            r = self.r
            common = self.basic_cad(h, 3)
            q = common["common_offset"]
            sizes = [
                size
                for size in (1, 5, 9)
                if (candidate := r.by_offset.get(q + 38 + size + 40)) is not None
                and candidate.class_name == "TextoDoElemento"
            ]
            r.require(
                len(sizes) == 1,
                "Prefixo geométrico da parede não reconhecido ou ambíguo",
            )
            p = q + 38 + sizes[0]
            r.raw(h, "line_attributes_raw", q + 38, p)
            xy2 = r.field(h, "endpoint_xy", p, "2d")
            vals = r.field(
                h,
                "height_thickness_specific_weight_candidates",
                p + 16,
                "3d",
                status="inferred",
            )
            text = r.header_at(p + 40, "TextoDoElemento")
            font = r.after(text, "AtributosFonte", 100)
            endtext = r.close(self.font_end(font))
            r.raw(h, "wall_flags_before_actions", endtext, endtext + 12)
            entries, endmap = self.scalar_map(h, endtext + 12, "wall_action_scalars")
            flags = r.field(h, "wall_tail_u32_raw", endmap, "I", status="raw")
            byte = r.field(h, "wall_tail_u8_raw", endmap + 4, "B", status="raw")
            load_data_id = None
            if byte == 0:
                p = endmap + 5
            elif byte == 2:
                child = r.header_at(endmap + 5, "TDadosCargasPlacasParedes")
                p = self.wall_load_data(child)["end"]
                load_data_id = child.serial_id
            elif byte == 1:
                child, p = r.ref(
                    h,
                    "wall_load_data_reference",
                    endmap + 4,
                    "TDadosCargasPlacasParedes",
                )
                self.wall_load_data(child)
                load_data_id = child.serial_id
            else:
                raise LayoutError("Ponteiro dos dados de parede não reconhecido")
            end = r.close(p)
            return dict(
                **r.identity(h),
                **common,
                xy_i_raw=common["xy_raw"],
                xy_j_raw=xy2,
                length_raw=math.dist(common["xy_raw"], xy2),
                height_raw=vals[0],
                thickness_raw=vals[1],
                specific_weight_raw=vals[2],
                geometric_weight_per_length_candidate_raw=vals[0] * vals[1] * vals[2],
                action_scalars=entries,
                tail_raw=[flags, byte],
                load_data_id=load_data_id,
                load_data_raw=self.wall_load_data(r.by_id[load_data_id])
                if load_data_id is not None
                else None,
                end=end,
                status="geometria decodificada; unidades e semântica dos escalares precisam de confirmação",
            )

        return self.cached("wall", h, parse)

    def wall_load_data(self, h):
        def parse(h):
            r = self.r
            r.field(h, "serialization_codes_raw", h.data_offset, "2I", status="raw")
            key = r.header_at(h.data_offset + 8, "TIdCargasPlacas")
            name, q = r.text_field(key, "name", key.data_offset + 4)
            q = r.close(q)
            raw = r.raw(h, "wall_load_properties_raw", q, q + 92)
            return dict(
                **r.identity(h), name=name, properties_raw=raw, end=r.close(q + 92)
            )

        return self.cached("wall_load_data", h, parse)

    def structural_bar_pointer(self, owner, p, depth=0):
        r = self.r
        r.require(depth < 100, "Árvore de barras excede a profundidade permitida")
        marker = r.bytes(p, 1)[0]
        if marker == 0:
            return p + 1
        if marker == 1:
            # Alguns fluxos usam a forma de referência com ID zero como nulo.
            if r.u32(p + 1) == 0:
                r.field(
                    owner,
                    "processed_bar_null_reference_" + hex(p),
                    p,
                    value={"target_id": 0, "target_class": None},
                    size=5,
                    status="raw",
                )
                return p + 5
            _, end = r.ref(
                owner, "processed_bar_reference_" + hex(p), p, "TBarraEstrutura"
            )
            return end
        r.require(marker == 2, "Ponteiro de barras processadas não reconhecido")
        h = r.header_at(p + 1, "TBarraEstrutura")
        cached = self.cache.get(("structural_bar_end", h.serial_id))
        if cached is not None:
            return cached
        values = r.field(
            h, "processed_bar_list_raw", h.data_offset + 4, "3I", status="raw"
        )
        count = values[1]
        r.require(
            count <= values[2] and count <= 10000,
            "Lista de barras processadas inválida",
        )
        q = h.data_offset + 16
        for index in range(count):
            # A lista de barras processadas pode referenciar barras de laje;
            # esses objetos são apenas evidência e não criam placas no OSA.
            _, q = r.ref(h, f"processed_bar_{index}", q, ("Barra", "BarraLaje"))
        # A árvore de barras processadas é evidência auxiliar e sua quantidade
        # de ramos varia entre fluxos. O fechamento imediato ou a cauda de nove
        # bytes delimita cada nível sem assumir um número fixo.
        for _ in range(10000):
            if r.bytes(q, 1) == b"]":
                self.cache[("structural_bar_end", h.serial_id)] = q + 1
                return q + 1
            if r.bytes(q + 9, 1) == b"]":
                r.raw(h, "processed_bar_tail_raw", q, q + 9)
                end = r.close(q + 9)
                self.cache[("structural_bar_end", h.serial_id)] = end
                return end
            q = self.structural_bar_pointer(h, q, depth + 1)
        raise LayoutError("Árvore de barras excede a quantidade permitida")

    def point(self, h):
        def parse(h):
            r = self.r
            common = self.basic_cad(h, 2)
            q = common["common_offset"]
            reference_at = q + 39
            marker = r.bytes(reference_at, 1)[0]
            target_id = r.u32(reference_at + 1)
            target = r.by_id.get(target_id)
            if marker != 1 or target is None or target.class_name != "No":
                return self._point_with_console_group(h, common, q)
            _, p = r.ref(h, "processed_point_reference", reference_at, "No")
            counts = r.field(h, "point_action_list_raw", p, "2I", status="raw")
            r.require(counts[1] <= 10000, "Lista de dados de ação de nó excessiva")
            p += 8
            actions = []
            for index in range(counts[1]):
                key = self.load_key(r.header_at(p, "TIdCarregamento"))
                load = r.header_at(key["end"], "CargaNo")
                values = r.field(
                    load, "six_components_raw", load.data_offset + 4, "6d", status="raw"
                )
                inner_key = self.load_key(
                    r.header_at(load.data_offset + 52, "TIdCarregamento")
                )
                r.require(
                    key["key"] == inner_key["key"],
                    "Identificadores de ação de nó não conferem",
                )
                p = r.close(inner_key["end"])
                actions.append(
                    {
                        "key": key["key"],
                        "components_raw": values,
                        "object_id": load.serial_id,
                    }
                )
            r.raw(h, "point_attributes_raw", p, p + 10)
            r.require(r.bytes(p + 10, 1) == b"\2", "Dados de nó inline esperados")
            group = r.header_at(p + 11, "TConjuntoElemConsolo")
            p = group.data_offset
            values = r.field(group, "console_list_raw", p + 4, "3I", status="raw")
            count = values[1]
            r.require(
                count <= values[2] and count <= 10000, "Lista de dados de nó inválida"
            )
            p += 16
            for index in range(count):
                r.require(r.bytes(p, 1) == b"\2", "Dado de nó inline esperado")
                item = r.header_at(p + 1, "TElementoConsolo")
                child = r.header_at(item.data_offset + 95, "TElNoDoConsolo")
                r.raw(item, "console_attributes_raw", item.data_offset, child.offset)
                end = self.point_console(child)
                r.field(item, "console_flag_raw", end, "I", status="raw")
                p = r.close(end + 4)
            r.require(r.bytes(p, 1) == b"\2", "Identificador do nó inline esperado")
            p = self.point_console(r.header_at(p + 1, "TElNoDoConsolo"))
            p = r.close(p)
            r.raw(h, "point_tail_raw", p, p + 16)
            end = r.close(p + 16)
            return dict(
                **r.identity(h),
                **common,
                name=f"No{h.occurrence}",
                action_records_raw=actions,
                end=end,
            )

        return self.cached("point", h, parse)

    def _point_with_console_group(self, h, common, q):
        """Lê pontos cuja variante não inclui a referência ao objeto ``No``.

        O grupo embutido de consolos continua fornecendo um limite verificável;
        os campos desconhecidos anteriores ficam preservados como bytes brutos.
        """
        r = self.r
        group = r.after(h, "TConjuntoElemConsolo", 3000)
        marker_at = group.offset - 1
        r.require(
            marker_at >= q + 38 and r.bytes(marker_at, 1) == b"\2",
            "Grupo geométrico do nó intermediário não localizado",
        )
        r.raw(h, "point_fields_before_console_group_raw", q + 38, marker_at)
        group = r.header_at(marker_at + 1, "TConjuntoElemConsolo")
        values = r.field(
            group,
            "console_list_raw",
            group.data_offset + 4,
            "3I",
            status="raw",
        )
        count = values[1]
        r.require(
            count <= values[2] and count <= 10000,
            "Lista de dados de nó inválida",
        )
        p = group.data_offset + 16
        for _ in range(count):
            r.require(r.bytes(p, 1) == b"\2", "Dado de nó inline esperado")
            item = r.header_at(p + 1, "TElementoConsolo")
            child = r.header_at(item.data_offset + 95, "TElNoDoConsolo")
            r.raw(item, "console_attributes_raw", item.data_offset, child.offset)
            end = self.point_console(child)
            r.field(item, "console_flag_raw", end, "I", status="raw")
            p = r.close(end + 4)
        r.require(r.bytes(p, 1) == b"\2", "Identificador do nó inline esperado")
        p = self.point_console(r.header_at(p + 1, "TElNoDoConsolo"))
        p = r.close(p)
        r.raw(h, "point_tail_raw", p, p + 16)
        end = r.close(p + 16)
        return dict(
            **r.identity(h),
            **common,
            name=f"No{h.occurrence}",
            action_records_raw=[],
            end=end,
        )

    def point_console(self, h):
        r = self.r
        r.field(h, "serialization_codes_raw", h.data_offset, "2I", status="raw")
        _, p = r.ref(h, "point_reference", h.data_offset + 8, "ElementoNo")
        return r.close(p)

    def column(self, h):
        def parse(h):
            r = self.r
            common = self.basic_cad(h, 4 if h.class_name == "ElPilarFundacao" else 3)
            q = common["common_offset"]
            _, _ = r.ref(h, "text_level_reference", q + 38, "TNivel")
            r.raw(h, "column_prefix_raw", q + 43, q + 70)
            sectionwrap = r.after(h, "SecaoTransversal", 4000)
            # O nome termina imediatamente antes da seção. Exige candidato único.
            candidates = []
            for s in range(
                max(h.data_offset, sectionwrap.offset - 100), sectionwrap.offset - 4
            ):
                n = r.u32(s)
                if 0 < n <= 64 and s + 4 + n == sectionwrap.offset:
                    try:
                        name, _ = r.string(s)
                    except LayoutError:
                        continue
                    if all(c.isprintable() for c in name):
                        candidates.append((s, name))
            r.require(len(candidates) == 1, "Nome do pilar ambíguo")
            name, _ = r.text_field(h, "name", candidates[0][0])
            section = self.section(
                r.header_at(sectionwrap.data_offset + 5, "TSecaoMista")
            )
            r.close(section["end"])
            rotation = r.field(
                h,
                "rotation_candidate_rad",
                section["end"] + 1,
                "d",
                status="inferred",
                unit="rad",
            )
            text = r.header_at(section["end"] + 9, "TextoDoElemento")
            font = r.after(text, "AtributosFonte", 100)
            endtext = r.close(self.font_end(font))
            temp_h = r.after(font, "TDadosTemperatura", 1000)
            r.raw(h, "column_fields_before_temperature_raw", endtext, temp_h.offset)
            temp = self.temperature(temp_h)
            foundation = None
            if h.class_name == "ElementoPilar":
                ends = [
                    p
                    for size in (25, 29)
                    if r.bytes(p := temp["end"] + size, 1) == b"]"
                ]
                r.require(len(ends) == 1, "Cauda do pilar não reconhecida ou ambígua")
                r.raw(h, "column_fields_after_temperature_raw", temp["end"], ends[0])
                end = r.close(ends[0])
            elif r.version in (3075, 3219):
                # O fechamento completo pode conter um bloco inline ou nulo;
                # a altura da barra tem seu próprio perfil verificável.
                start_fields = len(r.fields)
                end = None
                try:
                    foundation = self.foundation_bar_block(h, temp_h, temp["end"], endtext)
                except (LayoutError, struct.error):
                    del r.fields[start_fields:]
                    foundation = {"kind": "unmapped_foundation_geometry"}
                    if r.version == 3075:
                        try:
                            foundation = self.pad_footing(h, temp_h, temp["end"])
                            end = foundation["end"]
                        except (LayoutError, struct.error):
                            del r.fields[start_fields:]
            else:
                foundation = self.pad_footing(h, temp_h, temp["end"])
                end = foundation["end"]
            dims = section["geometric_values_raw"]
            return dict(
                **r.identity(h),
                **common,
                name=name,
                section_id=section["object_id"],
                rectangular_dimensions_candidate_raw=[dims[0], dims[5]],
                rotation_candidate_rad=rotation,
                temperature_id=temp_h.serial_id,
                foundation_raw=foundation,
                end=end,
            )

        return self.cached("column", h, parse)

    def foundation_bar_block(self, h, temp_h, temp_end, after_text):
        """Perfil de pilar sobre bloco observado nos códigos 3075 e 3219."""
        r = self.r
        q = temp_end + 25
        r.require(r.u32(q) == 0 and r.u32(q + 4) == 0, "Perfil de bloco não reconhecido")
        height = r.field(
            h, "foundation_bar_height", q + 8, "d", status="inferred",
            interpretation="Altura da barra de fundação; igual aos valores de TDadosGravPilar quando presentes.",
            unit="source_length",
        )
        r.require(height >= sys.float_info.min, "Altura da barra de fundação inválida")
        soil = r.after(temp_h, "TCamadaSolo", 1000)
        r.require(soil.offset - temp_end in (193, 197), "Posição do solo incompatível com o bloco")
        marker_at = r.close(soil.data_offset + 36)
        marker = r.bytes(marker_at, 1)
        gravity = None
        if marker == b"\2":
            gravity = r.header_at(marker_at + 1, "TDadosGravBloco")
        elif marker == b"\1":
            gravity, _ = r.ref(h, "foundation_block_reference", marker_at, "TDadosGravBloco")
        else:
            r.require(marker == b"\0", "Ponteiro dos dados de bloco não reconhecido")
        pillars = r.between(after_text, temp_h.offset, "TDadosGravPilar")
        r.require(len(pillars) <= 1, "Dados de pilar de fundação ambíguos")
        if pillars:
            values = r.unpack("2d", pillars[0].data_offset + 40)
            r.require(
                all(math.isclose(value, height, rel_tol=1e-9, abs_tol=1e-8) for value in values),
                "Altura da barra diverge dos dados do pilar de fundação",
            )
        return {
            "kind": "pile_cap",
            "bar_height_raw": height,
            "height_reference": "floor_to_foundation_bar_bottom",
            "support_mapping": "pending",
            "soil_object_id": soil.serial_id,
            "gravity_object_id": gravity.serial_id if gravity else None,
            "column_gravity_object_id": pillars[0].serial_id if pillars else None,
            "height_corroboration": "column_gravity" if pillars else "shared_layout",
        }

    def pad_footing(self, h, temp_h, temp_end):
        """Dois prefixos observados; o bloco opcional de sapata tem tamanho conferido.

        O código 1 foi observado nos registros de sapata mapeados. Outros tipos
        de fundação exigem calibração própria.
        """
        r = self.r
        candidates = []
        for prefix_size in (25, 29):
            q = temp_end + prefix_size
            (code,) = r.unpack("I", q)
            (depth,) = r.unpack("d", q + 4)
            if (
                code == 1
                and math.isfinite(depth)
                # A leitura desalinhada do outro prefixo gera um subnormal.
                # Nenhum código de apoio é usado para escolher o layout.
                and depth >= sys.float_info.min
            ):
                candidates.append((q, prefix_size))
        r.require(
            len(candidates) == 1,
            "Perfil de sapata/profundidade não reconhecido; blocos e outros tipos ainda não foram mapeados",
        )
        q, prefix_size = candidates[0]
        r.raw(h, "column_fields_after_temperature_raw", temp_end, q)
        foundation = {
            "kind": "pad_footing",
            "layout_prefix_size": prefix_size,
            "code_raw": r.field(h, "foundation_code_raw", q, "I", status="raw"),
            "settlement_depth_raw": r.field(
                h,
                "settlement_depth",
                q + 4,
                "d",
                status="inferred",
                interpretation="Distância do topo do baldrame ao assentamento da sapata, conforme definição do projeto.",
            ),
            "depth_reference": "baldrame_top_to_footing_bottom",
            "switch_raw": r.field(
                h, "foundation_switch_raw", q + 12, "I", status="raw"
            ),
            "six_flags_raw": r.field(
                h, "foundation_six_flags_raw", q + 16, "6I", status="raw"
            ),
            "six_values_raw": r.field(
                h, "foundation_six_values_raw", q + 40, "6d", status="raw"
            ),
            "support_mapping": "pending",
        }
        # Chave de evidência mantida para consumidores da primeira integração.
        foundation["value_raw"] = foundation["settlement_depth_raw"]
        soil = r.after(temp_h, "TCamadaSolo", 2000)
        r.raw(h, "foundation_before_soil_raw", q + 88, soil.offset)
        r.field(soil, "four_soil_values_raw", soil.data_offset + 4, "4d", status="raw")
        p = r.close(soil.data_offset + 36)
        marker = r.bytes(p, 1)
        gravity = None
        if marker == b"\0":
            p += 1
        elif marker == b"\2":
            gravity = r.header_at(p + 1, "TDadosGravSapata")
            p = self.footing_gravity(gravity)["end"]
        elif marker == b"\1":
            gravity, p = r.ref(h, "footing_gravity_reference", p, "TDadosGravSapata")
            self.footing_gravity(gravity)
        else:
            raise LayoutError("Ponteiro dos dados de sapata não reconhecido")
        r.raw(h, "foundation_after_soil_raw", p, p + 103)
        end = p + 103
        foundation_uuid = None
        # No layout 3575 observado na Casa Térrea, o pilar de fundação traz
        # um QiUUID adicional depois desse trecho e mais 16 bytes opacos antes
        # do fechamento. Layouts anteriores fecham diretamente em p + 103.
        if (candidate := r.by_offset.get(end)) is not None:
            r.require(
                candidate.class_name == "QiUUID",
                "Extensão após os dados de sapata não reconhecida",
            )
            foundation_uuid = self.uuid(candidate)
            r.raw(
                h,
                "foundation_after_uuid_raw",
                foundation_uuid["end"],
                foundation_uuid["end"] + 16,
            )
            end = foundation_uuid["end"] + 16
        foundation.update(
            soil_object_id=soil.serial_id,
            gravity_object_id=gravity.serial_id if gravity else None,
            foundation_uuid_object_id=(
                foundation_uuid["object_id"] if foundation_uuid else None
            ),
            end=r.close(end),
        )
        return foundation

    def footing_gravity(self, h):
        def parse(h):
            r = self.r
            p = h.data_offset
            r.field(h, "serialization_codes_raw", p, "3I", status="raw")
            r.raw(h, "footing_design_data_raw", p + 12, p + 148)
            return dict(**r.identity(h), end=r.close(p + 148))

        return self.cached("footing_gravity", h, parse)

    def element_pointer(
        self, owner, p, allowed, *, trailing_codes=0, trailing_allowed=()
    ):
        r = self.r
        marker = r.bytes(p, 1)[0]
        if marker == 1:
            h, end = r.ref(owner, "element_reference_" + hex(p), p, allowed)
            return h, end
        r.require(
            marker == 2,
            f"Ponteiro de elemento não reconhecido em {p:#x} (marcador {marker})",
        )
        h = r.header_at(p + 1)
        r.require(h.class_name in allowed, "Classe do ponteiro não permitida")
        value = self.anchor(h) if h.class_name != "Parede" else self.wall(h)
        end = value.get("end")
        if end is None and h.class_name == "ElPilarFundacao":
            end = self.inline_foundation_anchor_end(
                h, allowed, trailing_codes, trailing_allowed, owner=owner
            )
        r.require(
            end is not None,
            f"Fim do elemento inline {h.class_name} não reconhecido "
            f"(ponteiro {p:#x}, objeto {h.offset:#x})",
        )
        r.field(
            owner,
            "inline_element_" + hex(p),
            p,
            value={"target_id": h.serial_id, "target_class": h.class_name},
            size=1,
        )
        return h, end

    def inline_foundation_anchor_end(
        self, h, allowed, trailing_codes=0, trailing_allowed=(), *, owner=None
    ):
        """Delimita a fundação inline pelo ponteiro de apoio que vem em seguida.

        No código 3219, o bloco contém objetos inline além dos dados de
        fundação. O fechamento do objeto é seguido por nove bytes de cauda;
        o contexto da viga valida o ponteiro seguinte, ou os quatro códigos
        antes do ponteiro de parede no segundo apoio.
        """
        r = self.r
        if r.version == 3075 and trailing_codes and owner is not None:
            return self.foundation_tail_3075(owner, h)
        limit = min(len(r.data), h.offset + 200_000)
        candidates = []
        if trailing_codes:
            config_ids = {item.serial_id for item in r.classes.get("ConfigAcoes", ())}
            for pointer in range(h.offset, limit - 9):
                if r.bytes(pointer, 1) != b"\1":
                    continue
                if r.u32(pointer + 1) not in config_ids:
                    continue
                count = r.u32(pointer + 5)
                if count >= 1000 or r.bytes(pointer - 1, 1) != b"\0":
                    continue
                # A parede é nula nesta cauda: quatro códigos, um byte nulo
                # para parede e, em seguida, o mapa escalar da viga.
                candidates.append(pointer - 17)
            r.require(
                candidates,
                "Cauda do apoio inline antes do mapa escalar não reconhecida",
            )
            return candidates[0]
        for close in range(h.offset, limit - 10):
            if r.bytes(close, 1) != b"]":
                continue
            end = close + 10
            pointer = end
            marker = r.bytes(pointer, 1)[0]
            valid = marker == 0 and bool(trailing_allowed)
            if marker == 1:
                ident = r.u32(pointer + 1)
                target = r.by_id.get(ident)
                valid = target is not None and target.class_name in allowed
            elif marker == 2:
                target = r.by_offset.get(pointer + 1)
                valid = target is not None and target.class_name in allowed
            if valid:
                candidates.append(end)
        r.require(
            candidates,
            "Fechamento do pilar de fundação inline não reconhecido",
        )
        # O primeiro ponteiro válido pertence ao mesmo registro; candidatos
        # posteriores já podem ser apoios de outras vigas do fluxo.
        return candidates[0]

    def foundation_tail_3075(self, owner, foundation):
        """Delimita o segundo apoio usando a parede e as excentricidades nativas."""
        r = self.r
        limit = min(len(r.data), foundation.offset + 200_000)
        following = [
            item.offset for item in r.between(foundation.offset + 1, limit)
            if item.class_name in ("ElementoTrecho", "ElementoViga")
        ]
        if following:
            limit = min(limit, following[0])
        fmt = r.after(owner, "FormatoElementoBarraReta", 200)
        line = self.line(r.header_at(fmt.data_offset + 9, "EL_Linha"))
        column = self.column(foundation)
        expected = [
            line["xy_j_raw"][axis] - column["xy_raw"][axis]
            for axis in range(2)
        ]

        def closed_before(end):
            return any(
                end - size >= foundation.offset and r.bytes(end - size, 1) == b"]"
                for size in (1, 10)
            )

        def matches(end, map_pos):
            try:
                if not closed_before(end) or r.bytes(map_pos, 1) != b"\1":
                    return False
                config = r.by_id.get(r.u32(map_pos + 1))
                if config is None or config.class_name != "ConfigAcoes":
                    return False
                count = r.u32(map_pos + 5)
                if count >= 1000:
                    return False
                q = map_pos + 9
                for _ in range(count):
                    key = r.header_at(q, "TIdCarregamento")
                    q = r.close(key.data_offset + 12) + 8
                offsets = r.unpack("4d", q + 8)
                if not all(
                    math.isfinite(value) and math.isclose(value, target, abs_tol=1e-8)
                    for value, target in zip(offsets[2:], expected)
                ):
                    return False
                return any(
                    (text := r.by_offset.get(q + 40 + size)) is not None
                    and text.class_name == "TextoDoElemento"
                    for size in (10, 29, 44)
                )
            except (LayoutError, struct.error, OverflowError):
                return False

        candidates = []
        pointer = r.data.find(b"\1", foundation.offset, limit)
        while pointer >= 0 and pointer + 5 <= limit:
            target = r.by_id.get(r.u32(pointer + 1))
            if target is not None and target.class_name == "ConfigAcoes":
                end = pointer - 17
                if end >= foundation.offset and r.bytes(pointer - 1, 1) == b"\0":
                    candidates.append((end, pointer))
            elif target is not None and target.class_name == "Parede":
                end = pointer - 16
                if end >= foundation.offset:
                    candidates.append((end, pointer + 5))
            pointer = r.data.find(b"\1", pointer + 1, limit)
        for wall in r.between(foundation.offset, limit, "Parede"):
            end = wall.offset - 17
            if end < foundation.offset or r.bytes(wall.offset - 1, 1) != b"\2":
                continue
            if not closed_before(end):
                continue
            try:
                candidates.append((end, self.wall(wall)["end"]))
            except (LayoutError, struct.error, OverflowError):
                continue
        valid = sorted({end for end, map_pos in candidates if matches(end, map_pos)})
        r.require(len(valid) == 1, "Cauda de fundação 3075 não reconhecida ou ambígua")
        return valid[0]

    def anchor(self, h):
        return self.point(h) if h.class_name == "ElementoNo" else self.column(h)

    def endpoint(self, h):
        r = self.r
        p = h.data_offset
        vals = r.field(h, "four_codes_raw", p + 4, "4I", status="raw")
        flag = r.field(h, "flag_raw", p + 20, "B", status="raw")
        end = r.close(p + 21)
        return dict(**r.identity(h), codes_raw=vals, flag_raw=flag, end=end)

    def grav_endpoint(self, h):
        r = self.r
        p = h.data_offset
        r.field(h, "serialization_codes_raw", p, "3I", status="raw")
        vals = r.field(h, "five_values_raw", p + 12, "5d", status="raw")
        end = r.close(p + 52)
        return dict(**r.identity(h), values_raw=vals, end=end)

    def beam_material_data(self, owner, pointer):
        """Lê a seleção de material retangular presente em alguns trechos 3075."""
        r = self.r
        r.require(r.bytes(pointer, 1) == b"\2", "Dados de material inline esperados")
        material_data = r.header_at(pointer + 1, "TDadosMateriais")
        r.field(material_data, "serialization_code_raw", material_data.data_offset, "I", status="raw")
        q = material_data.data_offset + 4
        entries = {}
        for name in (
            "TMaterialGenerico", "TClasseMaterialGenerico", "TFamiliaMaterial",
            "TGrupoSecao", "TSecaoRetangular",
        ):
            marker = r.bytes(q, 1)
            if marker == b"\1":
                item, q = r.ref(material_data, "material_" + name, q, name)
            elif marker == b"\2":
                item = r.header_at(q + 1, name)
                if name in ("TMaterialGenerico", "TClasseMaterialGenerico"):
                    _, end_text = r.string(item.data_offset + 8)
                    q = r.close(end_text + 32)
                elif name in ("TFamiliaMaterial", "TGrupoSecao"):
                    _, end_text = r.string(item.data_offset + 4)
                    q = r.close(end_text + (4 if name == "TFamiliaMaterial" else 8))
                else:
                    # A seção inline contém um polígono com vértices. A sua
                    # geometria já foi lida em TSecaoMista; os fechamentos da
                    # seção, do material e do trecho delimitam a região opaca.
                    limit = min(len(r.data), item.offset + 200_000)
                    next_objects = [
                        x.offset for x in r.between(item.offset + 1, limit)
                        if x.class_name in ("ElementoTrecho", "ElementoViga", "Viga")
                    ]
                    if next_objects:
                        limit = min(limit, next_objects[0])
                    candidates = []
                    pos = r.data.find(b"]]", item.data_offset, limit)
                    while pos >= 0:
                        tail = pos + 2
                        if (
                            r.bytes(tail, 8) == b"\0" * 8
                            and r.u32(tail + 8) == 1
                            and r.bytes(tail + 12, 1) == b"]"
                        ):
                            candidates.append(pos)
                        pos = r.data.find(b"]]", pos + 1, limit)
                    r.require(len(candidates) == 1, "Seção de material inline não reconhecida ou ambígua")
                    r.raw(item, "inline_section_raw", item.data_offset, candidates[0])
                    q = r.close(candidates[0])
            else:
                raise LayoutError(f"Ponteiro de {name} não reconhecido em {q:#x}")
            entries[name] = item
        end = r.close(q)
        generic = entries["TMaterialGenerico"]
        category = entries["TClasseMaterialGenerico"]
        material_name, _ = r.text_field(generic, "material_name", generic.data_offset + 8)
        class_name, values_at = r.text_field(category, "material_class_name", category.data_offset + 8)
        values = r.field(category, "material_class_values_raw", values_at, "4d", status="raw")
        return {
            "type": material_name,
            "class_name": class_name,
            "class_values_raw": values,
            "object_id": material_data.serial_id,
            "section_object_id": entries["TSecaoRetangular"].serial_id,
        }, end

    def beam(self, h):
        r = self.r
        p = h.data_offset
        name, q = r.text_field(h, "name", p + 4)
        lst = r.field(h, "segment_list_version_count_capacity", q, "3I")
        q += 12
        r.require(
            1 <= lst[1] <= lst[2] and lst[1] <= 10000,
            "Lista de trechos da viga inválida",
        )
        segments = []
        null_slots = 0
        for index in range(lst[1]):
            marker = r.bytes(q, 1)
            if marker == b"\2":
                seg = r.header_at(q + 1, "ElementoTrecho")
                value = self.beam_segment(seg)
                q = value["end"]
            elif marker == b"\1":
                if r.u32(q + 1) == 0:
                    r.require(
                        index == lst[1] - 1,
                        "Ponteiro nulo antes do fim da lista de trechos da viga",
                    )
                    r.field(
                        h,
                        f"segment_{index}_null_reference_raw",
                        q,
                        value={"target_id": 0},
                        size=5,
                        status="raw",
                    )
                    null_slots += 1
                    q += 5
                    break
                seg, q = r.ref(h, f"segment_{index}", q, "ElementoTrecho")
                value = self.beam_segment(seg)
            else:
                raise LayoutError("Ponteiro de trecho da viga não reconhecido")
            segments.append(value)
        group = dict(
            **r.identity(h),
            name=name,
            segments=segments,
            segment_count=len(segments),
            declared_segment_count=lst[1],
            null_segment_slots=null_slots,
            launch_end=q,
            object_end_known=False,
        )
        # Dados Viga/TDadosGravViga posteriores são resultados/configurações de
        # dimensionamento. Não delimitam nem alteram o lançamento transcrito.
        if len(segments) == 1:
            group.update(
                {
                    k: v
                    for k, v in segments[0].items()
                    if k
                    not in ("object_id", "class_name", "offset", "offset_hex", "end")
                }
            )
        return group

    def beam_segment(self, seg):
        return self.cached("beam_segment", seg, self._beam_segment)

    def _beam_segment(self, seg):
        r = self.r
        common = self.basic_cad(seg, 3)
        fmt = r.after(seg, "FormatoElementoBarraReta", 200)
        r.require(r.bytes(fmt.data_offset + 8, 1) == b"\2", "Linha inline esperada")
        ln = self.line(r.header_at(fmt.data_offset + 9, "EL_Linha"))
        q = r.close(ln["end"])  # FormatoElementoBarraReta
        q = self.structural_bar_pointer(seg, q)
        r.field(seg, "before_supports_code_raw", q, "I", status="raw")
        q += 4
        anchors = ("ElementoPilar", "ElPilarFundacao", "ElementoNo")
        a, q = self.element_pointer(seg, q, anchors)
        c, q = self.element_pointer(
            seg, q, anchors, trailing_codes=4, trailing_allowed=("Parede",)
        )
        r.field(seg, "codes_before_wall_pointer_raw", q, "4I", status="raw")
        q += 16
        walls = []
        # Quatro códigos de significado desconhecido; depois ponteiro nulo ou parede.
        if r.bytes(q, 1) == b"\0":
            r.field(seg, "wall_pointer_null", q, "B")
            q += 1
        else:
            w, q = self.element_pointer(seg, q, ("Parede",))
            walls.append(w.serial_id)
        scalars, q = self.scalar_map(seg, q, "beam_action_scalars")
        r.field(seg, "pre_offsets_double_raw", q, "d", status="raw")
        q += 8
        offset_values = r.field(
            seg,
            "end_offsets_xy_candidate_raw"
            if r.version == 3219
            else "end_offsets_xy",
            q,
            "4d",
            status="raw" if r.version == 3219 else "inferred",
            interpretation=(
                "Bytes da variante 3219; não usados porque não coincidem com a geometria."
                if r.version == 3219
                else "Conferido por posição de extremidade menos ponto de inserção do pilar."
            ),
        )
        q += 32
        sizes = [
            size
            for size in (10, 29, 44)
            if (candidate := r.by_offset.get(q + size)) is not None
            and candidate.class_name == "TextoDoElemento"
        ]
        r.require(
            len(sizes) == 1,
            f"Campos do trecho após excentricidades não reconhecidos em {q:#x}",
        )
        r.raw(seg, "after_offsets_raw", q, q + sizes[0])
        q += sizes[0]
        text = r.header_at(q, "TextoDoElemento")
        font = r.after(text, "AtributosFonte", 100)
        q = r.close(self.font_end(font))
        r.require(r.bytes(q, 1) == b"\2", "FormatoTrecho inline esperado")
        fmt2 = r.header_at(q + 1, "FormatoElementoTrechoReto")
        q = r.close(fmt2.data_offset + 8)
        sectionwrap = r.header_at(q, "SecaoTransversal")
        section = self.section(r.header_at(sectionwrap.data_offset + 5, "TSecaoMista"))
        q = r.close(section["end"])
        r.raw(seg, "section_to_endpoints_raw", q, q + 52)
        end_pair = r.field(
            seg,
            "end_parameter_pair_raw",
            q + 24,
            "2d",
            status="raw",
            interpretation="Par próximo aos dados de extremidade; varia entre 0 e 0,15 nesta amostra. Não equivale ainda a uma liberação mapeada.",
        )
        section_codes = r.field(
            seg, "post_section_two_codes_raw", q, "2I", status="raw"
        )
        q += 52
        r.require(r.bytes(q, 1) == b"\2", "Primeira extremidade inline esperada")
        ei = self.endpoint(r.header_at(q + 1, "TExtremidadeTrecho"))
        q = ei["end"]
        r.require(r.bytes(q, 1) == b"\2", "Segunda extremidade inline esperada")
        ej = self.endpoint(r.header_at(q + 1, "TExtremidadeTrecho"))
        q = ej["end"]
        r.raw(seg, "endpoints_to_temperature_raw", q, q + 50)
        q += 50
        temp_h = r.header_at(q, "TDadosTemperatura")
        temp = self.temperature(temp_h)
        q = temp["end"]
        material = None
        if r.bytes(q, 1) == b"\2" and (child := r.by_offset.get(q + 1)) is not None and child.class_name == "TDadosMateriais":
            material, q = self.beam_material_data(seg, q)
            r.require(
                r.bytes(q, 8) == b"\0" * 8 and r.u32(q + 8) == 1,
                "Cauda do trecho com material individual não reconhecida",
            )
        sizes = [size for size in ((12,) if material else (9, 13)) if r.bytes(q + size, 1) == b"]"]
        r.require(len(sizes) == 1, "Fechamento do trecho não reconhecido ou ambíguo")
        r.raw(seg, "temperature_to_segment_end_raw", q, q + sizes[0])
        end = r.close(q + sizes[0])
        dims = section["geometric_values_raw"]
        ca = self.anchor(a)
        cc = self.anchor(c)
        expected = [ln["xy_i_raw"][i] - ca["xy_raw"][i] for i in range(2)] + [
            ln["xy_j_raw"][i] - cc["xy_raw"][i] for i in range(2)
        ]
        if r.version == 3219:
            # Não há excentricidades nativas confirmadas neste layout. A
            # diferença de coordenadas é calculada, não uma segunda leitura
            # independente que possa validar a própria geometria.
            offsets = expected
            ok = None
            r.checks.append(
                {"check": "beam_end_offsets_derived_from_coordinates",
                 "object_id": seg.serial_id, "status": "derived"}
            )
        else:
            offsets = offset_values
            ok = all(
                math.isclose(x, y, abs_tol=1e-8)
                for x, y in zip(offsets, expected)
            )
            r.require(
                ok,
                "Excentricidades não conferem com a geometria e referências "
                f"(segmento {seg.serial_id}, apoios {a.serial_id}/{c.serial_id}, "
                f"lidas {offsets}, esperadas {expected})",
            )
            r.checks.append(
                {"check": "beam_end_offsets_match_coordinates",
                 "object_id": seg.serial_id, "passed": True}
            )
        return dict(
            **r.identity(seg),
            segment_id=seg.serial_id,
            uuid=common["uuid"],
            line_id=ln["object_id"],
            xy_i_raw=ln["xy_i_raw"],
            xy_j_raw=ln["xy_j_raw"],
            clear_length_raw=math.dist(ln["xy_i_raw"], ln["xy_j_raw"]),
            support_i_id=a.serial_id,
            support_j_id=c.serial_id,
            support_i_name=ca["name"],
            support_j_name=cc["name"],
            support_insertion_distance_raw=math.dist(ca["xy_raw"], cc["xy_raw"]),
            section_id=section["object_id"],
            rectangular_dimensions_candidate_raw=dims[4:6],
            end_offsets_xy_raw=offsets,
            offsets_geometry_check=ok,
            offsets_source="derived_from_coordinates" if r.version == 3219 else "native",
            endpoint_records=[ei, ej],
            end_parameter_pair_raw=end_pair,
            post_section_codes_raw=section_codes,
            wall_ids=walls,
            action_scalars=scalars,
            temperature_id=temp_h.serial_id,
            material_override=material,
            end=end,
        )


def extract(reader):
    r = reader
    d = Decoder(r)
    native_launch = any(
        r.classes.get(name)
        for name in (
            "CroquiPavimento",
            "ElementoViga",
            "ElementoPilar",
            "ElPilarFundacao",
        )
    )
    out = {
        "source": r.source,
        "internal_version_code": r.version,
        "launch_layout": "prj-native-launch-v1",
        "native_launch_profile_attempted": native_launch,
    }

    def allof(name, fn):
        return [v for h in r.classes.get(name, []) if (v := r.run(h, fn)) is not None]

    # Nomes/UUIDs e coeficientes são dados de arquivo, não defaults inventados.
    out["uuids"] = allof("QiUUID", d.uuid)
    out["load_keys"] = allof("TIdCarregamento", d.load_key)
    out["actions"] = allof("AcaoPermanente", d.action) + allof(
        "AcaoAcidental", d.action
    )
    out["action_groups"] = []
    for h in r.classes.get("GrupoAcoes", []):

        def group(h):
            name, _q = r.text_field(h, "name", h.data_offset + 4)
            return dict(**r.identity(h), name=name)

        value = r.run(h, group)
        if value:
            out["action_groups"].append(value)
    for action in out["actions"]:
        groups = [g for g in out["action_groups"] if g["offset"] < action["offset"]]
        configs = [
            h for h in r.classes.get("ConfigAcoes", []) if h.offset < action["offset"]
        ]
        action["group_by_region"] = groups[-1]["name"] if groups else None
        action["config_object_id_by_region"] = (
            configs[-1].serial_id if configs else None
        )
    action_names = {tuple(a["key"]): a["symbol"] for a in out["actions"]}
    out["combinations"] = allof("Combinacao", d.combination)
    for comb in out["combinations"]:
        for t in comb["terms"]:
            t["symbol"] = action_names.get(tuple(t["key"]))
    out["concretes"] = allof("ClasseConcreto", d.concrete)
    out["sections"] = allof("TSecaoMista", d.section)
    out["floors"] = allof("Pavimento", d.floor)
    out["active_action_keys"] = []
    for h in r.classes.get("TCarregamentosAtivos", []):

        def active(h):
            p = h.data_offset
            n = r.field(h, "count", p + 4, "I")
            q = p + 8
            keys = []
            r.require(n <= 1000, "Lista de ações excessiva")
            for _ in range(n):
                k = d.load_key(r.header_at(q, "TIdCarregamento"))
                keys.append(k["key"])
                q = k["end"]
                # Há um flag/índice de 4 bytes depois de cada chave.
                r.field(h, "entry_raw_" + str(len(keys)), q, "I", status="raw")
                q += 4
            r.close(q)
            return keys

        keys = r.run(h, active)
        if keys is not None:
            out["active_action_keys"].extend(keys)
    out["drawing_levels"] = []
    for h in r.classes.get("TNivel", []):

        def level(h):
            name, _q = r.text_field(h, "name", h.data_offset + 4)
            return dict(**r.identity(h), name=name)

        v = r.run(h, level)
        if v:
            out["drawing_levels"].append(v)
    out["croquis"] = []
    out["columns"] = []
    out["points"] = []
    out["beams"] = []
    out["beam_groups"] = []
    out["walls"] = []
    out["temperature_records"] = []
    out["floor_material_settings"] = []
    if native_launch:
        out["croquis"] = allof("CroquiPavimento", d.croqui)
        out["columns"] = allof("ElPilarFundacao", d.column) + allof(
            "ElementoPilar", d.column
        )
        out["walls"] = allof("Parede", d.wall)
        out["points"] = allof("ElementoNo", d.point)
        beam_groups = allof("ElementoViga", d.beam)
        for beam in beam_groups:
            summary = {
                key: beam[key]
                for key in (
                    "object_id",
                    "class_name",
                    "offset",
                    "offset_hex",
                    "name",
                    "segment_count",
                    "declared_segment_count",
                    "null_segment_slots",
                    "launch_end",
                    "object_end_known",
                )
            }
            summary["segment_ids"] = [
                segment["object_id"] for segment in beam["segments"]
            ]
            out["beam_groups"].append(summary)
            for index, segment in enumerate(beam["segments"], 1):
                out["beams"].append(
                    {
                        **segment,
                        "beam_object_id": beam["object_id"],
                        "beam_name": beam["name"],
                        "name": beam["name"]
                        if beam["segment_count"] == 1
                        else f"{beam['name']}_T{index}",
                        "segment_index": index,
                        "segment_count": beam["segment_count"],
                    }
                )
        for name in ("TDadosTemperatura", "TVariacaoDeTemperatura", "TRetracao"):
            out["temperature_records"].extend(allof(name, d.temperature))
        floors_by_id = {x["floor_id"]: x for x in out["floors"]}
        for ix, c in enumerate(out["croquis"]):
            end = (
                out["croquis"][ix + 1]["offset"]
                if ix + 1 < len(out["croquis"])
                else min(
                    [f["offset"] for f in out["floors"] if f["offset"] > c["offset"]],
                    default=len(r.data),
                )
            )
            base = r.between(c["offset"], end, "TBaseCroqui")
            c["region_end"] = end
            c["base_cad_offset"] = base[0].offset if base else end
            c["floor_name"] = floors_by_id.get(c["floor_id"], {}).get("name")
            for group in ("columns", "points", "beams", "beam_groups", "walls"):
                for v in out[group]:
                    if c["offset"] <= v["offset"] < end:
                        v["floor_id"] = c["floor_id"]
                        v["floor_name"] = c["floor_name"]
                        v["region_role"] = (
                            "base_cad"
                            if v["offset"] >= c["base_cad_offset"]
                            else "beam_list_and_referenced_elements"
                        )
        levels = {v["object_id"]: v["name"] for v in out["drawing_levels"]}
        wall_owner = {
            wid: v["object_id"] for v in out["beams"] for wid in v["wall_ids"]
        }
        referenced = {
            v[k] for v in out["beams"] for k in ("support_i_id", "support_j_id")
        }
        for col in out["columns"]:
            col["referenced_by_beam"] = col["object_id"] in referenced
            col["drawing_level"] = levels.get(col["drawing_level_id"])
        for point in out["points"]:
            point["referenced_by_beam"] = point["object_id"] in referenced
            point["drawing_level"] = levels.get(point["drawing_level_id"])
        for wall in out["walls"]:
            wall["beam_owner_id"] = wall_owner.get(wall["object_id"])
            wall["drawing_level"] = levels.get(wall["drawing_level_id"])
        for name in (
            "CfgPavPilar",
            "CfgPavViga",
            "CfgPavLaje",
            "CfgPavSapata",
            "CfgPavBloco",
        ):
            for h in r.classes.get(name, []):

                def mat(h):
                    name, _q = r.text_field(h, "material_name", h.data_offset + 8)
                    return dict(**r.identity(h), material_name=name)

                v = r.run(h, mat)
                if v:
                    previous = [f for f in out["floors"] if f["offset"] < h.offset]
                    # Só as primeiras configurações junto ao cabeçalho do pavimento
                    # recebem associação; configurações tardias podem ser defaults.
                    f = previous[-1] if previous else None
                    v["floor_id"] = (
                        f["floor_id"] if f and h.offset - f["offset"] < 1600 else None
                    )
                    v["association"] = (
                        "adjacent_floor_settings"
                        if v["floor_id"]
                        else "unassigned_configuration"
                    )
                    out["floor_material_settings"].append(v)
        for f in out["floors"]:
            f["material_defaults"] = {
                x["class_name"]: x["material_name"]
                for x in out["floor_material_settings"]
                if x["floor_id"] == f["floor_id"]
            }
    out["slabs"] = collect_slabs(r, d, out["croquis"])
    out["file_prefix_hex"] = (
        r.data[: r.headers[0].offset].hex() if r.headers else r.data.hex()
    )
    out["checks"] = r.checks
    out["decode_errors"] = r.errors
    counts = collections.Counter(h.class_name for h in r.headers)
    fields_per_class = collections.Counter(f["class_name"] for f in r.fields)
    out["inventory"] = [
        {
            "class_name": name,
            "count": n,
            "first_offset": r.classes[name][0].offset,
            "field_records": fields_per_class[name],
            "interpretation_status": "partial_fields"
            if fields_per_class[name]
            else "signature_only",
        }
        for name, n in sorted(counts.items())
    ]
    out["summary"] = {
        "header_count": len(r.headers),
        "class_count": len(counts),
        "floor_count": len(out["floors"]),
        "beam_headers": counts.get("ElementoViga", 0),
        "beam_records": len(out["beams"]),
        "beam_groups": len(out["beam_groups"]),
        "point_records": len(out["points"]),
        "column_records": len(out["columns"]),
        "columns_referenced_by_beams": sum(
            c.get("referenced_by_beam", False) for c in out["columns"]
        ),
        "wall_records": len(out["walls"]),
        "action_records": len(out["actions"]),
        "combination_records": len(out["combinations"]),
        "concrete_records": len(out["concretes"]),
        "section_records": len(out["sections"]),
        "slab_records_preserved": len(out["slabs"]),
        "analytical_node_headers": counts.get("No", 0),
        "analytical_bar_headers": counts.get("Barra", 0),
        "decode_errors": len(r.errors),
    }
    out["status"] = "partial_mapping_not_solver_ready"
    out["limitations"] = [
        "Não é a especificação completa do PRJ. Indexação por assinaturas, layouts conferidos localmente.",
        "Cabeçalhos e contagens não são contagens de elementos físicos; há objetos embutidos e representações CAD.",
        "A unidade não foi recuperada de um campo explícito. Valores são mantidos brutos.",
        "Vínculos, enumerações, eixos locais, molas, critérios e propagação de cargas ainda não calibrados.",
        "Nome de material no pavimento é configuração; sobreposições por elemento não foram descartadas.",
        "Nenhuma ausência de carga não decodificada equivale a carga zero.",
        "Sem geração de modelo analítico, dimensionamento, escrita PRJ ou downgrade.",
        "Offsets sempre se referem ao fluxo descompactado. Campos raw não foram semanticamente mapeados.",
    ]
    return out
