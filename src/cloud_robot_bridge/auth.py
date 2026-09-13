"""Simple local auth service for dashboard access."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    username: str
    password: str
    role: str = "operator"


class AuthService:
    def __init__(self, users: list[User] | None = None) -> None:
        default_username = os.getenv("COMMAND_CENTER_USERNAME", "admin")
        default_password = os.getenv("COMMAND_CENTER_PASSWORD", "admin123")
        default_role = os.getenv("COMMAND_CENTER_ROLE", "admin")
        self.users = users or [User(default_username, default_password, default_role)]
        self.tokens: dict[str, str] = {}
        self.token_roles: dict[str, str] = {}

    def _user_by_name(self, username: str) -> User | None:
        for user in self.users:
            if user.username == username:
                return user
        return None

    def validate(self, username: str, password: str) -> bool:
        user = self._user_by_name(username)
        if user is None:
            return False
        return user.password == password

    def issue_token(self, username: str) -> str:
        user = self._user_by_name(username)
        if user is None:
            raise ValueError(f"Unknown user: {username}")
        token = secrets.token_urlsafe(32)
        self.tokens[token] = username
        self.token_roles[token] = user.role
        return token

    def validate_token(self, token: str | None, required_role: str | None = None) -> bool:
        if not token:
            return False
        if token not in self.tokens:
            return False
        if required_role is None:
            return True
        return self.token_roles.get(token) == required_role

    def username_for_token(self, token: str | None) -> str | None:
        if not token:
            return None
        return self.tokens.get(token)

    def role_for_token(self, token: str | None) -> str | None:
        if not token:
            return None
        return self.token_roles.get(token)
