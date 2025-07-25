import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

interface RouteParams {
  params: {
    lora_name: string;
  };
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const { lora_name } = params;
    
    if (!lora_name) {
      return NextResponse.json(
        { error: 'LoRA name is required' }, 
        { status: 400 }
      );
    }
    
    const response = await fetch(`${WEBUI_BASE_URL}/tacapi/v1/lora-info/${encodeURIComponent(lora_name)}`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'public, max-age=300', // Cache for 5 minutes
      },
    });
  } catch (error) {
    console.error('Error fetching LoRA info:', error);
    return NextResponse.json(
      { error: 'Failed to fetch LoRA info' }, 
      { status: 500 }
    );
  }
}
