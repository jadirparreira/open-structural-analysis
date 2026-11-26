"""Registro automático do plugin MCP local no Claude Code.

Equivalente ao registro feito para o ChatGPT/Codex em ``mcp_local``: ao ativar
o Servidor MCP, o OpenSA monta um marketplace local com o plugin
``mcp-opensa`` e pede ao CLI do Claude Code que o instale no escopo do usuário.

O plugin instalado inicia a ponte ``--mcp-stdio`` deste mesmo executável. Assim
as ferramentas aparecem em toda sessão do Claude, mesmo que ela comece antes de
o OpenSA ser aberto, e as chamadas funcionam assim que o servidor é ativado.
A aba Code do Claude Desktop usa a mesma configuração do Claude Code.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

MARKETPLACE_NAME = "open-structural-analysis-local"
PLUGIN_NAME = "mcp-opensa"
SERVER_NAME = "mcp-opensa"
_STAMP = ".installed-sha256"


def bridge_command() -> tuple[str, list[str]]:
    """Comando que inicia a ponte stdio a partir desta instalação do OpenSA."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        # sys.executable aponta para a montagem temporária do AppImage.
        return appimage, ["--mcp-stdio"]
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp-stdio"]
    return sys.executable, ["-m", "osa", "--mcp-stdio"]


def default_marketplace_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "OpenSA" / "claude-marketplace"
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "opensa" / "claude-marketplace"


def find_claude_cli() -> str | None:
    configured = os.environ.get("CLAUDE_CLI_PATH")
    candidates = [configured, shutil.which("claude")]
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        candidates.append(str(Path(os.environ["APPDATA"]) / "npm" / "claude.cmd"))
    # Programas abertos pelo menu gráfico (Linux) nem sempre herdam o PATH do terminal.
    executable = "claude.exe" if sys.platform == "win32" else "claude"
    candidates += [str(Path.home() / ".local" / "bin" / executable), str(Path.home() / ".claude" / "local" / executable)]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


Runner = Callable[[Sequence[str]], int]


def _run_cli(arguments: Sequence[str]) -> int:
    try:
        completed = subprocess.run(
            list(arguments),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return -1
    return completed.returncode


class ClaudeCodeIntegration:
    """Mantém o plugin ``mcp-opensa`` instalado no Claude Code do usuário."""

    def __init__(
        self,
        *,
        plugin_root: Path | None = None,
        marketplace_root: Path | None = None,
        command: tuple[str, list[str]] | None = None,
        cli: str | None = None,
        runner: Runner = _run_cli,
    ) -> None:
        project_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        self.plugin_source = (plugin_root or project_root / "plugins") / PLUGIN_NAME
        self.marketplace_root = marketplace_root or default_marketplace_root()
        self.command = command or bridge_command()
        self._cli = cli
        self._runner = runner

    @property
    def plugin_destination(self) -> Path:
        return self.marketplace_root / PLUGIN_NAME

    def server_configuration(self) -> dict:
        executable, arguments = self.command
        return {
            "mcpServers": {
                SERVER_NAME: {
                    "command": executable,
                    "args": list(arguments),
                    # O executável do Windows tem tela de abertura; a ponte não deve exibi-la.
                    "env": {"PYINSTALLER_SUPPRESS_SPLASH_SCREEN": "1"},
                }
            }
        }

    def marketplace_manifest(self) -> dict:
        manifest = self._read_json(self.plugin_source / ".claude-plugin" / "plugin.json")
        return {
            "name": MARKETPLACE_NAME,
            "owner": {"name": "Open Structural Analysis"},
            "metadata": {"description": "Plugin local instalado pelo Open Structural Analysis."},
            "plugins": [{
                "name": PLUGIN_NAME,
                "source": f"./{PLUGIN_NAME}",
                "description": manifest.get("description", ""),
                "version": manifest.get("version", ""),
                "category": "engineering",
            }],
        }

    def write_marketplace(self) -> str:
        """Grava o marketplace local e retorna a assinatura do seu conteúdo."""
        if not (self.plugin_source / ".claude-plugin" / "plugin.json").is_file():
            raise FileNotFoundError(f"Plugin do Claude não encontrado em {self.plugin_source}")
        destination = self.plugin_destination
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(
            self.plugin_source,
            destination,
            ignore=shutil.ignore_patterns(".codex-plugin", "mcp.json", "plugin.json"),
        )
        shutil.copytree(self.plugin_source / ".claude-plugin", destination / ".claude-plugin", dirs_exist_ok=True)
        self._write_json(destination / ".mcp.json", self.server_configuration())
        self._write_json(self.marketplace_root / ".claude-plugin" / "marketplace.json", self.marketplace_manifest())
        return self.content_signature()

    def content_signature(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.marketplace_root.rglob("*")):
            if path.is_file() and path.name != _STAMP:
                digest.update(path.relative_to(self.marketplace_root).as_posix().encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def is_current(self) -> bool:
        stamp = self.marketplace_root / _STAMP
        return stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == self.content_signature()

    def ensure_installed(self, *, background: bool = True) -> bool:
        """Atualiza o marketplace local e instala o plugin se o Claude Code existir.

        Retorna ``False`` quando o Claude Code não está instalado. A instalação
        pelo CLI roda em segundo plano para não atrasar a ativação do servidor.
        """
        cli = self._cli or find_claude_cli()
        if cli is None:
            return False
        signature = self.write_marketplace()
        stamp = self.marketplace_root / _STAMP
        if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == signature:
            return True
        if background:
            threading.Thread(
                target=self._install_with_cli, args=(cli, signature), name="osa-claude-plugin-install", daemon=True,
            ).start()
        else:
            self._install_with_cli(cli, signature)
        return True

    def _install_with_cli(self, cli: str, signature: str) -> None:
        plugin = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
        # "add" é idempotente para o mesmo caminho; "update" relê o conteúdo regravado.
        self._runner([cli, "plugin", "marketplace", "add", str(self.marketplace_root), "--scope", "user"])
        self._runner([cli, "plugin", "marketplace", "update", MARKETPLACE_NAME])
        installed = self._runner([cli, "plugin", "install", plugin, "--scope", "user"]) == 0
        updated = self._runner([cli, "plugin", "update", plugin, "--scope", "user"]) == 0
        if installed or updated:
            (self.marketplace_root / _STAMP).write_text(signature, encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
