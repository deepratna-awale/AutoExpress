# AutoExpress for ComfyUI

1. Install [ComfyUI Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) and [Impact Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack), which provides the face detector.
2. Install AutoExpress, any of these works:
   - Search for **AutoExpress** in ComfyUI Manager.
   - `comfy node install autoexpress` with [comfy-cli](https://github.com/Comfy-Org/comfy-cli), from the [Comfy Registry](https://registry.comfy.org).
   - Clone this repository into `ComfyUI/custom_nodes/`.
3. Restart ComfyUI and open one of the [ready-made workflows](#ready-made-workflows), or build the graph yourself:

<p align="center">
  <img src="../.github/readme/comfyui_graph.jpg" alt="A ComfyUI graph with the AutoExpress Expression Prompts, Save Expressions and Sprite Sheet nodes around FaceDetailer" width="100%">
</p>

The same graph as a diagram, with the optional LoRA node:

```
Load Checkpoint ─ model / clip ─► AutoExpress Expression LoRAs ─ model / clip ──────────────┐
                └ vae ──────────────────────────────────────────────────────────────────────┤
                                  AutoExpress Expression LoRAs ─ lora_trigger ─┐            │
Load Image ────────────────────────────────────────────────────────────────────┼────────────┤
UltralyticsDetectorProvider (bbox/face) ───────────────────────────────────────┼────────────┤
CLIP Text Encode (positive: your character prompt) ────────────────────────────┼────────────┤
                                                                               ▼            ▼
AutoExpress Expression Prompts ─ negative ─► CLIP Text Encode ─────────────────────► FaceDetailer
                               ─ prompts ──────────────────────────────────────────► (wildcard input)
                               ─ names ─┐                                                   │ image
                                        ├─► AutoExpress Save Expressions ◄──────────────────┤
                                        └─► AutoExpress Sprite Sheet ◄──────────────────────┘ ─► Preview Image
```

`prompts` is a list, so ComfyUI runs FaceDetailer once per expression on its own. Connect `names` to the save and sprite sheet nodes so every file is named after its expression. Set the same checkpoint in the `ckpt_name` input of the AutoExpress nodes so **auto** can pick the prompt style and LoRAs. The LoRA node is optional.

| Node | What it does |
| ---- | ------------ |
| AutoExpress Expression Prompts | Every expression (or a comma separated subset) as a prompt list in the right [prompt style](../README.md#prompt-styles), plus the matching negative prompt |
| AutoExpress Expression Prompt | One expression prompt |
| AutoExpress Expression LoRAs | Applies the matching [expression LoRAs](../README.md#expression-loras), downloading them into `models/loras` when missing, and outputs their trigger words |
| AutoExpress Save Expressions | Saves to `output/autoexpress/<character>/<expression>.png` |
| AutoExpress Sprite Sheet | Tiles the results into one labelled image |
## Ready-made workflows

Every workflow below runs Load Checkpoint → **AutoExpress Expression LoRAs** → **AutoExpress Expression Prompts** → FaceDetailer → **Save Expressions** and **Sprite Sheet**, with settings that suit the model family. After installing AutoExpress they show up in ComfyUI's template browser (**Workflow → Browse Templates**), or drag a `.json` file into ComfyUI. Pick your checkpoint and your character image, enter your character prompt, and queue.

| Workflow | Tested with | Settings | Run time on our test GPU |
| --- | --- | --- | --- |
| [SD1.5 anime](../example_workflows/AutoExpress%20SD1.5%20anime.json) | AAM AnyLora Anime Mix | 512 px, 28 steps, CFG 7, DPM++ 2M Karras, denoise 0.5 | 33 s |
| [SDXL](../example_workflows/AutoExpress%20SDXL.json) | RealVisXL V5 | 1024 px, 30 steps, CFG 5, DPM++ 2M SDE Karras, denoise 0.5 | 91 s |
| [Pony](../example_workflows/AutoExpress%20Pony.json) | Pony Diffusion V6 XL | 30 steps, CFG 7, Euler a, denoise 0.55 | 102 s |
| [Illustrious / NoobAI](../example_workflows/AutoExpress%20Illustrious%20NoobAI.json) | NoobAI-XL 1.1 (two LoRAs) | 30 steps, CFG 5, Euler a, denoise 0.55 | 105 s |
| [Flux](../example_workflows/AutoExpress%20Flux.json) | Flux.1 dev fp8 | 20 steps, CFG 1, Euler simple, denoise 0.5 | 200 s |

The LoRA node has `download_missing` on and an empty key, so it fetches the expression LoRAs with the [Civitai key](../README.md#civitai-key) it finds. Flux keeps the face clean but its expressions are milder than the SDXL-based families. Every workflow uses `face_yolov8m.pt` from Impact Subpack as the face detector.

<p align="center">
  <img src="../example_workflows/AutoExpress%20Illustrious%20NoobAI.jpg" alt="The Illustrious / NoobAI workflow" width="100%">
</p>


## Instruction edit mode (Qwen-Image-Edit)

Instead of repainting the face with FaceDetailer, AutoExpress can edit the whole image with Qwen-Image-Edit-2511 (2509 also works) from one sentence per expression. It needs no face detector or expression LoRA, gives stronger expressions and keeps the character.

<p align="center">
  <img src="../.github/readme/method_comparison.jpg" alt="FaceDetailer and LoRA compared with Qwen-Image-Edit" width="100%">
</p>

**Models.** Download them into your ComfyUI folder with

```bash
python -m autoexpress_core.instruction_edit download /path/to/ComfyUI
```

or run `python -m autoexpress_core.instruction_edit check /path/to/ComfyUI` to list what's missing. The files are:

| File | Folder |
| --- | --- |
| `qwen_image_edit_2511_fp8mixed` | `models/diffusion_models` |
| `qwen_2.5_vl_7b_fp8_scaled` | `models/text_encoders` |
| `qwen_image_vae` | `models/vae` |
| `Qwen-Image-Edit-2509-Lightning-8steps-V1.0-bf16` (optional, drawn images only) | `models/loras` |

With the Lightning LoRA use 8 steps at CFG 1, without it 40 steps at CFG 4.

**Photos.** Use the `photo` style and skip the Lightning LoRA: its 8 steps make real skin look plastic, so run 40 steps at CFG 4, about 2 minutes per expression on an A40. The photo instructions are just the expression's name plus "Keep it a realistic photo with natural skin color.", and the node's `denoise` output (0.6 at the default intensity) goes to the KSampler. The standalone app and the ComfyUI backend also paste only the edited face back onto the original photo, found with Impact Pack's face detector, so skin, hair and background stay untouched. In a graph, do the same with a face mask and `ImageCompositeMasked`.

**VRAM.** About 24 GB: the model is around 20 GB and the ~9 GB text encoder is offloaded by ComfyUI. 16 GB cards work with `--lowvram`, several times slower.

**Graph.** The **AutoExpress Edit Instructions** node outputs one instruction per expression. Connect `instructions` to the prompt of `TextEncodeQwenImageEditPlus`, and `names` to **AutoExpress Save Expressions** or **AutoExpress Sprite Sheet**. A ready graph is in [`example_workflows/AutoExpress Qwen-Image-Edit expressions.json`](../example_workflows/). Drag it into ComfyUI or open it from the template browser.


[← Back to the README](../README.md)
