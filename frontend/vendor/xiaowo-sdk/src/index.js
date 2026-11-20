/**
 * 小蜗工具 - 插件前端 SDK
 * 支持 ESM (Vue/React) 和 UMD (普通 HTML) 两种使用方式
 */

// SDK 状态
let sdkReady = false
let sdkReadyResolve = null
let sdkReadyReject = null
const sdkReadyPromise = new Promise((resolve, reject) => {
  sdkReadyResolve = resolve
  sdkReadyReject = reject
})

// 获取 Tauri API
const getTauri = () => window.__TAURI__
const getInvoke = () => window.__TAURI__?.core?.invoke

async function invokeFileCommand(command, payload = {}) {
  await waitReady()
  return getInvoke()(command, payload)
}

/** 等待 SDK 准备好 */
export async function waitReady() {
  return sdkReadyPromise
}

// ============ 后端通信 ============
const eventHandlers = {}  // { eventName: [handler1, handler2, ...] }
const exitHandlers = []
const backendReadyHandlers = []

/** 调用插件后端方法 */
export async function callBackend(method, params = {}) {
  await waitReady()
  return getInvoke()('plugin_call_backend', { method, params })
}

/** 获取插件基本信息（清单、扩展数据、窗口缩放、语言） */
let pluginInfoPromise = null
export async function getInfo() {
  await waitReady()
  if (!pluginInfoPromise) {
    pluginInfoPromise = getInvoke()('plugin_get_info').then(info => {
      window.__PLUGIN_INFO__ = info
      return info
    }).finally(() => {
      pluginInfoPromise = null
    })
  }
  return pluginInfoPromise
}

/** 获取当前应用资料：开发实例读取当前开发者的在线资料，正式实例读取在线目录。 */
export async function getAppInfo() {
  await waitReady()
  return getInvoke()('plugin_get_app_info')
}

/** 获取插件后端子进程状态 */
export async function getBackendState() {
  await waitReady()
  return getInvoke()('plugin_get_backend_state')
}

/** 重启插件后端进程 */
export async function restartBackend() {
  await waitReady()
  return getInvoke()('plugin_restart_backend')
}

/** 停止插件后端进程 */
export async function stopBackend() {
  await waitReady()
  return getInvoke()('plugin_stop_backend')
}

/** 监听后端事件 */
export function onBackendEvent(eventName, handler) {
  if (!eventHandlers[eventName]) {
    eventHandlers[eventName] = []
  }
  eventHandlers[eventName].push(handler)
}

/** 取消监听后端事件 */
export function offBackendEvent(eventName, handler) {
  if (!eventHandlers[eventName]) return
  if (handler) {
    const index = eventHandlers[eventName].indexOf(handler)
    if (index > -1) {
      eventHandlers[eventName].splice(index, 1)
    }
  } else {
    delete eventHandlers[eventName]
  }
}

/** 监听后端进程退出，返回取消监听函数 */
export function onBackendExit(handler) {
  exitHandlers.push(handler)
  return () => {
    const index = exitHandlers.indexOf(handler)
    if (index > -1) {
      exitHandlers.splice(index, 1)
    }
  }
}

/** 取消监听后端进程退出 */
export function offBackendExit(handler) {
  if (handler) {
    const index = exitHandlers.indexOf(handler)
    if (index > -1) {
      exitHandlers.splice(index, 1)
    }
  } else {
    exitHandlers.length = 0
  }
}

/** 监听后端就绪事件，返回取消监听函数 */
export function onBackendReady(handler) {
  backendReadyHandlers.push(handler)
  return () => {
    const index = backendReadyHandlers.indexOf(handler)
    if (index > -1) {
      backendReadyHandlers.splice(index, 1)
    }
  }
}

/** 取消监听后端就绪事件 */
export function offBackendReady(handler) {
  if (handler) {
    const index = backendReadyHandlers.indexOf(handler)
    if (index > -1) {
      backendReadyHandlers.splice(index, 1)
    }
  } else {
    backendReadyHandlers.length = 0
  }
}

// ============ 文件拖放事件 ============
const fileDropHandlers = []
const fileDropHoverHandlers = []
const fileDropCancelledHandlers = []

/** 监听文件拖放事件，返回取消监听函数 */
export function onFileDrop(handler) {
  fileDropHandlers.push(handler)
  return () => {
    const index = fileDropHandlers.indexOf(handler)
    if (index > -1) {
      fileDropHandlers.splice(index, 1)
    }
  }
}

