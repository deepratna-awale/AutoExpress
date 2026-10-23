# Lives in the shared core so every integration uses the same data.
import sys

from autoexpress_core import expression_loras

sys.modules[__name__] = expression_loras
