"""Conversão de resultados do PyNite para entidades do domínio."""

import numpy as np

from osa.domain import AnalysisResult


class ResultMapper:
    def map(self, source, model_revision: int, load_reference: str) -> AnalysisResult:
        node_results = {}
        for name, node in source.nodes.items():
            node_results[name] = {
                "DX": float(node.DX[load_reference]), "DY": float(node.DY[load_reference]),
                "DZ": float(node.DZ[load_reference]), "RX": float(node.RX[load_reference]),
                "RY": float(node.RY[load_reference]), "RZ": float(node.RZ[load_reference]),
                "RXN_FX": float(node.RxnFX[load_reference]), "RXN_FY": float(node.RxnFY[load_reference]),
                "RXN_FZ": float(node.RxnFZ[load_reference]), "RXN_MX": float(node.RxnMX[load_reference]),
                "RXN_MY": float(node.RxnMY[load_reference]), "RXN_MZ": float(node.RxnMZ[load_reference]),
            }
        member_results = {}
        for name, member in source.members.items():
            length = member.L()
            positions = np.linspace(0.0, length, 21)
            member_results[name] = {
                "length": float(length),
                "start": self._member_end_result(member, 0.0, load_reference),
                "end": self._member_end_result(member, length, load_reference),
                "samples": [self._member_sample(member, float(position), load_reference) for position in positions],
            }
        return AnalysisResult(model_revision, load_reference, node_results, member_results)

    @staticmethod
    def _member_end_result(member, position: float, load_reference: str) -> dict[str, float]:
        return {
            "axial": float(member.axial(position, load_reference)),
            "shear_y": float(member.shear("Fy", position, load_reference)),
            "shear_z": float(member.shear("Fz", position, load_reference)),
            "moment_y": float(member.moment("My", position, load_reference)),
            "moment_z": float(member.moment("Mz", position, load_reference)),
            "torque": float(member.torque(position, load_reference)),
            "deflection_x": float(member.deflection("dx", position, load_reference)),
            "deflection_y": float(member.deflection("dy", position, load_reference)),
            "deflection_z": float(member.deflection("dz", position, load_reference)),
        }

    @staticmethod
    def _member_sample(member, position: float, load_reference: str) -> dict[str, float]:
        return {
            "x": position,
            "axial": float(member.axial(position, load_reference)),
            "shear_y": float(member.shear("Fy", position, load_reference)),
            "shear_z": float(member.shear("Fz", position, load_reference)),
            "moment_y": float(member.moment("My", position, load_reference)),
            "moment_z": float(member.moment("Mz", position, load_reference)),
            "torque": float(member.torque(position, load_reference)),
            "deflection_x": float(member.deflection("dx", position, load_reference)),
            "deflection_y": float(member.deflection("dy", position, load_reference)),
            "deflection_z": float(member.deflection("dz", position, load_reference)),
        }
