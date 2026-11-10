"""Presentation modes for finite-element results on plates."""

PLATE_RESULT_DISPLAY_MODES = (
    ("centros", "Nos centros dos elementos"),
    ("nos_sem_media", "Nos nós, sem média"),
    ("nos_media", "Nos nós, com média"),
    ("nos_media_macro", "Nos nós, com média por placa"),
)
DEFAULT_PLATE_RESULT_DISPLAY_MODE = "nos_media_macro"


def is_plate_result_display_mode(value: str) -> bool:
    return value in {mode for mode, _label in PLATE_RESULT_DISPLAY_MODES}
