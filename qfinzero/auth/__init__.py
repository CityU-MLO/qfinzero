"""Authentication for the QFinZero hub: users, roles, API keys, sessions.

See :mod:`qfinzero.auth.store` (data) and :mod:`qfinzero.auth.middleware`
(policy). CLI: ``qfz-auth``.
"""

from .middleware import AuthMiddleware, auth_mode, required_role
from .store import ROLES, AuthError, AuthStore, User

__all__ = ["AuthMiddleware", "AuthStore", "AuthError", "User", "ROLES", "auth_mode",
           "required_role"]
