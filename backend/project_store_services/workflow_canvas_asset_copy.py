# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations

from .agent_sessions import _persistent_media_data_removed
from .canvas_store_mutations import write_canvas_records_v4
from .canvas_store_queries import read_canvas_card_record_v4
from .canvas_store_queries import read_card_results
from .canvas_store_queries import read_workflow_card_neighborhood_v4
from .projects import _touch_project_meta
from .store_core import _now
from .storyboard_templates import storyboard_image_prompt_spec
from .workflow_asset_resolution import _workflow_canvas_project_asset_versions
from .workflow_canvas_updates import _workflow_detach_project_asset_reference
from .workflow_contract import _CANVAS_NODE_ROLE_IMAGE_ASSET
from .workflow_contract import _VISUAL_HANDOFF_SLOT
from .workflow_contract import _assert_canvas_mutation_does_not_return_workflow
from .workflow_contract import _ensure_saved_workflow_node_contract
from .workflow_contract import _workflow_canvas_asset_node_identity_from_data
from .workflow_contract import _workflow_data_active_version_id
from .workflow_contract import _workflow_mutation_event_fields
from .workflow_contract import _workflow_new_node_id
from .workflow_contract import _workflow_node_is_visual_handoff_asset_like
from .workflow_contract import _workflow_node_payload_data
from .workflow_contract import _workflow_node_type_value
from .workflow_contract import _workflow_position_payload
from .workflow_input_resolution import _workflow_media_dict_has_reference
from .workflow_input_resolution import _workflow_node_data_current_media
from .workflow_input_resolution import workflow_current_media_reference
from .workflow_projection import _read_workflow_media
from .workflow_visual_handoff import _cleanup_promoted_media_copy
from .workflow_visual_handoff import _promote_cross_episode_media_reference
from typing import Any
from utils.frame_references import FRAME_IMAGE
from utils.frame_references import FRAME_SLOT
from utils.frame_references import is_frame_image
import copy
import json
import uuid


_WORKFLOW_COPYABLE_ASSET_NODE_TYPES = {
    "asset.image",
    "media.external",
    "storyboard.image",
    "video.result",
}


_WORKFLOW_COPY_BLOCKED_VERSION_STATUSES = {
    "failed",
    "blocked",
    "cancelled",
    "canceled",
    "processing",
    "queued",
    "running",
    "waiting",
    "waiting_upstream",
}


