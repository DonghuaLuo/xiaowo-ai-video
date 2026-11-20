import { cn } from "@/lib/utils"
import {
  getProviderCapabilityGroups,
  providerCapabilityGroupLabels,
  providerCapabilityGroupStyles,
  type ProviderRow,
} from "@/features/settings/provider-model"

export function ProviderCapabilityGroupBadges({
  provider,
  className,
  agentMode = "verified",
}: {
  provider: ProviderRow
  className?: string
  agentMode?: "candidate" | "verified"
}) {
  const groups = getProviderCapabilityGroups(provider).filter(
    (group) =>
      group !== "agent" ||
      agentMode === "candidate" ||
      provider.probeSummary?.agentRouteReady === true
  )
  if (!groups.length) return null
  return (
    <span className={cn("flex flex-wrap gap-1.5", className)}>
      {groups.map((group) => {
        const label = providerCapabilityGroupLabels[group]
        return (
          <span
            key={group}
            className={cn(
              "shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
              providerCapabilityGroupStyles[group]
            )}
          >
            {label}
          </span>
        )
      })}
    </span>
  )
}
