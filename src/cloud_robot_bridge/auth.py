"""Simple local auth service for dashboard access."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    username: str
    password: str


class AuthService:
    def __init__(self, users: list[User] | None = None) -> None:
        default_username = os.getenv("COMMAND_CENTER_USERNAME", "admin")
        default_password = os.getenv("COMMAND_CENTER_PASSWORD", "admin123")
        self.users = users or [User(default_username, default_password)]
        self.tokens: dict[str, str] = {}

    def validate(self, username: str, password: str) -> bool:
        for user in self.users:
            if user.username == username and user.password == password:
                return True
        return False

    def issue_token(self, username: str) -> str:
        if not any(user.username == username for user in self.users):
            raise ValueError(f"Unknown user: {username}")
        token = secrets.token_urlsafe(32)
        self.tokens[token] = username
        return token

    def validate_token(self, token: str | None) -> bool:
        if not token:
            return False
        return token in self.tokens

    def username_for_token(self, token: str | None) -> str | None:
        if not token:
            return None
        return self.tokens.get(token)
