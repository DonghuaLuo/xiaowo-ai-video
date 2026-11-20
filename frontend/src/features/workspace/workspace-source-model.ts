import {
  type EpisodeSourceText,
  type EpisodeSourceFile,
  type SourceSegment,
  type SourceText,
} from "@/backend"
import { countContentChars } from "@/lib/text-metrics"
import { errMsg } from "@/shared/backend-result"


export type SourceFile = {
  id: string
  title: string
  kind: string
  sourceGroup?: string
  source_group?: string
  status: string
  wordCount: number
  excerpt: string
  createdAt: string
  rawFilename?: string
  contentPath?: string
  relativePath?: string
  appendSegments?: SourceSegment[]
  append_segments?: SourceSegment[]
  sourceId?: string
  segmentId?: string
  sourceKind?: "source" | "segment"
  segmentKind?: string
  totalTextHash?: string
  total_text_hash?: string
  currentTotalTextHash?: string
  current_total_text_hash?: string
  totalTextHashStatus?: string
  total_text_hash_status?: string
  needsRestore?: boolean
  needs_restore?: boolean
  hasTotalTextBackup?: boolean
  has_total_text_backup?: boolean
}

type NovelSourcePayload = {
  title: string
  content: string
  kind?: string
  sourceGroup?: SourceFileGroup
  rawFilename?: string
}

export type SourceFileGroup = "novel" | "supplemental"

export const TOTAL_SOURCE_DESCRIPTION =
  "总文件路径：后续分集拆分、资产拆分与视频生成都以它作为核心原文。"

export const SOURCE_FILE_COLUMN_DESCRIPTIONS: Record<SourceFileGroup, string> = {
  novel: "用于按顺序追加连载章节，新章节会合并进总文件。",
  supplemental: "为角色、生物、场景、道具拆分补充设定、背景与参考资料。",
}

function isTxtNovelFile(file: File) {
  return file.name.toLowerCase().endsWith(".txt")
}

function isMarkdownFile(file: File) {
  return file.name.toLowerCase().endsWith(".md")
}

function isAllowedSourceFile(file: File, sourceGroup: SourceFileGroup) {
  if (sourceGroup === "novel") return isTxtNovelFile(file)
  return isTxtNovelFile(file) || isMarkdownFile(file)
}

function sourceFileFormatLabel(sourceGroup: SourceFileGroup) {
  return sourceGroup === "novel" ? ".txt" : ".txt 或 .md"
}

function sourceTitleFromFileName(fileName: string) {
  return fileName.replace(/\.[^.]+$/, "").trim() || "小说文本"
}

const SOURCE_TEXT_DECODER_LABELS = ["utf-8", "gb18030", "gbk", "big5"] as const

function sourceTextCorruptionReason(text: string) {
  const value = String(text || "")
  if (!value) return ""
  let replacementCount = 0
  for (let index = 0; index < value.length; index += 1) {
    if (value.charCodeAt(index) === 0xfffd) replacementCount += 1
  }
  if (replacementCount > Math.max(2, value.length * 0.001)) {
    return "文本包含大量编码替换字符"
  }
  const mojibakeCount = (value.match(/锟斤拷|ï¿½/g) ?? []).length
  if (mojibakeCount > Math.max(1, value.length * 0.0005)) {
    return "文本疑似已被错误编码转换"
  }
  return ""
}

function decodeNovelTextBuffer(buffer: ArrayBuffer, filename: string) {
  const errors: string[] = []
  for (const label of SOURCE_TEXT_DECODER_LABELS) {
    try {
      const decoded = new TextDecoder(label, { fatal: true }).decode(buffer)
      const text = decoded.replace(/^\uFEFF/, "")
      const reason = sourceTextCorruptionReason(text)
      if (!reason) return text
      errors.push(`${label}: ${reason}`)
    } catch (error) {
      errors.push(`${label}: ${errMsg(error, "解码失败")}`)
    }
  }
  throw new Error(
    `无法识别「${filename || "文本文件"}」的文本编码，请使用 UTF-8、GB18030 或 GBK 编码的 TXT 文件。${errors.slice(0, 2).join("；")}`
  )
}

export function sourceGroupOf(source: SourceFile): SourceFileGroup {
  const value = String(
    source.sourceGroup || source.source_group || source.kind || ""
  )
    .trim()
    .toLowerCase()
  return [
    "attachment",
    "attachments",
    "extra",
    "extras",
    "material",
    "materials",
    "reference",
    "references",
    "supplement",
    "supplemental",
    "扩展资料",
    "附加资料",
    "资料",
  ].includes(value)
    ? "supplemental"
    : "novel"
}

