"""Sprite poses: one gesture per expression, made with Qwen-Image-Edit in either method."""

import pytest

from autoexpress_core import ExpressionGenerator, instruction_edit
from autoexpress_core.backends.comfyui_api import ComfyUIClient

from test_instruction_edit import edit_routes
from test_remote_backends import ComfySession


def prompts(backend):
    return [kw["json"]["prompt"] for m, p, kw in backend.session.calls if p == "/prompt"]


def test_every_expression_has_a_pose():
    assert list(instruction_edit.get_poses()) == instruction_edit.instruction_names()
    assert instruction_edit.get_poses(["anger"]) == {"anger": "The arms are crossed over the chest."}


def test_pose_instruction_keeps_the_outfit_and_framing():
    text = instruction_edit.build_instruction("anger", pose=True)
    assert text.startswith("Change the facial expression and the pose. The character is furious")
    assert "The arms are crossed over the chest." in text
    assert "do not add, remove or change any clothing" in text and "same stance, body position and camera framing" in text
    # The face-only wording would forbid the pose.
    assert "Change only the facial expression" not in text and "head position and angle, pose" not in text


def test_pose_drops_the_head_lock_from_sadness():
    assert "The head does not move" in instruction_edit.build_instruction("sadness")
    text = instruction_edit.build_instruction("sadness", pose=True)
    assert "The head does not move" not in text and "The head is lowered" in text


def test_photo_pose_instruction():
    text = instruction_edit.build_instruction("joy", style="photo", pose=True)
    assert text.startswith("Facial expression: smiling. One hand is raised in a cheerful wave.")
    assert text.endswith("Keep it a realistic photo with natural skin color.") and "clothing" in text


def test_custom_pose_sentence():
    text = instruction_edit.build_instruction("anger", pose="Both fists are clenched at the sides.")
    assert "Both fists are clenched at the sides." in text and "arms are crossed" not in text
    assert instruction_edit.pose_sentence("anger", "on") == "The arms are crossed over the chest."
    assert instruction_edit.pose_sentence("anger", False) == ""


def test_pose_only_instruction_keeps_the_expression():
    text = instruction_edit.build_pose_instruction("embarrassment")
    assert text.startswith("Change only the pose. One hand scratches the back of the head.")
    assert "Keep the same facial expression." in text


def test_pose_settings_raise_denoise_and_skip_face_paste():
    settings = instruction_edit.EditSettings(intensity=0.5, photo=True)
    assert settings.resolved_denoise() == 0.6 and settings.resolved_paste_face()
    posed = instruction_edit.EditSettings(intensity=0.5, photo=True, pose=True)
    assert posed.resolved_denoise() == instruction_edit.POSE_MIN_DENOISE and not posed.resolved_paste_face()
    assert instruction_edit.EditSettings(intensity=0.5, photo=True, pose=True, denoise=0.7).resolved_denoise() == 0.7


def test_instruct_generator_adds_poses(face_image):
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(edit_routes())
    ExpressionGenerator(backend).generate(
        face_image, settings={"seed": 3, "pose": True, "poses": {"joy": "Both arms are raised."}}, only=["joy", "anger"], method="instruct"
    )
    texts = [w["positive"]["inputs"]["prompt"] for w in prompts(backend)]
    assert "The arms are crossed over the chest." in texts[0] and "Both arms are raised." in texts[1]
    assert all(w["sampler"]["inputs"]["denoise"] >= instruction_edit.POSE_MIN_DENOISE for w in prompts(backend))


def test_inpaint_generator_poses_first_then_inpaints_the_face(face_image):
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(edit_routes())
    results = ExpressionGenerator(backend).generate(face_image, settings={"seed": 3, "pose": "on"}, flavor="danbooru", only=["anger"])
    assert list(results) == ["anger"]
    first, second = prompts(backend)
    assert first["positive"]["inputs"]["prompt"].startswith("Change only the pose. The arms are crossed")
    assert "face_detailer" in second and "pose" not in str(second["face_detailer"]["inputs"].get("wildcard", ""))


def test_poses_off_by_default(face_image):
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(edit_routes())
    ExpressionGenerator(backend).generate(face_image, settings={"pose": "off"}, flavor="danbooru", only=["anger"])
    assert len(prompts(backend)) == 1 and "face_detailer" in prompts(backend)[0]


def test_poses_need_the_edit_mode(face_image, fake_backend):
    with pytest.raises(ValueError, match="Poses need Qwen-Image-Edit"):
        ExpressionGenerator(fake_backend).generate(face_image, settings={"pose": True}, only=["anger"])
