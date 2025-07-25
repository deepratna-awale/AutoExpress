import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const serialize = searchParams.get('serialize') || 'true';
    
    const response = await fetch(`${WEBUI_BASE_URL}/info?serialize=${serialize}`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'public, max-age=300', // Cache for 5 minutes
      },
    });
  } catch (error) {
    console.error('Error fetching API info:', error);
    return NextResponse.json(
      { error: 'Failed to fetch API info' }, 
      { status: 500 }
    );
  }
}
