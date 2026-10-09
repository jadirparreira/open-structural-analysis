"""Registro automático do plugin MCP local em clientes OpenAI locais."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

MARKETPLACE_NAME = "open-structural-analysis-local"
PLUGIN_NAME = "mcp-opensa"
PLUGIN_VERSION = "0.1.2"


class LocalMcpIntegration:
    """Instala o registro local do plugin sem depender do CLI do usuário."""

    def __init__(
        self,
        *,
        plugin_root: Path | None = None,
        config_path: Path | None = None,
        marketplace_root: Path | None = None,
    ) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.plugin_root = plugin_root or project_root / "plugins"
        self.config_path = config_path or self._default_config_path()
        self.marketplace_root = marketplace_root or Path.home() / ".agents" / "plugins"
        # A local marketplace resolves ``source.path`` relative to its own
        # directory.  Keep the copied plugin inside that directory so the
        # desktop client can validate and install it without another command.
        self.installed_plugin_root = self.marketplace_root

    @property
    def marketplace_plugin_path(self) -> str:
        """Retorna o caminho do plugin relativo à raiz do marketplace pessoal."""
        marketplace_root = self.marketplace_root.resolve()
        user_root = marketplace_root.parents[1]
        relative_path = marketplace_root.joinpath(PLUGIN_NAME).relative_to(user_root)
        return f"./{relative_path.as_posix()}"

    @staticmethod
    def _default_config_path() -> Path:
        configured_home = os.environ.get("CODEX_HOME")
        config_root = Path(configured_home) if configured_home else Path.home() / ".codex"
        return config_root / "config.toml"

    def ensure_installed(self) -> bool:
        """Registra o plugin e retorna se a configuração foi atualizada."""
        source_plugin = self.plugin_root / PLUGIN_NAME
        if not source_plugin.is_dir() or not (self.plugin_root / "marketplace.json").is_file():
            return False

        changed = self._install_personal_marketplace(source_plugin)
        if self.config_path.is_file():
            current = self.config_path.read_text(encoding="utf-8")
            if not self._configuration_matches(current):
                updated = self._without_osa_tables(current)
                updated = self._append_configuration(updated)
                temporary = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
                temporary.write_text(updated, encoding="utf-8")
                temporary.replace(self.config_path)
                changed = True
        if self._uses_default_locations():
            self._start_client_install()
        return changed

    def _uses_default_locations(self) -> bool:
        return (
            self.marketplace_root.resolve() == (Path.home() / ".agents" / "plugins").resolve()
            and self.config_path.resolve() == self._default_config_path().resolve()
        )

    def _start_client_install(self) -> None:
        cache_root = (
            Path.home()
            / ".codex"
            / "plugins"
            / "cache"
            / MARKETPLACE_NAME
            / PLUGIN_NAME
        )
        if any((cache_root / version).is_dir() for version in ("local", PLUGIN_VERSION)):
            return
        threading.Thread(
            target=self._install_with_client,
            name="osa-mcp-plugin-install",
            daemon=True,
        ).start()

    @staticmethod
    def _client_cli() -> str | None:
        candidates = (
            os.environ.get("CODEX_CLI_PATH"),
            shutil.which("codex"),
            "/usr/lib/chatgpt/resources/codex",
        )
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        return None

    def _install_with_client(self) -> None:
        cli = self._client_cli()
        if cli is None:
            return
        try:
            subprocess.run(
                [cli, "plugin", "add", f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return

    def _install_personal_marketplace(self, source_plugin: Path) -> bool:
        destination_plugin = self.installed_plugin_root / PLUGIN_NAME
        marketplace_path = self.marketplace_root / "marketplace.json"
        self.marketplace_root.mkdir(parents=True, exist_ok=True)
        before = self._read_marketplace(marketplace_path)
        after = dict(before)
        after.setdefault("name", MARKETPLACE_NAME)
        after.setdefault("interface", {"displayName": "Open Structural Analysis"})
        plugins = [
            plugin for plugin in after.get("plugins", [])
            if plugin.get("name") != PLUGIN_NAME
        ]
        plugins.append({
            "name": PLUGIN_NAME,
            "source": {"source": "local", "path": self.marketplace_plugin_path},
            "policy": {"installation": "INSTALLED_BY_DEFAULT", "authentication": "ON_INSTALL"},
            "category": "Engineering",
        })
        after["plugins"] = plugins
        shutil.copytree(source_plugin, destination_plugin, dirs_exist_ok=True)
        changed = after != before or not marketplace_path.is_file()
        if changed:
            temporary = marketplace_path.with_suffix(marketplace_path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(after, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(marketplace_path)
        return changed

    @staticmethod
    def _read_marketplace(path: Path) -> dict:
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def is_installed(self) -> bool:
        marketplace_path = self.marketplace_root / "marketplace.json"
        plugin_path = self.installed_plugin_root / PLUGIN_NAME
        marketplace = self._read_marketplace(marketplace_path)
        return plugin_path.is_dir() and any(
            plugin.get("name") == PLUGIN_NAME
            for plugin in marketplace.get("plugins", [])
        )

    def _configuration_matches(self, content: str) -> bool:
        return (
            self.is_installed()
            and f'[plugins."{PLUGIN_NAME}@{MARKETPLACE_NAME}"]' in content
            and 'enabled = true' in content
            and f"[marketplaces.{MARKETPLACE_NAME}]" not in content
        )

    def _without_osa_tables(self, content: str) -> str:
        headers = {
            f"[marketplaces.{MARKETPLACE_NAME}]",
            f'[plugins."{PLUGIN_NAME}@{MARKETPLACE_NAME}"]',
        }
        kept: list[str] = []
        skipping = False
        for line in content.splitlines(keepends=True):
            header = line.strip()
            if header.startswith("[") and header.endswith("]"):
                skipping = header in headers
            if not skipping:
                kept.append(line)
        return "".join(kept)

    def _append_configuration(self, content: str) -> str:
        separator = "" if not content or content.endswith("\n") else "\n"
        return (
            f"{content}{separator}\n"
            f"[plugins.\"{PLUGIN_NAME}@{MARKETPLACE_NAME}\"]\n"
            "enabled = true\n"
        )
