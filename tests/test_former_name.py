"""Things set up under the project's former name (AutoExpress) keep working."""

import json
import os
import runpy
import subprocess
import sys

import pytest

from emotica_core import overrides
from emotica_core.live2d import puppet


def test_old_environment_variables_are_read():
    env = {**os.environ, "AUTOEXPRESS_PORT": "6123", "AUTOEXPRESS_HOST": "1.2.3.4", "EMOTICA_HOST": "5.6.7.8"}
    env.pop("EMOTICA_PORT", None)
    code = "import os, emotica_core; print(os.environ['EMOTICA_PORT'], os.environ['EMOTICA_HOST'])"
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.split()
    assert out == ["6123", "5.6.7.8"]


def test_old_overrides_file_is_read_then_replaced(tmp_path):
    saved = {"joy": {"prompt": "big grin"}}
    (tmp_path / overrides.LEGACY_FILE_NAME).write_text(json.dumps(overrides.document(saved)))
    assert overrides.load(tmp_path) == saved
    overrides.save(tmp_path, saved)
    assert (tmp_path / overrides.FILE_NAME).is_file()
    assert not (tmp_path / overrides.LEGACY_FILE_NAME).exists()


def test_old_puppets_still_load(tmp_path):
    path = tmp_path / "old.puppet.model.json"
    path.write_text(json.dumps({"Type": "AutoExpress Puppet"}))
    assert puppet.load(path)["Type"] == "AutoExpress Puppet"


def test_old_mcp_module_runs_the_new_server():
    pytest.importorskip("mcp")
    import autoexpress_mcp
    import emotica_mcp.__main__

    assert runpy.run_module("autoexpress_mcp.__main__", run_name="not_main")["main"] is emotica_mcp.__main__.main
    assert autoexpress_mcp.__doc__
