"""
ComfyUI entry point. ComfyUI imports this file when the repository is cloned
into ComfyUI/custom_nodes. Other WebUIs never import it, and outside ComfyUI
(tests, the standalone app) it registers nothing.
"""

try:
    import folder_paths  # noqa: F401  only importable inside ComfyUI
except ImportError:
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}
else:
    from .autoexpress_comfy import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
