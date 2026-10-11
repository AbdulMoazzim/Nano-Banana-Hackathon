"""Image preparation and vision-model integration (implementation comes next)."""


class VisionError(Exception):
    """Raised when image analysis cannot be completed or parsed."""


def analyze_image(image_bytes: bytes, description: str | None = None) -> dict:
    """Analyze an image.

    This is an intentional scaffold: image validation and the OpenRouter request
    will be added in the next implementation milestone.
    """
    raise NotImplementedError("Vision-model integration has not been configured yet.")
