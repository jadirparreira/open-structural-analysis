import pytest

from osa.ui.palettes import AnalysisTopPalette


@pytest.mark.parametrize(
    ("position", "scale"),
    [(0, 1), *((position, position * 10) for position in range(1, 11))],
)
def test_deformation_slider_positions_map_to_requested_amplifications(position, scale):
    assert AnalysisTopPalette._deformation_scale_for_position(position) == scale
