"""API errors with a stable machine-readable `code` (the frontend switches on it) and a message."""


class ApiProblem(Exception):  # noqa: N818 - "problem" as in RFC 9457
    def __init__(self, status: int, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.status = status
        self.code = code
        self.message = message


def not_found() -> ApiProblem:
    """Also used for ids that exist in another school: never reveal that they exist."""
    return ApiProblem(404, "not_found", "Not found.")


def unauthenticated() -> ApiProblem:
    return ApiProblem(401, "unauthenticated", "Please sign in again.")


def forbidden() -> ApiProblem:
    return ApiProblem(403, "forbidden", "You don't have access to this.")


def conflict(code: str, message: str) -> ApiProblem:
    return ApiProblem(409, code, message)


AUTH_SERVICE_DOWN = "Couldn't reach the sign-in service. Nothing was changed; please try again."
