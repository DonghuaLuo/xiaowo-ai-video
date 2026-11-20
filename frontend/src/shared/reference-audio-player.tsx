import { useEffect, useRef, useState, type CSSProperties } from "react"
import { Pause, Play } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

function formatTime(value: number) {
  if (!Number.isFinite(value) || value < 0) return "0:00"
  const totalSeconds = Math.floor(value)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = String(totalSeconds % 60).padStart(2, "0")
  return `${minutes}:${seconds}`
}

export function ReferenceAudioPlayer({
  src,
  className,
}: {
  src?: string | null
  className?: string
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)

  useEffect(() => {
    setPlaying(false)
    setCurrentTime(0)
    setDuration(0)
    audioRef.current?.load()
  }, [src])

  const togglePlayback = async () => {
    const audio = audioRef.current
    if (!audio || !src) return
    if (audio.paused) {
      await audio.play()
    } else {
      audio.pause()
    }
  }

  return (
    <div
      className={cn(
        "ai-video-reference-audio-player flex h-9 min-w-0 items-center gap-2",
        className
      )}
    >
      <audio
        ref={audioRef}
        preload="metadata"
        src={src ?? undefined}
        onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
        onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false)
          setCurrentTime(0)
        }}
        className="sr-only"
      />
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="size-[30px] shrink-0 rounded-full bg-indigo-500/10 p-0 text-indigo-700 hover:bg-indigo-500/20 disabled:bg-gray-200/50 disabled:text-gray-400 dark:text-indigo-200 dark:hover:bg-indigo-400/20 dark:disabled:bg-white/5 dark:disabled:text-gray-500"
        onClick={() => void togglePlayback()}
        disabled={!src}
        aria-label={playing ? "暂停" : "播放"}
      >
        {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
      </Button>
      <span className="shrink-0 text-xs font-medium tabular-nums text-gray-600 dark:text-gray-300">
        {formatTime(currentTime)} / {formatTime(duration)}
      </span>
      <input
        type="range"
        min={0}
        max={duration || 0}
        step={0.01}
        value={Math.min(currentTime, duration || 0)}
        onChange={(event) => {
          const nextTime = Number(event.currentTarget.value)
          if (audioRef.current) audioRef.current.currentTime = nextTime
          setCurrentTime(nextTime)
        }}
        disabled={!src || duration <= 0}
        aria-label="音频进度"
        style={
          {
            "--audio-progress": `${duration > 0 ? (currentTime / duration) * 100 : 0}%`,
          } as CSSProperties
        }
        className="ai-video-reference-audio-range min-w-0 flex-1"
      />
    </div>
  )
}