export function sourceFileNameForSort(source: SourceFile) {
  const pathLike =
    source.sourceKind === "segment"
      ? source.rawFilename ||
        source.title ||
        source.relativePath ||
        source.contentPath
      : source.relativePath ||
        source.contentPath ||
        source.rawFilename ||
        source.title
  const normalized = String(pathLike || "").replace(/\\/g, "/")
  return (
    normalized.split("/").filter(Boolean).pop() || source.title || source.id
  )
}

function sourceSegmentsOf(source: SourceFile) {
  const rows = source.appendSegments || source.append_segments || []
  return Array.isArray(rows) ? rows : []
}

function segmentSourceId(segment: SourceSegment, fallback: string) {
  return String(segment.sourceId || segment.source_id || fallback)
}

function segmentStart(segment: SourceSegment) {
  return Number(segment.charStart ?? segment.char_start ?? 0)
}

function segmentEnd(segment: SourceSegment) {
  return Number(segment.charEnd ?? segment.char_end ?? 0)
}

function segmentCharCount(segment: SourceSegment) {
  return Number(
    segment.charCount ??
      segment.char_count ??
      segment.wordCount ??
      segment.word_count ??
      Math.max(0, segmentEnd(segment) - segmentStart(segment))
  )
}

function segmentLineStart(segment: SourceSegment) {
  return Number(segment.lineStart ?? segment.line_start ?? 0)
}

function segmentLineEnd(segment: SourceSegment) {
  return Number(segment.lineEnd ?? segment.line_end ?? 0)
}

function segmentCreatedAt(segment: SourceSegment) {
  return String(segment.createdAt || segment.created_at || "")
}

function segmentKind(segment: SourceSegment) {
  return String(segment.kind || "")
    .trim()
    .toLowerCase()
}

export function sourceSegmentKind(source: SourceFile) {
  return String(source.segmentKind || source.kind || "")
    .trim()
    .toLowerCase()
}

function segmentTitle(segment: SourceSegment) {
  return String(
    segment.rawFilename || segment.raw_filename || segment.title || "原文件"
  )
}

function segmentRangeLabel(segment: SourceSegment) {
  const lineStart = segmentLineStart(segment)
  const lineEnd = segmentLineEnd(segment)
  if (lineStart > 0 && lineEnd >= lineStart) {
    return `总文件行：${lineStart.toLocaleString()} - ${lineEnd.toLocaleString()}`
  }
  return `总文件范围：${segmentStart(segment).toLocaleString()} - ${segmentEnd(segment).toLocaleString()}`
}

export function sourceRowsFromSegments(sources: SourceFile[]) {
  const rows: SourceFile[] = []
  for (const source of sources) {
    const segments = sourceSegmentsOf(source)
    if (segments.length === 0) {
      if (Number(source.wordCount ?? 0) > 0) {
        rows.push({ ...source, sourceId: source.id, sourceKind: "source" })
      }
      continue
    }
    for (const segment of segments) {
      const sourceId = segmentSourceId(segment, source.id)
      const kind = segmentKind(segment)
      rows.push({
        id: `${sourceId}:${segment.id}`,
        title: segmentTitle(segment),
        kind: kind || "TXT",
        sourceGroup: "novel",
        status: source.status,
        wordCount: segmentCharCount(segment),
        excerpt: source.excerpt,
        createdAt: segmentCreatedAt(segment) || source.createdAt,
        rawFilename: segmentTitle(segment),
        contentPath: source.contentPath,
        relativePath: segmentRangeLabel(segment),
        sourceId,
        segmentId: segment.id,
        sourceKind: "segment",
        segmentKind: kind,
      })
    }
  }
  return rows
}

export function upsertSourceRows(current: SourceFile[], rows: SourceFile[]) {
  if (rows.length === 0) return current
  const next = [...current]
  for (const row of rows) {
    if (!row?.id) continue
    const index = next.findIndex((source) => source.id === row.id)
    if (index >= 0) {
      next[index] = { ...next[index], ...row }
    } else {
      next.push(row)
    }
  }
  return next
}

export function sourceTextToSourceFile(
  source: SourceFile,
  text: SourceText,
  fallbackText = ""
): SourceFile {
  const content = text.text ?? fallbackText
  return {
    ...source,
    title: text.title || source.title,
    wordCount: Number(
      text.wordCount ?? text.charCount ?? countContentChars(content)
    ),
    excerpt: content.slice(0, 120),
    contentPath: text.contentPath || source.contentPath,
    relativePath: text.relativePath || source.relativePath,
    rawFilename: text.rawFilename || source.rawFilename,
    appendSegments:
      text.appendSegments || text.append_segments || source.appendSegments,
    totalTextHash: text.totalTextHash || source.totalTextHash,
    currentTotalTextHash:
      text.currentTotalTextHash || source.currentTotalTextHash,
    totalTextHashStatus: text.totalTextHashStatus || source.totalTextHashStatus,
    needsRestore: text.needsRestore ?? source.needsRestore,
    hasTotalTextBackup: text.hasTotalTextBackup ?? source.hasTotalTextBackup,
  }
}

