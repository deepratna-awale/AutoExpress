# Lives in the shared core so every integration uses the same data.
import sys

from emotica_core import expression_sets

sys.modules[__name__] = expression_sets
