from types import SimpleNamespace

import pyvista as pv


SUPPORT_SIZE = 0.30


def _chamfered_top_block(node, x_index: int, y_index: int) -> pv.PolyData:
    small_size = SUPPORT_SIZE / 3.0
    x0 = node.x - SUPPORT_SIZE / 2.0 + x_index * small_size
    x1 = x0 + small_size
    y0 = node.y - SUPPORT_SIZE / 2.0 + y_index * small_size
    y1 = y0 + small_size
    z0 = node.z - small_size
    z1 = node.z
    if x_index == 0:
        points = [
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x1, y0, z1), (x1, y1, z1),
        ]
        faces = [
            4, 0, 1, 2, 3,
            4, 0, 3, 5, 4,
            4, 1, 4, 5, 2,
            3, 0, 1, 4,
            3, 3, 5, 2,
        ]
        return pv.PolyData(points, faces=faces)
    if x_index == 2:
        points = [
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x0, y1, z1),
        ]
        faces = [
            4, 0, 1, 2, 3,
            4, 0, 4, 5, 3,
            4, 1, 2, 5, 4,
            3, 0, 1, 4,
            3, 3, 5, 2,
        ]
        return pv.PolyData(points, faces=faces)
    points = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    faces = [
        4, 0, 1, 2, 3,
        4, 4, 7, 6, 5,
        4, 0, 4, 5, 1,
        4, 1, 5, 6, 2,
        4, 2, 6, 7, 3,
        4, 3, 7, 4, 0,
    ]
    return pv.PolyData(points, faces=faces)


def _chamfered_top_block_y(node, x_index: int, y_index: int) -> pv.PolyData:
    swapped_node = SimpleNamespace(x=node.y, y=node.x, z=node.z)
    local_mesh = _chamfered_top_block(swapped_node, y_index, x_index)
    points = local_mesh.points[:, (1, 0, 2)]
    return pv.PolyData(points, faces=local_mesh.faces)


def _double_chamfered_top_block(node, x_index: int, y_index: int) -> pv.PolyData:
    outer_x = x_index in (0, 2)
    outer_y = y_index in (0, 2)
    if outer_x and outer_y:
        small_size = SUPPORT_SIZE / 3.0
        x0 = node.x - SUPPORT_SIZE / 2.0 + x_index * small_size
        x1 = x0 + small_size
        y0 = node.y - SUPPORT_SIZE / 2.0 + y_index * small_size
        y1 = y0 + small_size
        z0 = node.z - small_size
        apex_x = x1 if x_index == 0 else x0
        apex_y = y1 if y_index == 0 else y0
        return pv.Pyramid(points=[
            (x0, y0, z0), (x1, y0, z0),
            (x1, y1, z0), (x0, y1, z0),
            (apex_x, apex_y, node.z),
        ])
    if outer_x:
        return _chamfered_top_block(node, x_index, y_index)
    if outer_y:
        return _chamfered_top_block_y(node, x_index, y_index)
    small_size = SUPPORT_SIZE / 3.0
    return pv.Cube(
        center=(
            node.x,
            node.y,
            node.z - small_size / 2.0,
        ),
        x_length=small_size,
        y_length=small_size,
        z_length=small_size,
    )


def _modular_cube_mesh(node, *, include_middle_layer: bool = True, center_cylinder: bool = False) -> pv.PolyData:
    small_size = SUPPORT_SIZE / 3.0
    cubes = []
    for x_index in range(3):
        for y_index in range(3):
            for z_index in range(3):
                if not include_middle_layer and z_index == 1:
                    continue
                cubes.append(pv.Cube(
                    center=(
                        node.x + (x_index - 1) * small_size,
                        node.y + (y_index - 1) * small_size,
                        node.z - (z_index + 0.5) * small_size,
                    ),
                    x_length=small_size,
                    y_length=small_size,
                    z_length=small_size,
                ))
    parts = cubes
    if center_cylinder:
        parts.append(pv.Cylinder(
            center=(node.x, node.y, node.z - 1.5 * small_size),
            direction=(0.0, 0.0, 1.0),
            radius=small_size / 2.0,
            height=small_size,
            resolution=24,
        ))
    return pv.merge(parts, merge_points=False)


