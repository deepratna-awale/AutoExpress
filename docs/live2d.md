# Live2D model kits

AutoExpress can turn pictures of a character into a **Live2D model kit**: the character split
into the layers of a Live2D model, with the hidden areas painted in, blink and mouth art, and
expressions and motions for the 28 emotions that the
[SillyTavern Live2D extension](https://github.com/SillyTavern/Extension-Live2d) plays.

Every kit has two ways to a moving character:

- **A ready-to-play puppet.** AutoExpress rigs the layers itself and saves them in its own open
  format, which the SillyTavern Live2D extension plays when the AutoExpress extension is installed
  too. It blinks, breathes, turns its head, follows the cursor, sways its hair and plays the 28
  expressions straight away. See [Ready-to-play puppet](#ready-to-play-puppet).
- **The source of a full Live2D model.** Live2D models play from a `.moc3` file, and only Live2D
  Cubism Editor writes those. So the kit gives you a PSD that is ready to rig in Cubism Editor (the
  free version is enough for a model this size), and the expressions to drop in after you export.

The puppet is quick and automatic; a model rigged by hand in Cubism moves better (real 3D-looking
turns, physics you tune, any parameter you like).

## What you need

- **ComfyUI** connected to the standalone app, local or on a rented GPU (see [RunPod](runpod.md)).
- The **[ComfyUI-See-through](https://github.com/jtydhr88/ComfyUI-See-through)** nodes. They run
  [See-through](https://github.com/shitagaki-lab/see-through) (SIGGRAPH 2026), a model trained on
  real Live2D models that splits one anime picture into up to 23 layers and paints in what each
  layer hides. Its models (about 10 GB) download from Hugging Face the first time it runs. It needs
  12 to 16 GB of VRAM at 1280 px and 20 to 24 GB at 2048 px (the default, since the layers become
  the puppet's textures), or 8 GB at 1280 px with **Low VRAM** (4-bit models, needs `bitsandbytes`).

  ```bash
  cd ComfyUI/custom_nodes
  git clone https://github.com/jtydhr88/ComfyUI-See-through
  pip install -r ComfyUI-See-through/requirements.txt
  # restart ComfyUI
  ```

  `scripts/runpod/setup_comfyui.sh` installs it for you.
- Optional: **Qwen-Image-Edit** on the same ComfyUI (see [ComfyUI](comfyui.md)) for the
  eyes-closed and mouth-open art (or a face inpainting checkpoint), and for swappable clothing.
- Optional: an **upscale model** in ComfyUI's `models/upscale_models` (the RunPod script downloads
  `RealESRGAN_x4plus_anime_6B`). Pictures smaller than the layer resolution are upscaled with it
  before the split; without one they're resized.

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
3. Optional: **Swappable clothing** (see below).
4. **Build the kit.** It takes a few minutes: two edits (four with swappable clothing), then See-through.

When it's done you get the reassembled character, every layer side by side, what's missing, and
downloads for the puppet (zip), the kit (zip), the Cubism PSD and the See-through PSD. **Try the
puppet** opens it in a new tab.

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
| `puppet/<name>/` | The ready-to-play puppet (also in `<name>_puppet.zip` next to the kit). |
| `manifest.json` | Layers and their boxes, the switch layers and the parameter each belongs to, the picture checks, what's missing. |
| `README.txt` | The steps below. |

### Swappable clothing

Live2D artists who want outfits that can change draw the whole body under the clothes and each
garment on its own layer. Turn on **Swappable clothing** and the kit does the same: two more
Qwen-Image-Edit runs draw the character with the clothes off (the body layer) and then in inner
wear (plain by default, or what you type under **Inner wear**), and they're cut out under
See-through's clothes. The puppet stacks body, inner wear and outer clothes, each with a switch
(`ParamClothesOuter`, `ParamClothesInner`) and outfit expressions `outfit_full`, `outfit_inner` and
`outfit_nude`. An outfit stays on while the emotions change. **Character description** helps the
body match the character (build, skin).

Each piece can also come off on its own (half off). The inner wear is split at the bare midriff
into **Inner top** and **Inner bottom** layers (a one-piece stays whole), and the outer clothes
follow See-through's top, bottom and legwear layers. Their switches are `ParamClothesTop`,
`ParamClothesBottom`, `ParamClothesLegs`, `ParamInnerTop` and `ParamInnerBottom`, and the puppet
gets the outfits its layers allow: `outfit_top_off`, `outfit_bottom_off`, `outfit_topless`,
`outfit_inner_top_off` and `outfit_inner_bottom_off`.

Accessories (headwear, eyewear, earrings, neckwear, held objects) are layers of their own, switched
by `ParamAccessories` with the `accessories_off` and `accessories_on` expressions, which also stay on
while the emotions change.

**Outfit** dresses the character in what you type (Qwen-Image-Edit) before the split, so every
layer has the new clothes. With **Read the clothing from the picture's prompt data** on, the
prompt saved in the picture (A1111, Forge, SD.Next, ComfyUI, InvokeAI or NovelAI metadata) fills
in the inner wear when you leave it empty, and tells the edits what the outfit is. An outfit that
asks for underwear or nudity needs the same checks as the body layer.

These layers show nudity, so they are only made for **drawn adult characters**:

- you tick that the character is an adult and the picture is a drawing,
- the picture has to look drawn (a photo of a real person is refused),
- a name, description, outfit or the picture's prompt that reads as a child (school ages, "loli",
  "15 years old" and similar) turns them off.

`safe_mode: false` in the settings skips only the drawing check, for drawings it wrongly reads as
photos. The adult confirmation and the child check always run.

When they aren't made, the kit says why and the clothes stay one layer.

### Clean-up after the split

See-through leaves a few things a hand-made model wouldn't have, which the kit fixes before it
writes the layers:

- Skin, clothes and hair are made opaque inside, with only an anti-aliased edge (no see-through neck).
- Clothing over the neck or face where the picture shows the neck or face (the back of a collar) is
  cut away, and anything visible that doesn't match the picture (grey patches in the hair) takes
  the picture's colours, so the puppet at rest looks like the picture.
- The hair colour is painted under the bangs, from the hairline down to the brows, so a swaying
  strand shows hair, never the scalp.

## Ready-to-play puppet

### Using it in SillyTavern

1. Install both extensions in SillyTavern (**Extensions > Install extension**): the
   [Live2D extension](https://github.com/SillyTavern/Extension-Live2d) and AutoExpress
   (`https://github.com/deepratna-awale/AutoExpress`, see [SillyTavern](sillytavern.md)). The
   AutoExpress extension is what lets the Live2D extension open puppets; the AutoExpress app doesn't
   need to be running for that.
2. Unzip `<name>_puppet.zip` into SillyTavern's `data/<user>/assets/live2d` (you get
   `assets/live2d/<name>/<name>.puppet.model.json`), or into the character's own `live2d` folder.
3. In the Live2D extension, pick `<name>.puppet.model.json` for the character. Its
   `sillytavern_settings.json` maps every emotion to its expression and reaction, sets the mouth
   parameter for lip sync and the cursor parameters, so there's nothing to set up.

Everything in the Live2D extension works the same as with a Live2D model: the emotion mapping, the
default and starter animations, the **Head** and **Body** hit areas for clicks, lip sync while a
message is shown, following the cursor, scale and position, and its `/live2d...` commands.

### Trying it in a browser

The puppet folder has `play.html`: double-click it to play the puppet with a menu of its
expressions, motions, outfits and blush (everything is packed into the page, so it opens straight
from the disk). `preview.html` is the same page loading the files next to it; browsers don't let a
page opened from disk load files, so serve the folder for that one:

```bash
cd puppet/<name>
python -m http.server 8000      # then open http://localhost:8000/preview.html
```

**Try the puppet** in the web app does this for you. The page loads PixiJS from cdnjs.

### What moves

| Parameter | What it does on the puppet |
| --- | --- |
| `ParamAngleX`, `ParamAngleY`, `ParamAngleZ` | Turn, nod and tilt the head. Layers in front of the face (front hair, nose, eyes) move more than the face and the back hair less, so the head reads as round. |
| `ParamEyeLOpen`, `ParamEyeROpen` | Close the eyes: the eye layers squash onto the lid line and the **Eye closed** art fades in. It blinks by itself every few seconds. |
| `ParamEyeLSmile`, `ParamEyeRSmile` | Push the lower lids up. |
| `ParamEyeBallX`, `ParamEyeBallY` | Move the irises. |
| `ParamBrowLY`, `ParamBrowLAngle`, `ParamBrowLForm` (and R) | Raise, angle and arch the brows. |
| `ParamMouthOpenY` | Open the mouth: the **Mouth open** art fades in. |
| `ParamMouthForm` | Smile (corners up) or frown. |
| `ParamCheek` | Blush: a soft pink that takes the skin's tone, with anime hatching when it's strong. |
| `ParamBodyAngleX`, `ParamBodyAngleY`, `ParamBodyAngleZ` | Lean and turn the upper body. |
| `ParamBreath` | Breathing (by itself when nothing else drives it). |
| `ParamHairFront`, `ParamHairBack` | Push the hair; it also swings on its own when the head moves. |
| `ParamBustX`, `ParamBustY`, `ParamHipX`, `ParamHipY` | Push the soft parts. They also jiggle on their own: each trails the body's movement on a bouncy spring, and bounces when poked. The clothes over them move with them. |
| `ParamClothesOuter`, `ParamClothesInner` | Show or hide the outer clothes and the inner wear (puppets with swappable clothing). |

Expression changes glide: every parameter eases towards its new value instead of jumping. Skirts
and ribbons swing behind the body like hair. Dragging the hair's ends, a skirt or a soft part pulls
it and it springs back with a wobble; a quick click on a soft part pokes it. In SillyTavern dragging
anywhere else still moves the model, and a click still plays the hit area's reaction. In the
preview everything can be pulled.

The bust and hip regions are placed from the head size with anime proportions. If they're off for
a character, change `Rig.Bust` and `Rig.Hips` (`Centers`, `Radius`) in the puppet file; a radius of
0 turns one off, and `Rig.Strength.bust`, `hips`, `cloth` and `drag` scale each effect.

### The format

The puppet is plain JSON and PNGs, so it can be edited by hand or played by other software:

| File | What it is |
| --- | --- |
| `<name>.puppet.model.json` | `Layers` (bottom to top: texture, place on the canvas, role such as `face`, `iris`, `eyelash`, `eye_closed`, `mouth_open`, `front_hair`, side, mesh grid), `Rig` (head box, centre and pivot, eye boxes and lid lines, mouth box, hair roots, body pivot, `Strength` and `Physics` numbers), `Parameters`, `HitAreas`, and `FileReferences` to the expressions and motions in the same shape as a Cubism `.model3.json`. The name has "model" in it because SillyTavern only lists Live2D files whose name does. |
| `textures/` | Each layer, cropped to what it shows. |
| `expressions/`, `motions/` | Cubism `exp3.json` and `motion3.json` files, the same ones a Cubism model gets. |
| `sillytavern_settings.json` | The Live2D extension's settings for the puppet. |
| `play.html` | The browser player with the puppet packed in (opens from the disk). |
| `preview.html`, `puppet.js` | The browser player, loading the files next to it (needs a web server). |

`Rig.Strength` sets how far things move: turn the head more with a bigger `turn`, sway the hair more
with a bigger `hair`. Reload the puppet after editing.

For a kit made before puppets existed, or after touching up the layer PNGs:

```bash
python -m autoexpress_core.live2d puppet path/to/kit_folder
```

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

## Using a Cubism model in SillyTavern

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
python -m autoexpress_core.live2d puppet path/to/kit_folder          # make the ready-to-play puppet from a kit
```

| Endpoint | What it does |
| --- | --- |
| `GET /live2d` | Whether the connected WebUI can make kits, what's missing (with the fix), defaults, and the picture advice |
| `POST /live2d/check` | `{"images": [base64 ...]}`: a report per picture and the best one |
| `POST /live2d/character-lora` | `{"name", "checkpoint"}` or a character card as `image`: Civitai matches, whether the WebUI has each, and how to install it |
| `POST /live2d` | `{"images", "name", "settings": {resolution, steps, seed, low_vram, base_index, variants, remove_background}, "character_lora"}`: a job; when it completes `job.live2d` has the links to the kit, the PSDs, the puppet zip (`puppet_zip`) and its preview page (`puppet_preview`) |

Kits are saved under the output folder in `live2d/<name>/`, with `live2d/<name>_live2d_kit.zip`.

[← Back to the docs](README.md)
