"""Loads the repository the way ComfyUI does (as a package) with stand-ins for ComfyUI modules."""

import importlib.util
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = "autoexpress_custom_node"


@pytest.fixture
def comfy(monkeypatch, tmp_path):
    lora_dir = tmp_path / "loras"
    lora_dir.mkdir()
    applied = []

    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_filename_list = lambda kind: ["ponyDiffusionV6XL.safetensors", "flux1-dev.safetensors"]
    folder_paths.get_folder_paths = lambda kind: [str(lora_dir)]
    folder_paths.get_output_directory = lambda: str(tmp_path / "output")

    def get_full_path(kind, name):
        path = lora_dir / name
        return str(path) if path.is_file() else None

    folder_paths.get_full_path = get_full_path

    comfy_pkg = types.ModuleType("comfy")
    comfy_sd = types.ModuleType("comfy.sd")
    comfy_utils = types.ModuleType("comfy.utils")
    comfy_utils.load_torch_file = lambda path, safe_load=True: {"path": path}

    def load_lora_for_models(model, clip, lora, strength_model, strength_clip):
        applied.append((pathlib.Path(lora["path"]).name, strength_model))
        return model + "+lora", clip + "+lora"

    comfy_sd.load_lora_for_models = load_lora_for_models
    comfy_pkg.sd, comfy_pkg.utils = comfy_sd, comfy_utils

    torch = types.ModuleType("torch")
    torch.Tensor = object  # only used in annotations here; tensor maths needs real torch

    for name, module in {
        "folder_paths": folder_paths,
        "comfy": comfy_pkg,
        "comfy.sd": comfy_sd,
        "comfy.utils": comfy_utils,
        "torch": torch,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location(
        PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    package = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, PACKAGE, package)
    spec.loader.exec_module(package)
    yield types.SimpleNamespace(nodes=package.NODE_CLASS_MAPPINGS, lora_dir=lora_dir, applied=applied)

    for name in [m for m in sys.modules if m.startswith(PACKAGE)]:
        sys.modules.pop(name)


def test_nodes_are_registered(comfy):
    assert set(comfy.nodes) == {
        "AutoExpressExpressionPrompts",
        "AutoExpressExpressionPrompt",
        "AutoExpressExpressionLoras",
        "AutoExpressEditInstructions",
        "AutoExpressSaveExpressions",
        "AutoExpressSpriteSheet",
    }
    for node in comfy.nodes.values():
        node.INPUT_TYPES()


def test_expression_prompts_auto_family_from_checkpoint(comfy):
    node = comfy.nodes["AutoExpressExpressionPrompts"]()
    prompts, names, negative, count = node.build(
        "auto", "1girl", "lowres", "joy, anger", ckpt_name="ponyDiffusionV6XL.safetensors",
        lora_trigger="cinematic expression style",
    )

    assert names == ["anger", "joy"] and count == 2
    assert prompts[0].startswith("score_9, score_8_up, score_7_up, 1girl, cinematic expression style, ")
    assert negative == "lowres, score_4, score_5, score_6"


def test_expression_loras_applies_installed_files(comfy):
    (comfy.lora_dir / "AutoExpress-expressions-pony.safetensors").write_bytes(b"x")
    node = comfy.nodes["AutoExpressExpressionLoras"]()

    model, clip, trigger = node.apply(
        "model", "clip", "ponyDiffusionV6XL.safetensors", "auto", "auto", download_missing=False
    )

    assert comfy.applied == [("AutoExpress-expressions-pony.safetensors", 0.6)]
    assert (model, clip) == ("model+lora", "clip+lora")
    assert trigger == "cinematic expression style"


def test_expression_loras_skips_missing_files(comfy):
    node = comfy.nodes["AutoExpressExpressionLoras"]()
    model, clip, trigger = node.apply("model", "clip", "", "auto", "flux", download_missing=False)
    assert comfy.applied == [] and (model, clip, trigger) == ("model", "clip", "")


def test_edit_instructions_node(comfy):
    node = comfy.nodes["AutoExpressEditInstructions"]()
    instructions, names, count, denoise = node.build("joy, anger", "illustration", -1.0, "Keep the glasses on.")
    assert names == ["anger", "joy"] and count == 2 and denoise == [0.85, 0.85]
    assert all(text.startswith("Change only the facial expression.") and "Keep the glasses on." in text for text in instructions)
    with pytest.raises(ValueError):
        node.build("smug", "illustration", -1.0, "")
    photo, _, _, photo_denoise = node.build("joy, anger", "photo", 0.03, "")
    assert photo[0] == "anger. Keep it a realistic photo with natural skin color."
    assert photo_denoise == [pytest.approx(0.224), pytest.approx(0.224)]
    posed, _, _, posed_denoise = node.build("anger", "photo", 0.5, "", pose=True)
    assert "The arms are crossed over the chest." in posed[0] and posed_denoise == [0.9]


def test_nodes_apply_intensity(comfy):
    prompts, *_ = comfy.nodes["AutoExpressExpressionPrompts"]().build("danbooru", "1girl", "", "joy", "", "", 0.25)
    assert prompts[0].startswith("(") is False and ":0.8)" in prompts[0]
    plain, *_ = comfy.nodes["AutoExpressExpressionPrompts"]().build("danbooru", "1girl", "", "joy", "", "", -1.0)
    assert ":0.8)" not in plain[0]


class _Tensor:
    def __init__(self, *shape):
        self.shape = shape


class _Model:
    """A MODEL stand-in: ModelPatcher.model is the BaseModel holding model_config and the weights."""

    def __init__(self, config=None, weights=None):
        self.model = types.SimpleNamespace(
            model_config=config, state_dict=lambda: {key: _Tensor(*shape) for key, shape in (weights or {}).items()}
        )

    def __add__(self, other):
        return "model" + other


def test_expression_loras_reads_sd15_from_unnamed_checkpoint(comfy):
    (comfy.lora_dir / "AutoExpress-expressions-sd15.safetensors").write_bytes(b"x")
    model = _Model(weights={"diffusion_model.input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight": (320, 768)})

    comfy.nodes["AutoExpressExpressionLoras"]().apply(
        model, "clip", "AAM_Anylora_AnimeMix.safetensors", "auto", "auto", download_missing=False
    )

    assert comfy.applied and comfy.applied[0][0] == "AutoExpress-expressions-sd15.safetensors"


def test_model_base_architecture_from_config(comfy):
    import importlib

    nodes = importlib.import_module("autoexpress_custom_node.autoexpress_comfy.nodes")
    SDXL = type("SDXL", (), {})
    SSD1B = type("SSD1B", (SDXL,), {})
    Flux = type("Flux", (), {})
    FluxSchnell = type("FluxSchnell", (Flux,), {})

    assert nodes.model_base_architecture(_Model(SSD1B())) == "sdxl"
    assert nodes.model_base_architecture(_Model(FluxSchnell())) == "flux"
    assert nodes.model_base_architecture(_Model(type("SD15", (), {})())) == "sd15"
    assert nodes.model_base_architecture("model") is None
