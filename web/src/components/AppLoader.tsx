"use client";

import dynamic from "next/dynamic";
import { APP_NAME } from "@/lib/config";

/**
 * The workspace is a client-only application (a WebGL map and browser state), so it is loaded
 * without server rendering. This placeholder is what the server sends.
 */
const AppShell = dynamic(() => import("./AppShell"), {
  ssr: false,
  loading: () => (
    <div className="grid h-dvh place-items-center bg-bg" role="status">
      <p className="text-[15px] text-ink-2">Loading {APP_NAME}</p>
    </div>
  ),
});

export function AppLoader() {
  return <AppShell />;
}