def _minus_x_face_cylinder_mesh(
    node, *, include_middle_layer: bool = True,
    middle_vertical_cylinder: bool = False,
) -> pv.PolyData:
    """Build the -X-face cylinder family used by supports 55 and 56."""
    small_size = SUPPORT_SIZE / 3.0
    parts = []

    # Remove the complete -X face (x_index == 0) from every layer. The two
    # remaining columns form the solid body behind the cylinders.
    for x_index in (1, 2):
        for y_index in range(3):
            z_indices = range(3) if include_middle_layer else (0, 2)
            for z_index in z_indices:
                parts.append(pv.Cube(
                    center=(
                        node.x + (x_index - 1) * small_size,
                        node.y + (y_index - 1) * small_size,
                        node.z - (z_index + 0.5) * small_size,
                    ),
                    x_length=small_size,
                    y_length=small_size,
                    z_length=small_size,
                ))

    # The middle line of the -X face remains empty. The upper and lower rows
    # each receive three cylinders spanning the complete Y direction.
    for z_index in (0, 2):
        for y_index in range(3):
            parts.append(pv.Cylinder(
                center=(
                    node.x - small_size,
                    node.y + (y_index - 1) * small_size,
                    node.z - (z_index + 0.5) * small_size,
                ),
                direction=(0.0, 1.0, 0.0),
                radius=small_size / 2.0,
                height=small_size,
                resolution=24,
            ))

    if middle_vertical_cylinder:
        parts.append(pv.Cylinder(
            center=(
                node.x,
                node.y,
                node.z - 1.5 * small_size,
            ),
            direction=(0.0, 0.0, 1.0),
            radius=small_size / 2.0,
            height=small_size,
            resolution=24,
        ))

    return pv.merge(parts, merge_points=False)


def _rotated_minus_z_face_cylinder_mesh(
    node, *, free_rx: bool = False, free_ry: bool = False,
    free_rz: bool = False,
) -> pv.PolyData:
    """Build support 48 after a 90-degree rotation around global X."""
    small_size = SUPPORT_SIZE / 3.0
    parts = []

    # The original -Y face becomes the -Z face after the rotation. The two
    # remaining layers in Z form the body behind the two rows of rollers.
    layer_indices = (0,) if free_rz else (0, 1)
    for x_index in range(3):
        for y_index in range(3):
            for z_index in layer_indices:
                if z_index == 0:
                    parts.append(_rotation_top_block(
                        node, x_index, y_index,
                        free_rx=free_rx, free_ry=free_ry,
                    ))
                else:
                    parts.append(_cell_cube(node, x_index, y_index, z_index))

    # Two sets of three adjacent cylinders span X. They sit on the -Z face,
    # one row at Y- and one at Y+; the central row in Y remains empty.
    for y_index in (0, 2):
        for x_index in range(3):
            parts.append(pv.Cylinder(
                center=(
                    node.x + (x_index - 1) * small_size,
                    node.y + (y_index - 1) * small_size,
                    node.z - 2.5 * small_size,
                ),
                direction=(1.0, 0.0, 0.0),
                radius=small_size / 2.0,
                height=small_size,
                resolution=24,
            ))

    if free_rz:
        parts.append(pv.Cylinder(
            center=(node.x, node.y, node.z - 1.5 * small_size),
            direction=(0.0, 0.0, 1.0),
            radius=small_size / 2.0,
            height=small_size,
            resolution=24,
        ))

    return pv.merge(parts, merge_points=False)


