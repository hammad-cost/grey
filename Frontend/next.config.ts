import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allows the frontend to call the local FastAPI backend during development.
  // In production, replace with your deployed backend URL via environment variable.
  async rewrites() {
    return [];
  },
};

export default nextConfig;
