"""Conversão de resultados do PyNite para entidades do domínio."""

from osa.domain import AnalysisResult


class ResultMapper:
    def map(self, source, model_revision: int, load_reference: str) -> AnalysisResult:
        node_results = {}
        for name, node in source.nodes.items():
            node_results[name] = {
                "DX": dict(node.DX), "DY": dict(node.DY), "DZ": dict(node.DZ),
                "RX": dict(node.RX), "RY": dict(node.RY), "RZ": dict(node.RZ),
            }
        return AnalysisResult(model_revision, load_reference, node_results=node_results)
