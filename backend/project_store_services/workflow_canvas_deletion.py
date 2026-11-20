# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations

from .canvas_ownership import work_chain_origin
from .canvas_store_database import retry_canvas_mutation_v4
from .canvas_store_database import validate_canvas_revision_v4
from .canvas_store_mutations import delete_canvas_records_v4
from .canvas_store_queries import get_canvas_scope_records_v4
from .canvas_store_queries import read_workflow_card_neighborhood_v4
from .reference_utils import asset_refs_has_value as _asset_refs_has_value
from .planning_contract import _is_user_locked_item
from .production_status import update_episode_production_status
from .projects import _touch_project_meta
from .project_resource_revisions import _append_resource_revision
from .project_resource_revisions import _resource_revision_value
from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json
from .workflow_contract import _assert_canvas_mutation_does_not_return_workflow
from .workflow_contract import _ensure_saved_workflow_node_contract
from .workflow_contract import _node_route_id
from .workflow_contract import _node_segment_id
from .workflow_contract import _node_work_chain_id
from .workflow_contract import _workflow_is_result_node_type
from .workflow_contract import _workflow_is_standalone_task_node
from .workflow_contract import _workflow_locked_system_edge_key
from .workflow_contract import _workflow_mutation_event_fields
from .workflow_contract import _workflow_node
from .workflow_contract import _workflow_node_result_of_id
from .workflow_contract import _workflow_node_type_value
from .workflow_contract import _workflow_node_is_copied_asset
from .workflow_contract import _workflow_protected_edge_delete_reason
from .workflow_contract import _workflow_protected_node_delete_reason
from .workflow_input_resolution import _workflow_asset_ref_removal_targets
from .workflow_input_resolution import _workflow_canvas_asset_node_project_asset_identity
from .workflow_input_resolution import _workflow_input_affected_ids
from .workflow_input_resolution import _workflow_input_link_direct_ids
from .workflow_input_resolution import _workflow_material_input_response_nodes
from .workflow_input_resolution import _workflow_remove_asset_refs_from_value
from .workflow_input_resolution import _workflow_remove_edges_from_memory
from .workflow_input_resolution import _workflow_remove_unlinked_asset_refs_from_node_data
from .workflow_input_resolution import _workflow_remove_unlinked_asset_refs_from_workflow
from .workflow_input_resolution import _workflow_shot_plan_row_matches_segment
from .workflow_input_resolution import _workflow_video_task_node_ids
from .workflow_projection import _work_chain_plan_path
from .workflow_projection import get_canvas_workflow_projection
from typing import Any
import copy
import traceback
from contextlib import nullcontext


def _is_independent_source_node(node: dict[str, Any] | None) -> bool:
    return bool(node and node.get("type") == "source.text" and (node.get("data") or {}).get("sourceMode") == "independent")


