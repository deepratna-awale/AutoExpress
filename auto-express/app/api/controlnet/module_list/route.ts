import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const alias_names = searchParams.get('alias_names') || 'false';
    
    const response = await fetch(`${WEBUI_BASE_URL}/controlnet/module_list?alias_names=${alias_names}`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'public, max-age=300', // Cache for 5 minutes
      },
    });
  } catch (error) {
    console.error('Error fetching ControlNet module list:', error);
    return NextResponse.json(
      { error: 'Failed to fetch ControlNet module list' }, 
      { status: 500 }
    );
  }
}
