# AutoExpress - Pre-built Release

This is a pre-built release of AutoExpress with all dependencies included.

## Quick Start

### Windows
1. Double-click `run.bat` to start AutoExpress
2. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser

### Linux
1. Make the script executable: `chmod +x run.sh` (if needed)
2. Run: `./run.sh`
3. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser

## Requirements
A Stable Diffusion WebUI with its API enabled, on this machine or hosted anywhere (LAN, RunPod, ...): AUTOMATIC1111, Forge / reForge, SD.Next, ComfyUI, SwarmUI or InvokeAI. After connecting, AutoExpress checks the WebUI and lists anything missing (for example ADetailer or Impact Pack) with steps to fix it.

## Usage
1. Start your WebUI with its API enabled (for A1111, Forge and SD.Next: `--api`, plus `--listen` if it runs on another machine)
2. Run AutoExpress using the appropriate script for your platform
3. Navigate to [http://127.0.0.1:5000](http://127.0.0.1:5000)
4. Enter the WebUI address, upload an image and generate expressions!

## Notes
- This release includes a pre-configured Python virtual environment with all dependencies installed
- No additional Python packages need to be installed
- If you encounter any issues, please visit the [GitHub repository](https://github.com/deepratna-awale/AutoExpress) for support

## What's AutoExpress?
AutoExpress automatically creates 28 different expressions from a given image, using the Stable Diffusion WebUI of your choice. Perfect for creating character expression sprites for games, chatbots, or any creative project!

For more information, visit: https://github.com/deepratna-awale/AutoExpress
