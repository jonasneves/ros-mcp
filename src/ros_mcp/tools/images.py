import io
import os

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from mcp.types import ImageContent, ToolAnnotations
from PIL import Image as PILImage


def convert_expects_image_hint(expects_image: str) -> bool | None:
    """Convert string-based expects_image hint to boolean for internal use.

    Args:
        expects_image: "true" (prioritize image parsing), "false" (skip image
            detection), or "auto" / any other value (auto-detect).

    Returns:
        True, False, or None (auto-detect) for use with parse_input.
    """
    if expects_image == "true":
        return True
    if expects_image == "false":
        return False
    return None


def _encode_image_to_imagecontent(image) -> ImageContent:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    img_bytes = buffer.getvalue()
    img_obj = Image(data=img_bytes, format="jpeg")
    return img_obj.to_image_content()


def register_image_tools(
    mcp: FastMCP,
) -> None:
    @mcp.tool(
        description=(
            "Analyze a previously received image that was saved by any ROS operation.\n"
            "Images can be received from:\n"
            "- Any topic containing image data (not just topics with 'Image' in the name)\n"
            "- Service responses containing image data\n"
            "- subscribe_once() or subscribe_for_duration() operations\n"
            "Use this tool to analyze the saved image after receiving it from any source.\n"
        ),
        annotations=ToolAnnotations(
            title="Analyze Previously Received Image",
            readOnlyHint=True,
        ),
    )
    def analyze_previously_received_image(
        image_path: str = "./camera/received_image.jpeg",
    ) -> ImageContent:  # type: ignore  # FastMCP wraps return value at runtime
        if not os.path.exists(image_path):
            return {"error": f"No image found at {image_path}"}  # type: ignore[return-value]  # error dict is valid MCP return
        img = PILImage.open(image_path)
        return _encode_image_to_imagecontent(img)
