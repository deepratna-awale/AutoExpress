"""Loads the repository the way InvokeAI's node loader does, with stand-ins for invokeai.invocation_api."""

import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "AutoExpress"  # InvokeAI names the pack after the cloned folder


class _Model:
    def __init__(self, **values):
        for cls in reversed(type(self).__mro__):
            for name in getattr(cls, "__annotations__", {}):
                if hasattr(cls, name):
                    setattr(self, name, getattr(cls, name))
        for name, value in values.items():
            setattr(self, name, value)


@pytest.fixture
def invoke_pack(monkeypatch):
    api = types.ModuleType("invokeai.invocation_api")
    api.BaseInvocation = type("BaseInvocation", (_Model,), {})
    api.BaseInvocationOutput = type("BaseInvocationOutput", (_Model,), {})
    api.InvocationContext = object
    api.UIComponent = types.SimpleNamespace(Textarea="textarea")
    api.InputField = lambda default=None, **kwargs: default
    api.OutputField = lambda **kwargs: None
    api.invocation = lambda *args, **kwargs: (lambda cls: cls)
    api.invocation_output = lambda *args, **kwargs: (lambda cls: cls)
    invokeai = types.ModuleType("invokeai")
    invokeai.invocation_api = api

    monkeypatch.setitem(sys.modules, "invokeai", invokeai)
    monkeypatch.setitem(sys.modules, "invokeai.invocation_api", api)
    monkeypatch.delitem(sys.modules, "folder_paths", raising=False)
    for name in [n for n in sys.modules if n == PACKAGE or n.startswith(PACKAGE + ".")]:
        monkeypatch.delitem(sys.modules, name)

    # Same calls as invokeai/app/invocations/load_custom_nodes.py
    spec = importlib.util.spec_from_file_location(PACKAGE, (ROOT / "__init__.py").absolute())
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_root_init_registers_the_invokeai_node(invoke_pack):
    assert invoke_pack.NODE_CLASS_MAPPINGS == {}
    node = invoke_pack.AutoExpressExpressionPromptsInvocation(prompt_style="pony", expressions="joy, anger")
    out = node.invoke(context=None)
    assert sorted(out.names) == ["anger", "joy"]
    assert len(out.prompts) == 2 and all("score_9" in p for p in out.prompts)


def test_root_init_registers_nothing_outside_a_host(monkeypatch):
    monkeypatch.delitem(sys.modules, "folder_paths", raising=False)
    monkeypatch.setitem(sys.modules, "invokeai", None)
    spec = importlib.util.spec_from_file_location("autoexpress_plain", ROOT / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.NODE_CLASS_MAPPINGS == {}
    assert not hasattr(module, "AutoExpressExpressionPromptsInvocation")
