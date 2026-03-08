from __future__ import annotations


class BolnaError(Exception):
    pass


class BolnaAuthError(BolnaError):
    pass


class BolnaRequestError(BolnaError):
    def __init__(self, message: str, *, status_code: int | None = None, details: object | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details

