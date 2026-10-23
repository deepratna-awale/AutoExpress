"""
InvokeAI community node for AutoExpress.

Copy or symlink this folder into <INVOKEAI_ROOT>/nodes/ and restart InvokeAI.
The node needs the autoexpress_core package: a symlink to this repository
finds it automatically, a plain copy needs `pip install` of the repository
into InvokeAI's environment.
"""

from .expression_prompts import AutoExpressExpressionPromptsInvocation

__all__ = ["AutoExpressExpressionPromptsInvocation"]
