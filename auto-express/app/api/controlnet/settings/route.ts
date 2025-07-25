import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function GET() {
  try {
    const response = await fetch(`${WEBUI_BASE_URL}/controlnet/settings`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'public, max-age=300', // Cache for 5 minutes
      },
    });
  } catch (error) {
    console.error('Error fetching ControlNet settings:', error);
    return NextResponse.json(
      { error: 'Failed to fetch ControlNet settings' }, 
      { status: 500 }
    );
  }
}
