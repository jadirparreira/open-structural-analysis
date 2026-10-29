"""Member-property editors backed by a transient placement draft."""

from dataclasses import replace
from types import SimpleNamespace

from osa.domain import StructuralModel
from osa.domain.entities import Member
from osa.services import ModelService

from .common import SECTION_PARAMETRIC_SPECS
from .displacement_panel import DisplacementPanel
from .property_panel import PropertyPanel
from .section_panel import (
    ILaminadoSectionPanel,
    LLaminadoSectionPanel,
    ParametricSectionPanel,
    TLaminadoSectionPanel,
    ULaminadoSectionPanel,
    WLaminadoSectionPanel,
    HPLaminadoSectionPanel,
)


class MemberPlacementEditor:
    """Reuse member editors without exposing an unfinished member to the project.

    The private model contains only a property draft, with no endpoint nodes.
    Its immutable member is copied when a real member is created. Editors can
    therefore use their normal services without touching project revisions,
    analysis results or existing members.
    """

    _draft_name = "draft"

    def __init__(self, window) -> None:
        self._window = window
        self.model = StructuralModel()
        self.model_service = ModelService(self.model)
        self.section_property_service = window.section_property_service
        self.section_profiles = {}
        self.section_geometry = {}
        self.selected = ("bar", self._draft_name)
        self.palette = SimpleNamespace(active_group="Geometria")
        self.properties = PropertyPanel(window, context=self, creation_mode=True)
        self.properties.point_mode_switch.kind_changed.connect(window._member_point_mode_changed)
        self.displacement_panel = DisplacementPanel(window)
        self.displacement_panel.window = self
        self.section_panels = {}
        self.section_panel = self._section_editor("W Laminado")
        self.reset()

    @property
    def point_mode(self) -> str:
        return (
            "midpoint" if self.properties.point_mode_switch._buttons["midpoint"].isChecked()
            else "exact"
        )

    @property
    def template(self) -> Member:
        return self.model.bars[self._draft_name]

    def reset(self) -> None:
        self.hide()
        self.model.clear()
        self.model.bars[self._draft_name] = Member(self._draft_name, "", "")
        self.section_profiles.clear()
        self.section_geometry.clear()
        self.properties.point_mode_switch.set_selection("exact")

    def show(self) -> None:
        project = self._window.model
        self.model.materials = dict(project.materials)
        self.model.material_types = dict(project.material_types)
        self.model.sections = {kind: list(items) for kind, items in project.sections.items()}
        draft = self.template
        if draft.material in self.model.materials:
            self.model_service.assign_material(draft.name, draft.material)
            available = self.properties._sections_for_material(draft.material)
            if draft.section and draft.section not in available:
                self.model_service.assign_section(draft.name, "")
                self.section_profiles.clear()
                self.section_geometry.clear()
        elif draft.material != "Indefinido":
            self.model.bars[draft.name] = replace(
                draft, material="Indefinido", material_values=Member("", "", "").material_values,
                section="", profile="", section_geometry=(), section_mirrored=False,
            )
            self.section_profiles.clear()
            self.section_geometry.clear()
        self.properties.show_for(*self.selected)

    def hide(self) -> None:
        self.properties.hide()
        self.close_section_panel()
        self.close_displacement_panel()

    def isVisible(self) -> bool:
        """Report whether any widget owned by this editor is currently shown."""
        return any(
            widget.isVisible()
            for widget in (self.properties, self.section_panel, self.displacement_panel)
        )

    def reposition(self) -> None:
        for panel in (self.properties, self.section_panel, self.displacement_panel):
            if panel.isVisible():
                panel.reposition()

    # PropertyPanel positions itself against its editor host; all widgets are
    # still parented to the real window so focus and viewport input stay intact.
    def width(self) -> int:
        return self._window.width()

    def height(self) -> int:
        return self._window.height()

    def isMaximized(self) -> bool:
        return self._window.isMaximized()

    def refresh_member_geometry(self, name: str) -> None:
        self.properties.update_positioning_status(name)

    def refresh_member_rotation(self, name: str) -> None:
        self.refresh_member_geometry(name)

    def refresh_member_releases(self, name: str) -> None:
        # The shared release controls update themselves after each edit.
        pass

    def show_error(self, message: str) -> None:
        self._window.show_error(message)

    def _section_editor(self, family: str):
        if family not in self.section_panels:
            factories = {
                "W Laminado": WLaminadoSectionPanel,
                "HP Laminado": HPLaminadoSectionPanel,
                "I Laminado": ILaminadoSectionPanel,
                "U Laminado": ULaminadoSectionPanel,
                "L Laminado": LLaminadoSectionPanel,
                "T Laminado": TLaminadoSectionPanel,
            }
            if family in factories:
                panel = factories[family](self._window)
            elif family in SECTION_PARAMETRIC_SPECS:
                panel = ParametricSectionPanel(self._window, family)
            else:
                return None
            panel.window = self
            self.section_panels[family] = panel
        return self.section_panels[family]

    def toggle_section_panel(self, section: str = "", button=None) -> None:
        if self.section_panel.isVisible() and self.section_panel._section_family == section:
            self.close_section_panel(button)
        else:
            self.show_section_panel(section, button)

    def show_section_panel(self, section: str, button=None) -> None:
        panel = self._section_editor(section)
        if panel is None:
            if button is not None:
                button.setChecked(False)
            return
        self.close_section_panel()
        self.close_displacement_panel()
        self.section_panel = panel
        panel.configure_for(self._draft_name, section)
        panel.reposition()
        panel.show()
        panel.raise_()
        if button is not None:
            button.setChecked(True)

    def close_section_panel(self, button=None) -> None:
        self.section_panel.hide()
        trigger = button if button is not None else self.properties._section_settings_button
        if trigger is not None:
            trigger.setChecked(False)

    def toggle_displacement_panel(self, button=None) -> None:
        if self.displacement_panel.isVisible():
            self.close_displacement_panel(button)
            return
        self.close_section_panel()
        self.displacement_panel.configure_for(self._draft_name)
        self.displacement_panel.reposition()
        self.displacement_panel.show()
        self.displacement_panel.raise_()
        if button is not None:
            button.setChecked(True)

    def close_displacement_panel(self, button=None) -> None:
        self.displacement_panel.hide()
        trigger = button if button is not None else self.properties._displacement_settings_button
        if trigger is not None:
            trigger.setChecked(False)
