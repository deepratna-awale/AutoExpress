# Expression LoRAs

AutoExpress also adds a LoRA that helps faces show emotion, matched to the checkpoint's architecture:

| Architecture | LoRA |
| --- | --- |
| Pony | [Facial Expressions (Pony v1.0)](https://civitai.com/models/541620?modelVersionId=1815859) |
| Illustrious / NoobAI | [Facial Expressions (Illu v1.0)](https://civitai.com/models/541620?modelVersionId=1815930) + [Face Enhancer Illustrious](https://civitai.com/models/1625070). The expressions LoRA is skipped for anger, where it smudges the mouth. |
| SDXL | [Facial Expressions (XL v3)](https://civitai.com/models/541620?modelVersionId=761462) |
| SD1.5 | [Facial Expressions (SD1.5)](https://civitai.com/models/541620?modelVersionId=715217) |
| Flux | [Expression Helper 2.0](https://civitai.com/models/914282) |

Missing LoRAs are downloaded into the WebUI's LoRA folder and checked against their SHA-256. Inside a WebUI or ComfyUI that folder is always known. The standalone app downloads them when the WebUI runs on the same machine, or when you set **WebUI LoRA folder** in settings or `AUTOEXPRESS_LORA_DIR`; otherwise it uses the LoRAs only if they're already installed. Turn them off with the **Expression LoRAs** switch. The list lives in `autoexpress_core/resources/expression_loras.json`.

<details>
<summary>Each prompt style with its expression LoRA off and on</summary>

<img src="../.github/readme/lora_on_off.jpg" alt="Every prompt style rendered with the expression LoRA off and on" width="100%">

</details>

## Civitai key

Civitai needs an API key for downloads. If you've already set one up, AutoExpress reuses it. It looks in this order and uses the first key it finds:

1. The key typed into AutoExpress, or its own setting (**Settings → AutoExpress** in a WebUI, the LoRA node's `civitai_api_key` input in ComfyUI).
2. The key saved by a Civitai extension in your WebUI:
   - A1111 / Forge / reForge / SD.Next: [Civitai Browser+](https://github.com/BlafKing/sd-civitai-browser-plus) or [Civitai Helper](https://github.com/zixaphir/Stable-Diffusion-Webui-Civitai-Helper)
   - ComfyUI: [ComfyUI LoRA Manager](https://github.com/willmiao/ComfyUI-Lora-Manager)
3. The `CIVITAI_API_KEY` or `CIVITAI_API_TOKEN` environment variable.

The standalone app does the same for a WebUI on the same machine. Logs only say which source the key came from, never the key itself.

[← Back to the docs](README.md)
