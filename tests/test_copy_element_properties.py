from osa.model import StructuralModel


def test_copy_node_restrictions_keeps_destination_coordinates():
    model = StructuralModel()
    model.add_node('N1', 0, 0, 0)
    model.add_node('N2', 2, 0, 0)
    model.update_node_supports('N1', (True,) * 6)
    model.update_node_support_stiffness('N1', (10.,) * 6)
    model.copy_element_properties('node', 'N1', 'N2', frozenset({'restrictions', 'component'}))
    assert model.nodes['N2'].supports == (True,) * 6
    assert model.nodes['N2'].support_stiffness == (10.,) * 6
    assert model.nodes['N2'].x == 2


def test_copy_plate_section_and_restrictions_preserves_geometry_and_positioning():
    model = StructuralModel()
    source = model.add_plate(((0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)), thickness_mm=180, restrictions=(True, False, True))
    target = model.add_plate(((3, 0, 0), (5, 0, 0), (5, 2, 0), (3, 2, 0)), positioning_displacement=0.2)
    copied = model.copy_element_properties('plate', source.name, target.name, frozenset({'section', 'restrictions'}))
    assert copied.thickness_mm == 180
    assert copied.restrictions == source.restrictions
    assert copied.contour == target.contour
    assert copied.positioning_displacement == 0.2
