"""Declared contact regions for concentrated transverse web forces."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class BearingRegion:
    name: str
    position_m: float
    contact_mm: float
    force_per_web_kn: float
    combination: str
    edge_distance_mm: float
    connected: bool = False
    loaded_flanges: int = 1

    def __post_init__(self):
        if not self.name.strip() or not self.combination.strip():
            raise ValueError('Informe a identificação da região e a combinação de cálculo.')
        if not all(isfinite(v) and v >= 0 for v in (self.position_m, self.edge_distance_mm)):
            raise ValueError('Posição e distância à extremidade devem ser finitas e não negativas.')
        if not all(isfinite(v) and v > 0 for v in (self.contact_mm, self.force_per_web_kn)):
            raise ValueError('Comprimento de contato e força por alma devem ser positivos e finitos.')
        if type(self.connected) is not bool or self.loaded_flanges not in (1, 2):
            raise ValueError('Condição de ligação e número de mesas carregadas inválidos.')
