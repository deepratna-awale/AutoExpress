<h1> <img src="autoexpress\static\ico\favicon-rounded.png" alt="Favicon" width="25px"> AutoExpress</h1>

# Introduction
Automatically creates 28 different expressions from a given image using [Automatic1111 Stable Diffusion WebUI API](https://github.com/AUTOMATIC1111/stable-diffusion-webui). The application uses Inpainting with [After Detailer Extension](https://github.com/Bing-su/adetailer) to inpaint the following expressions on the face:

### For the latest changes, goto: [Change Log](Changelog.md)

<p align="center">

| Emotion       | Emotion        | Emotion     | Emotion     |
| ------------- | -------------- | ----------- | ----------- |
| Admiration    | Amusement      | Anger       | Annoyance   |
| Approval      | Caring         | Confusion   | Curiosity   |
| Desire        | Disappointment | Disapproval | Disgust     |
| Embarrassment | Excitement     | Fear        | Gratitude   |
| Grief         | Joy            | Love        | Nervousness |
| Neutral       | Optimism       | Pride       | Realization |
| Relief        | Remorse        | Sadness     | Surprise    |

</p>


# Examples

### Anime

<div style="text-align:center">
    <figure>
        <img src ="autoexpress/resources/images/anime_grid.png" alt="Anime Image Grid" width="100%">
        <figcaption>Anime Image Emotion Grid</figcaption>
    </figure>
</div>


The above is an example anime expressions on the following image without cherry picking results.

<div style="text-align:center">
    <figure>
        <img src="autoexpress\resources\images\anime_input.png" alt="Realistic Input Image" width="100%">
        <figcaption>Anime input image</figcaption>
    </figure>
</div>


### Realistic

<div style="text-align:center">
    <figure>
        <img src ="autoexpress/resources/images/realistic_grid.png" alt="Realistic Image Grid" width="100%">
        <figcaption>Realistic Image Emotion Grid</figcaption>
    </figure>
</div>

The above is an example realistic expressions on the following image without cherry picking results.

<div style="text-align:center">
    <figure>
        <img src="autoexpress\resources\images\realistic_input.png" alt="Realistic Input Image" width="100%">
        <figcaption>Realistic input image</figcaption>
    </figure>
</div>

---

# Use AutoExpress inside your WebUI

AutoExpress can run inside the WebUI you already use. Inside a WebUI it runs in-process like any other extension, so the `--api` flag is not needed. All integrations share the same expression prompts and generation logic (`autoexpress_core`).

| WebUI | How it shows up | Face inpainting done by |
| ----- | --------------- | ----------------------- |
| AUTOMATIC1111, Forge, reForge, SD.Next | **AutoExpress** tab | [ADetailer](https://github.com/Bing-su/adetailer) |
| ComfyUI (and SwarmUI, which runs ComfyUI) | **AutoExpress** nodes | [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) FaceDetailer |
| InvokeAI | **AutoExpress Expression Prompts** node | InvokeAI's own inpainting nodes |
| Standalone (this repo's Flask app) | Web app on port 5000 | ADetailer through the A1111 API |

Fooocus has no extension system, so it is not supported.

## AUTOMATIC1111 / Forge / reForge / SD.Next

1. Install [ADetailer](https://github.com/Bing-su/adetailer) if you have not already.
2. Go to **Extensions → Install from URL**, paste `https://github.com/deepratna-awale/AutoExpress` and press **Install**. You can also clone the repository into `extensions/`.
3. Restart the WebUI and open the **AutoExpress** tab.
4. Drop in a character image. The prompt, sampler, steps, CFG and seed are filled in from the image's metadata when it has any.
5. Pick a prompt flavor and the expressions you want, then press **Generate**.

Images are saved to `outputs/autoexpress/<character name>/`. You can change that folder under **Settings → AutoExpress**. A labelled sprite sheet is saved next to them when that option is ticked.

## ComfyUI

1. Install [ComfyUI Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) and [Impact Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack), which provides the face detector.
2. Clone this repository into `ComfyUI/custom_nodes/` (or install it from ComfyUI Manager), then restart ComfyUI.
3. Build the graph:

```
Load Image ───────────────────────────────┐
Load Checkpoint ── model / clip / vae ────┤
CLIP Text Encode (positive / negative) ───┤
UltralyticsDetectorProvider (bbox/face) ──┤
                                          ▼
AutoExpress Expression Prompts ─ prompts ─► FaceDetailer (wildcard input) ─ image ─┬─► AutoExpress Save Expressions
                               └ names ────────────────────────────────────────────┼─► AutoExpress Save Expressions
                                                                                   └─► AutoExpress Sprite Sheet ─► Preview Image
```

`prompts` is a list, so ComfyUI runs FaceDetailer once per expression on its own. Connect `names` to the save and sprite sheet nodes so every file is named after its expression.

| Node | What it does |
| ---- | ------------ |
| AutoExpress Expression Prompts | Every expression (or a comma separated subset) as a prompt list, prefixed with your character prompt |
| AutoExpress Expression Prompt | One expression prompt |
| AutoExpress Save Expressions | Saves to `output/autoexpress/<character>/<expression>.png` |
| AutoExpress Sprite Sheet | Tiles the results into one labelled image |

## InvokeAI

Symlink (or copy) `invokeai_nodes/autoexpress` into `<INVOKEAI_ROOT>/nodes/` and restart InvokeAI. If you copied the folder, also run `pip install git+https://github.com/deepratna-awale/AutoExpress` inside InvokeAI's environment. The **AutoExpress Expression Prompts** node outputs one prompt per expression, ready to iterate over in a face inpainting graph.

---

# Standalone App

## Requirements
- [Python3](https://www.python.org/downloads/) Prefer version 10
- [Automatic1111 Stable Diffusion WebUI API](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
    - [Online Services](https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/Online-Services)
    - I'm currently working on integrating my [CivitAI-Model-Downloader](https://github.com/deepratna-awale/CivitAI-Model-Downloader) to automatically download LORAs.
- [After Detailer Extension](https://github.com/Bing-su/adetailer)

- ## Additional packages for Linux
- python3-pip
- python3-venv


## Run With Docker (Requires [Docker](https://www.docker.com/))

> Now AutoExpress is also available as a [Docker Image](https://hub.docker.com/r/deepratna/autoexpress)

Pull image from DockerHub
```bash
docker pull deepratna/autoexpress
```
Run
```bash
docker run -p 5000:5000 deepratna/autoexpress
```

## Quick Start with Pre-built Releases (Recommended)

Download the latest pre-built release for your platform from the [Releases page](https://github.com/deepratna-awale/AutoExpress/releases):

### Windows
1. Download `autoexpress-v*.*.* -Windows_Release.zip`
2. Extract the zip file
3. Double-click `run.bat` to start AutoExpress
4. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser

### Linux
1. Download `autoexpress-v*.*.* -Linux_Release.zip`
2. Extract the zip file
3. Run `./run.sh` to start AutoExpress
4. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser

**Note**: Pre-built releases include all dependencies pre-installed in a virtual environment. No additional setup required!

## Alternative Installation Methods

### Using Installer
- Clone repository
```bash
git clone https://github.com/deepratnaawale/AutoExpress.git
cd AutoExpress
```
- Run installer
  - Linux
  ```bash
  chmod +x install.sh
  ./install.sh
  ```
  - Windows (Simply execute the [install.bat](install.bat) file)

### Manual Installation
```bash
git clone https://github.com/deepratnaawale/AutoExpress.git
cd AutoExpress
```

- Create and activate virtual enviorenment
```bash
python3 -m venv .venv
```
- WINDOWS
```bash
.venv\Scripts\activate
```
- LINUX
```bash
source .venv/bin/activate
```

- Install Requirements
```bash
pip install -r requirements.txt
```
---

## Launch App
- Linux
```bash
chmod +x ./run.sh
./run.sh
```
- Windows (Simply execute the [run.bat](run.bat) file)

> Connect to the AutoExpress UI at
[http://127.0.0.1:5000](http:127.0.0.1:5000)


---

## Launch Your A1111 Stable Diffusion WebUI Api
> You can check if the api is active by accessing the docs (if running locally)
[http://127.0.0.1:7860/docs#/default/](http://127.0.0.1:7860/docs#/default/)


# Usage
![UI Description](autoexpress/resources/images/UI.png)

It's pretty Straight forward. Keep an eye on the logs in the console. Dropping an image will auto populate all attributes in the UI if the image has Stable Diffusion info text. Only supports A1111 WebUI API for now. 

PS: This is a very handy tool to use with [Silly Tavern](https://github.com/SillyTavern/SillyTavern) to **generate character expressions sprites** for any bot.

# Latest UI
![LatestUI](autoexpress/resources/images/AutoExpressUI_2024_11_13.png)

# Future Work
- Change pose along with expression keeping consistent clothes and background. (Probably via Controlnets and ADetailer)
- Better Expressions for Realistic Images.
- Tests to check each module.

# Special Thanks
[SD Parsers by d3x-at](https://github.com/d3x-at/sd-parsers)

[SD API Examples](https://github.com/AUTOMATIC1111/stable-diffusion-webui/discussions/3734)

[Avery Velfaire](https://github.com/AveryVeilfaire) for bug fixes, UI design, and prompt engineering.
