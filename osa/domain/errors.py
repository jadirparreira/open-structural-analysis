"""Erros próprios do domínio, independentes da interface."""


class DomainError(ValueError):
    """Uma operação violou uma regra do modelo estrutural."""


class DuplicateNodeCoordinatesError(DomainError):
    pass


class DuplicateMemberError(DomainError):
    pass


class EntityNotFoundError(DomainError):
    pass
