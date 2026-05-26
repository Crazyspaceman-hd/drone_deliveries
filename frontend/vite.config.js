import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The backend runs on http://localhost:8000.  We proxy /api/* to it so the
// frontend can fetch with relative paths and not care about CORS during dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
});
