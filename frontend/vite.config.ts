import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/phones": "http://localhost:8000",
      "/scrape": "http://localhost:8000",
      "/brands": "http://localhost:8000",
      "/operators": "http://localhost:8000",
    },
  },
});