def _workflow_copy_asset_title(node: dict[str, Any] | None) -> str:
    data = _workflow_node_payload_data(node)
    for key in ("assetName", "asset_name", "title", "name"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return str((node or {}).get("id") or "资产节点").strip() or "资产节点"


def _workflow_copyable_version_with_media(
    versions: list[dict[str, Any]],
    preferred_version_id: str = "",
) -> dict[str, Any] | None:
    usable: list[dict[str, Any]] = []
    for version in versions:
        if not isinstance(version, dict):
            continue
        status = str(version.get("status") or "").strip().lower()
        if status in _WORKFLOW_COPY_BLOCKED_VERSION_STATUSES:
            continue
        media = version.get("media") if isinstance(version.get("media"), dict) else {}
        if _workflow_media_dict_has_reference(media):
            usable.append(version)
    if not usable:
        return None
    if preferred_version_id:
        preferred = next(
            (
                item
                for item in usable
                if str(item.get("id") or "").strip() == preferred_version_id
            ),
            None,
        )
        if preferred:
            return preferred
    active = next((item for item in usable if bool(item.get("active"))), None)
    return active or usable[-1]


def _workflow_copy_asset_media_reference(
    project_id: str,
    episode_id: str,
    source_node: dict[str, Any],
) -> dict[str, Any] | None:
    source_data = _workflow_node_payload_data(source_node)
    current_media = _workflow_node_data_current_media(source_data)
    if current_media and not _workflow_data_active_version_id(source_data):
        return current_media

    source_node_id = str(source_node.get("id") or source_data.get("nodeId") or "").strip()
    if not source_node_id:
        return None
    try:
        workflow = read_workflow_card_neighborhood_v4(
            project_id,
            episode_id,
            source_node_id,
            detail="full",
        )
        media = workflow_current_media_reference(
            project_id,
            episode_id,
            workflow,
            source_node_id,
        )
        if media:
            return media
    except Exception:
        pass

    preferred_version_id = _workflow_data_active_version_id(source_data)
    version = _workflow_copyable_version_with_media(
        read_card_results(project_id, episode_id, source_node_id),
        preferred_version_id,
    )
    if version:
        media = copy.deepcopy(version.get("media") or {})
        media.setdefault("versionId", str(version.get("id") or ""))
        spec = storyboard_image_prompt_spec(current_media, version)
        if spec:
            media["storyboardPromptSpec"] = spec
        return media

    version = _workflow_copyable_version_with_media(
        _workflow_canvas_project_asset_versions(
            project_id,
            episode_id,
            source_node_id,
            source_node,
        ),
        preferred_version_id,
    )
    if version:
        media = copy.deepcopy(version.get("media") or {})
        media.setdefault("versionId", str(version.get("id") or ""))
        spec = storyboard_image_prompt_spec(current_media, version)
        if spec:
            media["storyboardPromptSpec"] = spec
        return media

    if current_media:
        return current_media

    workflow_media = _read_workflow_media(project_id, episode_id)
    media_id = str(source_data.get("mediaId") or source_data.get("media_id") or "").strip()
    for item in workflow_media.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_data = item.get("data") if isinstance(item.get("data"), dict) else {}
        item_media = item.get("media") if isinstance(item.get("media"), dict) else item.get("storage")
        if not _workflow_media_dict_has_reference(item_media):
            continue
        item_node_id = str(item.get("nodeId") or item.get("node_id") or item_data.get("nodeId") or "").strip()
        item_media_id = str(
            item.get("id")
            or item.get("mediaId")
            or item.get("media_id")
            or (item_media or {}).get("id")
            or (item_media or {}).get("mediaId")
            or ""
        ).strip()
        if item_node_id == source_node_id or (media_id and item_media_id == media_id):
            return copy.deepcopy(item_media)
    return None




class _CanvasAssetPaste:
    """一次操作独立持有业务状态，按验证、准备和提交阶段执行。"""

    def __init__(self, project_id, episode_id, payload):
        self.project_id = project_id
        self.episode_id = episode_id
        self.payload = payload

    def run(self) -> dict[str, Any] | None:
        self._load_source()
        self._prepare_independent_card()
        self._copy_media_and_provenance()
        self._commit_card()
        return self._build_response()

    def _load_source(self):
        if not self.episode_id:
            raise ValueError("缺少 episodeId")
        self.payload = self.payload if isinstance(self.payload, dict) else {}
        _assert_canvas_mutation_does_not_return_workflow(self.payload, "粘贴画布资产节点")
        self.source_project_id = str(
            self.payload.get("sourceProjectId")
            or self.payload.get("source_project_id")
            or self.project_id
            or ""
        ).strip()
        self.source_episode_id = str(
            self.payload.get("sourceEpisodeId") or self.payload.get("source_episode_id") or ""
        ).strip()
        self.source_node_id = str(
            self.payload.get("sourceNodeId") or self.payload.get("source_node_id") or ""
        ).strip()
        requested_source_type = str(
            self.payload.get("sourceNodeType") or self.payload.get("source_node_type") or ""
        ).strip()
        if self.source_project_id != self.project_id:
            raise ValueError("暂不支持跨项目粘贴资产节点")
        if not self.source_episode_id or not self.source_node_id:
            raise ValueError("缺少复制来源")

        self.source_node = read_canvas_card_record_v4(
            self.source_project_id,
            self.source_episode_id,
            self.source_node_id,
            detail="full",
        )
        self.source_node_type = _workflow_node_type_value(self.source_node)
        if self.source_node_type not in _WORKFLOW_COPYABLE_ASSET_NODE_TYPES:
            raise ValueError("当前节点不是可复制资产节点")
        if requested_source_type and requested_source_type != self.source_node_type:
            raise ValueError("复制来源节点类型已变化，请重新复制")

        self.source_data = _workflow_node_payload_data(self.source_node)
        self.source_is_visual_handoff = _workflow_node_is_visual_handoff_asset_like(self.source_node)
        self.root_asset_type, self.root_asset_id = _workflow_canvas_asset_node_identity_from_data(self.source_data)
        self.media = _workflow_copy_asset_media_reference(
            self.source_project_id,
            self.source_episode_id,
            self.source_node,
        )
        has_project_asset_ref = bool(self.root_asset_type and self.root_asset_id)
        if not self.media and (self.source_is_visual_handoff or not has_project_asset_ref):
            raise ValueError("当前节点没有可复制的图片或视频媒体")

    def _prepare_independent_card(self):
        self.node_id = _workflow_new_node_id(self.source_node_type.replace(".", "_"))
        self.now = _now()
        title = _workflow_copy_asset_title(self.source_node)
        self.node = copy.deepcopy(self.source_node)
        self.data = copy.deepcopy(self.source_data)

        self.node["id"] = self.node_id
        self.node["type"] = self.source_node_type
        self.node["position"] = _workflow_position_payload(
            self.payload.get("position"),
            {"x": 120, "y": 120},
        )
        self.node["deletable"] = True
        self.node["locked"] = False
        for key in ("workChainId", "routeId", "segmentId", "strategy"):
            self.node[key] = ""
        self.node.pop("lockedReason", None)

        for key in (
            "workChainId",
            "routeId",
            "segmentId",
            "strategy",
            "routeLabel",
            "routeStatus",
            "lockedReason",
            "lockedByUser",
            "preserveOnReplan",
            "sourceNodeId",
            "resultOfNodeId",
            "taskId",
            "jobId",
            "providerTaskId",
            "focusToken",
            "storyboardPlanHash",
            "storyboard_plan_hash",
            "storyboardPlanState",
            "storyboard_plan_state",
            "generationConfig",
            "modelSelection",
            "capabilityRequirements",
            "capabilityCheck",
            "referenceThumbnails",
            "assetThumbnails",
            "assetReferenceMediaIds",
            "referenceMediaIds",
            "inputContract",
            "needsRelink",
            "missingAssetRefs",
            "missingAssetRefsConfirmed",
            "assetRefs",
            "activeVersionId",
            "activeMediaVersionId",
            "mediaVersionId",
            "winnerVersionId",
            "sourceVersionId",
            "assetVersionId",
            "selectionReason",
            "selectedAt",
            "variantSelection",
        ):
            self.data.pop(key, None)

        self.data.update(
            {
                "projectId": self.project_id,
                "episodeId": self.episode_id,
                "nodeId": self.node_id,
                "eyebrow": self.source_node_type,
                "title": title,
                "status": "ready",
                "workChainId": "",
                "routeId": "",
                "segmentId": "",
                "strategy": "",
                "locked": False,
                "lockedByUser": False,
                "preserveOnReplan": False,
                "visibilityScope": "global",
                "inputLinks": [],
                "sourceType": "asset_copy",
                "copiedFromNodeId": self.source_node_id,
                "copiedFromProjectId": self.source_project_id,
                "copiedFromEpisodeId": self.source_episode_id,
            }
        )
        _workflow_detach_project_asset_reference(self.data)
        if is_frame_image(self.source_data):
            self.data.update({"assetType": FRAME_IMAGE, "assetKind": FRAME_IMAGE, "mediaPurpose": FRAME_IMAGE, "preferredTargetSlot": FRAME_SLOT})
        if self.root_asset_type and self.root_asset_id:
            self.data["rootAssetType"] = self.root_asset_type
            self.data["rootAssetId"] = self.root_asset_id
            self.data["rootAssetProjectId"] = self.source_project_id
        self.data["assetName"] = str(
            self.source_data.get("assetName")
            or self.source_data.get("asset_name")
            or self.source_data.get("title")
            or title
        ).strip() or title
        if self.source_node_type in {"asset.image", "media.external", "storyboard.image"}:
            self.data["assetScope"] = "reusable"
            if self.source_is_visual_handoff:
                self.data["mediaPurpose"] = "visual_handoff"
                self.data["preferredTargetSlot"] = _VISUAL_HANDOFF_SLOT
                self.data["assetKind"] = "visual_handoff"
                self.data["assetType"] = "visual_handoff"
                for key in (
                    "assetId",
                    "asset_id",
                    "media_purpose",
                    "preferred_target_slot",
                    "asset_kind",
                    "asset_type",
                ):
                    self.data.pop(key, None)
        if (
            self.source_node_type in {"asset.image", "media.external", "storyboard.image"}
            and not _workflow_node_is_visual_handoff_asset_like(
                {"type": self.source_node_type, "data": self.data}
            )
        ):
            self.data["canvasNodeRole"] = _CANVAS_NODE_ROLE_IMAGE_ASSET
            self.data.pop("canvas_node_role", None)

    def _copy_media_and_provenance(self):
        self.promotion_path = ""
        if self.media and self.source_episode_id != self.episode_id:
            self.media = _promote_cross_episode_media_reference(
                self.project_id,
                self.media,
                source_episode_id=self.source_episode_id,
                target_episode_id=self.episode_id,
                visual_handoff=self.source_is_visual_handoff,
            )
            self.promotion_path = str(self.media.pop("_promotionPath", "") or "")
        self.created_frame_origin_path = ""
        if self.media:
            clean_media = _persistent_media_data_removed(self.media)
            if isinstance(clean_media, dict):
                if self.source_node_type == "storyboard.image" or clean_media.get("storyboardPromptSpec"):
                    # 复制品不能通过共用媒体/版本 ID 回溯到原卡片。
                    clean_media["id"] = f"storyboard-copy-{uuid.uuid4().hex[:12]}"
                    clean_media.pop("mediaId", None)
                    clean_media.pop("versionId", None)
                if is_frame_image(self.source_data):
                    frame_media_id = f"frame-asset-{uuid.uuid4().hex[:12]}"
                    frame_origin = clean_media.get("frameOrigin") if isinstance(clean_media.get("frameOrigin"), dict) else {}
                    if self.source_episode_id != self.episode_id:
                        frame_origin = {
                            **copy.deepcopy(frame_origin),
                            "projectId": self.project_id,
                            "episodeId": self.episode_id,
                            "resultId": frame_media_id,
                            "copiedFrom": copy.deepcopy(frame_origin),
                        }
                        from .video_clips import _frame_origin_path

                        origin_path = _frame_origin_path(frame_origin)
                        try:
                            origin_path.parent.mkdir(parents=True, exist_ok=True)
                            origin_path.write_text(
                                json.dumps(frame_origin, ensure_ascii=False),
                                encoding="utf-8",
                            )
                        except Exception:
                            _cleanup_promoted_media_copy(self.project_id, self.promotion_path)
                            raise
                        self.created_frame_origin_path = str(origin_path)
                    clean_media = {
                        **clean_media,
                        "id": frame_media_id,
                        "frameOrigin": frame_origin,
                    }
                    clean_media.pop("mediaId", None)
                self.data["media"] = copy.deepcopy(clean_media)
                self.data["storage"] = copy.deepcopy(clean_media)
                media_id = str(clean_media.get("id") or clean_media.get("mediaId") or "").strip()
                if media_id:
                    self.data["mediaId"] = media_id
                media_kind = str(
                    clean_media.get("kind")
                    or clean_media.get("mediaType")
                    or clean_media.get("media_type")
                    or self.data.get("mediaKind")
                    or self.data.get("mediaType")
                    or ""
                ).strip().lower()
                if media_kind in {"image", "video"}:
                    self.data["mediaKind"] = media_kind
                    self.data["mediaType"] = media_kind
                self.data["mediaBindingMode"] = "pinned"
                self.data["mediaPinnedAt"] = self.now

        provenance = self.data.get("provenance") if isinstance(self.data.get("provenance"), dict) else {}
        self.data["provenance"] = {
            **copy.deepcopy(provenance),
            "source": "user",
            "action": "canvas_asset_node_pasted",
            "pastedAt": self.now,
            "copiedFromNodeId": self.source_node_id,
            "copiedFromProjectId": self.source_project_id,
            "copiedFromEpisodeId": self.source_episode_id,
        }

    def _commit_card(self):
        self.node["data"] = self.data
        try:
            _ensure_saved_workflow_node_contract(self.node)
        except Exception:
            _cleanup_promoted_media_copy(self.project_id, self.promotion_path)
            _cleanup_promoted_media_copy(self.project_id, self.created_frame_origin_path)
            raise

        try:
            self.save_result = write_canvas_records_v4(
                self.project_id,
                self.episode_id,
                nodes=[self.node],
                op_type="structure_patch",
                changed_resources=["canvas_node"],
                expected_revision=self.payload.get("expectedRevision"),
            )
        except Exception:
            _cleanup_promoted_media_copy(self.project_id, self.promotion_path)
            _cleanup_promoted_media_copy(self.project_id, self.created_frame_origin_path)
            raise

    def _build_response(self):
        _touch_project_meta(self.project_id)
        return {
            "success": True,
            "episodeId": self.episode_id,
            "nodes": [copy.deepcopy(self.node)],
            "workflowVersion": self.save_result.get("workflowVersion"),
            **_workflow_mutation_event_fields(self.save_result),
            "focusTarget": {
                "section": "episode",
                "episodeId": self.episode_id,
                "nodeId": self.node_id,
            },
            "projectChanged": True,
        }


def paste_workflow_asset_node(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _CanvasAssetPaste(project_id, episode_id, payload).run()
