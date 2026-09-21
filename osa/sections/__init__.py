"""Cálculo paramétrico de propriedades de seções transversais."""

from .geometry import SectionShape, section_shape
from .properties import SectionProperties, calculate_section_properties

__all__ = [
    "SectionProperties",
    "SectionShape",
    "calculate_section_properties",
    "section_shape",
]
