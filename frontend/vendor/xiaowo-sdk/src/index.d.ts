/**
 * 小蜗工具 - 插件前端 SDK 类型定义
 */

/** 后端事件处理函数 */
export type BackendEventHandler<T = unknown> = (data: T) => void

/** 后端退出信息 */
export interface BackendExitInfo {
  [key: string]: unknown
}

/** 后端退出处理函数 */
export type BackendExitHandler = (info: BackendExitInfo) => void

/** 后端就绪信息 */
export interface BackendReadyInfo {
  status: string
  [key: string]: unknown
}

/** 后端就绪处理函数 */
export type BackendReadyHandler = (info: BackendReadyInfo) => void

/** 文件拖放处理函数 */
export type FileDropHandler = (files: string[]) => void

/** 文件拖放悬停处理函数 */
export type FileDropHoverHandler = () => void

/** 文件拖放取消处理函数 */
export type FileDropCancelledHandler = () => void

/** 版权信息。可在清单中编辑并随版本发布同步到服务端，运行时读取在线资料。所有字段均可留空。 */
export interface OpenSourceInfo {
  upstream_name?: string
  upstream_author?: string
  upstream_url?: string[]
  source_url?: string[]
  license_name?: string
  license_spdx?: string
  license_files?: string[]
  notice_files?: string[]
  copyright_files?: string[]
  source_required?: boolean
  upstream_source_modified?: boolean
  modification_notice?: string
  modification_files?: string[]
}

/** 运行时合并信息。open_source 与其他展示字段均来自在线应用资料。 */
export interface PluginManifest {
  id: string
  title: string
  version: string
  description?: string
  author?: string
  /** 兼容旧字段；当前图标统一使用 app_info.icon 或 server_icon。 */
  icon?: string
  server_icon?: string
  frontend?: {
    theme?: 'dark' | 'light'
    [key: string]: unknown
  }
  open_source?: OpenSourceInfo | null
  /** 由宿主依据所在目录生成，不能在 manifest.json 中设置。 */
  is_dev?: boolean
}

/** 应用资料。id 是应用标识，正式应用的数据库编号保存在 server_id。 */
export interface ApplicationInfo {
  id: string
  model_name: string
  title: string
  source: 'development' | 'online'
  server_id?: number
  description?: string
  icon?: string
  dev_nickname?: string
  category_id?: number
  langs?: Record<string, Record<string, string>>
  extra_data?: unknown
  /** 服务端保存的完整版权资料，与运行时 manifest.open_source 使用同一在线来源。 */
  open_source?: OpenSourceInfo | null
  [key: string]: unknown
}

/** 插件基本信息（运行配置与当前应用资料） */
export interface PluginInfo {
  manifest: PluginManifest
  app_info: ApplicationInfo
  extra_data?: Record<string, unknown>
  window_scale: string
  language: string
  theme?: string
  plugin_dir: string
}

/** 后端状态响应 */
export interface BackendStateResponse {
  is_ready: boolean
}

/** 对话框打开选项 */
export interface DialogOpenOptions {
  multiple?: boolean
  directory?: boolean
  filters?: { name: string; extensions: string[] }[]
  defaultPath?: string
  title?: string
}

/** 对话框保存选项 */
export interface DialogSaveOptions {
  filters?: { name: string; extensions: string[] }[]
  defaultPath?: string
  title?: string
}

/** 对话框消息选项 */
export interface DialogMessageOptions {
  title?: string
  type?: 'info' | 'warning' | 'error'
}

/** 通知选项 */
export interface NotificationOptions {
  title: string
  body?: string
  icon?: string
}

/** 路径信息 */
export interface PathInfo {
  path: string
  exists: boolean
  is_file: boolean
  is_dir: boolean
}

/** 插件 SDK 类 */
export interface IPluginSDK {
  /** 等待 SDK 准备好 */
  waitReady(): Promise<void>

  /** 调用插件后端方法 */
  callBackend<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T>

  /** 获取插件基本信息（清单、扩展数据、窗口缩放、语言） */
  getInfo(): Promise<PluginInfo>

  /** 获取当前应用资料，缺失时标题使用 ID，其余缺失字段不返回。 */
  getAppInfo(): Promise<ApplicationInfo>

  /** 获取插件后端子进程状态 */
  getBackendState(): Promise<BackendStateResponse>

  /** 重启插件后端进程 */
  restartBackend(): Promise<void>

  /** 停止插件后端进程 */
  stopBackend(): Promise<void>

