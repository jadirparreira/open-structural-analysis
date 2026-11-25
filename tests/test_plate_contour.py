import pytest

from osa.services.plate_contour import plate_contour


A, B, C, D = (0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)


def test_orders_unordered_closed_segments():
    contour = plate_contour([(C, B), (A, D), (C, D), (B, A)])
    assert set(contour) == {A, B, C, D}
    assert len(contour) == 4


def test_automatically_connects_nearest_free_ends_without_creating_bars():
    contour = plate_contour([(A, B), (C, D)], close_automatically=True)
    assert set(contour) == {A, B, C, D}
    assert all(frozenset(edge) in {frozenset((A, B)), frozenset((B, C)),
                                   frozenset((C, D)), frozenset((D, A))}
               for edge in zip(contour, contour[1:] + contour[:1]))


def test_open_contour_is_rejected_without_automatic_closing():
    with pytest.raises(ValueError, match="fechado"):
        plate_contour([(A, B), (B, C)])


@pytest.mark.parametrize("segments", [
    [(A, B), (B, C), (B, D)],
    [(A, C), (C, B), (B, D), (D, A)],
    [(A, B), (B, C), (C, (0, 3, 1)), ((0, 3, 1), A)],
    [(A, B), (B, A), (B, C)],
])
def test_rejects_invalid_contours(segments):
    with pytest.raises(ValueError):
        plate_contour(segments)


def test_triangle_is_valid_on_an_inclined_plane():
    points = ((0, 0, 0), (1, 0, 1), (0, 1, 1))
    assert set(plate_contour(list(zip(points, points[1:] + points[:1])))) == set(points)
