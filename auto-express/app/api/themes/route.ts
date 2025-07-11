import { NextRequest, NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import { join } from 'path';

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const name = searchParams.get('name');

    if (!name) {
      return NextResponse.json({ error: 'Theme name is required' }, { status: 400 });
    }

    // Security: validate filename to prevent path traversal
    if (!/^[a-z0-9\-]+$/.test(name)) {
      return NextResponse.json({ error: 'Invalid theme name' }, { status: 400 });
    }

    const filePath = join(process.cwd(), 'lib', 'theme', 'defaults', `${name}.json`);
    
    try {
      const fileContents = await readFile(filePath, 'utf8');
      const themeData = JSON.parse(fileContents);
      
      return NextResponse.json(themeData, {
        headers: {
          'Cache-Control': 'public, max-age=3600', // Cache for 1 hour
        },
      });
    } catch (fileError) {
      console.error(`Theme file not found: ${name}`, fileError);
      return NextResponse.json({ error: 'Theme not found' }, { status: 404 });
    }
  } catch (error) {
    console.error('API error:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