/** 取消监听文件拖放事件 */
export function offFileDrop(handler) {
  if (handler) {
    const index = fileDropHandlers.indexOf(handler)
    if (index > -1) {
      fileDropHandlers.splice(index, 1)
    }
  } else {
    fileDropHandlers.length = 0
  }
}

/** 监听文件拖放悬停事件，返回取消监听函数 */
export function onFileDropHover(handler) {
  fileDropHoverHandlers.push(handler)
  return () => {
    const index = fileDropHoverHandlers.indexOf(handler)
    if (index > -1) {
      fileDropHoverHandlers.splice(index, 1)
    }
  }
}

/** 取消监听文件拖放悬停事件 */
export function offFileDropHover(handler) {
  if (handler) {
    const index = fileDropHoverHandlers.indexOf(handler)
    if (index > -1) {
      fileDropHoverHandlers.splice(index, 1)
    }
  } else {
    fileDropHoverHandlers.length = 0
  }
}

/** 监听文件拖放取消事件，返回取消监听函数 */
export function onFileDropCancelled(handler) {
  fileDropCancelledHandlers.push(handler)
  return () => {
    const index = fileDropCancelledHandlers.indexOf(handler)
    if (index > -1) {
      fileDropCancelledHandlers.splice(index, 1)
    }
  }
}

/** 取消监听文件拖放取消事件 */
export function offFileDropCancelled(handler) {
  if (handler) {
    const index = fileDropCancelledHandlers.indexOf(handler)
    if (index > -1) {
      fileDropCancelledHandlers.splice(index, 1)
    }
  } else {
    fileDropCancelledHandlers.length = 0
  }
}

// ============ 窗口控制 ============
/** 显示窗口（前端 UI 渲染完毕后调用） */
export async function showWindow() {
  await waitReady()
  return getInvoke()('plugin_show_window')
}

/** 关闭窗口 */
export async function close() {
  await waitReady()
  return getTauri().window.getCurrentWindow().close()
}

/** 最小化窗口 */
export async function minimize() {
  await waitReady()
  return getTauri().window.getCurrentWindow().minimize()
}

/** 最大化窗口 */
export async function maximize() {
  await waitReady()
  return getTauri().window.getCurrentWindow().maximize()
}

/** 取消最大化 */
export async function unmaximize() {
  await waitReady()
  return getTauri().window.getCurrentWindow().unmaximize()
}

/** 切换最大化状态 */
export async function toggleMaximize() {
  await waitReady()
  return getTauri().window.getCurrentWindow().toggleMaximize()
}

// ============ 应用信息 ============
export const app = {
  getName: async () => {
    await waitReady()
    return getTauri().app.getName()
  },
  getVersion: async () => {
    await waitReady()
    return getTauri().app.getVersion()
  },
  getTauriVersion: async () => {
    await waitReady()
    return getTauri().app.getTauriVersion()
  }
}

// ============ 系统信息 ============
export const os = {
  platform: async () => {
    await waitReady()
    return getTauri().os.platform()
  },
  version: async () => {
    await waitReady()
    return getTauri().os.version()
  },
  arch: async () => {
    await waitReady()
    return getTauri().os.arch()
  },
  locale: async () => {
    await waitReady()
    return getTauri().os.locale()
  },
  hostname: async () => {
    await waitReady()
    return getTauri().os.hostname()
  }
}

// ============ 路径操作 ============
export const path = {
  appDataDir: async () => {
    await waitReady()
    return getTauri().path.appDataDir()
  },
  homeDir: async () => {
    await waitReady()
    return getTauri().path.homeDir()
  },
  desktopDir: async () => {
    await waitReady()
    return getTauri().path.desktopDir()
  },
  downloadDir: async () => {
    await waitReady()
    return getTauri().path.downloadDir()
  },
  documentDir: async () => {
    await waitReady()
    return getTauri().path.documentDir()
  },
  tempDir: async () => {
    await waitReady()
    return getTauri().path.tempDir()
  },
  join: async (...paths) => {
    await waitReady()
    return getTauri().path.join(...paths)
  },
  basename: async (p) => {
    await waitReady()
    return getTauri().path.basename(p)
  },
  dirname: async (p) => {
    await waitReady()
    return getTauri().path.dirname(p)
  },
  extname: async (p) => {
    await waitReady()
    return getTauri().path.extname(p)
  }
}

// ============ 剪贴板 ============
export const clipboard = {
  readText: async () => {
    await waitReady()
    return getTauri().clipboard.readText()
  },
  writeText: async (text) => {
    await waitReady()
    return getTauri().clipboard.writeText(text)
  }
}