def _workflow_cleanup_asset_refs_for_deleted_asset_nodes(
    project_id: str,
    episode_id: str,
    workflow: dict[str, Any],
    node_by_id: dict[str, dict[str, Any]],
    deleted_node_ids: set[str],
) -> tuple[bool, bool]:
    def fallback_segment_ids(node: dict[str, Any] | None) -> list[str]:
        if not isinstance(node, dict):
            return []
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        segment_ids: list[str] = []
        for value in (
            node.get("segmentId"),
            node.get("segment_id"),
            data.get("segmentId"),
            data.get("segment_id"),
        ):
            text = str(value or "").strip()
            if text:
                segment_ids.append(text)
        route_id = str(node.get("routeId") or node.get("route_id") or data.get("routeId") or data.get("route_id") or "").strip()
        work_chain_id = str(
            node.get("workChainId")
            or node.get("work_chain_id")
            or data.get("workChainId")
            or data.get("work_chain_id")
            or ""
        ).strip()
        routes = workflow.get("routes") if isinstance(workflow.get("routes"), list) else []
        for route in routes:
            if not isinstance(route, dict):
                continue
            current_route_id = str(route.get("id") or "").strip()
            current_chain_id = str(route.get("workChainId") or route.get("work_chain_id") or "").strip()
            if (route_id and current_route_id == route_id) or (work_chain_id and current_chain_id == work_chain_id):
                text = str(route.get("segmentId") or route.get("segment_id") or "").strip()
                if text:
                    segment_ids.append(text)
        chains = workflow.get("workChains") if isinstance(workflow.get("workChains"), list) else []
        for chain in chains:
            if not isinstance(chain, dict) or str(chain.get("id") or "").strip() != work_chain_id:
                continue
            chain_segment_ids = chain.get("segmentIds")
            if not isinstance(chain_segment_ids, list):
                chain_segment_ids = chain.get("segment_ids")
            if not isinstance(chain_segment_ids, list):
                chain_segment_ids = []
            for value in chain_segment_ids:
                text = str(value or "").strip()
                if text:
                    segment_ids.append(text)
        return list(dict.fromkeys(segment_ids))

    def link_matches_removed_material(
        link: dict[str, Any],
        *,
        input_link_id: str,
        source_node_id: str,
    ) -> bool:
        if not isinstance(link, dict):
            return False
        if input_link_id and input_link_id in _workflow_input_link_direct_ids(link):
            return True
        return str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip() == source_node_id

    edges = workflow.get("edges") if isinstance(workflow.get("edges"), list) else []
    shot_plan_changed = False
    asset_refs_changed = False
    for node_id in {str(item or "").strip() for item in deleted_node_ids if str(item or "").strip()}:
        removed_node = node_by_id.get(node_id)
        removed_asset_node = str((removed_node or {}).get("type") or "").strip() == "asset.image"
        if not removed_asset_node:
            continue
        removed_asset_type, removed_asset_id = _workflow_canvas_asset_node_project_asset_identity(removed_node)
        fallback_link = (
            {
                "sourceType": "asset",
                "assetType": removed_asset_type,
                "assetId": removed_asset_id,
                "rootAssetType": removed_asset_type,
                "rootAssetId": removed_asset_id,
                "sourceId": node_id,
                "sourceNodeId": node_id,
                "sourceNodeType": "asset.image",
            }
            if removed_asset_type and removed_asset_id
            else None
        )
        removed_any_refs = False
        for edge in edges:
            if not isinstance(edge, dict) or str(edge.get("source") or "").strip() != node_id:
                continue
            edge_data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
            if str(edge_data.get("kind") or "") != "material":
                continue
            target_node = node_by_id.get(str(edge.get("target") or "").strip())
            if not target_node:
                continue
            target_data = target_node.setdefault("data", {})
            if not isinstance(target_data, dict):
                target_data = {}
                target_node["data"] = target_data
            input_link_id = str(edge_data.get("inputLinkId") or "").strip()
            links = target_data.get("inputLinks") if isinstance(target_data.get("inputLinks"), list) else []
            removed_links = [
                copy.deepcopy(link)
                for link in links
                if link_matches_removed_material(
                    link,
                    input_link_id=input_link_id,
                    source_node_id=node_id,
                )
            ]
            if input_link_id or removed_links:
                target_data["inputLinks"] = [
                    link
                    for link in links
                    if not link_matches_removed_material(
                        link,
                        input_link_id=input_link_id,
                        source_node_id=node_id,
                    )
                ]
            if not removed_links and fallback_link:
                removed_links = [fallback_link]
            if not removed_links:
                continue
            if _workflow_remove_unlinked_asset_refs_from_node_data(project_id, target_data, removed_links):
                asset_refs_changed = True
            segment_id = str(edge_data.get("segmentId") or edge_data.get("segment_id") or _node_segment_id(target_node) or "").strip()
            if _workflow_remove_unlinked_asset_refs_from_workflow(
                project_id,
                workflow,
                segment_id=segment_id,
                removed_links=removed_links,
            ):
                asset_refs_changed = True
            if _workflow_remove_unlinked_asset_refs_from_shot_plan(
                project_id,
                episode_id,
                segment_id=segment_id,
                removed_links=removed_links,
            ):
                shot_plan_changed = True
            removed_any_refs = True
        if not removed_any_refs and fallback_link:
            for segment_id in fallback_segment_ids(removed_node):
                if _workflow_remove_unlinked_asset_refs_from_workflow(
                    project_id,
                    workflow,
                    segment_id=segment_id,
                    removed_links=[fallback_link],
                ):
                    asset_refs_changed = True
                if _workflow_remove_unlinked_asset_refs_from_shot_plan(
                    project_id,
                    episode_id,
                    segment_id=segment_id,
                    removed_links=[fallback_link],
                ):
                    shot_plan_changed = True
    return asset_refs_changed, shot_plan_changed


def delete_workflow_node(project_id: str, episode_id: str, node_id: str) -> dict[str, Any]:
    return delete_workflow_item(
        project_id,
        episode_id,
        {
            "itemType": "node",
            "itemId": node_id,
            "nodeId": node_id,
            "source": "user",
            "versionSource": "user",
            "version_source": "user",
        },
    )




