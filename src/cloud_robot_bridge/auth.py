"""Simple local auth service for dashboard access."""

from __future__ import annotations

import os
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

    def validate(self, username: str, password: str) -> bool:
        for user in self.users:
            if user.username == username and user.password == password:
                return True
        return False
