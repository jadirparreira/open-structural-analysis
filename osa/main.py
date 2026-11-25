"""Ponto de entrada estável do executável."""
import sys


def main() -> None:
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
