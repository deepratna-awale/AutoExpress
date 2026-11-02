# Live2D model kits

AutoExpress can turn pictures of a character into a **Live2D model kit**: the character split
into the layers of a Live2D model, with the hidden areas painted in, blink and mouth art, and
expressions and motions for the 28 emotions that the
[SillyTavern Live2D extension](https://github.com/SillyTavern/Extension-Live2d) plays.

The kit is the source of a model, not a finished rig. Live2D models play from a `.moc3` file,
and only Live2D Cubism Editor writes those. So the kit gives you a PSD that is ready to rig in
Cubism Editor (the free version is enough for a model this size), and the expressions to drop in
after you export. For an instant, rougher result without Cubism, the kit also has a PSD that
browser auto-riggers take as is (see [Without Cubism](#without-cubism)).

## What you need

- **ComfyUI** connected to the standalone app, local or on a rented GPU (see [RunPod](runpod.md)).
- The **[ComfyUI-See-through](https://github.com/jtydhr88/ComfyUI-See-through)** nodes. They run
  [See-through](https://github.com/shitagaki-lab/see-through) (SIGGRAPH 2026), a model trained on
  real Live2D models that splits one anime picture into up to 23 layers and paints in what each
  layer hides. Its models (about 10 GB) download from Hugging Face the first time it runs. It needs
  12 to 16 GB of VRAM at 1280 px, or 8 GB with **Low VRAM** (4-bit models, needs `bitsandbytes`).

  ```bash
  cd ComfyUI/custom_nodes
  git clone https://github.com/jtydhr88/ComfyUI-See-through
  pip install -r ComfyUI-See-through/requirements.txt
  # restart ComfyUI
  ```

  `scripts/runpod/setup_comfyui.sh` installs it for you.
- Optional: **Qwen-Image-Edit** on the same ComfyUI (see [ComfyUI](comfyui.md)) for the
  eyes-closed and mouth-open art, or a face inpainting checkpoint.

The setup checklist in the app shows whether the nodes are there, with the commands to fix it.

## Making a kit

In the web app, open the sidebar and choose **Tools > Live2D model kit**.

1. **Add pictures** of the character (up to 8). Each one gets a score and a list of checks. The
   best one is used, or click another to use it instead.
2. **Character name**, then **Find LoRA**: AutoExpress looks for the character's LoRA on Civitai,
   for the base model of your checkpoint. When the WebUI has it, **Use** it and the eyes-closed and
   mouth-open edits are made with face inpainting and that LoRA, so they stay on model. Without
   one, Qwen-Image-Edit makes them from the picture alone. A LoRA the WebUI doesn't have is listed
   with its download link: put it in ComfyUI's `models/loras` folder and search again.
3. **Build the kit.** It takes a few minutes: two edits, then See-through.

When it's done you get the reassembled character, every layer side by side, what's missing, and
downloads for the kit (zip), the Cubism PSD and the See-through PSD.

### Pictures that work best

The layer split sees one picture, so that picture decides most of the result.

- One character, facing the viewer (front view or a slight three-quarter turn), calm neutral face, mouth closed.
- Waist up or full body, so the body, arms and hair get their own parts. A face crop only gives a head.
- At least 1280 px on the short side, sharp, no heavy glow or grain.
- A plain or transparent background, and nothing in front of the character. A busy background is
  removed first when rembg is installed.
- Arms a little away from the body, hair not covering the eyes, nothing cut off at the top or sides.
- Even better: the same picture with the eyes closed and the mouth open, drawn by the artist, or a
  turnaround sheet (front, three-quarter, side) to pick the front view from.

Avoid action poses, strong perspective, crowds and loose sketches.

## What's in the kit

| File | What it is |
| --- | --- |
| `<name>.psd` | The Cubism PSD: one group per part (Front hair, Headwear, Face, Eye L, Eye R, Mouth, Ears, Body, Back hair ...), every layer an art mesh with its hidden area painted in. **Eye L closed**, **Eye R closed** and **Mouth open** are hidden layers on top of the parts they replace. L and R are the character's own left and right, like Live2D's parameters. |
| `<name>_seethrough.psd` | The same layers, flat and named the way See-through names them (`front hair`, `irides-l` ...). |
| `layers/` | Every layer as its own PNG at its place on the canvas. |
| `preview.png`, `sheet.jpg` | The layers put back together, and every layer on its own. |
| `runtime/` | `expressions/*.exp3.json` and `motions/*.motion3.json` for the 28 emotions, a looping idle, and `sillytavern_settings.json`. |
| `manifest.json` | Layers and their boxes, the switch layers and the parameter each belongs to, the picture checks, what's missing. |
| `README.txt` | The steps below. |

## Rigging it in Cubism Editor

1. **File > Open** the Cubism PSD. Every layer becomes an art mesh and every group a part.
2. **Modeling > Automatic mesh generation**, then add deformers and parameters. Use Live2D's
   standard parameter ids (`ParamAngleX/Y/Z`, `ParamEyeLOpen`, `ParamEyeROpen`, `ParamEyeLSmile`,
   `ParamBrowLY`, `ParamBrowLAngle`, `ParamMouthForm`, `ParamMouthOpenY`, `ParamCheek`,
   `ParamBodyAngleX`, `ParamBreath` ...): the expressions in `runtime/` drive those. Cubism's
   automatic generation of facial motion and its templates do much of this for you.
3. Key the hidden **Eye L closed** / **Eye R closed** layers to show at `ParamEyeLOpen` /
   `ParamEyeROpen` = 0, and **Mouth open** at `ParamMouthOpenY` = 1.
4. **File > Export For Runtime > Export as moc3 file.**

## Using it in SillyTavern

Copy `runtime/` into the exported model folder and run:

```bash
python -m autoexpress_core.live2d attach path/to/exported_model_folder
```

It writes one expression and one short reaction motion per emotion plus the idle, registers them
in the `.model3.json` (keeping a `.bak` copy, and any expressions or motions the model already had),
adds the `EyeBlink` and `LipSync` groups, and writes `sillytavern_settings.json`. When the model
has a `.cdi3.json` (Cubism exports one), only parameters the model has are used.

Put the folder in SillyTavern's `data/<user>/assets/live2d` (or the character's own `live2d`
folder) and pick it for the character in the Live2D extension. The extension reads
`sillytavern_settings.json` the first time a model is picked, so every emotion is already mapped:
each one the classifier detects plays its expression and reaction, and the idle breathes in between.

`attach` works on **any** rigged Cubism 3/4 model that uses the standard parameter ids, not just
ones made from a kit.

The expressions follow the same rule as the animated sprites: the character reacts to the chat and
doesn't talk. The mouth only changes shape (smile, frown), except for a small held "o" for
surprise and realization. The motions are small and calm: nods, head tilts, looking down or away.

## Without Cubism

Tools that rig See-through output automatically take `<name>_seethrough.psd` directly:

- [StretchyStudio](https://editor.stretchy.studio): a free browser puppet editor that auto-rigs it.
- [Anime2.5DRig](https://852wa.github.io/Anime2.5DRig/): a browser 2.5D avatar with blinking, lip-sync and hair physics.

Their output is not a Live2D model, so the SillyTavern Live2D extension can't load it.

## Command line and API

```bash
python -m autoexpress_core.live2d check picture.png more.png        # check pictures and print the advice
python -m autoexpress_core.live2d kit --url http://127.0.0.1:8188 --name mira picture.png
python -m autoexpress_core.live2d lora "Mira" --arch illustrious     # look for a character LoRA
python -m autoexpress_core.live2d attach path/to/model_folder        # add the 28 emotions to a rigged model
```

| Endpoint | What it does |
| --- | --- |
| `GET /live2d` | Whether the connected WebUI can make kits, what's missing (with the fix), defaults, and the picture advice |
| `POST /live2d/check` | `{"images": [base64 ...]}`: a report per picture and the best one |
| `POST /live2d/character-lora` | `{"name", "checkpoint"}` or a character card as `image`: Civitai matches, whether the WebUI has each, and how to install it |
| `POST /live2d` | `{"images", "name", "settings": {resolution, steps, seed, low_vram, base_index, variants, remove_background}, "character_lora"}`: a job; when it completes `job.live2d` has the kit's links |

Kits are saved under the output folder in `live2d/<name>/`, with `live2d/<name>_live2d_kit.zip`.

[← Back to the docs](README.md)
