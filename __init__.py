"""
Entry point for hosts that import the repository root as a package:

- ComfyUI, when the repository is cloned into ComfyUI/custom_nodes (or
  installed from the Comfy Registry / ComfyUI Manager).
- InvokeAI, when the repository is cloned into <INVOKEAI_ROOT>/nodes (or
  installed by URL from the Custom Node Manager).

A1111-style WebUIs never import it, and outside those hosts (tests, the
standalone app) it registers nothing.
"""

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

try:
    import folder_paths  # noqa: F401  only importable inside ComfyUI
except ImportError:
    try:
        import invokeai.invocation_api  # noqa: F401  only importable inside InvokeAI
    except ImportError:
        pass
    else:
        from .invokeai_nodes.autoexpress import AutoExpressExpressionPromptsInvocation  # noqa: F401
else:
    from .autoexpress_comfy import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
