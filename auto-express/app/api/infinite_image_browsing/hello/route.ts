import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function GET() {
  try {
    const response = await fetch(`${WEBUI_BASE_URL}/infinite_image_browsing/hello`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'no-cache',
      },
    });
  } catch (error) {
    console.error('Error fetching Infinite Image Browsing greeting:', error);
    return NextResponse.json(
      { error: 'Failed to fetch Infinite Image Browsing greeting' }, 
      { status: 500 }
    );
  }
}
