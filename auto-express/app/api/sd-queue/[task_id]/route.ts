import { NextRequest, NextResponse } from 'next/server';

const WEBUI_BASE_URL = process.env.WEBUI_BASE_URL || 'http://localhost:7860';

interface RouteParams {
  params: {
    task_id: string;
  };
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    const { task_id } = params;
    
    if (!task_id) {
      return NextResponse.json(
        { error: 'Task ID is required' }, 
        { status: 400 }
      );
    }
    
    const response = await fetch(`${WEBUI_BASE_URL}/sd-queue/${task_id}/status`);
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'no-cache',
      },
    });
  } catch (error) {
    console.error('Error fetching task status:', error);
    return NextResponse.json(
      { error: 'Failed to fetch task status' }, 
      { status: 500 }
    );
  }
}

export async function DELETE(request: NextRequest, { params }: RouteParams) {
  try {
    const { task_id } = params;
    
    if (!task_id) {
      return NextResponse.json(
        { error: 'Task ID is required' }, 
        { status: 400 }
      );
    }
    
    const response = await fetch(`${WEBUI_BASE_URL}/sd-queue/${task_id}/remove`, {
      method: 'DELETE',
    });
    
    const data = await response.json();
    
    return NextResponse.json(data, {
      status: response.status,
      headers: {
        'Cache-Control': 'no-cache',
      },
    });
  } catch (error) {
    console.error('Error removing task:', error);
    return NextResponse.json(
      { error: 'Failed to remove task' }, 
      { status: 500 }
    );
  }
}
