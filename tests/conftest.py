import pytest
from PIL import Image


@pytest.fixture
def face_image():
    return Image.new("RGB", (64, 96), (200, 150, 120))


class FakeBackend:
    """Records payloads and returns a solid image per call."""

    def __init__(self, fail_on: int | None = None):
        self.payloads = []
        self.interrupted = False
        self.fail_on = fail_on

    def img2img(self, payload):
        self.payloads.append(payload)
        if self.fail_on is not None and len(self.payloads) == self.fail_on:
            return None
        return Image.new("RGB", (64, 96), (len(self.payloads) * 8 % 255, 0, 0))

    def interrupt(self):
        self.interrupted = True


@pytest.fixture
def fake_backend():
    return FakeBackend()
