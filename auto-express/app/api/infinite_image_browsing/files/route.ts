import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const folder_path = searchParams.get('folder_path');
    
    if (!folder_path) {
      return NextResponse.json(
        { error: 'Folder path is required' }, 
        { status: 400 }
      );
    }
    
    const response = await fetch(`${WEBUI_BASE_URL}/infinite_image_browsing/files?folder_path=${encodeURIComponent(folder_path)}`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'no-cache',
      },
    });
  } catch (error) {
    console.error('Error fetching files:', error);
    return NextResponse.json(
      { error: 'Failed to fetch files' }, 
      { status: 500 }
    );
  }
}
