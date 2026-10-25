"""
Background removal for exported expressions, so only the character is left.

Uses rembg, which is optional: the WebUI integrations don't need it, and the
standalone app installs it with its "standalone" extra (pyproject.toml). Each rembg model is
downloaded once on first use (about 170 MB) and then kept in memory for the
next image.
"""

import os
import threading

from PIL import Image

# isnet-anime is trained on anime and illustration characters; u2net_human_seg
# keeps the whole person in a photo. Both take a few seconds per image on a
# CPU. The BiRefNet models cut hair a little cleaner but take 20 to 70 seconds
# and up to 12 GB of RAM per image on a CPU; pick one with MODEL_ENV on a GPU.
ILLUSTRATION_MODEL = "isnet-anime"
PHOTO_MODEL = "u2net_human_seg"
MODEL_ENV = "AUTOEXPRESS_BACKGROUND_MODEL"
INSTALL_COMMAND = 'pip install "rembg[cpu]"'

_sessions: dict = {}
_lock = threading.Lock()


def available() -> bool:
    """True when rembg and its ONNX runtime can be imported."""
    try:
        import rembg  # noqa: F401
    except ImportError:
        return False
    return True


def model_for(photo: bool) -> str:
    """The rembg model for this kind of image. AUTOEXPRESS_BACKGROUND_MODEL overrides both."""
    return os.environ.get(MODEL_ENV, "").strip() or (PHOTO_MODEL if photo else ILLUSTRATION_MODEL)


def _session(model: str):
    from rembg import new_session

    with _lock:
        if model not in _sessions:
            _sessions[model] = new_session(model)
        return _sessions[model]


def remove_background(image: Image.Image, model: str = ILLUSTRATION_MODEL) -> Image.Image:
    """
    Cut the character out of image.

    Returns:
        Image.Image: An RGBA image with a transparent background.

    Raises:
        ImportError: rembg isn't installed.
    """
    from rembg import remove

    result = remove(image.convert("RGB"), session=_session(model), post_process_mask=True)
    return result.convert("RGBA")
