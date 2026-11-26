"""Project sheets and file output through the same geometry and painters as the UI."""
from __future__ import annotations

import copy
from html import escape
from math import isfinite
from pathlib import Path
from typing import Any


class ProjectFeatures:
    def _sheet_state(self):
        if self._get_detailing_data is not None:
            self.model.detailing_data = copy.deepcopy(self._get_detailing_data())
        state = copy.deepcopy(self.model.detailing_data or {})
        sheets = state.setdefault('sheets', {})
        for key, default in (('sheet_names', []), ('sheet_settings', {}), ('sheet_views', {}),
                             ('sheet_texts', {}), ('sheet_lines', {}), ('project_settings', {})):
            sheets.setdefault(key, default)
        return state, sheets

    def _publish_sheets(self, state):
        self.model.detailing_data = state
        self.model.view_revision += 1
        if self._on_detailing_changed is not None:
            self._on_detailing_changed()

    @staticmethod
    def _output_path(path, suffix, overwrite):
        target = Path(path).expanduser()
        if not target.is_absolute() or target.suffix.lower() != suffix:
            raise ValueError(f'Informe um caminho absoluto com extensão {suffix}.')
        if not target.parent.is_dir():
            raise ValueError('O diretório de destino não existe.')
        if target.exists() and not overwrite:
            raise ValueError('O arquivo já existe; informe overwrite=true para substituí-lo.')
        return target

    @staticmethod
    def _finite_point(values, size=2):
        if len(values) != size or not all(isfinite(float(v)) for v in values):
            raise ValueError(f'Informe {size} coordenadas finitas.')
        return tuple(float(v) for v in values)

    def get_project_sheets(self) -> dict[str, Any]:
        """Consulta folhas, vistas, cotas e textos. Posições de folha são frações da área útil (0 a 1)."""
        _state, sheets = self._sheet_state()
        return copy.deepcopy(sheets)

    def create_project_sheet(
        self, name: str, paper_size: str = 'A3', orientation: str = 'Paisagem',
        project: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Cria folha A0–A4, em Paisagem/Retrato. project: client/work/address/responsible/crea; não altera análise."""
        from osa.ui.project_sheet import PAPER_SIZES_MM, default_project_settings, default_project_sheet_settings
        name = name.strip()
        state, sheets = self._sheet_state()
        if not name or name in sheets['sheet_names']:
            raise ValueError('Informe um nome de folha novo e não vazio.')
        if paper_size not in PAPER_SIZES_MM or orientation not in ('Paisagem', 'Retrato'):
            raise ValueError('Use A0–A4 e Paisagem ou Retrato.')
        if project and set(project) - {'client', 'work', 'address', 'responsible', 'crea'}:
            raise ValueError('Campo de identificação do projeto desconhecido.')
        sheets['project_settings'] = {**default_project_settings(), **sheets['project_settings'], **(project or {})}
        sheets['sheet_names'].append(name)
        sheets['active_sheet'] = name
        sheets['sheet_settings'][name] = {**default_project_sheet_settings(name), 'paper_size': paper_size,
                                         'orientation': orientation}
        sheets['sheet_views'][name] = []
        sheets['sheet_texts'][name] = []
        sheets['sheet_lines'][name] = []
        self._publish_sheets(state)
        return {'sheet_name': name, 'settings': sheets['sheet_settings'][name]}

    def create_sheet_view(
        self, sheet_name: str, name: str, plane: str, coordinate: float,
        scale_denominator: float = 50, position: list[float] | None = None,
        upper_offset_cm: float = 50, lower_offset_cm: float = 50,
        excluded_owners: list[str] | None = None,
    ) -> dict[str, Any]:
        """Projeta geometria real na folha. plane: XY/XZ/YZ; coordinate em m; offsets em cm; position: [0..1,0..1]."""
        from types import SimpleNamespace

        from osa.domain.node_components import node_component_geometry_signature
        from osa.ui.detailing_preview import DETAILING_LINEWORK_VERSION, DetailingViewPreview, _ViewGeometryCalculator
        from osa.ui.detailing_viewport import _DetachedDetailingScene
        state, sheets = self._sheet_state()
        if sheet_name not in sheets['sheet_names']:
            raise ValueError('Folha não encontrada.')
        if plane not in ('XY', 'XZ', 'YZ') or not isfinite(coordinate):
            raise ValueError('Use plano XY, XZ ou YZ e coordenada finita em m.')
        if not isfinite(scale_denominator) or scale_denominator < 1:
            raise ValueError('A escala deve ter denominador finito maior ou igual a 1.')
        if not all(isfinite(v) and v >= 0 for v in (upper_offset_cm, lower_offset_cm)):
            raise ValueError('Os afastamentos devem ser finitos e não negativos.')
        location = self._finite_point(position if position is not None else [.5, .5])
        if any(v < 0 or v > 1 for v in location):
            raise ValueError('A posição deve estar entre 0 e 1 na área útil da folha.')
        if not name.strip() or any(v.get('name') == name for v in sheets['sheet_views'][sheet_name]):
            raise ValueError('Informe um nome novo e não vazio para a vista.')
        calculator = _ViewGeometryCalculator()
        calculator._detail_scene = _DetachedDetailingScene(SimpleNamespace())
        projection = {'plane': plane, 'coordinate': coordinate, 'upper_offset_cm': upper_offset_cm,
                          'lower_offset_cm': lower_offset_cm, 'orientation': 'Superior para inferior', 'rotation_degrees': 0}
        DetailingViewPreview.set_view(calculator, self.model, **projection, excluded_owners=excluded_owners or ())
        segments = tuple(calculator._segments_2d)
        if not segments:
            raise ValueError('O plano e os afastamentos selecionados não contêm geometria.')
        view = {'name': name, 'projection': projection, 'segments': segments,
                    'segment_owners': tuple(calculator._segment_sources), 'axes_visible': True,
                    'scale_denominator': scale_denominator, 'position': location, 'model_revision': self.model.revision,
                    'linework_version': DETAILING_LINEWORK_VERSION,
                    'component_geometry_signature': node_component_geometry_signature(self.model),
                    'hidden_owners': list(excluded_owners or ())}
        views = sheets['sheet_views'][sheet_name]
        views.append(view)
        sheets['active_sheet'] = sheet_name
        self._publish_sheets(state)
        return {'sheet_name': sheet_name, 'view_index': len(views)-1, 'segments': len(segments)}

    def add_sheet_text(
        self, sheet_name: str, text: str, position: list[float], width_mm: float = 100,
        height_mm: float = 20, text_height_mm: float = 3,
    ) -> dict[str, Any]:
        """Adiciona texto simples à folha; position é fração da área útil; tamanhos em mm."""
        state, sheets = self._sheet_state()
        if sheet_name not in sheets['sheet_names']:
            raise ValueError('Folha não encontrada.')
        point = self._finite_point(position)
        if any(v < 0 or v > 1 for v in point):
            raise ValueError('A posição deve estar entre 0 e 1.')
        if not all(isfinite(v) and v > 0 for v in (width_mm, height_mm, text_height_mm)):
            raise ValueError('Os tamanhos de texto devem ser positivos e finitos.')
        texts = sheets['sheet_texts'].setdefault(sheet_name, [])
        texts.append({'anchor': point, 'width_mm': width_mm, 'height_mm': height_mm, 'text_height_mm': text_height_mm,
                          'html': '<p>'+escape(text).replace('\n', '<br>')+'</p>'})
        sheets['active_sheet'] = sheet_name
        self._publish_sheets(state)
        return {'text_index': len(texts)-1}

    def update_sheet_view(
        self, sheet_name: str, view_index: int, name: str | None = None,
        position: list[float] | None = None, scale_denominator: float | None = None,
        axes_visible: bool | None = None, clear_dimensions: bool = False,
    ) -> dict[str, Any]:
        """Edita nome, posição (frações 0..1), escala e eixos; em detalhes, posição move o grupo inteiro. clear_dimensions remove cotas."""
        state, sheets = self._sheet_state()
        views = sheets['sheet_views'].get(sheet_name, [])
        if not 0 <= view_index < len(views):
            raise ValueError('Vista não encontrada.')
        view = views[view_index]
        if name is not None:
            if not name.strip() or any(v is not view and v.get('name') == name for v in views):
                raise ValueError('Informe um nome novo e não vazio para a vista.')
            view['name'] = name
        if position is not None:
            point = self._finite_point(position)
            if any(v < 0 or v > 1 for v in point):
                raise ValueError('A posição deve estar entre 0 e 1.')
            view['position'] = point
            group = view.get('component_detail_group')
            if isinstance(group, dict) and group.get('id'):
                old = group.get('group_position', (.5, .53))
                delta = (point[0]-old[0], point[1]-old[1])
                for sibling in views:
                    metadata = sibling.get('component_detail_group')
                    if isinstance(metadata, dict) and metadata.get('id') == group['id']:
                        label = metadata.get('label_position', (.5, .40))
                        metadata['group_position'] = point
                        metadata['label_position'] = (label[0]+delta[0], label[1]+delta[1])
        if scale_denominator is not None:
            if not isfinite(scale_denominator) or scale_denominator < 1:
                raise ValueError('A escala deve ter denominador finito maior ou igual a 1.')
            view['scale_denominator'] = scale_denominator
        if axes_visible is not None:
            view['axes_visible'] = axes_visible
        if clear_dimensions:
            view['dimensions'] = []
        sheets['active_sheet'] = sheet_name
        self._publish_sheets(state)
        return {'sheet_name': sheet_name, 'view_index': view_index}

    def add_view_dimension(
        self, sheet_name: str, view_index: int, start: list[float], end: list[float],
        offset: list[float], unit: str = 'cm',
    ) -> dict[str, Any]:
        """Adiciona cota linear em m projetados: XY=(X,Y), XZ=(-X,Z), YZ=(Y,Z); offset também 2D; unidade mm/cm/m."""
        state, sheets = self._sheet_state()
        views = sheets['sheet_views'].get(sheet_name, [])
        if not 0 <= view_index < len(views):
            raise ValueError('Vista não encontrada.')
        if unit not in ('mm', 'cm', 'm'):
            raise ValueError('Use unidade mm, cm ou m.')
        a, b, shift = (self._finite_point(v) for v in (start, end, offset))
        if a == b:
            raise ValueError('A cota deve ter comprimento positivo.')
        dims = views[view_index].setdefault('dimensions', [])
        dims.append({'start': a, 'end': b, 'offset': shift, 'unit': unit, 'decimal_places': 0 if unit != 'm' else 3})
        sheets['active_sheet'] = sheet_name
        self._publish_sheets(state)
        return {'dimension_index': len(dims)-1}

    def create_component_detail(
        self, sheet_name: str, node_name: str, name: str = 'Base de pilar',
        scale_denominator: float = 10,
    ) -> dict[str, Any]:
        """Cria vistas superior/lateral cotadas da chapa de base do nó, usando a geometria da interface; não dimensiona a ligação."""
        from hashlib import sha1

        from osa.domain.node_components import node_component_geometry_signature
        from osa.services.base_plate_details import add_base_plate_annotations, arrange_base_plate_views
        from osa.ui.detailing_preview import DETAILING_LINEWORK_VERSION
        from osa.ui.dialogs import ComponentDetailsDialog
        from osa.ui.project_sheet import PAPER_SIZES_MM
        state, sheets = self._sheet_state()
        node = self.model.nodes.get(node_name)
        if sheet_name not in sheets['sheet_names']:
            raise ValueError('Folha não encontrada.')
        if node is None or node.component is None or node.component.component_id != 'base_plate':
            raise ValueError('O nó deve possuir uma chapa de base/topo.')
        if not name.strip() or not isfinite(scale_denominator) or scale_denominator < 1:
            raise ValueError('Informe nome e escala válidos.')
        group_id = sha1(f'{sheet_name}:{node_name}:{name}'.encode()).hexdigest()[:12]
        if any(v.get('component_detail_group', {}).get('id') == group_id
               for v in sheets['sheet_views'][sheet_name]):
            raise ValueError('Este detalhe já existe na folha.')
        generated = ComponentDetailsDialog._build_group_views(
            self.model, .05, {'nodes': [node_name], 'parameters': dict(node.component.parameters)},
        )
        views = []
        for key, title in [('top', 'Superior'), ('west', 'Oeste')]:
            part = generated[key]
            view = {'name': f'{name} - {title}', 'segments': part['segments'],
                    'segment_owners': part['segment_owners'], 'dimensions': part['dimensions'],
                    'scale_denominator': scale_denominator,
                    'component_annotation_geometry': part['component_annotation_geometry'],
                    'model_revision': self.model.revision, 'linework_version': DETAILING_LINEWORK_VERSION,
                    'component_geometry_signature': node_component_geometry_signature(self.model),
                    'projection': {'plane': 'custom', 'coordinate': part['coordinate']},
                    'component_detail_group': {'id': group_id, 'component_id': 'base_plate',
                        'members': [node_name], 'direction': title, 'title': name,
                        'offset': len(views), 'view_count': 2}}
            add_base_plate_annotations(self.model, view)
            views.append(view)
        settings = sheets['sheet_settings'][sheet_name]
        width, height = PAPER_SIZES_MM[settings['paper_size']]
        if settings['orientation'] == 'Retrato':
            width, height = min(width, height), max(width, height)
        arrange_base_plate_views(views, width-55, height-20, 0, 80)
        start = len(sheets['sheet_views'][sheet_name])
        sheets['sheet_views'][sheet_name].extend(views)
        sheets['active_sheet'] = sheet_name
        self._publish_sheets(state)
        return {'sheet_name': sheet_name, 'view_indices': [start, start+1]}

    def save_project(self, path: str, overwrite: bool = False) -> dict[str, Any]:
        """Salva o projeto completo em caminho absoluto .osa; overwrite=true permite substituir arquivo existente."""
        from osa.persistence.project_repository import ProjectRepository
        target = self._output_path(path, '.osa', overwrite)
        self._sheet_state()
        ProjectRepository().save(self.model, target)
        if self._on_project_saved is not None:
            self._on_project_saved(target)
        return {'path': str(target), 'revision': self.model.revision, 'bytes': target.stat().st_size}

    def export_project_sheet_pdf(self, sheet_name: str, path: str, overwrite: bool = False) -> dict[str, Any]:
        """Exporta uma folha para PDF vetorial em caminho absoluto; preserva a navegação e seleção da interface."""
        from PySide6.QtWidgets import QApplication

        from osa.ui.project_sheet import ProjectSheetWorkspace
        from osa.ui.project_sheet_pdf import export_sheet_pdf
        target = self._output_path(path, '.pdf', overwrite)
        _state, sheets = self._sheet_state()
        if sheet_name not in sheets['sheet_names']:
            raise ValueError('Folha não encontrada.')
        if QApplication.instance() is None:
            raise ValueError('A exportação PDF requer uma sessão gráfica Qt ativa.')
        workspace = ProjectSheetWorkspace()
        try:
            from osa.services.component_accessories import component_accessory_rows
            from osa.services.steel_quantities import steel_plate_rows
            from osa.ui.sheet_tables import steel_profile_rows
            workspace.model = self.model
            workspace.steel_profile_rows_provider = lambda: steel_profile_rows(self.model)
            workspace.steel_plate_rows_provider = lambda: steel_plate_rows(self.model)
            workspace.accessory_rows_provider = lambda: component_accessory_rows(self.model)
            workspace.set_sheet_settings(sheet_name, sheets['sheet_settings'][sheet_name],
                                         sheets['project_settings'], len(sheets['sheet_names']))
            workspace.set_sheet_views(sheets['sheet_views'][sheet_name])
            workspace.set_sheet_annotations(sheets['sheet_texts'].get(sheet_name, []),
                                            sheets['sheet_lines'].get(sheet_name, []))
            export_sheet_pdf(workspace, target)
        finally:
            workspace.close()
            workspace.deleteLater()
        return {'path': str(target), 'bytes': target.stat().st_size}

    def export_model_dxf(self, path: str, overwrite: bool = False) -> dict[str, Any]:
        """Exporta eixos analíticos das barras para DXF 3D em m, em caminho absoluto."""
        from osa.exporters.model_dxf import export_model_to_dxf
        target = self._output_path(path, '.dxf', overwrite)
        return {'path': str(target), 'members': export_model_to_dxf(target, self.model)}

    def import_drawing_reference(self, path: str) -> dict[str, Any]:
        """Importa referência DXF/DWG do caminho absoluto local, preservando o arquivo de origem."""
        from osa.importers.drawing_reference import import_drawing_reference
        target = Path(path).expanduser()
        if not target.is_absolute():
            raise ValueError('Informe um caminho absoluto.')
        result = import_drawing_reference(target)
        self.model.add_reference(result.reference)
        self._notify_model_changed()
        return {'reference_id': result.reference.id, 'warnings': list(result.warnings)}
