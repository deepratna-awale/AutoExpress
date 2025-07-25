import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const attachment = searchParams.get('attachment') || 'false';
    
    const response = await fetch(`${WEBUI_BASE_URL}/internal/sysinfo?attachment=${attachment}`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'no-cache',
      },
    });
  } catch (error) {
    console.error('Error fetching sysinfo:', error);
    return NextResponse.json(
      { error: 'Failed to fetch sysinfo' }, 
      { status: 500 }
    );
  }
}
