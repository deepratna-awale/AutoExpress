import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

export async function POST(request: NextRequest) {
  try {
    const { params } = await request.json();
    const { api_name } = params;
    
    if (!api_name) {
      return NextResponse.json(
        { error: 'API name is required' }, 
        { status: 400 }
      );
    }
    
    const body = await request.json();
    
    const response = await fetch(`${WEBUI_BASE_URL}/api/${api_name}/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'no-cache',
      },
    });
  } catch (error) {
    console.error('Error making API prediction:', error);
    return NextResponse.json(
      { error: 'Failed to make API prediction' }, 
      { status: 500 }
    );
  }
}
