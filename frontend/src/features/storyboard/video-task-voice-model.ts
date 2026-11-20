import type { MediaAsset } from "@/backend"

export type VideoVoiceOverride = {
  mode: "auto" | "text" | "reference_audio"
  displayName?: string
  voiceStyle?: string
  referenceAudio?: MediaAsset | null
}
export type VideoVoiceSettings = {
  usedSpeakerIds: string[]
  voiceDesign: { speakers: Array<{ speakerId: string; displayName: string; voiceStyle: string }> }
  voiceOverrides: Record<string, VideoVoiceOverride | null>
}

export function videoVoiceSettingsFromCard(card: Record<string, any> = {}): VideoVoiceSettings {
  const speakers = Array.isArray(card.voiceDesign?.speakers) ? card.voiceDesign.speakers : []
  return {
    usedSpeakerIds: Array.isArray(card.usedSpeakerIds) ? card.usedSpeakerIds : speakers.map((row: { speakerId: string }) => row.speakerId),
    voiceDesign: { speakers },
    voiceOverrides: card.voiceOverrides ?? {},
  }
}

export function videoVoiceSettingsKey(settings?: VideoVoiceSettings) {
  return JSON.stringify(settings ? [
    settings.usedSpeakerIds,
    [...settings.voiceDesign.speakers].sort((a, b) => a.speakerId.localeCompare(b.speakerId)),
    Object.entries(settings.voiceOverrides).sort(([a], [b]) => a.localeCompare(b)),
  ] : [[], [], []])
}

export function videoTaskVoiceName(settings: VideoVoiceSettings, speakerId: string, sources: Array<{ speakerId: string; displayName: string }> = []) {
  return (settings.voiceOverrides[speakerId]?.displayName || sources.find((row) => row.speakerId === speakerId)?.displayName
    || settings.voiceDesign.speakers.find((row) => row.speakerId === speakerId)?.displayName || speakerId).trim()
}

export function hasVideoTaskVoiceName(settings: VideoVoiceSettings, name: string, sources: Array<{ speakerId: string; displayName: string }> = []) {
  return settings.usedSpeakerIds.some((speakerId) => videoTaskVoiceName(settings, speakerId, sources) === name.trim())
}

export function addVideoTaskVoice(settings: VideoVoiceSettings, voice: { speakerId: string; displayName: string; voiceStyle: string }, mode: VideoVoiceOverride["mode"] = "text", sources: Array<{ speakerId: string; displayName: string }> = []): VideoVoiceSettings {
  if (!voice.displayName.trim() || settings.usedSpeakerIds.includes(voice.speakerId) || hasVideoTaskVoiceName(settings, voice.displayName, sources)) return settings
  voice = { ...voice, displayName: voice.displayName.trim() }
  return {
    usedSpeakerIds: [voice.speakerId, ...settings.usedSpeakerIds],
    voiceDesign: { speakers: [{
      speakerId: voice.speakerId, displayName: voice.displayName, voiceStyle: voice.voiceStyle,
    }, ...settings.voiceDesign.speakers.filter((row) => row.speakerId !== voice.speakerId)] },
    voiceOverrides: { ...settings.voiceOverrides, [voice.speakerId]: { mode, displayName: voice.displayName, voiceStyle: voice.voiceStyle } },
  }
}

export function removeVideoTaskVoice(settings: VideoVoiceSettings, speakerId: string): VideoVoiceSettings {
  return {
    usedSpeakerIds: settings.usedSpeakerIds.filter((id) => id !== speakerId),
    voiceDesign: { speakers: settings.voiceDesign.speakers.filter((row) => row.speakerId !== speakerId) },
    voiceOverrides: { ...settings.voiceOverrides, [speakerId]: null },
  }
}

export function updateVideoVoiceStyle(soundPrompt: string, name: string, style: string) {
  const rowPrefix = `- ${name}：`
  const line = `${rowPrefix}${style.replace(/\r?\n/g, " ")}`
  const lines = soundPrompt.split("\n")
  const index = lines.findIndex((row) => row.trim().startsWith(rowPrefix))
  if (index >= 0) lines[index] = line
  else lines.push(line)
  return lines.join("\n")
}

export function videoVoiceStyleFromSoundPrompt(soundPrompt: string, name: string, fallback: string) {
  const rowPrefix = `- ${name}：`
  const row = soundPrompt.split("\n").find((line) => line.trim().startsWith(rowPrefix))
  return row === undefined ? fallback : row.replace(/\r$/, "").trimStart().slice(rowPrefix.length)
}
