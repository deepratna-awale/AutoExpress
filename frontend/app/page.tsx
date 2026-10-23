"use client";

import { AutoExpressApp } from "@/components/auto-express-app";
import { AutoExpressProvider } from "@/lib/store";

export default function Home() {
  return (
    <AutoExpressProvider>
      <AutoExpressApp />
    </AutoExpressProvider>
  );
}
