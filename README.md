<h1> <img src="autoexpress\static\ico\favicon-rounded.png" alt="Favicon" width="25px"> AutoExpress</h1>

# Introduction
Automatically creates 28 different expressions from a given image using [Automatic1111 Stable Diffusion WebUI API](https://github.com/AUTOMATIC1111/stable-diffusion-webui). The application uses Inpainting with [After Detailer Extension](https://github.com/Bing-su/adetailer) to inpaint the following expressions on the face:

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

# Requirements
- [Python3](https://www.python.org/downloads/)
- [Automatic1111 Stable Diffusion WebUI API](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
- [After Detailer Extension](https://github.com/Bing-su/adetailer)

# Installation

- Clone Github Repo  
```bash
git clone https://github.com/deepratnaawale/AutoExpress.git
```

- Goto cloned repo
```bash
cd AutoExpress
```

- Create and activate virtual enviorenment
```bash
python3 -m venv .venv
```
```bash
.venv\Scripts\activate
```

- Install Requirements
```bash
pip install -e .
```

- Launch App
```bash
flask --app autoexpress run
```

- Launch A1111 Stable Diffusion WebUI Api
> You can check if the api is active by accessing the docs (if running locally)
[http://127.0.0.1:7860/docs#/default/](http://127.0.0.1:7860/docs#/default/)

- Connect to the UI at
[http://127.0.0.1:5000](http:127.0.0.1:5000)

# Usage
![UI Description](autoexpress/resources/images/UI.png)

It's pretty Straight forward. Keep an eye on the logs in the console. Dropping an image will auto populate all attributes in the UI if the image has Stable Diffusion info text. Only supports A1111 WebUI API for now. 

PS: This is a very handy tool to use with [Silly Tavern](https://github.com/SillyTavern/SillyTavern) to **generate character expressions sprites** for any bot.


# Future Work (Need contributers)
- Change pose along with expression keeping consistent clothes and background. (Probably via Controlnets and ADetailer)
- Better Expressions for Realistic Images.
- Support for Comfy UI, Next, etc.
- Better refactoring especially for JS and pythonic project setup using setuptools.
- Tests to check each module.

# Special Thanks
[SD Parsers by d3x-at](https://github.com/d3x-at/sd-parsers)

[SD API Examples](https://github.com/AUTOMATIC1111/stable-diffusion-webui/discussions/3734)