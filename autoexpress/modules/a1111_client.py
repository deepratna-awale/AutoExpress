# The client now lives in the shared core so every integration uses the same code.
from autoexpress_core.backends.a1111_api import A1111Client

__all__ = ["A1111Client"]
