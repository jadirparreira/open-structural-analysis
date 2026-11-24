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
}
PLATE_DIAGRAMS = (
    *((name, name) for name in PLATE_FIELDS),
    *DEFORMATION_DIAGRAMS,
)