  /** 监听后端事件 */
  onBackendEvent<T = unknown>(eventName: string, handler: BackendEventHandler<T>): void

  /** 取消监听后端事件 */
  offBackendEvent<T = unknown>(eventName: string, handler?: BackendEventHandler<T>): void

  /** 监听后端进程退出，返回取消监听函数 */
  onBackendExit(handler: BackendExitHandler): () => void

  /** 取消监听后端进程退出 */
  offBackendExit(handler?: BackendExitHandler): void

  /** 监听后端就绪事件，返回取消监听函数 */
  onBackendReady(handler: BackendReadyHandler): () => void

  /** 取消监听后端就绪事件 */
  offBackendReady(handler?: BackendReadyHandler): void

  /** 监听文件拖放事件，返回取消监听函数 */
  onFileDrop(handler: FileDropHandler): () => void

  /** 取消监听文件拖放事件 */
  offFileDrop(handler?: FileDropHandler): void

  /** 监听文件拖放悬停事件，返回取消监听函数 */
  onFileDropHover(handler: FileDropHoverHandler): () => void

  /** 取消监听文件拖放悬停事件 */
  offFileDropHover(handler?: FileDropHoverHandler): void

  /** 监听文件拖放取消事件，返回取消监听函数 */
  onFileDropCancelled(handler: FileDropCancelledHandler): () => void

  /** 取消监听文件拖放取消事件 */
  offFileDropCancelled(handler?: FileDropCancelledHandler): void

  /** 显示插件窗口（前端 UI 渲染完毕后调用） */
  showWindow(): Promise<void>

  /** 关闭插件窗口 */
  close(): Promise<void>

  /** 最小化窗口 */
  minimize(): Promise<void>

  /** 最大化窗口 */
  maximize(): Promise<void>

  /** 取消最大化 */
  unmaximize(): Promise<void>

  /** 切换最大化状态 */
  toggleMaximize(): Promise<void>

  /** 创建桌面快捷方式 */
  createDesktopShortcut(pluginName?: string): Promise<void>

  /** 打开法律文件阅读窗口 */
  openLegalDocumentViewer(relativePath: string, displayName?: string): Promise<string>

  /**
   * 将本地文件路径转换为可在 webview 中加载的 URL
   * @param filePath - 本地文件路径
   * @param protocol - 协议名称，默认 'asset'
   * @returns 转换后的 URL
   */
  convertFileSrc(filePath: string, protocol?: string): string

  /** 应用信息 */
  app: {
    getName(): Promise<string>
    getVersion(): Promise<string>
    getTauriVersion(): Promise<string>
  }

  /** 操作系统信息 */
  os: {
    platform(): Promise<string>
    version(): Promise<string>
    arch(): Promise<string>
    locale(): Promise<string | null>
    hostname(): Promise<string>
  }

  /** 路径操作 */
  path: {
    appDataDir(): Promise<string>
    homeDir(): Promise<string>
    desktopDir(): Promise<string>
    downloadDir(): Promise<string>
    documentDir(): Promise<string>
    tempDir(): Promise<string>
    join(...paths: string[]): Promise<string>
    basename(path: string): Promise<string>
    dirname(path: string): Promise<string>
    extname(path: string): Promise<string>
  }

  /** 剪贴板 */
  clipboard: {
    readText(): Promise<string | null>
    writeText(text: string): Promise<void>
  }

  /** Shell 操作 */
  shell: {
    open(path: string): Promise<void>
  }

  /** 对话框 */
  dialog: {
    open(options?: DialogOpenOptions): Promise<string | string[] | null>
    save(options?: DialogSaveOptions): Promise<string | null>
    message(message: string, options?: DialogMessageOptions): Promise<void>
    ask(message: string, options?: DialogMessageOptions): Promise<boolean>
    confirm(message: string, options?: DialogMessageOptions): Promise<boolean>
  }

  /** 文件管理 */
  fs: {
    createFile(path: string, overwrite?: boolean): Promise<void>
    createDir(path: string, recursive?: boolean): Promise<void>
    writeTextFile(path: string, content: string, append?: boolean): Promise<void>
    writeBase64File(path: string, base64Data: string, append?: boolean): Promise<void>
    readTextFile(path: string): Promise<string>
    removeFile(path: string): Promise<void>
    removeDir(path: string, recursive?: boolean): Promise<void>
    getInfo(path: string): Promise<PathInfo>
    exists(path: string): Promise<boolean>
    isFile(path: string): Promise<boolean>
    isDir(path: string): Promise<boolean>
    copyFile(src: string, dest: string): Promise<void>
  }

