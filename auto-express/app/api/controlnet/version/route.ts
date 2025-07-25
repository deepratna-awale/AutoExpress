import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function GET() {
  try {
    const response = await fetch(`${WEBUI_BASE_URL}/controlnet/version`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'public, max-age=3600', // Cache for 1 hour
      },
    });
  } catch (error) {
    console.error('Error fetching ControlNet version:', error);
    return NextResponse.json(
      { error: 'Failed to fetch ControlNet version' }, 
      { status: 500 }
    );
  }
}
