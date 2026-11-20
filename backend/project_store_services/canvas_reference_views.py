"""Reference previews are read projections, never persisted task-card state."""

from .canvas_ownership import VIDEO_TASK_NODE_TYPES
from typing import Any


REFERENCE_NODE_TYPES = {"director.board", "storyboard.card", *VIDEO_TASK_NODE_TYPES}
REFERENCE_VIEW_FIELDS = (
    "referenceDisplayRows", "assetThumbnails", "referenceThumbnails", "referenceVideoThumbnails", "referenceManifest", "referenceMediaIds", "assetReferenceMediaIds",
    "assetRefsResolvedByInputLinks", "inputContract", "needsRelink",
)
REFERENCE_CARD_VIEW_FIELDS = (
    "referenceMediaIds", "assetReferenceMediaIds", "assetRefs", "assetRefsResolvedByInputLinks",
    "referenceThumbnailCount", "assetThumbnailCount", "referenceManifest",
)


def remove_reference_views(node: dict[str, Any]) -> None:
    if node.get("type") not in REFERENCE_NODE_TYPES:
        return
    data = node.get("data")
    if not isinstance(data, dict):
        return
    for key in REFERENCE_VIEW_FIELDS:
        data.pop(key, None)
    card = data.get("videoTaskCard")
    if isinstance(card, dict):
        for key in REFERENCE_CARD_VIEW_FIELDS:
            card.pop(key, None)
