export type SourceSplitSegment = {
  id: string
  text: string
  start: number
  end: number
  workChainId?: string
  templateWorkChainId?: string
}

export type SourceSplitSeed = {
  id?: string
  text: string
  start?: number
  end?: number
}

function clampOffset(value: number, length: number) {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(length, Math.round(value)))
}

// Browser selections use UTF-16 offsets. Never cut a surrogate pair in half.
function textOffset(text: string, value: number) {
  const offset = clampOffset(value, text.length)
  const before = text.charCodeAt(offset - 1)
  const after = text.charCodeAt(offset)
  return before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff
    ? offset + 1
    : offset
}

function boundaryScore(text: string, offset: number) {
  const before = text[offset - 1] ?? ""
  const after = text[offset] ?? ""
  if (["。", "！", "？", "；", ".", "!", "?", ";"].includes(before)) return 5
  if (["，", "、", ",", ":", "："].includes(before)) return 3
  if (/\s/.test(before) || /\s/.test(after)) return 2
  return 0
}

function sentenceBoundaries(text: string) {
  const result: number[] = []
  for (let index = 1; index < text.length; index += 1) {
    if (boundaryScore(text, index) >= 5) result.push(index)
  }
  return result
}

function nearestBoundary(text: string, target: number, min: number, max: number) {
  const candidates = sentenceBoundaries(text).filter(
    (value) => value >= min && value <= max
  )
  if (!candidates.length) return Math.max(min, Math.min(max, target))
  return candidates.reduce((best, value) => {
    const bestDistance = Math.abs(best - target)
    const distance = Math.abs(value - target)
    if (distance < bestDistance) return value
    if (distance === bestDistance && boundaryScore(text, value) > boundaryScore(text, best)) {
      return value
    }
    return best
  }, candidates[0])
}

export function segmentsFromBreakpoints(
  text: string,
  breakpoints: number[],
  ids: string[] = []
): SourceSplitSegment[] {
  const length = text.length
  const points = [...new Set(
    breakpoints
      .map((value) => clampOffset(value, length))
      .filter((value) => value > 0 && value < length)
  )].sort((left, right) => left - right)
  const boundaries = [0, ...points, length]
  return boundaries.slice(0, -1).map((start, index) => {
    const end = boundaries[index + 1]
    return {
      id: ids[index] || `split-${index + 1}`,
      text: text.slice(start, end),
      start,
      end,
    }
  })
}

function findSeedRange(text: string, seed: SourceSplitSeed, from: number) {
  const explicitStart = typeof seed.start === "number" ? seed.start : undefined
  const explicitEnd = typeof seed.end === "number" ? seed.end : undefined
  if (
    explicitStart !== undefined &&
    explicitEnd !== undefined &&
    explicitStart >= from &&
    explicitEnd > explicitStart &&
    explicitEnd <= text.length
  ) {
    return { start: explicitStart, end: explicitEnd }
  }
  const exactStart = text.indexOf(seed.text, from)
  if (exactStart >= 0 && seed.text.length > 0) {
    return { start: exactStart, end: exactStart + seed.text.length }
  }
  const compactSeed = seed.text.replace(/\s+/g, "")
  if (!compactSeed) return null
  let compact = ""
  const indexMap: number[] = []
  for (let index = from; index < text.length; index += 1) {
    if (/\s/.test(text[index])) continue
    compact += text[index]
    indexMap.push(index)
    if (compact.endsWith(compactSeed)) {
      const start = indexMap[indexMap.length - compactSeed.length]
      return { start, end: index + 1 }
    }
  }
  return null
}

export function initialSourceSplitSegments(
  text: string,
  seeds: SourceSplitSeed[]
): SourceSplitSegment[] {
  if (!text) return []
  const ranges: Array<{ start: number; end: number; id?: string }> = []
  let cursor = 0
  for (const seed of seeds) {
    const range = findSeedRange(text, seed, cursor)
    if (!range || range.start < cursor) continue
    ranges.push({ ...range, id: seed.id })
    cursor = range.end
  }
  if (ranges.length === seeds.length && ranges.length && !text.slice(0, ranges[0].start).trim()) {
    return ranges.map((range, index) => {
      const start = index === 0 ? 0 : ranges[index - 1].end
      const end = index === ranges.length - 1 ? text.length : Math.max(start + 1, range.end)
      return {
        id: range.id || `split-${index + 1}`,
        workChainId: range.id,
        templateWorkChainId: range.id,
        text: text.slice(start, end),
        start,
        end,
      }
    })
  }
  return segmentsFromBreakpoints(text, [])
}

