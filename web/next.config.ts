import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  // The development badge sits over the bottom of the side panel.
  devIndicators: false,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
