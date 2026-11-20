import { useCallback, useEffect, useRef } from "react"

/** Reject work from an earlier activation, including A → B → A before cleanup. */
export function useProjectSettingsLifetime(key: string) {
  const current = useRef({ key, active: true })
  if (current.current.key !== key) {
    current.current.active = false
    current.current = { key, active: true }
  }
  const activation = current.current
  useEffect(() => {
    activation.active = true
    return () => {
      activation.active = false
    }
  }, [activation])
  return useCallback(
    () => current.current === activation && activation.active,
    [activation]
  )
}
