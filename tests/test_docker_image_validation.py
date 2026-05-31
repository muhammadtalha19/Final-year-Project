from docker_image_validation import validate_docker_images


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
    assert result["errors"] == []
    assert result["warnings"] == []
