"""Keep multisampling effective around translucent analytical plates."""


class PlateAntialiasing:
    """Use standard alpha blending while analytical plate faces are visible.

    VTK's order-independent transparency pass can leave bright samples beside
    opaque strokes when MSAA is active. Standard blending avoids those seams
    and lets the configured sample count control the image directly.
    """

    def __init__(self, renderer) -> None:
        self._renderer = renderer
        self._active = False
        self._previous_oit = None

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        # Older VTK releases use traditional blending and have no OIT switch.
        if not hasattr(self._renderer, "SetUseOIT"):
            return
        if active:
            self._previous_oit = self._renderer.GetUseOIT()
            self._renderer.SetUseOIT(False)
        else:
            self._renderer.SetUseOIT(self._previous_oit)
            self._previous_oit = None
