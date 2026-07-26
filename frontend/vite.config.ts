import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend serves its routes at the root (/serials, /lots, ...). The
// frontend calls them under /api and Vite proxies to the FastAPI dev server,
// so there is no CORS setup and no hardcoded host in the client.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
