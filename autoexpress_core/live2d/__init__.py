"""
Live2D model kits: a character picture split into the layers of a Live2D model.

    guidance        which pictures work, and a quick check of the ones a user sends
    character_lora  find the character's LoRA on Civitai
    layers          See-through layers -> Cubism-named groups, plus blink and mouth art
    psd             the layered PSD writer
    model_files     .exp3.json / .motion3.json for the 28 emotions, wired into a rigged model
                    and mapped for the SillyTavern Live2D extension (sillytavern_settings.json)
    kit             the whole pipeline: pick picture, edit, split, write the kit

Run python -m autoexpress_core.live2d --help for the command line.
"""

# check_ready() method name for the layer split (See-through on ComfyUI).
DECOMPOSE = "live2d_layers"