// ============ Shell ============
export const shell = {
  open: async (path) => {
    await waitReady()
    return getTauri().shell.open(path)
  }
}

// ============ 文件路径转换 ============
/**
 * 将本地文件路径转换为可在 webview 中加载的 URL
 * - 生产环境：使用当前插件的 plugin:// 协议同域名加载，避免跨域
 * - 开发环境：使用 Tauri 内置的 convertFileSrc
 * @param {string} filePath - 本地文件路径
 * @returns {string} 转换后的 URL
 */
export function convertFileSrc(filePath) {
  // 判断是否为生产环境（hostname 包含 plugin. 前缀，如 plugin.audio-split.localhost）
  const isProduction = window.location.hostname.startsWith('plugin.')
  if (isProduction) {
    // 生产环境：使用当前插件的同源 URL
    let path = filePath.replace(/\\/g, '/')
    if (!path.startsWith('/')) {
      path = '/' + path
    }
    return `${window.location.origin}${path}`
  } else {
    // 开发环境：使用 Tauri 内置方法
    if (window.__TAURI__?.core?.convertFileSrc) {
      return window.__TAURI__.core.convertFileSrc(filePath)
    }
    // 回退方案
    let path = filePath.replace(/\\/g, '/')
    if (!path.startsWith('/')) {
      path = '/' + path
    }
    return `asset://localhost${path}`
  }
}

// ============ 对话框 ============
export const dialog = {
  open: async (options = {}) => {
    await waitReady()
    return getTauri().dialog.open(options)
  },
  save: async (options = {}) => {
    await waitReady()
    return getTauri().dialog.save(options)
  },
  message: async (message, options = {}) => {
    await waitReady()
    return getTauri().dialog.message(message, options)
  },
  ask: async (message, options = {}) => {
    await waitReady()
    return getTauri().dialog.ask(message, options)
  },
  confirm: async (message, options = {}) => {
    await waitReady()
    return getTauri().dialog.confirm(message, options)
  }
}

// ============ 文件管理 ============
export const fs = {
  createFile: async (path, overwrite = false) => {
    return invokeFileCommand('create_file', { path, overwrite })
  },
  createDir: async (path, recursive = true) => {
    return invokeFileCommand('create_dir', { path, recursive })
  },
  writeTextFile: async (path, content, append = false) => {
    return invokeFileCommand('write_text_file', { path, content, append })
  },
  writeBase64File: async (path, base64Data, append = false) => {
    return invokeFileCommand('write_base64_file', { path, base64Data, append })
  },
  readTextFile: async (path) => {
    return invokeFileCommand('read_text_file', { path })
  },
  removeFile: async (path) => {
    return invokeFileCommand('remove_file', { path })
  },
  removeDir: async (path, recursive = true) => {
    return invokeFileCommand('remove_dir', { path, recursive })
  },
  getInfo: async (path) => {
    return invokeFileCommand('get_path_info', { path })
  },
  exists: async (path) => {
    return invokeFileCommand('path_exists', { path })
  },
  isFile: async (path) => {
    return invokeFileCommand('path_is_file', { path })
  },
  isDir: async (path) => {
    return invokeFileCommand('path_is_dir', { path })
  },
  copyFile: async (src, dest) => {
    return invokeFileCommand('copy_file', { src, dest })
  }
}

// ============ 通知 ============
export const notification = {
  isPermissionGranted: async () => {
    await waitReady()
    return getTauri().notification.isPermissionGranted()
  },
  requestPermission: async () => {
    await waitReady()
    return getTauri().notification.requestPermission()
  },
  send: async (options) => {
    await waitReady()
    return getTauri().notification.sendNotification(options)
  }
}

// ============ 进程控制 ============
export const process = {
  exit: async (code = 0) => {
    await waitReady()
    return getTauri().process.exit(code)
  },
  relaunch: async () => {
    await waitReady()
    return getTauri().process.relaunch()
  }
}

// ============ 桌面快捷方式 ============
/**
 * 创建桌面快捷方式
 * @param {string} pluginName - 快捷方式显示名称（可选，默认使用插件 title）
 * @returns {Promise<void>}
 */
export async function createDesktopShortcut(pluginName) {
  await waitReady()
  return getInvoke()('plugin_create_shortcut', { pluginName: pluginName || null })
}

// ============ 法律文件阅读窗口 ============
/**
 * 打开法律文件阅读窗口
 * @param {string} relativePath - 相对插件根目录的文件路径
 * @param {string} displayName - 窗口显示名（可选）
 * @returns {Promise<string>}
 */
