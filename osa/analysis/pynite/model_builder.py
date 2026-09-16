"""Tradução do domínio para um modelo PyNite.

As conversões de unidade são explícitas. A construção recusa membros sem seção
completa em vez de atribuir propriedades fictícias.
"""

from __future__ import annotations

from osa.domain import StructuralModel


class ModelBuilder:
    def build(self, source: StructuralModel):
        try:
            from Pynite import FEModel3D
        except ImportError as error:
            raise RuntimeError("PyNiteFEA não está disponível neste ambiente.") from error
        target = FEModel3D()
        for node in source.nodes.values():
            target.add_node(node.name, node.x, node.y, node.z)
            if any(node.supports):
                target.def_support(node.name, *node.supports)
        if source.bars:
            raise ValueError(
                "A análise ainda requer A, Iy, Iz e J para cada seção; "
                "a geometria visual atual não contém todas essas propriedades."
            )
        return target
