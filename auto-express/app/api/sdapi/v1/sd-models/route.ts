import { NextRequest, NextResponse } from 'next/server';

const DEFAULT_WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function GET(request: NextRequest) {
  try {
    // Get base URL from query parameters or use default
    const { searchParams } = new URL(request.url);
    const baseUrl = searchParams.get('baseUrl') || DEFAULT_WEBUI_BASE_URL;
    
    // Ensure the base URL has the correct protocol
    const webuiUrl = baseUrl.startsWith('http') ? baseUrl : `http://${baseUrl}`;
    
    const response = await fetch(`${webuiUrl}/sdapi/v1/sd-models/`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'public, max-age=300', // Cache for 5 minutes
        'accept': 'application/json',
      },
    });
  } catch (error) {
    console.error('Error fetching models:', error);
    return NextResponse.json(
      { error: 'Failed to fetch models' }, 
      { status: 500 }
    );
  }
}
