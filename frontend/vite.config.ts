import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import { viteSingleFile } from 'vite-plugin-singlefile'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import type { Plugin } from 'vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const styleThumbnailDir = path.resolve(__dirname, '../backend/public/style-imgs')
const projectFilesDir = path.resolve(__dirname, '../backend/data/projects')
const globalFilesDir = path.resolve(__dirname, '../backend/data/global')
const imageFileExtensions = new Set(['.png', '.jpg', '.jpeg', '.webp'])

function styleThumbnailDevServer(): Plugin {
  return {
    name: 'ai-video-style-thumbnails-dev-server',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/style-imgs', (req, res, next) => {
        const rawUrl = req.url?.split('?')[0] ?? ''
        let fileName: string
        try {
          fileName = decodeURIComponent(rawUrl).replace(/^\/+/, '')
        } catch {
          next()
          return
        }

        if (
          !fileName ||
          fileName.includes('/') ||
          fileName.includes('\\') ||
          fileName.includes('..')
        ) {
          next()
          return
        }

        const filePath = path.resolve(styleThumbnailDir, fileName)
        if (!filePath.startsWith(`${styleThumbnailDir}${path.sep}`)) {
          next()
          return
        }

        fs.stat(filePath, (statError, stat) => {
          if (statError || !stat.isFile()) {
            next()
            return
          }
          const ext = path.extname(fileName).toLowerCase()
          if (!imageFileExtensions.has(ext)) {
            next()
            return
          }
          const contentType =
            ext === '.jpg' || ext === '.jpeg'
              ? 'image/jpeg'
              : ext === '.webp'
                ? 'image/webp'
                : 'image/png'
          res.setHeader('Content-Type', contentType)
          res.setHeader('Content-Length', String(stat.size))
          fs.createReadStream(filePath).pipe(res)
        })
      })
    },
  }
}

function projectFilesDevServer(): Plugin {
  return {
    name: 'ai-video-project-files-dev-server',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/project-files', (req, res, next) => {
        const rawUrl = req.url?.split('?')[0] ?? ''
        let relativePath: string
        try {
          relativePath = decodeURIComponent(rawUrl).replace(/^\/+/, '')
        } catch {
          next()
          return
        }

        if (
          !relativePath ||
          relativePath.includes('\\') ||
          relativePath.split('/').some((part) => part === '..' || part === '.')
        ) {
          next()
          return
        }

        const filePath = path.resolve(projectFilesDir, relativePath)
        if (!filePath.startsWith(`${projectFilesDir}${path.sep}`)) {
          next()
          return
        }

        fs.stat(filePath, (statError, stat) => {
          if (statError || !stat.isFile()) {
            next()
            return
          }
          const ext = path.extname(filePath).toLowerCase()
          if (!imageFileExtensions.has(ext)) {
            next()
            return
          }
          const contentType =
            ext === '.jpg' || ext === '.jpeg'
              ? 'image/jpeg'
              : ext === '.webp'
                ? 'image/webp'
                : 'image/png'
          res.setHeader('Content-Type', contentType)
          res.setHeader('Content-Length', String(stat.size))
          fs.createReadStream(filePath).pipe(res)
        })
      })
    },
  }
}

function globalFilesDevServer(): Plugin {
  return {
    name: 'ai-video-global-files-dev-server',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/global-files', (req, res, next) => {
        const rawUrl = req.url?.split('?')[0] ?? ''
        let relativePath: string
        try {
          relativePath = decodeURIComponent(rawUrl).replace(/^\/+/, '')
        } catch {
          next()
          return
        }

        if (
          !relativePath ||
          relativePath.includes('\\') ||
          relativePath.split('/').some((part) => part === '..' || part === '.')
        ) {
          next()
          return
        }

        const filePath = path.resolve(globalFilesDir, relativePath)
        if (!filePath.startsWith(`${globalFilesDir}${path.sep}`)) {
          next()
          return
        }

        fs.stat(filePath, (statError, stat) => {
          if (statError || !stat.isFile()) {
            next()
            return
          }
          const ext = path.extname(filePath).toLowerCase()
          if (!imageFileExtensions.has(ext)) {
            next()
            return
          }
          const contentType =
            ext === '.jpg' || ext === '.jpeg'
              ? 'image/jpeg'
              : ext === '.webp'
                ? 'image/webp'
                : 'image/png'
          res.setHeader('Content-Type', contentType)
          res.setHeader('Content-Length', String(stat.size))
          fs.createReadStream(filePath).pipe(res)
        })
      })
    },
  }
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    styleThumbnailDevServer(),
    projectFilesDevServer(),
    globalFilesDevServer(),
    viteSingleFile(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: 'dist',
    assetsInlineLimit: 100000000,
    cssCodeSplit: false,
  },
})
