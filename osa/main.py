"""Ponto de entrada estável do executável."""

from osa.app import run


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