def _z_rotated_minus_z_face_cylinder_mesh(
    node, *, free_rx: bool = False, free_ry: bool = False,
    free_rz: bool = False,
) -> pv.PolyData:
    """Build the Dx-free roller family based on support 32."""
    small_size = SUPPORT_SIZE / 3.0
    parts = []

    # The two solid layers of support 32 are unchanged by the Z rotation.
    layer_indices = (0,) if free_rz else (0, 1)
    for x_index in range(3):
        for y_index in range(3):
            for z_index in layer_indices:
                if z_index == 0:
                    parts.append(_rotation_top_block(
                        node, x_index, y_index,
                        free_rx=free_rx, free_ry=free_ry,
                    ))
                else:
                    parts.append(_cell_cube(node, x_index, y_index, z_index))

    # The rollers remain on -Z, but their axes change from X to Y. The two
    # rows are now located at X- and X+.
    for x_index in (0, 2):
        for y_index in range(3):
            parts.append(pv.Cylinder(
                center=(
                    node.x + (x_index - 1) * small_size,
                    node.y + (y_index - 1) * small_size,
                    node.z - 2.5 * small_size,
                ),
                direction=(0.0, 1.0, 0.0),
                radius=small_size / 2.0,
                height=small_size,
                resolution=24,
            ))

    if free_rz:
        parts.append(pv.Cylinder(
            center=(node.x, node.y, node.z - 1.5 * small_size),
            direction=(0.0, 0.0, 1.0),
            radius=small_size / 2.0,
            height=small_size,
            resolution=24,
        ))

    return pv.merge(parts, merge_points=False)


def _cell_cube(node, x_index: int, y_index: int, z_index: int) -> pv.PolyData:
    small_size = SUPPORT_SIZE / 3.0
    return pv.Cube(
        center=(
            node.x + (x_index - 1) * small_size,
            node.y + (y_index - 1) * small_size,
            node.z - (z_index + 0.5) * small_size,
        ),
        x_length=small_size,
        y_length=small_size,
        z_length=small_size,
    )


def _rotation_top_block(node, x_index: int, y_index: int, *, free_rx: bool, free_ry: bool):
    """Return the top-layer triangle pattern for the released rotations."""
    if free_rx and free_ry:
        return _double_chamfered_top_block(node, x_index, y_index)
    if free_rx:
        return _chamfered_top_block_y(node, x_index, y_index)
    if free_ry:
        return _chamfered_top_block(node, x_index, y_index)
    return _cell_cube(node, x_index, y_index, 0)


def _sphere_cell(node, x_index: int, y_index: int, z_index: int) -> pv.PolyData:
    small_size = SUPPORT_SIZE / 3.0
    return pv.Sphere(
        center=(
            node.x + (x_index - 1) * small_size,
            node.y + (y_index - 1) * small_size,
            node.z - (z_index + 0.5) * small_size,
        ),
        radius=small_size / 2.0,
        theta_resolution=24,
        phi_resolution=16,
    )


def _minus_x_sphere_mesh(
    node, *, free_rx: bool = False, free_ry: bool = False,
    free_rz: bool = False,
) -> pv.PolyData:
    """Build the Dx-restrained, Dy/Dz-free sphere family on the -X face."""
    parts = [
        _sphere_cell(node, 0, y_index, z_index)
        for y_index in (0, 2)
        for z_index in (0, 2)
    ]
    for x_index in (1, 2):
        for y_index in range(3):
            z_indices = (0, 2) if free_rz else range(3)
            for z_index in z_indices:
                if z_index == 0:
                    parts.append(_rotation_top_block(
                        node, x_index, y_index,
                        free_rx=free_rx, free_ry=free_ry,
                    ))
                else:
                    parts.append(_cell_cube(node, x_index, y_index, z_index))
    if free_rz:
        small_size = SUPPORT_SIZE / 3.0
        parts.append(pv.Cylinder(
            center=(node.x, node.y, node.z - 1.5 * small_size),
            direction=(0.0, 0.0, 1.0),
            radius=small_size / 2.0,
            height=small_size,
            resolution=24,
        ))
    return pv.merge(parts, merge_points=False)


