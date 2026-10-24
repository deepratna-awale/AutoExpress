---
title: AutoExpress
emoji: 🎭
colorFrom: indigo
colorTo: pink
sdk: docker
app_port: 5000
license: mit
short_description: One character image in, 28 facial expressions out
---

# AutoExpress

One character image in, a full set of 28 facial expressions out. AutoExpress repaints a character's face with each emotion and keeps the pose, outfit, background and art style, for expression sprites such as SillyTavern character cards and visual novels.

This Space runs the standalone web app. It does no image generation itself: paste the address of your own WebUI (AUTOMATIC1111, Forge, SD.Next, ComfyUI, SwarmUI or InvokeAI), for example a RunPod proxy URL such as `https://<pod-id>-7860.proxy.runpod.net`, and AutoExpress drives it over its API. The WebUI has to be reachable from the internet.

**This is one shared instance.** The connected WebUI, a Civitai key you enter and the generated images are shared with everyone using the Space at the same time. To use it privately, click **⋮ → Duplicate this Space** and make your copy private, then set your WebUI there (or as the `AUTOEXPRESS_BACKEND_URL` variable, with `AUTOEXPRESS_BACKEND_USERNAME` / `_PASSWORD` / `_TOKEN` as secrets).

Generated images are kept only until the Space restarts, so download them when a run finishes. **Remove background** runs on the Space's CPU and takes a few seconds per image.

Source code, the WebUI extensions and nodes, and setup guides: [github.com/deepratna-awale/AutoExpress](https://github.com/deepratna-awale/AutoExpress). This Space is updated automatically from the `main` branch.
