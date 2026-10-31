# SillyTavern

AutoExpress makes sprites for SillyTavern's **Character Expressions** extension. Its 28 expressions are the labels SillyTavern uses (`joy`, `anger`, `sadness`, ...), so the files work as they are.

There are two ways to get them into SillyTavern: the AutoExpress extension for SillyTavern, which makes a character's sprites from inside SillyTavern, or copying the results of any other AutoExpress setup by hand.

## The SillyTavern extension

The extension sends a character's avatar (or another image of them) to the [standalone AutoExpress app](standalone.md), which runs it on the WebUI it's connected to: A1111, Forge, reForge, SD.Next, ComfyUI, SwarmUI or InvokeAI, on this computer or a rented GPU. Each finished expression goes straight into the character's sprite folder, so the sprites show up in Character Expressions while the rest are still being made.

### Install

1. Start the AutoExpress app (`run.sh` / `run.bat` from the [release zip](https://github.com/deepratna-awale/AutoExpress/releases), `python -m autoexpress`, or `docker run -p 5000:5000 ghcr.io/deepratna-awale/autoexpress`) and connect it to your WebUI. See the [standalone guide](standalone.md).
2. In SillyTavern, open **Extensions → Install extension**, paste `https://github.com/deepratna-awale/AutoExpress` and install it.
3. Open **Extensions → AutoExpress**. It should say **Connected to** your WebUI. If AutoExpress isn't at `http://127.0.0.1:5000`, change **AutoExpress address**.

The WebUI only needs to be reachable from the AutoExpress app, not from SillyTavern. To switch WebUI from SillyTavern, paste its address (for example a RunPod proxy URL) into **WebUI address** and press **Connect**; AutoExpress detects which WebUI it is. When something is missing on the WebUI, such as ADetailer or a face model, the panel lists it with the steps to fix it.

### Make sprites

1. Open a chat with the character.
2. Press **Generate expression sprites** in the extensions menu (the magic wand), in **Extensions → AutoExpress**, or **Generate with AutoExpress** in **Character Expressions**. The `/autoexpress` command opens it too.
3. Pick the character, the image to start from and the expressions. **Missing** selects the expressions the character has no sprite for yet.
4. Press **Generate**. A progress bar in **Extensions → AutoExpress** shows how far it is, with a **Cancel** button.

| Option | |
| --- | --- |
| Use the avatar / Use another image | The avatar is what SillyTavern shows for the character, often cropped to 512×768. A larger, uncropped image works better, and a PNG made by A1111, ComfyUI or InvokeAI also brings its prompt, checkpoint and seed. |
| Checkpoint | The model to inpaint the face with. By default it's the one in the image's metadata, else the WebUI's current model. |
| Prompt style | Which [expression prompts](prompt-styles.md) to use. **Auto** picks them from the checkpoint name. |
| Method | Face inpainting, or the [instruction edit](comfyui.md#instruction-edit-mode-qwen-image-edit) (Qwen-Image-Edit, ComfyUI only). Only the methods the WebUI can run are listed. |
| Expression intensity | How far each expression is pushed. Off uses the model's calibrated default. |
| Character prompt | Describes the character, e.g. `1girl, long silver hair, blue eyes`. Read from the image when it has one. |
| Remove background | Saves the sprites with a transparent background (needs rembg on the AutoExpress machine). |
| Change the pose too | A small gesture per expression, keeping the outfit and background. Needs Qwen-Image-Edit on ComfyUI. |
| Keep existing sprites | Uploads each sprite as `joy-autoexpress.png` next to the existing `joy.png` instead of replacing it. Turn on **Allow multiple sprites** in Character Expressions to use both. |

Sprites go into the folder Character Expressions reads: `characters/<character name>/`, or the character's **Override folder name** when it has one. AutoExpress also keeps a copy in its own `Output/<folder>/`.

### SillyTavern on another address

SillyTavern calls the AutoExpress API from your browser, so AutoExpress has to allow SillyTavern's address. `http://localhost:8000` and `http://127.0.0.1:8000`, SillyTavern's default, are allowed out of the box. For any other address, such as another port, a LAN IP or a tunnel, start AutoExpress with that address in `AUTOEXPRESS_CORS_ORIGINS`:

```sh
AUTOEXPRESS_CORS_ORIGINS="http://localhost:8000,http://192.168.1.20:8000" python -m autoexpress
```

The **AutoExpress address** in the extension must be reachable from the browser you use SillyTavern in. When you open SillyTavern from your phone, `127.0.0.1` is the phone, so use the AutoExpress computer's LAN address instead. A SillyTavern page served over `https` can only call AutoExpress over `https` or on `localhost`/`127.0.0.1`.

## Copying sprites by hand

Results from the WebUI extension, the ComfyUI nodes or the standalone app are named `joy.png`, `anger.png` and so on. Copy the character's output folder into SillyTavern's `data/<user>/characters/<character name>/` folder, or zip it and use **Upload sprite pack** in Character Expressions.

[← Back to the docs](README.md)