  /** 通知 */
  notification: {
    isPermissionGranted(): Promise<boolean>
    requestPermission(): Promise<string>
    send(options: NotificationOptions): Promise<void>
  }

  /** 进程控制 */
  process: {
    exit(code?: number): Promise<void>
    relaunch(): Promise<void>
  }
}

/** 插件 SDK 实例 */
export const PluginSDK: IPluginSDK

// ============ 独立导出的函数 ============

/** 等待 SDK 准备好 */
export function waitReady(): Promise<void>

/** 调用插件后端方法 */
export function callBackend<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T>

/** 获取插件基本信息（清单、扩展数据、窗口缩放、语言） */
export function getInfo(): Promise<PluginInfo>

export function getAppInfo(): Promise<ApplicationInfo>

/** 获取插件后端子进程状态 */
export function getBackendState(): Promise<BackendStateResponse>

/** 重启插件后端进程 */
export function restartBackend(): Promise<void>

/** 停止插件后端进程 */
export function stopBackend(): Promise<void>

/** 监听后端事件 */
export function onBackendEvent<T = unknown>(eventName: string, handler: BackendEventHandler<T>): void

/** 取消监听后端事件 */
export function offBackendEvent<T = unknown>(eventName: string, handler?: BackendEventHandler<T>): void

/** 监听后端进程退出，返回取消监听函数 */
export function onBackendExit(handler: BackendExitHandler): () => void

/** 取消监听后端进程退出 */
export function offBackendExit(handler?: BackendExitHandler): void

/** 监听后端就绪事件，返回取消监听函数 */
export function onBackendReady(handler: BackendReadyHandler): () => void

/** 取消监听后端就绪事件 */
export function offBackendReady(handler?: BackendReadyHandler): void

/** 监听文件拖放事件，返回取消监听函数 */
export function onFileDrop(handler: FileDropHandler): () => void

/** 取消监听文件拖放事件 */
export function offFileDrop(handler?: FileDropHandler): void

/** 监听文件拖放悬停事件，返回取消监听函数 */
export function onFileDropHover(handler: FileDropHoverHandler): () => void

/** 取消监听文件拖放悬停事件 */
export function offFileDropHover(handler?: FileDropHoverHandler): void

/** 监听文件拖放取消事件，返回取消监听函数 */
export function onFileDropCancelled(handler: FileDropCancelledHandler): () => void

/** 取消监听文件拖放取消事件 */
export function offFileDropCancelled(handler?: FileDropCancelledHandler): void

/** 显示插件窗口（前端 UI 渲染完毕后调用） */
export function showWindow(): Promise<void>

/** 关闭插件窗口 */
export function close(): Promise<void>

/** 最小化窗口 */
export function minimize(): Promise<void>

/** 最大化窗口 */
export function maximize(): Promise<void>

/** 取消最大化 */
export function unmaximize(): Promise<void>

/** 切换最大化状态 */
export function toggleMaximize(): Promise<void>

/** 创建桌面快捷方式 */
export function createDesktopShortcut(pluginName?: string): Promise<void>

/** 打开法律文件阅读窗口 */
export function openLegalDocumentViewer(relativePath: string, displayName?: string): Promise<string>

/**
 * 将本地文件路径转换为可在 webview 中加载的 URL
 * @param filePath - 本地文件路径
 * @param protocol - 协议名称，默认 'asset'
 * @returns 转换后的 URL
 */
export function convertFileSrc(filePath: string, protocol?: string): string

// ============ 独立导出的模块对象 ============

/** 应用信息 */
export const app: IPluginSDK['app']

/** 操作系统信息 */
export const os: IPluginSDK['os']

/** 路径操作 */
export const path: IPluginSDK['path']

/** 剪贴板 */
export const clipboard: IPluginSDK['clipboard']

/** Shell 操作 */
export const shell: IPluginSDK['shell']

/** 对话框 */
export const dialog: IPluginSDK['dialog']

/** 文件管理 */
export const fs: IPluginSDK['fs']

/** 通知 */
export const notification: IPluginSDK['notification']

/** 进程控制 */
export const process: IPluginSDK['process']

export default PluginSDK

declare global {
  interface Window {
    PluginSDK: IPluginSDK
    __PLUGIN_INFO__?: PluginInfo
  }
}
