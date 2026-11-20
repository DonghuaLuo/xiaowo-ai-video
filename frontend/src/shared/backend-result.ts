type BackendFailureLike = {
  success: false
  message?: string | null
  failureReason?: string | null
  providerResponseSummary?: string | null
  error?: string | null
  errorSummary?: string | null
}

function cleanBackendText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim()
}

export function backendFailureMessage(
  result: unknown,
  fallback = "操作失败"
): string {
  if (!result || typeof result !== "object") return fallback
  const payload = result as Partial<BackendFailureLike>
  return (
    cleanBackendText(payload.failureReason) ||
    cleanBackendText(payload.providerResponseSummary) ||
    cleanBackendText(payload.error) ||
    cleanBackendText(payload.errorSummary) ||
    cleanBackendText(payload.message) ||
    fallback
  )
}

export function errMsg(err: unknown, fallback = "操作失败"): string {
  if (err instanceof Error) return err.message || fallback
  if (typeof err === "string") return err || fallback
  return backendFailureMessage(err, fallback)
}

export function isBackendFailure(
  result: unknown
): result is BackendFailureLike {
  return (
    typeof result === "object" &&
    result !== null &&
    "success" in result &&
    (result as { success?: unknown }).success === false
  )
}