class _CanvasNodeDeletion:
    """一次操作独立持有业务状态，按验证、准备和提交阶段执行。"""

    def __init__(self, project_id, episode_id, item_id, payload, *, node_ids=None):
        self.project_id = project_id
        self.episode_id = episode_id
        self.item_id = item_id
        self.payload = payload
        self.batch_node_ids = node_ids

    def run(self) -> dict[str, Any] | None:
        result = self._load_and_check_node()
        if result is not None:
            return result
        selected_ids = set(self.batch_node_ids or [self.item_id])
        self.independent_source_ids = {
            node["id"] for node in self.workflow.get("nodes", [])
            if node.get("id") in selected_ids and _is_independent_source_node(node)
        }
        from .task_storage import _TASK_STORAGE_LOCK
        with _TASK_STORAGE_LOCK if self.independent_source_ids else nullcontext():
            return self._delete_loaded_nodes()

    def _delete_loaded_nodes(self):
        result = self._collect_removed_links()
        if result is not None:
            return result
        result = self._prepare_remaining_inputs()
        if result is not None:
            return result
        self._commit_and_cleanup()
        return self._build_response()

    def _load_and_check_node(self):
        if self.batch_node_ids is not None:
            self.workflow = get_canvas_workflow_projection(self.project_id, self.episode_id, {"detail": "full"})
            validate_canvas_revision_v4(self.workflow["version"], self.payload.get("expectedRevision"))
            self.source = "user"
            for node_id in self.batch_node_ids:
                node = _workflow_node(self.workflow, node_id)
                if node is None:
                    raise ValueError("选中的卡片已变化，请重新选择")
                reason = _workflow_protected_node_delete_reason(node)
                if reason:
                    raise ValueError(reason)
                node_type = _workflow_node_type_value(node)
                if not (_workflow_is_standalone_task_node(node)
                        or _is_independent_source_node(node)
                        or node_type in {"asset.image", "media.external"}
                        or (_workflow_is_result_node_type(node_type) and _workflow_node_is_copied_asset(node))):
                    raise ValueError("选中卡片中包含不支持删除的类型")
                if _is_user_locked_item(node):
                    raise ValueError("选中卡片中有用户锁定内容，请先解锁")
            self.matched_item = _workflow_node(self.workflow, self.item_id)
            return None
        try:
            self.workflow = read_workflow_card_neighborhood_v4(self.project_id, self.episode_id, self.item_id, detail="full")
            self.matched_item = _workflow_node(self.workflow, self.item_id)
            if self.matched_item is None:
                raise FileNotFoundError("节点不存在")
            if _is_independent_source_node(self.matched_item):
                # The entire source-owned scope must be checked and removed atomically.
                self.workflow = get_canvas_workflow_projection(self.project_id, self.episode_id, {"detail": "full"})
                self.matched_item = _workflow_node(self.workflow, self.item_id)
                if self.matched_item is None:
                    raise FileNotFoundError("节点不存在")
        except FileNotFoundError:
            return {
                "success": True,
                "message": f"未找到 node {self.item_id}，无需删除。",
                "episodeId": self.episode_id,
                "itemType": "node",
                "itemId": self.item_id,
                "changedResources": [],
                "focusTarget": {"section": "episode", "episodeId": self.episode_id, "itemId": self.item_id},
                "projectChanged": False,
            }

        validate_canvas_revision_v4(self.workflow["version"], self.payload.get("expectedRevision", self.payload.get("expected_revision")))
        self.source = str(self.payload.get("source") or self.payload.get("versionSource") or self.payload.get("version_source") or "").strip().lower()
        protected_reason = _workflow_protected_node_delete_reason(self.matched_item)
        if protected_reason:
            raise ValueError(protected_reason)
        if _is_user_locked_item(self.matched_item):
            return {
                "success": True,
                "message": f"node {self.item_id} 已由用户锁定，未删除。",
                "episodeId": self.episode_id,
                "itemType": "node",
                "itemId": self.item_id,
                "skippedLocked": True,
                "changedResources": [],
                "focusTarget": {"section": "episode", "episodeId": self.episode_id, "itemId": self.item_id},
                "projectChanged": False,
            }

    def _collect_removed_links(self):
        self.node_by_id = {
            str(node.get("id") or "").strip(): node
            for node in self.workflow.get("nodes", [])
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        self.delete_node_ids: set[str] = set(self.batch_node_ids or [self.item_id])
        source_chains = [
            chain for chain in self.workflow.get("workChains", [])
            if (chain.get("origin") or {}).get("kind") == "independent_source"
            and (chain.get("origin") or {}).get("sourceNodeId") in self.independent_source_ids
        ]
        self.deleted_work_chain_ids = {chain["id"] for chain in source_chains}
        self.deleted_route_ids = {
            route["id"] for route in self.workflow.get("routes", [])
            if route.get("workChainId") in self.deleted_work_chain_ids
        }
        self.delete_node_ids.update(
            node["id"] for node in self.workflow.get("nodes", [])
            if _node_work_chain_id(node) in self.deleted_work_chain_ids
        )
        if any(_is_user_locked_item(chain) for chain in source_chains):
            raise ValueError("关联工作链已锁定，请先解锁")
        for selected_id in list(self.delete_node_ids):
            if not _workflow_is_standalone_task_node(self.node_by_id.get(selected_id)):
                continue
            self.delete_node_ids.update(
                node_id
                for node_id, node in self.node_by_id.items()
                if _workflow_is_result_node_type(_workflow_node_type_value(node))
                and _workflow_node_result_of_id(node) == selected_id
                and (self.batch_node_ids is None or not _workflow_node_is_copied_asset(node))
            )
        if self.batch_node_ids is not None or self.independent_source_ids:
            if any(_is_user_locked_item(self.node_by_id.get(node_id)) for node_id in self.delete_node_ids):
                raise ValueError("关联结果中有用户锁定内容，请先解锁")
            from .task_lifecycle import _background_storyboard_task_has_running_thread
            from .task_storage import _load_tasks_for_project
            for task in _load_tasks_for_project(self.project_id):
                task_nodes = {str(task.get(key) or "") for key in ("nodeId", "taskNodeId", "generationTaskNodeId", "resultNodeId", "versionNodeId")}
                if str(task.get("episodeId") or "") != self.episode_id or not task_nodes.intersection(self.delete_node_ids):
                    continue
                if task.get("status") in {"created", "queued", "pending", "running", "cancelling"} or _background_storyboard_task_has_running_thread(task):
                    raise ValueError("选中卡片或关联结果仍有任务执行，请等待任务结束")

        self.deleted_edge_ids: list[str] = []
        self.removed_input_link_ids: set[str] = set()
        affected_input_seed_node_ids: set[str] = set()
        self.removed_links_by_target: dict[str, list[dict[str, Any]]] = {}
        self.deleted_asset_links: list[dict[str, Any]] = []

        def deleted_asset_link_for_node(node: dict[str, Any] | None) -> dict[str, Any] | None:
            if not isinstance(node, dict):
                return None
            if str(node.get("type") or "").strip() != "asset.image":
                return None
            asset_type, asset_id = _workflow_canvas_asset_node_project_asset_identity(node)
            if not asset_type or not asset_id:
                return None
            link = {
                "sourceType": "asset",
                "assetType": asset_type,
                "assetId": asset_id,
                "rootAssetType": asset_type,
                "rootAssetId": asset_id,
                "sourceId": node.get("id"),
                "sourceNodeId": node.get("id"),
                "sourceNodeType": "asset.image",
                "routeId": _node_route_id(node),
                "workChainId": _node_work_chain_id(node),
                "segmentId": _node_segment_id(node),
            }
            return link if _asset_refs_has_value(link) else None

        def link_matches_removed_material_edge(
            link: dict[str, Any],
            *,
            input_link_id: str,
            source_node_id: str,
        ) -> bool:
            if not isinstance(link, dict):
                return False
            if input_link_id and input_link_id in _workflow_input_link_direct_ids(link):
                return True
            return str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip() == source_node_id

        for delete_node_id in self.delete_node_ids:
            deleted_asset_link = deleted_asset_link_for_node(self.node_by_id.get(delete_node_id))
            if deleted_asset_link:
                self.deleted_asset_links.append(deleted_asset_link)
        edges = self.workflow.get("edges") if isinstance(self.workflow.get("edges"), list) else []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source_id = str(edge.get("source") or "").strip()
            target_id = str(edge.get("target") or "").strip()
            if source_id not in self.delete_node_ids and target_id not in self.delete_node_ids:
                continue
            if self.independent_source_ids:
                from .workflow_source_split import _source_split_is_explicit_user_lock
                if _source_split_is_explicit_user_lock(edge):
                    raise ValueError("关联链接已由用户锁定，请先解锁")
            if self.source not in {"agent", "system", "planner"}:
                locked_edge_key = _workflow_locked_system_edge_key(edge, self.node_by_id, self.workflow)
                if locked_edge_key:
                    locked_source_id, locked_target_id, edge_role = locked_edge_key
                    if locked_source_id in self.delete_node_ids and locked_target_id in self.delete_node_ids:
                        pass
                    elif edge_role in {"source_storyboard", "visual_handoff"} and locked_target_id in self.delete_node_ids:
                        pass
                    else:
                        edge_reason = _workflow_protected_edge_delete_reason(edge, self.node_by_id, self.workflow)
                        if edge_reason:
                            raise ValueError(edge_reason)
                else:
                    edge_reason = _workflow_protected_edge_delete_reason(edge, self.node_by_id, self.workflow)
                    if edge_reason:
                        raise ValueError(edge_reason)
            edge_id = str(edge.get("id") or "").strip()
            if edge_id:
                self.deleted_edge_ids.append(edge_id)
            self.data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
            if self.data.get("kind") == "material":
                input_link_id = str(self.data.get("inputLinkId") or "").strip()
                if input_link_id:
                    self.removed_input_link_ids.add(input_link_id)
                if target_id and target_id not in self.delete_node_ids:
                    affected_input_seed_node_ids.add(target_id)
                    target_node = self.node_by_id.get(target_id)
                    target_data = target_node.get("data") if isinstance((target_node or {}).get("data"), dict) else {}
                    target_links = target_data.get("inputLinks") if isinstance(target_data.get("inputLinks"), list) else []
                    self.removed_links = [
                        copy.deepcopy(link)
                        for link in target_links
                        if link_matches_removed_material_edge(
                            link,
                            input_link_id=input_link_id,
                            source_node_id=source_id,
                        )
                    ]
                    if not self.removed_links:
                        fallback_link = deleted_asset_link_for_node(self.node_by_id.get(source_id))
                        if fallback_link:
                            self.removed_links = [fallback_link]
                    if self.removed_links:
                        self.removed_links_by_target.setdefault(target_id, []).extend(self.removed_links)

        self.affected_input_node_ids: set[str] = set()
        for target_id in affected_input_seed_node_ids:
            target_node = self.node_by_id.get(target_id)
            if not isinstance(target_node, dict):
                continue
            self.affected_input_node_ids.update(
                _workflow_input_affected_ids(
                    self.workflow,
                    scope="node",
                    target_node=target_node,
                    route_id=_node_route_id(target_node),
                    work_chain_id=_node_work_chain_id(target_node),
                    payload={"nodeId": target_id},
                )
            )
        self.affected_input_node_ids.difference_update(self.delete_node_ids)

    def _prepare_remaining_inputs(self):
        def link_in_deleted_scope(link: dict[str, Any]) -> bool:
            if not isinstance(link, dict):
                return False
            if _workflow_input_link_direct_ids(link).intersection(self.removed_input_link_ids):
                return True
            source_node_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip()
            target_node_id = str(link.get("targetNodeId") or link.get("target_node_id") or "").strip()
            return bool(self.delete_node_ids and (source_node_id in self.delete_node_ids or target_node_id in self.delete_node_ids))

        self.patched_nodes: list[dict[str, Any]] = []
        self.asset_refs_changed = False
        self.shot_plan_cleanups: list[tuple[str, list[dict[str, Any]]]] = []
        if self.removed_input_link_ids or self.delete_node_ids:
            for node_id, self.node in self.node_by_id.items():
                if node_id in self.delete_node_ids:
                    continue
                self.data = self.node.get("data") if isinstance(self.node.get("data"), dict) else {}
                links = self.data.get("inputLinks") if isinstance(self.data.get("inputLinks"), list) else []
                self.removed_links = self.removed_links_by_target.get(node_id) or self.deleted_asset_links
                if self.batch_node_ids is not None or self.independent_source_ids:
                    # A batch snapshot spans the whole canvas. Only clean actual
                    # consumers; another chain may legitimately use the same asset.
                    self.removed_links = self.removed_links_by_target.get(node_id) or [
                        copy.deepcopy(link) for link in links if link_in_deleted_scope(link)
                    ]
                if not links and not self.removed_links:
                    continue
                kept_links = [link for link in links if not link_in_deleted_scope(link)]
                if len(kept_links) == len(links) and not self.removed_links:
                    continue
                next_node = copy.deepcopy(self.node)
                next_data = next_node.get("data") if isinstance(next_node.get("data"), dict) else {}
                node_changed = False
                if len(kept_links) != len(links):
                    next_data["inputLinks"] = kept_links
                    node_changed = True
                if self.removed_links and _workflow_remove_unlinked_asset_refs_from_node_data(self.project_id, next_data, self.removed_links):
                    self.asset_refs_changed = True
                    node_changed = True
                if self.removed_links:
                    self.segment_id = str(
                        _node_segment_id(next_node)
                        or next_data.get("segmentId")
                        or next_data.get("segment_id")
                        or ""
                    ).strip()
                    self.shot_plan_cleanups.append((self.segment_id, self.removed_links))
                if not node_changed:
                    continue
                next_node["data"] = next_data
                _ensure_saved_workflow_node_contract(next_node)
                self.patched_nodes.append(next_node)
                self.affected_input_node_ids.add(node_id)

        self.patched_node_by_id = {
            str(node.get("id") or "").strip(): copy.deepcopy(node)
            for node in self.patched_nodes
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        self.workflow_nodes = self.workflow.get("nodes") if isinstance(self.workflow.get("nodes"), list) else []
        self.workflow["nodes"] = [
            copy.deepcopy(self.patched_node_by_id.get(node_id, node))
            for node in self.workflow_nodes
            if isinstance(node, dict)
            and (node_id := str(node.get("id") or "").strip())
            and node_id not in self.delete_node_ids
        ]
        _workflow_remove_edges_from_memory(self.workflow, self.deleted_edge_ids)
        self.patched_nodes = [
            copy.deepcopy(node)
            for node_id, node in self.patched_node_by_id.items()
            if node_id not in self.delete_node_ids
        ]

    def _commit_and_cleanup(self):
        self.workflow["routes"] = [route for route in self.workflow.get("routes", []) if route.get("id") not in self.deleted_route_ids]
        self.workflow["workChains"] = [chain for chain in self.workflow.get("workChains", []) if chain.get("id") not in self.deleted_work_chain_ids]
        self.changed_resources = [
            "canvas_node",
            *(["canvas_edge"] if self.deleted_edge_ids else []),
            *(["canvas_route"] if self.deleted_route_ids else []),
            *(["canvas_work_chain"] if self.deleted_work_chain_ids else []),
            *(["canvas_projection"] if self.asset_refs_changed else []),
        ]
        self.save_result = delete_canvas_records_v4(
            self.project_id,
            self.episode_id,
            node_ids=sorted(self.delete_node_ids),
            edge_ids=list(dict.fromkeys(self.deleted_edge_ids)),
            route_ids=self.deleted_route_ids,
            work_chain_ids=self.deleted_work_chain_ids,
            nodes=self.patched_nodes,
            op_type="structure_patch",
            changed_resources=self.changed_resources,
            expected_revision=self.workflow["version"],
        )
        for self.segment_id, self.removed_links in self.shot_plan_cleanups:
            if _workflow_remove_unlinked_asset_refs_from_shot_plan(
                self.project_id, self.episode_id, segment_id=self.segment_id, removed_links=self.removed_links,
            ) and "workChainPlan" not in self.changed_resources:
                self.changed_resources.append("workChainPlan")
        _touch_project_meta(self.project_id)

    def _build_response(self):
        mutation_fields = _workflow_mutation_event_fields(
            self.save_result,
            self.changed_resources,
        )
        self.patched_node_by_id = {
            str(node.get("id") or "").strip(): copy.deepcopy(node)
            for node in self.patched_nodes
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        self.workflow_nodes = self.workflow.get("nodes") if isinstance(self.workflow.get("nodes"), list) else []
        self.workflow["nodes"] = [
            copy.deepcopy(self.patched_node_by_id.get(node_id, node))
            for node in self.workflow_nodes
            if isinstance(node, dict)
            and (node_id := str(node.get("id") or "").strip())
            and node_id not in self.delete_node_ids
        ]
        _workflow_remove_edges_from_memory(self.workflow, self.deleted_edge_ids)
        synced_video_task_node_ids = sorted(_workflow_video_task_node_ids(self.workflow, self.affected_input_node_ids))
        workflow_version = self.save_result.get("workflowVersion")
        if workflow_version:
            self.workflow["version"] = workflow_version
        response_node_ids = {
            *self.affected_input_node_ids,
            *synced_video_task_node_ids,
        }
        response_node_ids.difference_update(self.delete_node_ids)
        response_base_nodes = _workflow_material_input_response_nodes(
            self.project_id,
            self.episode_id,
            self.workflow,
            response_node_ids,
        )
        response_base_node_ids = {
            str(node.get("id") or "").strip()
            for node in response_base_nodes
            if isinstance(node, dict)
        }
        for patched_node in self.patched_nodes:
            patched_node_id = str(patched_node.get("id") or "").strip() if isinstance(patched_node, dict) else ""
            if (
                patched_node_id
                and patched_node_id not in self.delete_node_ids
                and patched_node_id not in response_base_node_ids
            ):
                response_base_nodes.append(copy.deepcopy(patched_node))
                response_base_node_ids.add(patched_node_id)
        response_nodes = response_base_nodes
        return {
            "success": True,
            "episodeId": self.episode_id,
            "itemType": "node",
            "itemId": self.item_id,
            "deletedNodeIds": sorted(self.delete_node_ids),
            "deletedRouteIds": sorted(self.deleted_route_ids),
            "deletedWorkChainIds": sorted(self.deleted_work_chain_ids),
            "deletedEdgeIds": list(dict.fromkeys(self.deleted_edge_ids)),
            "removedInputLinkIds": sorted(self.removed_input_link_ids),
            "affectedNodeIds": sorted(self.affected_input_node_ids),
            "inputDirtyNodeIds": sorted(self.affected_input_node_ids),
            "syncedVideoTaskNodeIds": synced_video_task_node_ids,
            "nodes": response_nodes,
            "workflowVersion": workflow_version,
            **mutation_fields,
            "focusTarget": {"section": "episode", "episodeId": self.episode_id},
            "projectChanged": True,
        }


def _delete_workflow_node_item_fast_v4(
    project_id: str,
    episode_id: str,
    item_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    return _CanvasNodeDeletion(project_id, episode_id, item_id, payload).run()


def _delete_workflow_scope_item_fast_v4(
    project_id: str,
    episode_id: str,
    item_type: str,
    item_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if item_type not in {"route", "workChain"}:
        return None
    scope_result = get_canvas_scope_records_v4(
        project_id,
        episode_id,
        {
            "detail": "full",
            "routeIds": [item_id] if item_type == "route" else [],
            "workChainIds": [item_id] if item_type == "workChain" else [],
            "deleteOrphanWorkChains": True,
        },
    )
    validate_canvas_revision_v4(scope_result["currentRevision"], payload.get("expectedRevision", payload.get("expected_revision")))
    records = scope_result.get("records") if isinstance(scope_result.get("records"), dict) else {}
    routes = [copy.deepcopy(route) for route in records.get("routes", []) if isinstance(route, dict)]
    work_chains = [copy.deepcopy(chain) for chain in records.get("workChains", []) if isinstance(chain, dict)]
    nodes = [copy.deepcopy(node) for node in records.get("nodes", []) if isinstance(node, dict)]
    edges = [copy.deepcopy(edge) for edge in records.get("edges", []) if isinstance(edge, dict)]
    matched_item = (
        next((route for route in routes if str(route.get("id") or "").strip() == item_id), None)
        if item_type == "route"
        else next((chain for chain in work_chains if str(chain.get("id") or "").strip() == item_id), None)
    )
    if matched_item is None and not nodes and not edges:
        result = {
            "success": True,
            "message": f"未找到 {item_type} {item_id}，无需删除。",
            "episodeId": episode_id,
            "itemType": item_type,
            "itemId": item_id,
            "changedResources": [],
            "focusTarget": {"section": "episode", "episodeId": episode_id, "itemId": item_id},
            "projectChanged": False,
        }
        return result
    if item_type != "workChain" or not matched_item or work_chain_origin(matched_item, records)["kind"] not in {"independent", "independent_source"}:
        raise ValueError("仅独立工作链支持整链删除，不能单独删除工作链中的路线")
    # Scope queries also include route neighbors; only ownership authorizes deletion.
    nodes = [node for node in nodes if _node_work_chain_id(node) == item_id]
    delete_node_ids = {str(node["id"]) for node in nodes}
    routes = [route for route in routes if route.get("workChainId") == item_id]
    edges = [edge for edge in edges if edge.get("source") in delete_node_ids or edge.get("target") in delete_node_ids]
    if any(_is_user_locked_item(item) for item in [matched_item, *nodes]):
        raise ValueError("工作链中有用户锁定的卡片，请先解锁")
    from .task_lifecycle import _background_storyboard_task_has_running_thread
    from .task_storage import _TASK_STORAGE_LOCK
    from .task_storage import _load_tasks_for_project

    with _TASK_STORAGE_LOCK:
        for task in _load_tasks_for_project(project_id):
            task_nodes = {str(task.get(key) or "") for key in ("nodeId", "taskNodeId", "generationTaskNodeId", "resultNodeId", "versionNodeId")}
            if str(task.get("episodeId") or "") != episode_id or not task_nodes.intersection(delete_node_ids):
                continue
            if task.get("status") in {"created", "queued", "pending", "running", "cancelling"} or _background_storyboard_task_has_running_thread(task):
                raise ValueError("工作链中仍有任务执行，请等待任务结束后再删除")
        workflow = get_canvas_workflow_projection(project_id, episode_id)
        if workflow.get("version") != scope_result.get("currentRevision"):
            raise ValueError("画布版本已变化，请刷新后重试")
        workflow["nodes"] = [node for node in workflow["nodes"] if node["id"] not in delete_node_ids]
        workflow["edges"] = [edge for edge in workflow["edges"] if edge.get("source") not in delete_node_ids and edge.get("target") not in delete_node_ids]
        consumer_ids = {str(edge.get("target")) for edge in edges if edge.get("source") in delete_node_ids and edge.get("target") not in delete_node_ids}
        patched_nodes = []
        for node in workflow["nodes"]:
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            links = data.get("inputLinks") if isinstance(data.get("inputLinks"), list) else []
            removed = [link for link in links if isinstance(link, dict) and str(link.get("sourceNodeId") or link.get("source_node_id") or link.get("source") or "") in delete_node_ids]
            if not removed and node["id"] not in consumer_ids:
                continue
            data["inputLinks"] = [link for link in links if link not in removed]
            _workflow_remove_unlinked_asset_refs_from_node_data(project_id, data, removed)
            patched_nodes.append(node)
        result = delete_canvas_records_v4(
            project_id, episode_id, node_ids=delete_node_ids,
            edge_ids=[edge["id"] for edge in edges], route_ids=[route["id"] for route in routes],
            work_chain_ids=[item_id], nodes=patched_nodes,
            expected_revision=scope_result["currentRevision"],
        )
    _touch_project_meta(project_id)
    try:
        update_episode_production_status(project_id, episode_id)
    except Exception:
        print(traceback.format_exc(), flush=True)
    return {
        **result, "projectChanged": True, "itemType": "workChain", "itemId": item_id,
        "deletedNodeIds": result["removedNodeIds"], "deletedEdgeIds": result["removedEdgeIds"],
        "deletedRouteIds": result["removedRouteIds"], "deletedWorkChainIds": result["removedWorkChainIds"],
    }


def delete_workflow_item(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "删除画布记录")
    raw_item_type = str(payload.get("itemType") or payload.get("item_type") or payload.get("kind") or "node").strip()
    item_type = {
        "work_chain": "workChain",
        "workchain": "workChain",
        "chain": "workChain",
    }.get(raw_item_type, raw_item_type)
    if item_type not in {"node", "route", "workChain"}:
        raise ValueError("itemType 必须是 node、route 或 workChain；取消资产关联请使用 unlink_workflow_input")
    item_id = str(payload.get("itemId") or payload.get("item_id") or payload.get("nodeId") or payload.get("node_id") or payload.get("id") or "").strip()
    if not item_id:
        raise ValueError("缺少 itemId")
    if item_type == "node":
        fast_result = retry_canvas_mutation_v4(
            lambda: _delete_workflow_node_item_fast_v4(project_id, episode_id, item_id, payload),
            expected_revision=payload.get("expectedRevision", payload.get("expected_revision")),
        )
        if fast_result is not None:
            return fast_result
        raise RuntimeError("删除画布节点未产生 v4 事务")
    if item_type in {"route", "workChain"}:
        fast_result = _delete_workflow_scope_item_fast_v4(
            project_id,
            episode_id,
            item_type,
            item_id,
            payload,
        )
        if fast_result is not None:
            return fast_result
        raise RuntimeError("删除画布作用域未产生 v4 事务")
    raise RuntimeError("删除画布记录未产生 v4 事务")


def _workflow_remove_unlinked_asset_refs_from_shot_plan(
    project_id: str,
    episode_id: str,
    *,
    segment_id: str,
    removed_links: list[dict[str, Any]],
) -> bool:
    if not project_id or not episode_id or not segment_id:
        return False
    targets = _workflow_asset_ref_removal_targets(removed_links)
    if not targets:
        return False
    path = _work_chain_plan_path(project_id, episode_id)
    if not path.exists():
        return False
    shot_plan = _read_json(path, {})
    if not isinstance(shot_plan, dict):
        return False
    before = copy.deepcopy(shot_plan)
    changed = False
    for collection_name in ("segments", "shots", "panels"):
        rows = shot_plan.get(collection_name)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not _workflow_shot_plan_row_matches_segment(row, segment_id):
                continue
            for key in ("assetRefs", "asset_refs"):
                if key not in row:
                    continue
                next_refs, removed = _workflow_remove_asset_refs_from_value(row.get(key), targets)
                if removed:
                    row[key] = next_refs if _asset_refs_has_value(next_refs) else {}
                    changed = True
            for card_key in ("directorTaskCard", "director_task_card", "storyboardTaskCard", "storyboard_task_card"):
                task_card = row.get(card_key) if isinstance(row.get(card_key), dict) else {}
                if task_card and _workflow_remove_unlinked_asset_refs_from_node_data(project_id, task_card, removed_links):
                    changed = True
    if not changed:
        return False
    shot_plan["episodeId"] = episode_id
    shot_plan["revision"] = _resource_revision_value(before) + 1
    shot_plan["updatedAt"] = _now()
    _append_resource_revision(
        project_id,
        resource="workChainPlan",
        relative_path=f"episodes/{episode_id}/work_chain_plan.json",
        document=before,
        reason="workflow_asset_input_unlinked",
    )
    _write_json(path, shot_plan)
    _touch_project_meta(project_id)
    return True
