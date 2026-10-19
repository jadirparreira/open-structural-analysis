import json
from pathlib import Path

from osa.integrations import LocalMcpIntegration


def test_packaged_mcp_server_needs_no_credential():
    manifest = Path(__file__).resolve().parents[1] / "plugins" / "mcp-opensa" / "mcp.json"
    server = json.loads(manifest.read_text(encoding="utf-8"))["mcpServers"]["mcp-opensa"]
    assert server["url"] == "http://127.0.0.1:8765/mcp-opensa"
    assert server["type"] == "streamable-http"
    assert "extensions" not in server
    assert "headers" not in server


def test_local_mcp_integration_registers_and_updates_the_plugin(tmp_path: Path):
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    (plugin_root / "marketplace.json").write_text("{}", encoding="utf-8")
    source_plugin = plugin_root / "mcp-opensa"
    source_plugin.mkdir()
    (source_plugin / "plugin.json").write_text("{}", encoding="utf-8")
    (source_plugin / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"mcp-opensa": {"type": "http", "url": "http://127.0.0.1:8765/mcp-opensa"}}}),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text('[desktop]\nfollowUpQueueMode = "steer"\n', encoding="utf-8")
    marketplace_root = tmp_path / "home" / ".agents" / "plugins"

    integration = LocalMcpIntegration(
        plugin_root=plugin_root,
        config_path=config_path,
        marketplace_root=marketplace_root,
    )

    assert integration.ensure_installed() is True
    first = config_path.read_text(encoding="utf-8")
    marketplace = (marketplace_root / "marketplace.json").read_text(encoding="utf-8")
    assert '[plugins."mcp-opensa@open-structural-analysis-local"]' in first
    assert '"path": "./.agents/plugins/mcp-opensa"' in marketplace
    assert "enabled = true" in first
    assert '"mcp-opensa"' in marketplace
    assert (marketplace_root / "mcp-opensa" / "plugin.json").is_file()
    installed_config = marketplace_root / "mcp-opensa" / ".mcp.json"
    installed = json.loads(installed_config.read_text(encoding="utf-8"))
    assert "headers" not in installed["mcpServers"]["mcp-opensa"]
    assert integration.is_installed() is True

    assert integration.ensure_installed() is False
    second = config_path.read_text(encoding="utf-8")
    assert second == first


def test_local_mcp_integration_checks_its_own_enabled_table(tmp_path: Path):
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    (plugin_root / "marketplace.json").write_text("{}", encoding="utf-8")
    source_plugin = plugin_root / "mcp-opensa"
    source_plugin.mkdir()
    (source_plugin / "plugin.json").write_text("{}", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[plugins."mcp-opensa@open-structural-analysis-local"]\nenabled = false\n'
        '[plugins.other]\nenabled = true\n',
        encoding="utf-8",
    )
    integration = LocalMcpIntegration(
        plugin_root=plugin_root,
        config_path=config_path,
        marketplace_root=tmp_path / "home" / ".agents" / "plugins",
    )

    integration.ensure_installed()

    assert integration._configuration_matches(config_path.read_text(encoding="utf-8"))
    assert '[plugins.other]\nenabled = true' in config_path.read_text(encoding="utf-8")


def test_local_mcp_integration_does_not_create_unknown_client_config(tmp_path: Path):
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    (plugin_root / "marketplace.json").write_text("{}", encoding="utf-8")
    source_plugin = plugin_root / "mcp-opensa"
    source_plugin.mkdir()
    (source_plugin / "plugin.json").write_text("{}", encoding="utf-8")

    integration = LocalMcpIntegration(
        plugin_root=plugin_root,
        config_path=tmp_path / "missing" / "config.toml",
        marketplace_root=tmp_path / "home" / ".agents" / "plugins",
    )

    assert integration.ensure_installed() is True
    assert integration.is_installed()
    assert not (tmp_path / "missing" / "config.toml").exists()
