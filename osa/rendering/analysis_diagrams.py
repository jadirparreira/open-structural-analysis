"""Diagram labels and physical components for the analysis palette."""

DEFORMATION_DIAGRAMS = tuple(
    (f"Deformação {axis} (D{axis.lower()})", f"Deformação {axis}")
    for axis in ("X", "Y", "Z", "XYZ")
)
BAR_DIAGRAMS = (
    ("Normal (N)", "Normal"),
    ("Cortante Y (Vy)", "Cortante Y"),
    ("Cortante Z (Vz)", "Cortante Z"),
    ("Torsor (T)", "Torsor"),
    ("Fletor Y (My)", "Fletor Y"),
    ("Fletor Z (Mz)", "Fletor Z"),
    *DEFORMATION_DIAGRAMS,
    ("Reações de apoio", "Reações de apoio"),
)
# Membrane values from PyNite are stresses, not forces per unit length.
PLATE_FIELDS = {
    "Fletor X (Mx)": ("moment", 0, "kN·m/m", -1.0),
    "Fletor Y (My)": ("moment", 1, "kN·m/m", -1.0),
    "Momento volvente XY (Mxy)": ("moment", 2, "kN·m/m", 1.0),
    "Cortante X (Qx)": ("shear", 0, "kN/m", 1.0),
    "Cortante Y (Qy)": ("shear", 1, "kN/m", 1.0),
    "Tensão normal X (σx)": ("membrane", 0, "kN/m²", 1.0),
    "Tensão normal Y (σy)": ("membrane", 1, "kN/m²", 1.0),
    "Tensão de cisalhamento XY (τxy)": ("membrane", 2, "kN/m²", 1.0),
    "Wood-Armer X superior (Mwx,sup)": ("wood_armer", 0, "kN·m/m", 1.0),
    "Wood-Armer Y superior (Mwy,sup)": ("wood_armer", 1, "kN·m/m", 1.0),
    "Wood-Armer X inferior (Mwx,inf)": ("wood_armer", 2, "kN·m/m", 1.0),
    "Wood-Armer Y inferior (Mwy,inf)": ("wood_armer", 3, "kN·m/m", 1.0),
    "Von Mises superior (σvm,sup)": ("von_mises", 0, "MPa", 1.0),
    "Von Mises inferior (σvm,inf)": ("von_mises", 1, "MPa", 1.0),
    "Von Mises máximo (σvm,máx)": ("von_mises", 2, "MPa", 1.0),
}


def plate_diagram_tooltip(diagram: str) -> str:
    if diagram.startswith("Wood-Armer"):
        return (
            "Momento para armadura ortogonal nos eixos X/Y da placa, em kN·m/m. "
            "Magnitude não negativa; considera flexão e torção, sem incluir membrana ou calcular armadura. "
            "Face superior = +Z local; inferior = -Z local."
        )
    if diagram.startswith("Von Mises"):
        return (
            "Tensão equivalente em MPa, combinando membrana e flexão nas faces. "
            "Superior = +Z local; inferior = -Z local; máximo = maior entre as faces. "
            "Não constitui verificação de resistência do concreto."
        )
    return "Esforços e tensões nos eixos locais; deslocamentos nos eixos globais."


PLATE_DIAGRAMS = (
    *((name, name) for name in PLATE_FIELDS),
    *DEFORMATION_DIAGRAMS,
)
