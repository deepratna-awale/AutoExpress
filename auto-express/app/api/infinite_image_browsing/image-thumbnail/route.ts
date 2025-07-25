import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const path = searchParams.get('path');
    const t = searchParams.get('t');
    const size = searchParams.get('size') || '256x256';
    
    if (!path || !t) {
      return NextResponse.json(
        { error: 'Path and timestamp are required' }, 
        { status: 400 }
      );
    }
    
    const response = await fetch(`${WEBUI_BASE_URL}/infinite_image_browsing/image-thumbnail?path=${encodeURIComponent(path)}&t=${t}&size=${size}`);
    
    // Handle binary response for image thumbnails
    if (response.headers.get('content-type')?.startsWith('image/')) {
      const buffer = await response.arrayBuffer();
      return new NextResponse(buffer, {
        status: response.status,
        headers: {
          'Content-Type': response.headers.get('content-type') || 'image/jpeg',
          'Cache-Control': 'public, max-age=3600',
        },
      });
    }
    
    const data = await response.json();
    return NextResponse.json(data, {
      status: response.status,
    });
  } catch (error) {
    console.error('Error fetching thumbnail:', error);
    return NextResponse.json(
      { error: 'Failed to fetch thumbnail' }, 
      { status: 500 }
    );
  }
}
