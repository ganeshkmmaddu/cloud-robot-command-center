from cloud_robot_bridge.auth import AuthService


def test_auth_service_validates_default_credentials() -> None:
    service = AuthService()

    assert service.validate("admin", "admin123") is True
    assert service.validate("admin", "wrong") is False
