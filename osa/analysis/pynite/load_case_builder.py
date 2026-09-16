"""Tradução futura de ações e casos de carga para PyNite."""


class LoadCaseBuilder:
    def apply(self, target, model) -> None:
        for _action in model.actions.values():
            raise NotImplementedError("A tradução de ações será implementada com os tipos de carga.")
