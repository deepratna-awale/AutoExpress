"""
Live2D model kits from the command line.

    python -m autoexpress_core.live2d check picture.png [more.png ...]
        Check pictures for a Live2D model and print the advice.
    python -m autoexpress_core.live2d kit --url http://127.0.0.1:8188 --name hinata picture.png [more.png ...]
        Build a model kit with a ComfyUI that has the See-through nodes (and Qwen-Image-Edit for the
        eyes-closed / mouth-open art). --outfits --adult adds swappable clothing (drawn adult characters only).
    python -m autoexpress_core.live2d attach path/to/exported_model_folder
        Add the 28 emotions' expressions and motions to a rigged model (a folder with a .model3.json)
        and write sillytavern_settings.json for the SillyTavern Live2D extension.
    python -m autoexpress_core.live2d puppet path/to/kit_folder [--output folder]
        Make the ready-to-play puppet from a kit folder (for kits made before puppets, or after
        editing the layer PNGs).
    python -m autoexpress_core.live2d lora "Hinata Hyuga" [--arch illustrious]
        Look for a character LoRA on Civitai.
"""

import argparse
import json
import sys

from PIL import Image


def _check(args) -> int:
    from .guidance import ADVICE, check_image

    for path in args.pictures:
        with Image.open(path) as image:
            report = check_image(image)
        print(f"{path}: score {report['score']}")
        for check in report["checks"]:
            print(f"  [{'ok' if check['ok'] else check['level']}] {check['message']}")
    print()
    print(ADVICE["title"])
    for line in ADVICE["best"]:
        print(f"  - {line}")
    return 0


def _kit(args) -> int:
    from ..backends.registry import create_backend
    from .kit import build_kit

    backend = create_backend("comfyui", args.url)
    images = []
    for path in args.pictures:
        with Image.open(path) as image:
            image.load()
            images.append(image.copy())
    settings = {"resolution": args.resolution, "low_vram": args.low_vram, "variants": args.variants, "use_prompt_data": not args.no_prompt_data, "clothing_slots": not args.no_clothing_slots, "expression_art": not args.no_expression_art}
    if args.outfit:
        settings["outfit_prompt"] = args.outfit
        settings.setdefault("adult_confirmed", args.adult)
    if args.outfits:
        settings.update(
            outfit_layers=True,
            adult_confirmed=args.adult,
            character_description=args.description or "",
            inner_wear=args.inner_wear or "",
        )
    result = build_kit(backend, images, args.output, args.name, settings, log=print)
    print(json.dumps({"zip": str(result.zip_path), "missing": result.manifest["missing"], "notes": result.manifest["notes"]}, indent=2))
    return 0


def _attach(args) -> int:
    from .model_files import attach_to_model

    print(json.dumps(attach_to_model(args.folder, backup=not args.no_backup), indent=2))
    return 0


def _puppet(args) -> int:
    from .puppet import from_kit

    print(from_kit(args.folder, args.output))
    return 0


def _lora(args) -> int:
    from ..civitai_key import find_civitai_key
    from .character_lora import search

    key, _ = find_civitai_key()
    found = search(args.name, args.arch, key)
    print(json.dumps(found[:5], indent=2) if found else "No character LoRA found.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m autoexpress_core.live2d", description="Live2D model kits.")
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="check pictures for a Live2D model")
    check.add_argument("pictures", nargs="+")
    check.set_defaults(run=_check)

    kit = commands.add_parser("kit", help="build a Live2D model kit with ComfyUI")
    kit.add_argument("pictures", nargs="+")
    kit.add_argument("--url", default="http://127.0.0.1:8188", help="ComfyUI's address")
    kit.add_argument("--name", default="character")
    kit.add_argument("--output", default="Output")
    kit.add_argument("--resolution", type=int, default=2048)
    kit.add_argument("--low-vram", action="store_true", help="4-bit See-through models for 8-12 GB GPUs")
    kit.add_argument("--variants", default="auto", choices=["auto", "instruct", "inpaint", "none"], help="how to draw the eyes-closed and mouth-open art")
    kit.add_argument("--outfits", action="store_true", help="swappable clothing: body, inner wear and outer clothes as separate layers (drawn adult characters only)")
    kit.add_argument("--adult", action="store_true", help="confirm the character is an adult (needed with --outfits)")
    kit.add_argument("--description", default="", help="the character's description, for the body and inner wear edits")
    kit.add_argument("--inner-wear", default="", help="what the inner wear looks like (default: from the picture's prompt, else matching lace lingerie)")
    kit.add_argument("--outfit", default="", help="dress the character in this outfit (Qwen-Image-Edit) before the split")
    kit.add_argument("--no-prompt-data", action="store_true", help="don't read the clothing from the picture's prompt metadata")
    kit.add_argument("--no-clothing-slots", action="store_true", help="don't put the coat on its own layer (saves an edit)")
    kit.add_argument("--no-expression-art", action="store_true", help="don't draw angry brows, a grin and teary eyes for the strongest emotions (saves three edits)")
    kit.set_defaults(run=_kit)

    attach = commands.add_parser("attach", help="add the 28 emotions to a rigged model folder")
    attach.add_argument("folder")
    attach.add_argument("--no-backup", action="store_true", help="don't keep a .bak copy of the .model3.json")
    attach.set_defaults(run=_attach)

    puppet = commands.add_parser("puppet", help="make the ready-to-play puppet from a kit folder")
    puppet.add_argument("folder")
    puppet.add_argument("--output", default=None, help="where to write it (default: <kit>/puppet/<name>)")
    puppet.set_defaults(run=_puppet)

    lora = commands.add_parser("lora", help="look for a character LoRA on Civitai")
    lora.add_argument("name")
    lora.add_argument("--arch", default=None, choices=["illustrious", "pony", "sdxl", "sd15", "flux"])
    lora.set_defaults(run=_lora)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
