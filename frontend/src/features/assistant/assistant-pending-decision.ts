import type { AssistantPendingInteraction } from "./assistant-session-normalization"

export function pendingDecisionSendOptions(
  interaction: AssistantPendingInteraction,
  decision: "confirm" | "cancel"
) {
  const candidateRef = interaction.candidateId && interaction.runId &&
    interaction.candidateDigest && interaction.candidateVersion
    ? {
        runId: interaction.runId,
        candidateId: interaction.candidateId,
        candidateDigest: interaction.candidateDigest,
        candidateVersion: interaction.candidateVersion,
        ...(interaction.kind === "asset_range" ? { candidateType: "asset_range_candidate" as const } : {}),
      }
    : undefined
  return {
    taskOptions: {
      pendingDecision: {
        sessionId: interaction.sessionId,
        pendingOperationId: interaction.pendingOperationId,
        operationType: interaction.operationType,
        createdAt: interaction.createdAt,
        candidateId: interaction.candidateId,
        runId: interaction.runId,
        candidateDigest: interaction.candidateDigest,
        candidateVersion: interaction.candidateVersion,
        decision,
      },
    },
    candidateRef,
  }
}
