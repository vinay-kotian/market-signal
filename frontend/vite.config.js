import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: {
      '/ws': { target: process.env.API_TARGET || 'http://127.0.0.1:8000', ws: true },
      '/api': {
        target: process.env.API_TARGET || 'http://127.0.0.1:8000',
        rewrite: path => path.replace(/^\/api/, ''),
      },
    },
  },
});
