"""
Live check of the instruction edit mode against a running ComfyUI (not collected by pytest).

    python tests/live/qwen_edit_smoke.py --url http://127.0.0.1:8188 --image character.png --out out/

Checks the server has the Qwen-Image-Edit nodes and models, edits each expression,
saves <expression>.png plus a labelled sheet.png, and prints the time per image.
"""

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from PIL import Image  # noqa: E402

from autoexpress_core import ExpressionGenerator, instruction_edit, make_sprite_sheet  # noqa: E402
from autoexpress_core.backends.comfyui_api import ComfyUIClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8188")
    parser.add_argument("--image", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--expressions", default="neutral,joy,anger,sadness,surprise,embarrassment,confusion,fear,disgust,pride")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-lightning", action="store_true")
    parser.add_argument("--style", choices=instruction_edit.STYLES, default=instruction_edit.ILLUSTRATION, help="photo for realistic photos")
    args = parser.parse_args()

    backend = ComfyUIClient(args.url)
    ok, message = backend.check_ready(instruction_edit.INSTRUCT)
    print(f"check_ready(instruct): {ok} {message}")
    if not ok:
        return 1

    names = [name.strip() for name in args.expressions.split(",") if name.strip()]
    settings = {"seed": args.seed, "edit_lightning": not args.no_lightning, "edit_style": args.style}
    source = Image.open(args.image).convert("RGB")
    images, labels = [source], ["input"]
    started = time.monotonic()
    for name, image in ExpressionGenerator(backend).iter_generate(
        source, settings=settings, only=names, output_dir=args.out, method=instruction_edit.INSTRUCT
    ):
        now = time.monotonic()
        print(f"{name}: {now - started:.1f}s, {image.size}")
        started = now
        images.append(image)
        labels.append(name)
    if backend.last_error:
        print(f"failed: {backend.last_error}")
        return 1
    make_sprite_sheet(images, labels, columns=min(len(images), 6)).save(pathlib.Path(args.out) / "sheet.png")
    print(f"saved {len(images) - 1} expressions and sheet.png to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
