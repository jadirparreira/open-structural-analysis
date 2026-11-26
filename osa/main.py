"""Ponto de entrada estável do executável."""
import sys


def main() -> None:
    if '--mcp-stdio' in sys.argv[1:]:
        # Ponte MCP para clientes stdio (Claude Code/Desktop); não abre a interface.
        try:
            import pyi_splash
            pyi_splash.close()
        except ImportError:
            pass
        from osa.mcp.stdio_bridge import main as run_stdio_bridge
        raise SystemExit(run_stdio_bridge())
    if '--mcp-self-test' in sys.argv[1:]:
        from osa.mcp.self_test import run_self_test
        index = sys.argv.index('--mcp-self-test')
        if index + 1 >= len(sys.argv):
            raise SystemExit('--mcp-self-test exige o caminho do relatório JSON.')
        try:
            import pyi_splash
            pyi_splash.close()
        except ImportError:
            pass
        raise SystemExit(run_self_test(sys.argv[index + 1]))
    from osa.app import run
    raise SystemExit(run())


if __name__ == '__main__':
    main()