def _minus_z_sphere_mesh(
    node, *, free_rx: bool = False, free_ry: bool = False,
    free_rz: bool = False,
) -> pv.PolyData:
    """Build the Dx/Dy-free, Dz-restrained sphere family on the -Z face."""
    parts = [
        _sphere_cell(node, x_index, y_index, 2)
        for x_index in (0, 2)
        for y_index in (0, 2)
    ]
    z_indices = (0,) if free_rz else (0, 1)
    for x_index in range(3):
        for y_index in range(3):
            for z_index in z_indices:
                if z_index == 0:
                    parts.append(_rotation_top_block(
                        node, x_index, y_index,
                        free_rx=free_rx, free_ry=free_ry,
                    ))
                else:
                    parts.append(_cell_cube(node, x_index, y_index, z_index))
    if free_rz:
        small_size = SUPPORT_SIZE / 3.0
        parts.append(pv.Cylinder(
            center=(node.x, node.y, node.z - 1.5 * small_size),
            direction=(0.0, 0.0, 1.0),
            radius=small_size / 2.0,
            height=small_size,
            resolution=24,
        ))
    return pv.merge(parts, merge_points=False)


def _planar_cylinder(node, x_index: int, y_index: int, *, direction: str) -> pv.PolyData:
    small_size = SUPPORT_SIZE / 3.0
    axis = (0.0, 1.0, 0.0) if direction == "y" else (1.0, 0.0, 0.0)
    return pv.Cylinder(
        center=(
            node.x + (x_index - 1) * small_size,
            node.y + (y_index - 1) * small_size,
            node.z - 1.5 * small_size,
        ),
        direction=axis,
        radius=small_size / 2.0,
        height=small_size,
        resolution=24,
    )


def _translation_overlay(node, free_dx: bool, free_dy: bool, free_dz: bool):
    """Return cell replacements for the released translation directions."""
    occupied: set[tuple[int, int, int]] = set()
    blocked_faces: set[str] = set()
    parts: list[pv.PolyData] = []

    free_count = sum((free_dx, free_dy, free_dz))
    if free_count == 1 and free_dx:
        # X and Y are the two in-plane directions; X uses Y-oriented rollers.
        for x_index in range(3):
            occupied.add((x_index, 0, 1))
            parts.append(_planar_cylinder(node, x_index, 0, direction="y"))
    elif free_count == 1 and free_dy:
        # The perpendicular in-plane arrangement is used for free Y.
        for y_index in range(3):
            occupied.add((0, y_index, 1))
            parts.append(_planar_cylinder(node, 0, y_index, direction="x"))
    elif free_count == 2:
        # Four spheres mark the corners of the released two-axis plane. The
        # face carrying them is completely reserved for the spheres.
        if free_dx and free_dy:
            sphere_cells = ((0, 0, 0), (0, 2, 0), (0, 0, 2), (0, 2, 2))
            blocked_faces.add("-x")
        elif free_dx and free_dz:
            sphere_cells = ((0, 0, 0), (2, 0, 0), (0, 0, 2), (2, 0, 2))
            blocked_faces.add("-y")
        else:  # free_dy and free_dz
            sphere_cells = ((0, 0, 2), (2, 0, 2), (0, 2, 2), (2, 2, 2))
            blocked_faces.add("-z")
        for cell in sphere_cells:
            occupied.add(cell)
            parts.append(_sphere_cell(node, *cell))
    elif free_count == 3:
        # With all three translations released, use only the three negative
        # faces. Duplicate corner positions are intentionally merged so a
        # corner never receives two coincident spheres.
        blocked_faces.update(("-x", "-y", "-z"))
        sphere_cells = tuple({
            (0, 0, 0), (0, 2, 0), (0, 0, 2), (0, 2, 2),
            (2, 0, 0), (2, 0, 2), (2, 2, 2),
        })
        for cell in sphere_cells:
            occupied.add(cell)
            parts.append(_sphere_cell(node, *cell))

    return occupied, blocked_faces, parts


