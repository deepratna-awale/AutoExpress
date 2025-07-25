import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function GET() {
  try {
    const response = await fetch(`${WEBUI_BASE_URL}/internal/ping`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'no-cache',
      },
    });
  } catch (error) {
    console.error('Error pinging internal:', error);
    return NextResponse.json(
      { error: 'Failed to ping internal' }, 
      { status: 500 }
    );
  }
}
