import { NextRequest, NextResponse } from 'next/server';

/**
 * API Documentation Route
 * This route provides documentation for all available WebUI API endpoints
 */
export async function GET() {
  const apiEndpoints = {
    info: 'AutoExpress WebUI API Endpoints',
    version: '1.0.0',
    baseUrl: process.env.WEBUI_BASE_URL || 'http://localhost:7860',
    endpoints: {
      // Authentication & User Management
      authentication: {
        '/api/user': {
          method: 'GET',
          description: 'Get current user information',
        },
        '/api/login-check': {
          method: 'GET',
          description: 'Check login status',
        },
        '/api/token': {
          method: 'GET',
          description: 'Get authentication token',
        },
        '/api/login': {
          method: 'POST',
          description: 'Login with credentials',
          body: 'FormData with username and password',
        },
      },

      // System Information
      system: {
        '/api/info': {
          method: 'GET',
          description: 'Get API information',
          params: { serialize: 'boolean (optional)' },
        },
        '/api/config': {
          method: 'GET',
          description: 'Get WebUI configuration',
        },
        '/api/startup-events': {
          method: 'GET',
          description: 'Get startup events',
        },
        '/api/internal/ping': {
          method: 'GET',
          description: 'Health check endpoint',
        },
        '/api/internal/pending-tasks': {
          method: 'GET',
          description: 'Get pending tasks',
        },
        '/api/internal/progress': {
          method: 'POST',
          description: 'Get progress information',
          body: 'ProgressRequest',
        },
        '/api/internal/quicksettings-hint': {
          method: 'GET',
          description: 'Get quicksettings hints',
        },
        '/api/internal/sysinfo': {
          method: 'GET',
          description: 'Get system information',
          params: { attachment: 'boolean (optional)' },
        },
      },

      // Queue Management
      queue: {
        '/api/queue/status': {
          method: 'GET',
          description: 'Get queue status',
        },
        '/api/reset': {
          method: 'POST',
          description: 'Reset iterator',
          body: 'ResetBody',
        },
      },

      // File Operations
      files: {
        '/api/upload': {
          method: 'POST',
          description: 'Upload files',
          body: 'multipart/form-data',
        },
      },

      // LoRA Management
      lora: {
        '/api/sdapi/v1/loras': {
          method: 'GET',
          description: 'Get available LoRAs',
        },
        '/api/sdapi/v1/refresh-loras': {
          method: 'POST',
          description: 'Refresh LoRA list',
        },
        '/api/tacapi/v1/lora-info/[lora_name]': {
          method: 'GET',
          description: 'Get LoRA information',
          params: { lora_name: 'string (path parameter)' },
        },
      },

      // ADetailer Extension
      adetailer: {
        '/api/adetailer/v1/version': {
          method: 'GET',
          description: 'Get ADetailer version',
        },
        '/api/adetailer/v1/schema': {
          method: 'GET',
          description: 'Get ADetailer schema',
        },
        '/api/adetailer/v1/ad_model': {
          method: 'GET',
          description: 'Get ADetailer models',
        },
      },

      // SD-Queue Extension
      'sd-queue': {
        '/api/sd-queue/login': {
          method: 'GET',
          description: 'SD-Queue login status',
        },
        '/api/sd-queue/txt2img': {
          method: 'POST',
          description: 'Execute text-to-image generation',
          body: 'StableDiffusionProcessingTxt2Img',
        },
        '/api/sd-queue/[task_id]': {
          method: 'GET',
          description: 'Get task status',
          params: { task_id: 'string (path parameter)' },
        },
        '/api/sd-queue/[task_id] (DELETE)': {
          method: 'DELETE',
          description: 'Remove task',
          params: { task_id: 'string (path parameter)' },
        },
      },

      // ControlNet Extension
      controlnet: {
        '/api/controlnet/version': {
          method: 'GET',
          description: 'Get ControlNet version',
        },
        '/api/controlnet/model_list': {
          method: 'GET',
          description: 'Get ControlNet model list',
          params: { update: 'boolean (optional)' },
        },
        '/api/controlnet/module_list': {
          method: 'GET',
          description: 'Get ControlNet module list',
          params: { alias_names: 'boolean (optional)' },
        },
        '/api/controlnet/control_types': {
          method: 'GET',
          description: 'Get ControlNet control types',
        },
        '/api/controlnet/settings': {
          method: 'GET',
          description: 'Get ControlNet settings',
        },
        '/api/controlnet/detect': {
          method: 'POST',
          description: 'Run ControlNet detection',
          body: 'ControlNet detection body',
        },
      },

      // Background Removal
      'background-removal': {
        '/api/rembg': {
          method: 'POST',
          description: 'Remove background from image',
          body: 'RemBG request body',
        },
      },

      // Image Browsing
      'image-browsing': {
        '/api/infinite_image_browsing/hello': {
          method: 'GET',
          description: 'Infinite Image Browsing greeting',
        },
        '/api/infinite_image_browsing/files': {
          method: 'GET',
          description: 'Get files from folder',
          params: { folder_path: 'string (required)' },
        },
        '/api/infinite_image_browsing/image-thumbnail': {
          method: 'GET',
          description: 'Get image thumbnail',
          params: { 
            path: 'string (required)',
            t: 'string (required)',
            size: 'string (optional, default: 256x256)'
          },
        },
      },

      // Tag Auto Complete
      'tag-autocomplete': {
        '/api/tacapi/v1/refresh-temp-files': {
          method: 'POST',
          description: 'Refresh temporary files',
        },
        '/api/tacapi/v1/refresh-embeddings': {
          method: 'POST',
          description: 'Refresh embeddings',
        },
      },

      // Generic API
      generic: {
        '/api/api/[api_name]': {
          method: 'POST',
          description: 'Execute generic API prediction',
          params: { api_name: 'string (path parameter)' },
          body: 'PredictBody',
        },
      },

      // Theme Management (Custom)
      themes: {
        '/api/themes': {
          method: 'GET',
          description: 'Get theme configuration',
          params: { name: 'string (required)' },
        },
      },
    },

    // Common request/response types
    types: {
      StableDiffusionProcessingTxt2Img: {
        prompt: 'string',
        negative_prompt: 'string',
        styles: 'string[]',
        seed: 'number',
        steps: 'number',
        cfg_scale: 'number',
        width: 'number',
        height: 'number',
        // ... many more fields available
      },
      ProgressRequest: {
        id_task: 'string',
        id_live_preview: 'number',
        live_preview: 'boolean',
      },
      ResetBody: {
        session_hash: 'string',
        fn_index: 'number',
      },
    },

    // Environment variables
    environment: {
      WEBUI_BASE_URL: process.env.WEBUI_BASE_URL || 'Not set',
      API_TIMEOUT: process.env.API_TIMEOUT || 'Default: 30000ms',
    },

    // Usage examples
    examples: {
      'Check WebUI Health': 'GET /api/internal/ping',
      'Get System Info': 'GET /api/info',
      'Upload File': 'POST /api/upload (with multipart/form-data)',
      'Generate Image': 'POST /api/sd-queue/txt2img (with StableDiffusionProcessingTxt2Img body)',
      'Get LoRAs': 'GET /api/sdapi/v1/loras',
      'ControlNet Detection': 'POST /api/controlnet/detect',
    },
  };

  return NextResponse.json(apiEndpoints, {
    headers: {
      'Cache-Control': 'public, max-age=300',
      'Content-Type': 'application/json',
    },
  });
}
