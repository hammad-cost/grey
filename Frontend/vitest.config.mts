/**
 * Vitest configuration — frontend component tests.
 *
 * Run with: npm test
 *
 * - jsdom gives tests a fake browser page to render React components into.
 * - The "@" alias matches tsconfig.json, so tests import files the same way the app does.
 */

import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // Compile JSX with React's automatic runtime (no `import React` needed).
  oxc: { jsx: { runtime: "automatic" } },
  resolve: {
    alias: { "@": fileURLToPath(new URL("./", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**"],
  },
});
