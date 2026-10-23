"""NBR 8800 checks for solid square steel bars.

The equations share the solid-bar implementation, while this module keeps a
separate public routine set and restricts it to square-section members.
"""

from osa.verification.rectangular_bar import (
    verify_rectangular_bar_compression,
    verify_rectangular_bar_flexion_y,
    verify_rectangular_bar_flexion_z,
    verify_rectangular_bar_flexocompression,
    verify_rectangular_bar_flexotension,
    verify_rectangular_bar_oblique,
    verify_rectangular_bar_shear_y,
    verify_rectangular_bar_shear_z,
    verify_rectangular_bar_tension,
)

_FAMILY = "Barra Quadrada"


def verify_square_bar_tension(element, model, results):
    return verify_rectangular_bar_tension(element, model, results, _FAMILY)


def verify_square_bar_compression(element, model, results):
    return verify_rectangular_bar_compression(element, model, results, _FAMILY)


def verify_square_bar_flexion_y(element, model, results):
    return verify_rectangular_bar_flexion_y(element, model, results, _FAMILY)


def verify_square_bar_flexion_z(element, model, results):
    return verify_rectangular_bar_flexion_z(element, model, results, _FAMILY)


def verify_square_bar_shear_y(element, model, results):
    return verify_rectangular_bar_shear_y(element, model, results, _FAMILY)


def verify_square_bar_shear_z(element, model, results):
    return verify_rectangular_bar_shear_z(element, model, results, _FAMILY)


def verify_square_bar_oblique(element, model, results, flex_y, flex_z):
    return verify_rectangular_bar_oblique(element, model, results, flex_y, flex_z, _FAMILY)


def verify_square_bar_flexotension(element, model, results, tension, flex_y, flex_z):
    return verify_rectangular_bar_flexotension(
        element, model, results, tension, flex_y, flex_z, _FAMILY,
    )


def verify_square_bar_flexocompression(element, model, results, compression, flex_y, flex_z):
    return verify_rectangular_bar_flexocompression(
        element, model, results, compression, flex_y, flex_z, _FAMILY,
    )
