"""Physical story inputs for equivalent geometric imperfections."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class NotionalStation:
    level: str
    upper_node: str
    base_node: str
    gravity_kn: tuple[tuple[str, float], ...]

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip() for value in (self.level, self.upper_node, self.base_node)):
            raise ValueError('Identifique o nível e os nós de referência na base e no nível.')
        if self.upper_node == self.base_node:
            raise ValueError('Os nós de referência na base e no nível devem ser distintos.')
        names = [name for name, _ in self.gravity_kn]
        if len(set(names)) != len(names) or any(not isinstance(name, str) or not name for name in names):
            raise ValueError('Combinações gravitacionais duplicadas ou inválidas.')
        if not self.gravity_kn or any(not isfinite(value) or value < 0 for _, value in self.gravity_kn):
            raise ValueError('Forças gravitacionais devem ser finitas e não negativas, em kN.')


@dataclass(frozen=True, slots=True)
class NotionalPlan:
    stations: tuple[NotionalStation, ...]
    actions: tuple[str, ...]
    combinations: tuple[str, ...]
    basis: str | None = None
    allow_large_displacement: bool = False

    def __post_init__(self):
        if type(self.allow_large_displacement) is not bool:
            raise ValueError('A opção do procedimento para grande deslocabilidade deve ser booleana.')
