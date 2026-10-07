from pathlib import Path

from osa.integrations import LocalMcpIntegration


def test_local_mcp_integration_registers_and_updates_the_plugin(tmp_path: Path):
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    (plugin_root / "marketplace.json").write_text("{}", encoding="utf-8")
    source_plugin = plugin_root / "mcp-opensa"
    source_plugin.mkdir()
    (source_plugin / "plugin.json").write_text("{}", encoding="utf-8")
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
    assert integration.is_installed() is True

    assert integration.ensure_installed() is False
    second = config_path.read_text(encoding="utf-8")
    assert second == first


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
