import { useEffect, useRef, useState } from "react"

/** Backend acknowledgements may update the baseline, never a newer local draft. */
export function useStoryboardEditorDraft<T>(key: string, saved: T) {
  const [draft, setDraft] = useState(saved)
  const previous = useRef({ key, saved })
  const savedKey = JSON.stringify(saved)
  useEffect(() => {
    const prior = previous.current
    setDraft((current) => prior.key !== key || JSON.stringify(current) === JSON.stringify(prior.saved) ? saved : current)
    previous.current = { key, saved }
  }, [key, savedKey])
  return [draft, setDraft] as const
}
