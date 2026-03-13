import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// For local development, set API_TARGET to your API Gateway URL:
//   API_TARGET=https://xxx.execute-api.eu-west-2.amazonaws.com npm run dev
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
  },
  server: {
    proxy: process.env.API_TARGET
      ? {
          '/api': {
            target: process.env.API_TARGET,
            changeOrigin: true,
            rewrite: (p) => p.replace(/^\/api/, ''),
          },
        }
      : {},
  },
})
