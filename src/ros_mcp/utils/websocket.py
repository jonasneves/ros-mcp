import base64
import json
import os
import sys
import threading

import cv2
import numpy as np
import websocket


def extract_service_failure_error(response: dict) -> dict | None:
    """Return an error dict if the rosbridge response indicates a service failure, else None."""
    if "result" in response and not response["result"]:
        error_msg = response.get("values", {}).get("message", "Service call failed")
        return {"error": f"Service call failed: {error_msg}"}
    if "error" in response:
        return {"error": f"WebSocket error: {response['error']}"}
    return None


def extract_provider_node(response: dict) -> str | None:
    """Extract a provider node name from a rosbridge service_node response.

    Handles both ``values`` and ``result`` response formats.
    """
    for key in ("values", "result"):
        data = response.get(key)
        if isinstance(data, dict):
            node = data.get("node", "")
            if node:
                return node
    return None


def parse_json(raw: str | bytes | None) -> dict | None:
    """Safely parse JSON from string or bytes, returning a dict or None."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


_COMPRESSED_FORMATS = ("jpeg", "jpg", "png", "bmp", "compressed")

# sensor_msgs/Image standard encodings (substring-matched to cover variants like bayer_rggb8)
_IMAGE_ENCODINGS = (
    "rgb8", "rgba8", "bgr8", "bgra8", "mono8", "mono16",
    "8uc1", "8uc3", "8uc4", "16uc1", "bayer", "yuv",
)


def is_image_like(msg_content: dict) -> bool:
    """Check if a message looks like an image by examining its fields.

    Distinguishes images from other binary-data messages (PointCloud2, ByteMultiArray)
    by requiring image-specific fields and valid sensor_msgs/Image encodings.
    """
    if not isinstance(msg_content, dict):
        return False

    # CompressedImage: has data + format with a known image format
    if "data" in msg_content and "format" in msg_content:
        format_str = msg_content.get("format", "").lower()
        if any(fmt in format_str for fmt in _COMPRESSED_FORMATS):
            return True

    # Raw Image: requires data, width, height, encoding
    required_fields = {"data", "width", "height", "encoding"}
    if not required_fields.issubset(msg_content.keys()):
        return False

    if not isinstance(msg_content.get("width"), int) or not isinstance(
        msg_content.get("height"), int
    ):
        return False

    encoding = msg_content.get("encoding", "").lower()
    return any(enc in encoding for enc in _IMAGE_ENCODINGS)


def parse_image(raw: str | bytes | None) -> dict | None:
    """Decode an image message (JSON with base64 data) and save it as JPEG."""
    if raw is None:
        return None

    try:
        result = json.loads(raw)
        msg = result["msg"]
    except (json.JSONDecodeError, KeyError):
        print("[Image] Invalid JSON or missing 'msg' field.", file=sys.stderr)
        return None

    data_b64 = msg.get("data")
    if not data_b64:
        print("[Image] Missing 'data' field in message.", file=sys.stderr)
        return None

    os.makedirs("./camera", exist_ok=True)

    img_format = msg.get("format")
    print(f"[Image] Format: {img_format}", file=sys.stderr)

    if img_format and any(fmt in img_format.lower() for fmt in _COMPRESSED_FORMATS):
        return _handle_compressed_image(data_b64, result)

    height, width, encoding = msg.get("height"), msg.get("width"), msg.get("encoding")
    if not all([height, width, encoding]):
        print("[Image] Missing required fields for raw image.", file=sys.stderr)
        return None

    return _handle_raw_image(data_b64, height, width, encoding, msg, result)


def _handle_compressed_image(data_b64: str, result: dict) -> dict | None:
    """Handle compressed image data (JPEG/PNG already encoded)."""
    path = "./camera/received_image.jpeg"
    image_bytes = base64.b64decode(data_b64)

    with open(path, "wb") as f:
        f.write(image_bytes)

    print(f"[Image] Saved CompressedImage to {path}", file=sys.stderr)
    return result


def _handle_raw_image(
    data_b64: str, height: int, width: int, encoding: str, msg: dict, result: dict
) -> dict | None:
    """Handle raw image data (needs decoding and conversion)."""
    image_bytes = base64.b64decode(data_b64)

    dtype = np.uint16 if encoding.lower() in ("mono16", "16uc1") else np.uint8
    img_np = np.frombuffer(image_bytes, dtype=dtype)

    try:
        img_cv = _decode_image_data(img_np, height, width, encoding, msg)
        if img_cv is None:
            return None
    except ValueError as e:
        print(f"[Image] Reshape error: {e}", file=sys.stderr)
        return None

    if not cv2.imwrite("./camera/received_image.jpeg", img_cv, [cv2.IMWRITE_JPEG_QUALITY, 95]):
        return None

    print("[Image] Saved raw Image to ./camera/received_image.jpeg", file=sys.stderr)
    return result


def _decode_image_data(
    img_np: np.ndarray, height: int, width: int, encoding: str, msg: dict
) -> np.ndarray | None:
    """Decode raw image data based on encoding type."""
    enc = encoding.lower()

    if enc == "rgb8":
        return cv2.cvtColor(img_np.reshape((height, width, 3)), cv2.COLOR_RGB2BGR)

    if enc == "bgr8":
        return img_np.reshape((height, width, 3))

    if enc == "mono8":
        return img_np.reshape((height, width))

    if enc in ("mono16", "16uc1"):
        img16 = img_np.reshape((height, width))
        try:
            if int(msg.get("is_bigendian", 0)) == 1:
                img16 = img16.byteswap().newbyteorder()
        except (ValueError, TypeError):
            pass
        # Normalize 16-bit depth to 8-bit for saving/preview
        return cv2.normalize(img16, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

    print(f"[Image] Unsupported encoding: {encoding}", file=sys.stderr)
    return None


def parse_input(
    raw: str | bytes | None, expects_image: bool | None = None
) -> tuple[dict | None, bool]:
    """Parse input data with optional image hint for optimized handling.

    Returns (parsed_data, was_parsed_as_image). When ``expects_image`` is True,
    tries image parsing first with JSON fallback. When False, parses as JSON only.
    When None, auto-detects based on message fields.
    """
    if raw is None:
        return None, False

    parsed_data = parse_json(raw)
    if parsed_data is None:
        return None, False

    if expects_image is True:
        return _handle_image_hint(raw, parsed_data)
    if expects_image is False:
        return parsed_data, False
    return _handle_auto_detection(raw, parsed_data)


def _handle_image_hint(raw: str | bytes, parsed_data: dict) -> tuple[dict | None, bool]:
    """Handle explicit image hint - try image parsing first."""
    result = parse_image(raw)
    if result is not None:
        return result, True
    return parsed_data, False


def _handle_auto_detection(raw: str | bytes, parsed_data: dict) -> tuple[dict | None, bool]:
    """Handle auto-detection - check if message looks like an image."""
    if parsed_data.get("op") == "publish":
        msg_content = parsed_data.get("msg", {})
        if is_image_like(msg_content):
            result = parse_image(raw)
            if result is not None:
                return result, True

    return parsed_data, False


class WebSocketManager:
    def __init__(self, ip: str, port: int, default_timeout: float = 2.0):
        self.ip = ip
        self.port = port
        self.default_timeout = default_timeout
        self.ws = None
        self.lock = threading.RLock()

    def set_ip(self, ip: str, port: int):
        self.ip = ip
        self.port = port
        print(f"[WebSocket] IP set to {self.ip}:{self.port}", file=sys.stderr)

    def connect(self) -> str | None:
        """Connect to rosbridge. Returns None on success, or an error message."""
        with self.lock:
            if self.ws is not None and self.ws.connected:
                return None

            try:
                url = f"ws://{self.ip}:{self.port}"
                self.ws = websocket.create_connection(url, timeout=self.default_timeout)
                print(
                    f"[WebSocket] Connected ({self.default_timeout}s timeout)", file=sys.stderr
                )
                return None
            except Exception as e:
                error_msg = f"[WebSocket] Connection error: {e}"
                print(error_msg, file=sys.stderr)
                self.ws = None
                return error_msg

    def send(self, message: dict) -> str | None:
        """Send a JSON-serializable message. Returns None on success, or an error message."""
        with self.lock:
            conn_error = self.connect()
            if conn_error:
                return conn_error

            if not self.ws:
                return "[WebSocket] Not connected, send aborted."

            try:
                self.ws.send(json.dumps(message))
                return None
            except TypeError as e:
                error_msg = f"[WebSocket] JSON serialization error: {e}"
                print(error_msg, file=sys.stderr)
                self.close()
                return error_msg
            except Exception as e:
                error_msg = f"[WebSocket] Send error: {e}"
                print(error_msg, file=sys.stderr)
                self.close()
                return error_msg

    def receive(self, timeout: float | None = None) -> str | bytes | None:
        """Receive a single message from rosbridge, or None on timeout/error."""
        with self.lock:
            self.connect()
            if not self.ws:
                return None

            try:
                self.ws.settimeout(timeout if timeout is not None else self.default_timeout)
                return self.ws.recv()
            except Exception as e:
                print(f"[WebSocket] Receive error or timeout: {e}", file=sys.stderr)
                self.close()
                return None

    def request(self, message: dict, timeout: float | None = None) -> dict:
        """Send a request to rosbridge and return the parsed response.

        Returns ``{"error": ...}`` on connection, send, receive, or parse failure.
        """
        send_error = self.send(message)
        if send_error:
            return {"error": send_error}

        response = self.receive(timeout=timeout)
        if response is None:
            return {"error": "no response or timeout from rosbridge"}

        parsed = parse_json(response)
        if parsed is None:
            print(f"[WebSocket] JSON decode error for response: {response}", file=sys.stderr)
            return {"error": "invalid_json", "raw": response}
        return parsed

    def close(self):
        with self.lock:
            if self.ws is None:
                return
            try:
                self.ws.close()
                print("[WebSocket] Closed", file=sys.stderr)
            except Exception as e:
                print(f"[WebSocket] Close error: {e}", file=sys.stderr)
            finally:
                self.ws = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
