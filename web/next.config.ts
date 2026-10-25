import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Every page reads the live database the cron writes to, so caching
  // components would serve yesterday's roles. Off deliberately.
  cacheComponents: false,
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
