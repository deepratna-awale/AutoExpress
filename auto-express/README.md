# Auto Express - Next.js Port

This is a modern Next.js port of the AutoExpress AI image generation interface, built with shadcn/ui components and Tailwind CSS.

## Features

- **Collapsible Sidebar**: Contains the Auto Express logo and a settings menu at the bottom
- **Resizable Layout**: Two-column layout with parameters panel on the left and drag & drop area on the right
- **Parameters Panel**: All original controls including:
  - A1111 API connection
  - Model, Sampler, Scheduler, and LoRA selection dropdowns
  - Clip Skip and Seed inputs
  - Interactive sliders for Steps, Width, Height, CFG Scale, and Denoising Strength
  - Anime/Realistic style toggle
- **Drag & Drop Zone**: File upload area with prompt and negative prompt text areas
- **Image Carousel**: Sheet that slides in from the right to display generated images
- **Theme Support**: Light/Dark/System theme switching
- **Settings Dialog**: GUI configuration options

## Technology Stack

- **Next.js 15** with App Router
- **TypeScript** for type safety
- **Tailwind CSS** for styling
- **shadcn/ui** components including:
  - Sidebar with collapsible functionality
  - Resizable panels for flexible layout
  - Dialog/Sheet components for modals
  - Form controls (Input, Textarea, Slider, Switch, Select)
  - Theme provider for dark/light mode
  - And many more UI primitives

## Getting Started

1. Install dependencies:
   ```bash
   cd auto-express
   npm install
   ```

2. Run the development server:
   ```bash
   npm run dev
   ```

3. Open [http://localhost:3000](http://localhost:3000) in your browser

## Structure

The application follows a modern React component architecture:

- `app/page.tsx` - Main entry point
- `components/auto-express-app.tsx` - Main application layout
- `components/app-sidebar.tsx` - Collapsible sidebar with settings
- `components/parameters-panel.tsx` - Left panel with all AI generation parameters
- `components/drop-zone-panel.tsx` - Right panel with file upload and prompts
- `components/image-carousel.tsx` - Image viewer sheet

## Original vs New

This port maintains all the functionality of the original AutoExpress while:
- Using modern React patterns and TypeScript
- Implementing responsive design with Tailwind CSS
- Following accessibility best practices with shadcn/ui
- Providing a clean, modern interface with the default theme
- Maintaining the exact same parameter controls and layout structure

The interface is fully functional and ready for integration with the original Python backend.