export function adjustSegmentCount(
  text: string,
  segments: SourceSplitSegment[],
  targetCount: number
) {
  const count = Math.max(1, Math.min(30, Math.round(targetCount)))
  if (!text) return []
  if (!segments.length) return segmentsFromBreakpoints(text, [])
  if (segments.length === count) return segments

  const currentBreakpoints = segments.slice(0, -1).map((segment) => segment.end)
  if (count < segments.length) {
    const keepCount = count - 1
    const candidates = currentBreakpoints.map((offset, index) => ({
      offset,
      index,
      score: boundaryScore(text, offset) * 1000 + Math.min(
        segments[index].text.length,
        segments[index + 1].text.length
      ),
    }))
    candidates.sort((left, right) => right.score - left.score)
    const kept = candidates
      .slice(0, keepCount)
      .sort((left, right) => left.offset - right.offset)
      .map((item) => item.offset)
    return segmentsFromBreakpoints(text, kept, segments.map((segment) => segment.id))
  }

  const points = [...currentBreakpoints]
  while (points.length < count - 1) {
    const next = segmentsFromBreakpoints(text, points)
    const longestIndex = next.reduce(
      (best, segment, index) =>
        segment.text.length > next[best].text.length ? index : best,
      0
    )
    const target = next[longestIndex].start + Math.floor(next[longestIndex].text.length / 2)
    const min = next[longestIndex].start + 1
    const max = next[longestIndex].end - 1
    const point = nearestBoundary(text, target, min, max)
    if (points.includes(point) || point <= 0 || point >= text.length) break
    points.push(point)
    points.sort((left, right) => left - right)
  }
  return segmentsFromBreakpoints(text, points, segments.map((segment) => segment.id))
}

export function moveSegmentBoundary(
  text: string,
  segments: SourceSplitSegment[],
  boundaryIndex: number,
  offset: number
) {
  if (segments.length < 2 || boundaryIndex < 0 || boundaryIndex >= segments.length - 1) return segments
  const index = Math.max(0, Math.min(segments.length - 2, boundaryIndex))
  const min = segments[index].start + 1
  const max = segments[index + 1].end - 1
  const nextOffset = textOffset(text, Math.max(min, Math.min(max, offset)))
  if (nextOffset === segments[index].end || nextOffset > max) return segments
  if (!text.slice(segments[index].start, nextOffset).trim() || !text.slice(nextOffset, segments[index + 1].end).trim()) return segments
  const points = segments.slice(0, -1).map((segment) => segment.end)
  points[index] = nextOffset
  return segmentsFromBreakpoints(text, points).map((segment, cursor) => ({
    ...segments[cursor], ...segment, id: segments[cursor].id,
  }))
}

export function addSegmentBoundary(text: string, segments: SourceSplitSegment[], offset: number) {
  if (segments.length >= 30) return segments
  const point = textOffset(text, offset)
  if (!point || point >= text.length || segments.some((segment) => segment.end === point)) return segments
  const bounded = segments.find((segment) => point > segment.start && point < segment.end)
  if (!bounded) return segments
  if (!text.slice(bounded.start, point).trim() || !text.slice(point, bounded.end).trim()) return segments
  const index = segments.indexOf(bounded)
  const origins = [...segments]
  origins.splice(index + 1, 0, {
    ...bounded,
    id: crypto.randomUUID(),
    workChainId: undefined,
    templateWorkChainId: bounded.workChainId || bounded.templateWorkChainId,
  })
  return segmentsFromBreakpoints(text, [...segments.slice(0, -1).map((segment) => segment.end), point])
    .map((segment, cursor) => ({ ...origins[cursor], ...segment, id: origins[cursor].id }))
}

export function removeSegmentBoundary(text: string, segments: SourceSplitSegment[], boundaryIndex: number) {
  if (segments.length <= 1 || boundaryIndex < 0 || boundaryIndex >= segments.length - 1) return segments
  const points = segments.slice(0, -1).map((segment) => segment.end)
  points.splice(Math.max(0, Math.min(points.length - 1, boundaryIndex)), 1)
  const origins = [...segments]
  const first = origins[boundaryIndex]
  const second = origins[boundaryIndex + 1]
  origins.splice(boundaryIndex, 2, first.workChainId ? first : {
    ...first,
    workChainId: second.workChainId,
    templateWorkChainId: first.templateWorkChainId || second.templateWorkChainId,
  })
  return segmentsFromBreakpoints(text, points)
    .map((segment, index) => ({ ...origins[index], ...segment, id: origins[index].id }))
}

export function editSourceSplitSegment(segments: SourceSplitSegment[], index: number, text: string) {
  let cursor = 0
  return segments.map((segment, current) => {
    const nextText = current === index ? text : segment.text
    const start = cursor
    cursor += nextText.length
    return { ...segment, text: nextText, start, end: cursor }
  })
}

export function sourceSplitIsValid(segments: SourceSplitSegment[], text: string) {
  return Boolean(
    text &&
    segments.length &&
    segments.every((segment) => segment.text.trim()) &&
    segments.map((segment) => segment.text).join("") === text
  )
}
