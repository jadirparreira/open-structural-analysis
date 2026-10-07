"""Casos de uso expostos pelo MCP local.

Esta camada mantém o protocolo MCP separado da janela Qt. Ela reutiliza os
serviços e a sessão de comandos do aplicativo para que uma chamada de IA
altere o mesmo modelo que está aberto na interface.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from osa.commands import CommandSession
from osa.domain import StructuralModel
from osa.services import ModelService

TemplateName = Literal["barrabieng", "galpao", "mezanino", "portico"]


class McpApplication:
    """Fachada thread-safe no nível da aplicação para o servidor MCP."""

    def __init__(
        self,
        model: StructuralModel,
        model_service: ModelService,
        command_session: CommandSession,
        *,
        on_model_changed: Callable[[], None] | None = None,
    ) -> None:
        self.model = model
        self.model_service = model_service
        self.command_session = command_session
        self._on_model_changed = on_model_changed

    def get_project_summary(self) -> dict[str, Any]:
        """Retorna um resumo pequeno e estável do modelo aberto."""
        return {
            "revision": self.model.revision,
            "nodes": len(self.model.nodes),
            "members": len(self.model.bars),
            "rigid_bars": len(self.model.rigid_bars),
            "actions": len(self.model.actions),
            "load_cases": len(self.model.load_cases),
            "load_combinations": len(self.model.load_combinations),
            "analysis_results": len(self.model.analysis_results),
        }

    def list_nodes(self) -> dict[str, Any]:
        """Retorna os nós do projeto atualmente aberto."""
        return {
            "revision": self.model.revision,
            "nodes": [
                {
                    "name": node.name,
                    "x": node.x,
                    "y": node.y,
                    "z": node.z,
                    "supports": list(node.supports),
                }
                for node in self.model.nodes.values()
            ],
        }

    def list_members(self) -> dict[str, Any]:
        """Retorna os membros do projeto atualmente aberto."""
        return {
            "revision": self.model.revision,
            "members": [
                {
                    "name": member.name,
                    "start_node": member.start_node,
                    "end_node": member.end_node,
                    "material": member.material,
                    "section": member.section,
                    "profile": member.profile,
                }
                for member in self.model.bars.values()
            ],
        }

    def create_node(self, x: float, y: float, z: float, name: str | None = None) -> dict[str, Any]:
        """Cria um nó no modelo aberto."""
        node = self.model_service.create_node(x, y, z, name=name)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "node": {
                "name": node.name,
                "x": node.x,
                "y": node.y,
                "z": node.z,
            },
        }

    def create_member(
        self,
        start_node: str,
        end_node: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Cria um membro entre dois nós existentes."""
        member = self.model_service.create_member(start_node, end_node, name=name)
        self._notify_model_changed()
        return {
            "revision": self.model.revision,
            "member": {
                "name": member.name,
                "start_node": member.start_node,
                "end_node": member.end_node,
            },
        }

    def create_template(self, template: TemplateName) -> dict[str, Any]:
        """Cria uma estrutura inicial existente no fluxo de comandos do OSA."""
        response = self.command_session.submit(template)
        if response.level == "error":
            raise ValueError(response.message)
        self._notify_model_changed()
        return {
            "template": template,
            "message": response.message,
            "revision": self.model.revision,
            "summary": self.get_project_summary(),
        }

    def _notify_model_changed(self) -> None:
        if self._on_model_changed is not None:
            self._on_model_changed()