function sourceCreatedAtRank(source: SourceFile) {
  const timestamp = Date.parse(source.createdAt)
  return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY
}

export function sortedSourceFiles(sources: SourceFile[]) {
  return sources
    .map((source, index) => ({ source, index }))
    .sort((left, right) => {
      const timeDiff =
        sourceCreatedAtRank(right.source) - sourceCreatedAtRank(left.source)
      return timeDiff || right.index - left.index
    })
    .map((item) => item.source)
}

async function readNovelTextFile(
  file: File,
  sourceGroup: SourceFileGroup = "novel"
): Promise<NovelSourcePayload> {
  const formatLabel = sourceFileFormatLabel(sourceGroup)
  if (!isAllowedSourceFile(file, sourceGroup)) {
    throw new Error(`请选择 ${formatLabel} 文本文件`)
  }
  const content = decodeNovelTextBuffer(await file.arrayBuffer(), file.name)
  if (!content.trim()) {
    throw new Error(`文本为空，请选择包含内容的 ${formatLabel} 文件`)
  }
  return {
    title: sourceTitleFromFileName(file.name),
    content,
    kind: sourceGroup === "novel" ? "TXT" : "supplemental",
    sourceGroup,
    rawFilename: file.name,
  }
}

export async function readNovelTextFiles(
  files: File[],
  sourceGroup: SourceFileGroup = "novel"
) {
  const textFiles = files.filter((file) =>
    isAllowedSourceFile(file, sourceGroup)
  )
  if (textFiles.length === 0) {
    throw new Error(`请选择 ${sourceFileFormatLabel(sourceGroup)} 文本文件`)
  }
  return Promise.all(
    textFiles.map((file) => readNovelTextFile(file, sourceGroup))
  )
}

export function sourceCollectionName(sources: SourceFile[]) {
  if (sources.length === 0) return ""
  if (sources.length === 1) return sources[0]?.title ?? "小说文本"
  const preview = sources
    .slice(0, 2)
    .map((source) => source.title)
    .join("、")
  return `${sources.length} 部小说：${preview}${sources.length > 2 ? "…" : ""}`
}

export function episodeActionKey(source: EpisodeSourceFile, action: string) {
  return `${source.episodeId}:${action}`
}

export function sourceActionKey(source: SourceFile, action: string) {
  return `${source.id}:${action}`
}

const EPISODE_SOURCE_EXCERPT_CHARS = 180

export function episodeSourceExcerpt(text?: string | null) {
  const value = String(text ?? "")
    .replace(/\s+/g, " ")
    .trim()
  if (value.length <= EPISODE_SOURCE_EXCERPT_CHARS) return value
  return `${value.slice(0, EPISODE_SOURCE_EXCERPT_CHARS)}…`
}

export function sourceStoragePath(source: {
  relativePath?: string
  contentPath?: string
  rawFilename?: string
}) {
  if (source.relativePath) return source.relativePath
  if (source.contentPath) return `sources/${source.contentPath}`
  return source.rawFilename || "未记录存储位置"
}

export function episodeStoragePath(source: {
  relativePath?: string
  episodeId?: string
}) {
  return (
    source.relativePath ||
    `episodes/${source.episodeId || "episode"}/source.txt`
  )
}

export function episodeTitleWithId(
  source: EpisodeSourceFile,
  detail?: EpisodeSourceText
) {
  const episodeId = source.episodeId.trim()
  const title = String(detail?.title || source.title || "").trim()
  if (!episodeId) return title || "未命名分集"
  if (!title) return episodeId
  const normalizedTitle = title.toLowerCase()
  const normalizedEpisodeId = episodeId.toLowerCase()
  if (
    normalizedTitle === normalizedEpisodeId ||
    normalizedTitle.startsWith(`${normalizedEpisodeId} `) ||
    normalizedTitle.startsWith(`${normalizedEpisodeId} ·`) ||
    normalizedTitle.startsWith(`${normalizedEpisodeId}·`) ||
    normalizedTitle.startsWith(`${normalizedEpisodeId} -`) ||
    normalizedTitle.startsWith(`${normalizedEpisodeId}-`)
  ) {
    return title || episodeId
  }
  return `${episodeId} · ${title}`
}
