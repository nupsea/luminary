import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'fs'
import path from 'path'

// Plugin: serve prd.json from the parent directory (scripts/ralph/prd.json)
// so the app can fetch('/prd.json') and get live story status
const servePrdJson = () => ({
  name: 'serve-prd-json',
  configureServer(server: any) {
    server.middlewares.use('/prd.json', (_req: any, res: any) => {
      try {
        const filePath = path.resolve(__dirname, '../prd.json')
        const data = fs.readFileSync(filePath, 'utf-8')
        res.setHeader('Content-Type', 'application/json')
        res.setHeader('Cache-Control', 'no-cache')
        res.end(data)
      } catch {
        res.statusCode = 404
        res.end('not found')
      }
    })
  },
})

export default defineConfig({
  plugins: [react(), servePrdJson()],
})
