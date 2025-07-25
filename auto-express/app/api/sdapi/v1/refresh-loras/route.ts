import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function POST() {
  try {
    const response = await fetch(`${WEBUI_BASE_URL}/sdapi/v1/refresh-loras`, {
      method: 'POST',
    });
    
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'no-cache',
      },
    });
  } catch (error) {
    console.error('Error refreshing LoRAs:', error);
    return NextResponse.json(
      { error: 'Failed to refresh LoRAs' }, 
      { status: 500 }
    );
  }
}
