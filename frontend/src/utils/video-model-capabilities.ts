/** Supplied by the backend's STORYBOARD_VIDEO_MODEL_CAPABILITIES table.
 * Official support is informational; adapter support controls available actions.
 * Missing metadata means unknown, never supported by default.
 */
export type VideoVisualInputRole =
  | "first_frame"
  | "last_frame"
  | "reference_image"
  | "reference_video"

export type VideoVisualInputMode = {
  id: "reference_to_video" | "first_frame_to_video" | "first_last_frame_to_video"
  endpoint: string
  required_roles: VideoVisualInputRole[]
  /** Zero means the role is not accepted in this mode. */
  max_counts: Record<VideoVisualInputRole, number>
  /** Counts reference images + reference videos, excluding native frames.
   * Storyboards and prompted frames each consume a reference_image slot.
   */
  min_reference_materials: number
  max_reference_materials: number
}

export type VideoVisualInputCapabilities = {
  durations?: number[]
  native_frame_controls_aspect_ratio: boolean
  supports_first_frame: boolean
  supports_last_frame: boolean
  supports_last_frame_only: boolean
  supports_multi_reference_images: boolean
  storyboard_support: "documented" | "image_reference_only"
  prompted_frame_support: "documented" | "unverified" | "not_implemented"
  supports_native_pseudo_frame: boolean
  /** Match one complete mode; do not combine capabilities across modes. */
  modes: VideoVisualInputMode[]
  verified_on: string
  source_urls: string[]
}

export type VideoCapabilityDetails = {
  task_types?: string[]
  supports_video_generation?: boolean
  supports_reference_video?: boolean
  max_reference_images?: number
  max_reference_videos?: number
  visual_inputs?: VideoVisualInputCapabilities
  keyframe_visual_inputs?: VideoVisualInputCapabilities
  [key: string]: unknown
}

export type VideoCapabilityMetadata = {
  official_capabilities?: VideoCapabilityDetails | null
  adapter_capabilities?: VideoCapabilityDetails | null
}
