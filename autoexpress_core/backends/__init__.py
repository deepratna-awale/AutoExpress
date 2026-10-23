"""
Backends run the img2img request bodies built by the core.

- a1111_api: talks to an A1111 compatible server over HTTP (A1111, Forge, reForge, SD.Next).
- comfyui_api: runs each expression as a FaceDetailer workflow on a ComfyUI server.
- swarmui_api: uses SwarmUI's <segment:face> refining on a SwarmUI server.
- invokeai_api: queues a face mask inpainting graph on an InvokeAI server.
- a1111_inprocess: runs inside A1111 / Forge / reForge / SD.Next, no --api needed.

The HTTP backends are listed in registry.REMOTE_BACKENDS for the standalone app.
"""
