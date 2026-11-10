from concurrent.futures import ThreadPoolExecutor

from osa.analysis.pynite.plate_mesh import generate_plate_mesh
from osa.model import StructuralModel


def test_first_gmsh_initialization_is_safe_from_analysis_worker_thread():
    model = StructuralModel()
    model.add_plate(((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)))

    with ThreadPoolExecutor(max_workers=1) as executor:
        mesh = executor.submit(generate_plate_mesh, model.plates).result(timeout=20)

    assert len(mesh.nodes) > 4
    assert mesh.elements["P1"]


def test_gmsh_quads_share_a_consistent_plate_local_axis():
    model = StructuralModel()
    model.add_plate(((0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)))

    mesh = generate_plate_mesh(model.plates)
    local_x = (1.0, 0.0, 0.0)
    normal = (0.0, 0.0, 1.0)

    for quad in mesh.elements["P1"]:
        points = mesh.nodes[list(quad)]
        first_edge = points[1] - points[0]
        fourth_edge = points[3] - points[0]
        assert first_edge @ local_x > 0
        assert (first_edge @ local_x) / (first_edge @ first_edge) ** 0.5 > 0.5
        assert (first_edge[1] * fourth_edge[0] - first_edge[0] * fourth_edge[1]) * normal[2] < 0
