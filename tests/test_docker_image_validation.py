from docker_image_validation import validate_docker_images
import docker_image_validation


def _config(image):
    return {
        "services": [
            {
                "name": "web",
                "image": image,
                "port": 80,
                "public": True,
                "replicas": 1,
            }
        ]
    }


def test_placeholder_dockerhub_username_image_fails():
    result = validate_docker_images(_config("YOUR_DOCKERHUB_USERNAME/app:latest"))

    assert result["valid"] is False
    assert "YOUR_DOCKERHUB_USERNAME" in result["errors"][0]


def test_empty_image_fails():
    result = validate_docker_images(_config(""))

    assert result["valid"] is False
    assert "empty" in result["errors"][0]


def test_image_without_tag_warns():
    result = validate_docker_images(_config("dockertalha19/fyp-books-api"))

    assert result["valid"] is True
    assert result["warnings"]
    assert "no explicit tag" in result["warnings"][0]


def test_valid_tagged_docker_image_passes():
    result = validate_docker_images(_config("dockertalha19/fyp-books-api:latest"))

    assert result["valid"] is True
    assert result["check_type"] == "syntax_only"
    assert result["errors"] == []
    assert result["warnings"] == []


def test_registry_check_disabled_does_not_call_requests(monkeypatch):
    monkeypatch.setenv("ENABLE_IMAGE_REGISTRY_CHECK", "false")
    monkeypatch.setattr(
        docker_image_validation.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no internet")),
    )

    result = validate_docker_images(_config("dockertalha19/fyp-books-api:latest"))

    assert result["valid"] is True
    assert result["check_type"] == "syntax_only"


def test_registry_check_enabled_uses_mocked_request(monkeypatch):
    class Response:
        status_code = 200

    monkeypatch.setenv("ENABLE_IMAGE_REGISTRY_CHECK", "true")
    monkeypatch.setattr(docker_image_validation.requests, "get", lambda *args, **kwargs: Response())

    result = validate_docker_images(_config("dockertalha19/fyp-books-api:latest"))

    assert result["valid"] is True
    assert result["check_type"] == "registry_checked"
