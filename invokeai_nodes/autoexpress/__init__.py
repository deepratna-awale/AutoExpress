"""
InvokeAI community node for AutoExpress.

Installing the repository into <INVOKEAI_ROOT>/nodes/ (Custom Node Manager or
git clone) loads this package through the repository's root __init__.py.
You can also copy or symlink just this folder into nodes/.
The node needs the autoexpress_core package: a symlink to this repository
finds it automatically, a plain copy needs `pip install` of the repository
into InvokeAI's environment.
"""

from .expression_prompts import AutoExpressExpressionPromptsInvocation

__all__ = ["AutoExpressExpressionPromptsInvocation"]