def _generic_support_mesh(node) -> pv.PolyData | None:
    """Build a compositional model for patterns without a dedicated variant."""
    free_dx, free_dy, free_dz, free_rx, free_ry, free_rz = (
        not value for value in node.supports
    )
    if not any(node.supports):
        return None

    small_size = SUPPORT_SIZE / 3.0
    overlay_cells, blocked_faces, overlay_parts = _translation_overlay(
        node, free_dx, free_dy, free_dz,
    )
    parts = list(overlay_parts)

    # The established Z-only family uses the -X face as its reference: the
    # upper and lower rows become three Y-oriented cylinders. This same base
    # is retained when a rotational release is composed with free Z.
    z_face_family = free_dz and not free_dx and not free_dy
    if z_face_family:
        for z_index in (0, 2):
            for y_index in range(3):
                cell = (0, y_index, z_index)
                overlay_cells.add(cell)
                parts.append(pv.Cylinder(
                    center=(
                        node.x - small_size,
                        node.y + (y_index - 1) * small_size,
                        node.z - (z_index + 0.5) * small_size,
                    ),
                    direction=(0.0, 1.0, 0.0),
                    radius=small_size / 2.0,
                    height=small_size,
                    resolution=24,
                ))

    # Rz releases always replace the central cell with a vertical cylinder.
    # It has priority over a cube, but does not overlap the two-axis corner
    # spheres or the one-axis in-plane cylinder rows.
    if free_rz:
        overlay_cells.add((1, 1, 1))
        parts.append(pv.Cylinder(
            center=(node.x, node.y, node.z - 1.5 * small_size),
            direction=(0.0, 0.0, 1.0),
            radius=small_size / 2.0,
            height=small_size,
            resolution=24,
        ))

    # The Z-only face family removes the whole middle layer when Rz is also
    # released, matching the established model 55 convention.
    remove_middle_layer = free_rz
    if z_face_family and free_rz:
        remove_middle_layer = True

    for x_index in range(3):
        for y_index in range(3):
            for z_index in range(3):
                cell = (x_index, y_index, z_index)
                if cell in overlay_cells:
                    continue
                if "-x" in blocked_faces and x_index == 0:
                    continue
                if "-y" in blocked_faces and y_index == 0:
                    continue
                if "-z" in blocked_faces and z_index == 2:
                    continue
                if z_face_family and x_index == 0:
                    continue
                if remove_middle_layer and z_index == 1:
                    continue
                if z_index == 0:
                    parts.append(_rotation_top_block(
                        node, x_index, y_index,
                        free_rx=free_rx, free_ry=free_ry,
                    ))
                else:
                    parts.append(_cell_cube(node, x_index, y_index, z_index))

    return pv.merge(parts, merge_points=False)


def _chamfered_modular_cube_mesh(
    node, *, chamfer_axis: str = "x", include_middle_layer: bool = True,
    center_cylinder: bool = False,
) -> pv.PolyData:
    small_size = SUPPORT_SIZE / 3.0
    parts = []
    for x_index in range(3):
        for y_index in range(3):
            top_block = (
                _chamfered_top_block(node, x_index, y_index)
                if chamfer_axis == "x"
                else _chamfered_top_block_y(node, x_index, y_index)
            )
            parts.append(top_block)
            lower_layers = (1, 2) if include_middle_layer else (2,)
            for z_index in lower_layers:
                parts.append(pv.Cube(
                    center=(
                        node.x + (x_index - 1) * small_size,
                        node.y + (y_index - 1) * small_size,
                        node.z - (z_index + 0.5) * small_size,
                    ),
                    x_length=small_size,
                    y_length=small_size,
                    z_length=small_size,
                ))
    if center_cylinder:
        parts.append(pv.Cylinder(
            center=(node.x, node.y, node.z - 1.5 * small_size),
            direction=(0.0, 0.0, 1.0),
            radius=small_size / 2.0,
            height=small_size,
            resolution=24,
        ))
    return pv.merge(parts, merge_points=False)


