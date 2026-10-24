# Prompt styles and expression intensity

## Prompt styles

Different checkpoints understand prompts differently, so the expression prompts come in one set per model family. Pick one from the **Prompt Style** dropdown, or leave it on **Auto** to choose from the checkpoint name.

| Prompt Style | Use for | Quality tags added |
| --- | --- | --- |
| Danbooru tags | SD1.5 anime models, Animagine, Anything, Counterfeit | `masterpiece, best quality` |
| e621 tags | Furry/anthro models (FluffyRock, Fluffusion, YiffyMix) | `best quality, detailed` |
| Pony Diffusion | Pony V6 XL and merges | `score_9, score_8_up, score_7_up` |
| Illustrious / NoobAI | NoobAI-XL, WAI and other Illustrious finetunes. Base Illustrious-XL 0.1 barely changes expressions. | `masterpiece, best quality, amazing quality` |
| SDXL / SD1.5 (CLIP) | General and realistic SDXL/SD1.5 models | none |
| Natural language | Flux, SD3/3.5, HiDream, Chroma, Qwen-Image, Lumina (for face detailing on Flux, use dev rather than schnell) | none |

<details>
<summary>The same character rendered with each prompt style</summary>

<img src="../.github/readme/prompt_styles.jpg" alt="The same expressions generated with each prompt style: Danbooru, Pony, Illustrious, SDXL and natural language" width="100%">

</details>

Quality and negative tags are only added when your prompt doesn't already contain them. The sets live in `autoexpress_core/resources/expressions/`, one JSON file per family, so adding a new family is just adding a file.

## Expression intensity

One slider, from 0 to 1, sets how far each expression is pushed. 0.5 is the classic AutoExpress strength. Photos have their own scale, gentler than the one for drawn styles, so 0.5 is a natural strength for both.

- **Face inpainting** (ADetailer / FaceDetailer): the slider scales the expression prompt's weight, the [expression LoRA](expression-loras.md) strength and the denoising strength. At 0 the LoRA is off.
- **Instruction edit** (Qwen-Image-Edit): the slider picks subtler or stronger wording and lowers the denoise, so low values keep more of the input.

Each prompt style has its own default, used when you leave the slider on **auto**:

| Images | Recommended |
| --- | --- |
| Anime and other drawn styles (Danbooru, Pony, Illustrious) | Face inpainting at 0.5 with the expression LoRA on |
| Photos (SDXL / realistic, Flux) | Instruction edit at 0.5. Photos get just the expression's name plus a note to keep a realistic photo with natural skin color, and the slider only sets how much of the input is kept. |

The slider is the **Expression intensity** control in the standalone app and the `intensity` input on the AutoExpress ComfyUI nodes, where -1 means the default.

[← Back to the docs](README.md)
