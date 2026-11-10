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
        segment_map = getattr(source, "_osa_member_segments", None)
        if segment_map:
            groups = segment_map.items()
        else:
            groups = ((name, ((name, 0.0, 1.0),)) for name in source.members)
        for name, segments in groups:
            first_name, first_start, first_end = segments[0]
            first = source.members[first_name]
            length = float(first.L()) / (first_end - first_start)
            positions = np.linspace(0.0, length, 21)
            samples = []
            for position in positions:
                ratio = float(position) / length
                segment_name, start_ratio, end_ratio = segments[-1]
                for candidate in segments:
                    if candidate[1] - 1e-10 <= ratio < candidate[2] - 1e-10:
                        segment_name, start_ratio, end_ratio = candidate
                        break
                segment = source.members[segment_name]
                local_position = max(0.0, min(float(segment.L()), (ratio - start_ratio) / (end_ratio - start_ratio) * float(segment.L())))
                sample = self._member_sample(segment, local_position, load_reference)
                # The solver member is only one finite-element segment. Keep
                # x in the original member's coordinate system so the result
                # renderer spans the full user-visible bar.
                sample["x"] = float(position)
                samples.append(sample)
            # The first and last samples are exactly the member endpoints.
            # Reusing them avoids querying PyNite for the same nine result
            # components a second time for every member and combination.
            start = {key: value for key, value in samples[0].items() if key != "x"}
            end = {key: value for key, value in samples[-1].items() if key != "x"}
            member_results[name] = {
                "length": float(length),
                "start": start,
                "end": end,
                "samples": samples,
            }
        plate_results = {}
        for plate_name, elements in getattr(source, "_osa_plate_elements", {}).items():
            plate_nodes = {}
            element_results = {}
            for element_name, node_names, coordinates in elements:
                quad = source.quads[element_name]
                element_results[element_name] = {
                    "nodes": list(node_names),
                    "moment": np.asarray(quad.moment(combo_name=load_reference), dtype=float).reshape(-1).tolist(),
                    "shear": np.asarray(quad.shear(combo_name=load_reference), dtype=float).reshape(-1).tolist(),
                    "membrane": np.asarray(quad.membrane(combo_name=load_reference), dtype=float).reshape(-1).tolist(),
                    "moment_nodal": self._quad_nodal_values(quad, "moment", load_reference),
                    "shear_nodal": self._quad_nodal_values(quad, "shear", load_reference),
                    "membrane_nodal": self._quad_nodal_values(quad, "membrane", load_reference),
                }
                for node_name, point in zip(node_names, coordinates):
                    node = source.nodes[node_name]
                    plate_nodes[node_name] = {
                        "coordinates": list(point),
                        "DX": float(node.DX[load_reference]),
                        "DY": float(node.DY[load_reference]),
                        "DZ": float(node.DZ[load_reference]),
                    }
            plate_results[plate_name] = {"nodes": plate_nodes, "elements": element_results}
        return AnalysisResult(model_revision, load_reference, node_results, member_results, plate_results)

    @staticmethod
    def _quad_nodal_values(quad, result_name: str, load_reference: str) -> list[list[float]]:
        """Extrapolate element integration-point results to its four nodes."""
        result_method = getattr(quad, result_name)
        return [
            np.asarray(
                result_method(xi, eta, combo_name=load_reference), dtype=float,
            ).reshape(-1).tolist()
            for xi, eta in ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))
        ]

    @staticmethod
    def _member_end_result(member, position: float, load_reference: str) -> dict[str, float]:
        deflections = ResultMapper._global_deflections(member, position, load_reference)
        return {
            "axial": float(member.axial(position, load_reference)),
            "shear_y": float(member.shear("Fy", position, load_reference)),
            "shear_z": float(member.shear("Fz", position, load_reference)),
            "moment_y": float(member.moment("My", position, load_reference)),
            "moment_z": float(member.moment("Mz", position, load_reference)),
            "torque": float(member.torque(position, load_reference)),
            **deflections,
        }

    @staticmethod
    def _member_sample(member, position: float, load_reference: str) -> dict[str, float]:
        deflections = ResultMapper._global_deflections(member, position, load_reference)
        return {
            "x": position,
            "axial": float(member.axial(position, load_reference)),
            "shear_y": float(member.shear("Fy", position, load_reference)),
            "shear_z": float(member.shear("Fz", position, load_reference)),
            "moment_y": float(member.moment("My", position, load_reference)),
            "moment_z": float(member.moment("Mz", position, load_reference)),
            "torque": float(member.torque(position, load_reference)),
            **deflections,
        }

    @staticmethod
    def _global_deflections(member, position: float, load_reference: str) -> dict[str, float]:
        """Return the member displacement components in global XYZ axes.

        PyNite's member ``deflection`` API returns local x/y/z components.
        Its transformation matrix maps global vectors to local vectors, so
        the transpose maps the sampled local displacement back to global XYZ.
        """
        local = np.array((
            member.deflection("dx", position, load_reference),
            member.deflection("dy", position, load_reference),
            member.deflection("dz", position, load_reference),
        ), dtype=float)
        local_from_global = np.asarray(member.T()[:3, :3], dtype=float)
        global_displacement = local_from_global.T @ local
        return {
            "deflection_x": float(global_displacement[0]),
            "deflection_y": float(global_displacement[1]),
            "deflection_z": float(global_displacement[2]),
        }