def _double_chamfered_modular_cube_mesh(
    node, *, include_middle_layer: bool = True, center_cylinder: bool = False,
) -> pv.PolyData:
    small_size = SUPPORT_SIZE / 3.0
    parts = []
    for x_index in range(3):
        for y_index in range(3):
            parts.append(_double_chamfered_top_block(node, x_index, y_index))
            lower_layers = (1, 2) if include_middle_layer else (2,)
            for z_index in lower_layers:
                parts.append(pv.Cube(
                    center=(
                        node.x + (x_index - 1) * small_size,
                        node.y + (y_index - 1) * small_size,
                        node.z - (z_index + 0.5) * small_size,
                    ),
                    x_length=small_size,
                    y_length=small_size,
                    z_length=small_size,
                ))
    if center_cylinder:
        parts.append(pv.Cylinder(
            center=(node.x, node.y, node.z - 1.5 * small_size),
            direction=(0.0, 0.0, 1.0),
            radius=small_size / 2.0,
            height=small_size,
            resolution=24,
        ))
    return pv.merge(parts, merge_points=False)


def build_support_mesh(node) -> pv.PolyData | None:
    if node.supports == (True, True, True, True, True, True):
        return _modular_cube_mesh(node)
    if node.supports == (True, True, True, True, False, True):
        return _chamfered_modular_cube_mesh(node, chamfer_axis="x")
    if node.supports == (True, True, True, False, True, True):
        return _chamfered_modular_cube_mesh(node, chamfer_axis="y")
    if node.supports == (True, True, True, False, False, True):
        return _double_chamfered_modular_cube_mesh(node)
    if node.supports == (True, True, True, False, False, False):
        return _double_chamfered_modular_cube_mesh(
            node, include_middle_layer=False, center_cylinder=True,
        )
    if node.supports == (True, True, True, True, False, False):
        return _chamfered_modular_cube_mesh(
            node, include_middle_layer=False, center_cylinder=True,
        )
    if node.supports == (True, True, True, False, True, False):
        return _chamfered_modular_cube_mesh(
            node, chamfer_axis="y", include_middle_layer=False, center_cylinder=True,
        )
    if node.supports == (True, True, True, True, True, False):
        return _modular_cube_mesh(node, include_middle_layer=False, center_cylinder=True)
    if node.supports == (True, True, False, True, True, True):
        return _minus_x_face_cylinder_mesh(node)
    if node.supports == (True, True, False, True, True, False):
        return _minus_x_face_cylinder_mesh(
            node, include_middle_layer=False, middle_vertical_cylinder=True,
        )
    if node.supports[0] and not node.supports[1] and not node.supports[2]:
        return _minus_x_sphere_mesh(
            node,
            free_rx=not node.supports[3],
            free_ry=not node.supports[4],
            free_rz=not node.supports[5],
        )
    if node.supports[0] and not node.supports[1] and node.supports[2]:
        return _rotated_minus_z_face_cylinder_mesh(
            node,
            free_rx=not node.supports[3],
            free_ry=not node.supports[4],
            free_rz=not node.supports[5],
        )
    if not node.supports[0] and node.supports[1] and node.supports[2]:
        return _z_rotated_minus_z_face_cylinder_mesh(
            node,
            free_rx=not node.supports[3],
            free_ry=not node.supports[4],
            free_rz=not node.supports[5],
        )
    if not node.supports[0] and not node.supports[1] and node.supports[2]:
        return _minus_z_sphere_mesh(
            node,
            free_rx=not node.supports[3],
            free_ry=not node.supports[4],
            free_rz=not node.supports[5],
        )
    return _generic_support_mesh(node)


class SupportRenderer:
    def render(self, plotter, node, radius: float) -> object | None:
        del radius
        mesh = build_support_mesh(node)
        if mesh is None:
            return None
        return plotter.add_mesh(
            mesh, color="#a8b0b9", edge_color="#6e7781", show_edges=True,
            line_width=1.5, pickable=False, reset_camera=False,
            name=f"support-{node.name}",
        )