export async function openLegalDocumentViewer(relativePath, displayName) {
  await waitReady()
  return getInvoke()('plugin_open_legal_document_viewer', {
    relativePath,
    displayName: displayName || null,
  })
}

// ============ localStorage 统计 ============
/**
 * 计算当前域名的 localStorage 大小
 * @returns {string} 格式化后的大小字符串
 */
function calculateLocalStorageSize() {
  // 检查 localStorage 是否可用
  if (typeof localStorage === 'undefined') {
    return '0'
  }

  try {
    let totalSize = 0
    for (let key in localStorage) {
      if (localStorage.hasOwnProperty(key)) {
        totalSize += localStorage[key].length + key.length
      }
    }
    // 转换为KB或MB（UTF-16编码，每个字符2字节）
    const sizeInKB = (totalSize * 2) / 1024
    if (sizeInKB < 1024) {
      return `${sizeInKB.toFixed(2)} KB`
    } else {
      return `${(sizeInKB / 1024).toFixed(2)} MB`
    }
  } catch (error) {
    console.error('计算 localStorage 大小失败:', error)
    return '0'
  }
}

/**
 * 输出 localStorage 统计信息
 */
function logLocalStorageStats() {
  const hostname = window.location.hostname
  const port = window.location.port
  const domain = `${hostname}${port ? ':' + port : ''}`
  const size = calculateLocalStorageSize()

  console.log('=== localStorage 统计信息 ===')
  console.log(`域名: ${domain}`)
  console.log(`存储大小: ${size}`)
  console.log('============================')
}

// ============ 初始化 ============
let eventListenerSetup = false  // 防止重复注册

async function setupEventListener() {
  if (eventListenerSetup) return  // 已注册则跳过
  eventListenerSetup = true

  const listen = getTauri()?.event?.listen
  if (!listen) return

  await listen('plugin-backend-event', (event) => {
    const data = event.payload
    if (data?.event && eventHandlers[data.event]) {
      eventHandlers[data.event].forEach(handler => handler(data.data))
    }
  })

  await listen('plugin-backend-exit', (event) => {
    exitHandlers.forEach(handler => handler(event.payload))
  })

  await listen('plugin-backend-ready', (event) => {
    backendReadyHandlers.forEach(handler => handler(event.payload))
  })

  // 监听文件拖放事件
  await listen('tauri://file-drop', (event) => {
    const files = event.payload
    fileDropHandlers.forEach(handler => handler(files))
  })

  await listen('tauri://file-drop-hover', (event) => {
    fileDropHoverHandlers.forEach(handler => handler(event.payload))
  })

  await listen('tauri://file-drop-cancelled', (event) => {
    fileDropCancelledHandlers.forEach(handler => handler(event.payload))
  })
}

function initWhenReady() {
  if (window.__TAURI__?.core && window.__TAURI__?.event) {
    sdkReady = true
    setupEventListener()
    sdkReadyResolve()

    // 输出 localStorage 统计信息
    logLocalStorageStats()

    return true
  }
  return false
}

// 自动初始化
if (typeof window !== 'undefined') {
  if (!initWhenReady()) {
    const checkInterval = setInterval(() => {
      if (initWhenReady()) {
        clearInterval(checkInterval)
      }
    }, 50)

    setTimeout(() => {
      clearInterval(checkInterval)
      if (!sdkReady) {
        const error = new Error('PluginSDK 初始化超时: window.__TAURI__ 不可用')
        console.error(error.message)
        sdkReadyReject(error)
      }
    }, 10000)
  }
}

// ============ 导出 PluginSDK 对象 ============
export const PluginSDK = {
  waitReady,
  callBackend,
  getInfo,
  getAppInfo,
  getBackendState,
  restartBackend,
  stopBackend,
  onBackendEvent,
  offBackendEvent,
  onBackendExit,
  offBackendExit,
  onBackendReady,
  offBackendReady,
  onFileDrop,
  offFileDrop,
  onFileDropHover,
  offFileDropHover,
  onFileDropCancelled,
  offFileDropCancelled,
  showWindow,
  close,
  minimize,
  maximize,
  unmaximize,
  toggleMaximize,
  createDesktopShortcut,
  openLegalDocumentViewer,
  convertFileSrc,
  app,
  os,
  path,
  clipboard,
  shell,
  dialog,
  fs,
  notification,
  process
}

// UMD 全局变量
if (typeof window !== 'undefined') {
  window.PluginSDK = PluginSDK
}
