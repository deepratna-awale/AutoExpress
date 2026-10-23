## 2026-10-23
- Expression prompts now come in one set per model family: Danbooru, e621, Pony, Illustrious/NoobAI, SDXL/SD1.5 (CLIP) and natural language (Flux, SD3, ...).
- The Anime/Realistic switch is replaced by a **Prompt Style** dropdown. **Auto** picks the family from the checkpoint name.
- Family quality tags (e.g. Pony `score_` tags) and negatives are added only when missing from your prompt.
- Expression LoRAs matched to the checkpoint (Pony, Illustrious/NoobAI, SDXL, SD1.5, Flux) are added to the prompt, and downloaded from Civitai into the WebUI's LoRA folder when they're missing.
- AutoExpress now runs inside other WebUIs:
  - **AUTOMATIC1111 / Forge / reForge / SD.Next extension**: an AutoExpress tab that runs ADetailer in-process, so `--api` is not needed. It reads prompt, sampler and seed from the uploaded image and can build a sprite sheet.
  - **ComfyUI nodes**: Expression Prompts, Expression Prompt, Expression LoRAs, Save Expressions and Sprite Sheet, used together with Impact Pack's FaceDetailer.
  - **InvokeAI node**: Expression Prompts.
- Expression prompt sets, expression LoRAs, payloads and the generation loop moved into a shared `autoexpress_core` package that every integration uses.
- Fixed the Interrupt button in the standalone app, which raised an error instead of stopping generation.
- The base prompt and expression prompt are now joined with a comma.
- The seed setting now reaches A1111 1.9+ (it was overridden by the built-in Seed script).

## 2024-11-13
- Docker image available here: [AutoExpress on DockerHub](https://hub.docker.com/r/deepratna/autoexpress)
- Added Logo to UI
- Added Scheduler dropdown
- Added info icon to UI
  - Whenever you hover on the image or the info icon, it will show the raw generation data for convienience.
- Added Settings cog to have a modal for infrequently used settings.
- If element does not exist in dropdown (Model, Sampler, Scheduler, Lora), a new dropdown element is created.

**Avery Contributions**
- Boiler plate Theming Support by modifying [main.css](autoexpress/static/stylesheet/main.css)
- Implemented Gradient pause feature for performace increase.
- Expression jsons are now in different flavours instead of only being Anime/Realistic.
- 
![Latest UI](autoexpress/resources/images/AutoExpressUI_2024_11_13.png)


## 2024-09-26
- Tested on Ububtu (22.04.3 | jammy)

## 2024-06-23
- Added revamped UI
![AutoExpress Reskinned](autoexpress/resources/images/AutoExpressUI_Revamped.png)

- Removed my custom logger and added loguru library.

