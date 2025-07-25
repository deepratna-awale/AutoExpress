import { NextRequest, NextResponse } from 'next/server';
import { makeWebUIRequest } from '@/lib/webui-client';
import type { UpdatedValues, ParseMetadataResponse } from '@/lib/api-types';

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get('file') as File;
    const apiUrl = formData.get('apiUrl') as string || 'http://127.0.0.1:7860';
    
    if (!file) {
      return NextResponse.json(
        { error: 'No file provided' },
        { status: 400 }
      );
    }

    // Validate file type
    if (!file.type.startsWith('image/')) {
      return NextResponse.json(
        { error: 'File must be an image' },
        { status: 400 }
      );
    }

    // Convert File to Buffer for server-side parsing
    const arrayBuffer = await file.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);

    // Parse metadata from image
    const { parseImageMetadataFromBuffer, validateParameters } = await import('@/lib/metadata-parser');
    const metadata = await parseImageMetadataFromBuffer(buffer);
    
    if (!metadata) {
      return NextResponse.json({
        success: false,
        error: 'No metadata found in image',
      });
    }

    // Fetch available options from WebUI API to validate against
    const [modelsResponse, samplersResponse, schedulersResponse, lorasResponse] = await Promise.allSettled([
      makeWebUIRequest('/sdapi/v1/sd-models', { baseUrl: apiUrl }),
      makeWebUIRequest('/sdapi/v1/samplers', { baseUrl: apiUrl }),
      makeWebUIRequest('/sdapi/v1/schedulers', { baseUrl: apiUrl }),
      makeWebUIRequest('/sdapi/v1/loras', { baseUrl: apiUrl }),
    ]);

    // Transform API data to options format, with fallbacks for when API is unavailable
    const modelOptions = modelsResponse.status === 'fulfilled' && modelsResponse.value.data && Array.isArray(modelsResponse.value.data) 
      ? modelsResponse.value.data.map((model: any) => ({ value: model.title, label: model.model_name }))
      : [];
    
    const samplerOptions = samplersResponse.status === 'fulfilled' && samplersResponse.value.data && Array.isArray(samplersResponse.value.data)
      ? samplersResponse.value.data.map((sampler: any) => ({ value: sampler.name, label: sampler.name }))
      : [];
    
    const schedulerOptions = schedulersResponse.status === 'fulfilled' && schedulersResponse.value.data && Array.isArray(schedulersResponse.value.data)
      ? schedulersResponse.value.data.map((scheduler: any) => ({ value: scheduler.name, label: scheduler.label }))
      : [];
    
    const loraOptions = lorasResponse.status === 'fulfilled' && lorasResponse.value.data && Array.isArray(lorasResponse.value.data)
      ? lorasResponse.value.data.map((lora: any) => ({ value: lora.name, label: lora.alias }))
      : [];

    // Validate parameters against available options
    const validation = validateParameters(metadata, {
      models: modelOptions,
      samplers: samplerOptions,
      schedulers: schedulerOptions,
      loras: loraOptions,
    });

    // Build response with only validated values that should update the form
    const updatedValues: UpdatedValues = {};

    // Only include dropdown values that are valid (have matching options)
    if (validation.model.isValid && validation.model.value) {
      updatedValues.model = validation.model.value;
    }
    
    if (validation.sampler.isValid && validation.sampler.value) {
      updatedValues.sampler = validation.sampler.value;
    }
    
    if (validation.scheduler.isValid && validation.scheduler.value) {
      updatedValues.scheduler = validation.scheduler.value;
    }
    
    // Handle LoRAs differently - convert metadata loras to UI format
    if (metadata.loras && metadata.loras.length > 0) {
      // Validate each LoRA and build the UI string format
      const validLoras = metadata.loras.filter(lora => {
        // Simple validation - check if LoRA name exists in available options
        return loraOptions.some(option => 
          option.value === lora.name || 
          option.label === lora.name ||
          option.value.toLowerCase() === lora.name.toLowerCase() ||
          option.label.toLowerCase() === lora.name.toLowerCase()
        );
      });
      
      if (validLoras.length > 0) {
        const loraString = validLoras.map(lora => `${lora.name}:${lora.strength}`).join(', ');
        updatedValues.lora = loraString;
      }
    }

    // Always include these numeric values if they exist in metadata (don't need validation)
    if (metadata.clipSkip !== undefined) updatedValues.clipSkip = metadata.clipSkip;
    if (metadata.seed !== undefined) updatedValues.seed = metadata.seed;
    if (metadata.steps !== undefined) updatedValues.steps = metadata.steps;
    if (metadata.width !== undefined) updatedValues.width = metadata.width;
    if (metadata.height !== undefined) updatedValues.height = metadata.height;
    if (metadata.cfgScale !== undefined) updatedValues.cfgScale = metadata.cfgScale;
    if (metadata.denoisingStrength !== undefined) updatedValues.denoisingStrength = metadata.denoisingStrength;
    
    // Always include prompts if they exist
    if (metadata.prompt) updatedValues.prompt = metadata.prompt;
    if (metadata.negativePrompt) updatedValues.negativePrompt = metadata.negativePrompt;
    
    return NextResponse.json({
      success: true,
      updatedValues,
      validation,
      rawMetadata: metadata, // Include for debugging if needed
    });
    
  } catch (error) {
    console.error('Error parsing image metadata:', error);
    return NextResponse.json(
      { error: 'Failed to parse image metadata' },
      { status: 500 }
    );
  }
}
