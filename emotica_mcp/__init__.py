"""MCP server for Emotica."""

import os as _os

# Settings made under the project's former name (AUTOEXPRESS_*) keep working.
for _key, _value in list(_os.environ.items()):
    if _key.startswith("AUTOEXPRESS_"):
        _os.environ.setdefault("EMOTICA_" + _key[len("AUTOEXPRESS_"):], _value)
