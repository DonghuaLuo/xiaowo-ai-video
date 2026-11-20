export type ModelAvailability = {
  available?: boolean
  availability_note?: string
}

export function modelUnavailableReason(model?: ModelAvailability) {
  return model?.available === false
    ? model.availability_note?.trim() || "当前模型尚未适配"
    : ""
}
