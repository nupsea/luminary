import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

// Plugin: serve prd.json and prd-v2.json from the parent directory
// so the app can fetch('/prd.json') and fetch('/prd-v2.json') and get live story status
const servePrdFiles = () => ({
  name: 'serve-prd-files',
  configureServer(server: any) {
    const serveFile = (urlPath: string, filePath: string) => {
      server.middlewares.use(urlPath, (_req: any, res: any) => {
        try {
          const data = fs.readFileSync(path.resolve(__dirname, filePath), 'utf-8')
          res.setHeader('Content-Type', 'application/json')
          res.setHeader('Cache-Control', 'no-cache')
          res.end(data)
        } catch {
          res.statusCode = 404
          res.end('not found')
        }
      })
    }
    serveFile('/prd.json', '../prd.json')
    serveFile('/prd-v2.json', '../prd-v2.json')
  },
})

export default defineConfig({
  plugins: [react(), servePrdFiles()],
})
