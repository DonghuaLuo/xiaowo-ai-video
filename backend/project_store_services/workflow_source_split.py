# -*- coding: utf-8 -*-
"""原文拆分与手动工作链创建。

该模块承载原文工作链的结构调整逻辑。
工作流兼容模块通过显式导入公开入口，保留既有调用路径。
"""

from __future__ import annotations

import copy
import math
import re
import uuid
from typing import Any

from utils.agent_context import _compact_text

from .agent_sessions import _project_dir
from .projects import _touch_project_meta
from .canvas_store_queries import get_canvas_context_v4
from .canvas_store_mutations import replace_canvas_records_from_workflow_projection_v4, write_canvas_records_v4
from .canvas_store_database import retry_canvas_mutation_v4

from .workflow_contract import (
    _assert_canvas_mutation_does_not_return_workflow,
    _ensure_saved_workflow_chain_contract,
    _ensure_saved_workflow_contract,
    _ensure_saved_workflow_node_contract,
    _ensure_saved_workflow_route_contract,
    _workflow_is_video_task_type,
    _workflow_mutation_event_fields,
)
from .canvas_ownership import work_chain_origin
from .workflow_contract import _translate_workflow_layout
from .workflow_projection import get_canvas_workflow_projection
from .work_chain_factory import build_independent_work_chain
from .source_text_store import get_episode_source_text
from .planning_workflow_layout import _layout_workflow_by_work_chain

def _source_split_chain_rows(workflow: dict[str, Any], source_node_id: str, origin_kind: str = "source_split") -> list[dict[str, Any]]:
    rows = []
    for chain in workflow.get("workChains", []) if isinstance(workflow.get("workChains"), list) else []:
        if not isinstance(chain, dict):
            continue
        origin = work_chain_origin(chain, workflow)
        if origin.get("kind") != origin_kind or str(origin.get("sourceNodeId") or "").strip() != source_node_id:
            continue
        rows.append(chain)
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("order") or 0) if str(row.get("order") or "").strip() else 999999,
            str(row.get("id") or ""),
        ),
    )


def _source_split_is_explicit_user_lock(item: Any) -> bool:
    """Only block source-split deletion for explicit user locks.

    Workflow-generated dependency links commonly carry preserveOnReplan so they
    survive agent replanning. That flag is a system protection marker, not a
    user lock, and must not prevent manual source-split count adjustments.
    """
    records = [item]
    if isinstance(item, dict) and isinstance(item.get("data"), dict):
        records.append(item["data"])
    for record in records:
        if not isinstance(record, dict):
            continue
        if any(
            bool(record.get(key))
            for key in ("lockedByUser", "locked_by_user", "userLocked")
        ):
            return True
        if not record.get("locked") or record.get("preserveOnReplan"):
            continue
        reason = str(
            record.get("lockedReason") or record.get("locked_reason") or ""
        ).strip()
        if reason not in {
            "locked_system_edge",
            "task_result_edge",
            "workflow_chain_storyboard_video_input",
            "workflow_chain_video_result_input",
        }:
            return True
    return False


def _source_split_segment_mapping(
    chains: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Use editor identities; never reconstruct submitted text from old offsets."""
    chain_indexes = {str(chain["id"]): index for index, chain in enumerate(chains)}
    claimed_ids: set[str] = set()
    mappings: list[dict[str, Any]] = []
    for segment in segments:
        chain_id = str(segment.get("workChainId") or "")
        template_id = str(segment.get("templateWorkChainId") or chain_id)
        if chain_id and (chain_id not in chain_indexes or chain_id in claimed_ids):
            raise ValueError("拆分结果包含无效或重复的工作链，请重新打开编辑器")
        if template_id not in chain_indexes:
            raise ValueError("拆分结果缺少有效的来源工作链，请重新打开编辑器")
        if chain_id:
            claimed_ids.add(chain_id)
        mappings.append({
            "oldIndex": chain_indexes.get(chain_id),
            "templateIndex": chain_indexes[template_id],
        })
    return mappings


def _source_split_script_nodes(workflow: dict[str, Any], work_chain_id: str) -> list[dict[str, Any]]:
    rows = [
        node
        for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else [])
        if isinstance(node, dict)
        and str(node.get("workChainId") or (node.get("data") or {}).get("workChainId") or "").strip() == work_chain_id
        and str(node.get("type") or "").strip() == "prompt.storyboard"
    ]
    return sorted(
        rows,
        key=lambda node: (
            float((node.get("position") or {}).get("y") or 0),
            float((node.get("position") or {}).get("x") or 0),
            str(node.get("id") or ""),
        ),
    )


def _source_split_set_script_text(node: dict[str, Any], text: str) -> None:
    data = node.setdefault("data", {})
    if not isinstance(data, dict):
        data = {}
        node["data"] = data
    data["sourceFactText"] = text
    prompt = data.get("prompt") if isinstance(data.get("prompt"), dict) else {}
    prompt = copy.deepcopy(prompt)
    prompt["sourceFactText"] = text
    data["prompt"] = prompt
    task_card = data.get("storyboardTaskCard") if isinstance(data.get("storyboardTaskCard"), dict) else {}
    task_card = copy.deepcopy(task_card)
    task_card["sourceFactText"] = text
    data["storyboardTaskCard"] = task_card
    data["summary"] = data.get("summary") or _compact_text(text, 160)
    _ensure_saved_workflow_node_contract(node)


def _source_split_reset_node_data(
    data: dict[str, Any],
    node_type: str,
    text: str,
) -> dict[str, Any]:
    next_data = copy.deepcopy(data) if isinstance(data, dict) else {}
    for key in (
        "cinematicStoryText", "cinematic_story_text", "directorPlan", "directorPlanShots",
        "speakerRoster", "speechBudgetNote",
        "storyboardAnalysis", "storyboardAnalysisStoryTextHash", "storyboard_plan_hash",
        "shots", "shotIds", "shotTimingPlan", "shot_timing_plan", "quality",
        "assetThumbnails", "referenceThumbnails", "referenceMediaIds", "assetRefs",
        "assetRefsResolvedByInputLinks", "missingAssetRefs", "missingAssetRefsConfirmed",
        "media", "storage", "mediaId", "mediaVersionId", "activeMediaVersionId",
        "activeVersionId", "winnerVersionId", "selectionReason", "selectedAt",
        "sourceVersionId", "inputContract", "needsRelink", "copiedFromNodeId",
    ):
        next_data.pop(key, None)
    next_data["inputLinks"] = []
    next_data["sourceRefs"] = []
    next_data["summary"] = ""
    if node_type == "prompt.storyboard":
        next_data["status"] = "ready"
        next_data["narrativeMode"] = "drama"
        next_data["sourceFactText"] = text
        next_data["cinematicStoryText"] = ""
        next_data["prompt"] = {"sourceFactText": text, "cinematicStoryText": ""}
        next_data["storyboardTaskCard"] = {
            "title": str(next_data.get("title") or "原文片段"),
            "sourceFactText": text,
            "cinematicStoryText": "",
            "state": "pending_script",
            "scriptState": "pending_script",
        }
        card_state = next_data.get("cardState") if isinstance(next_data.get("cardState"), dict) else {}
        next_data["cardState"] = {**card_state, "state": "pending_script", "scriptState": "pending_script"}
    elif node_type == "director.board":
        next_data["status"] = "draft"
        next_data["directorPlan"] = ""
        next_data["directorPlanShots"] = []
        next_data["speakerRoster"] = []
        next_data["prompt"] = {"directorPlan": "", "directorPlanShots": [], "speakerRoster": []}
        next_data["directorTaskCard"] = {
            "title": str(next_data.get("title") or "分镜脚本"),
            "directorPlan": "",
            "directorPlanShots": [],
            "speakerRoster": [],
            "state": "pending_director_plan",
        }
    elif node_type in {"storyboard.image"}:
        next_data["status"] = "waiting"
    elif _workflow_is_video_task_type(node_type):
        next_data["status"] = "waiting"
        next_data["videoTaskCard"] = {"finalVideoPrompt": ""}
    elif node_type == "video.result":
        next_data["status"] = "waiting"
    else:
        next_data["status"] = "draft"
    return next_data


def _source_split_clone_chain(
    workflow: dict[str, Any],
    template_chain: dict[str, Any],
    text: str,
    order: int,
    source_node_id: str,
    *,
    origin_kind: str = "source_split",
    label_prefix: str = "原文事实段落",
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    old_chain_id = str(template_chain.get("id") or "").strip()
    old_route_ids = {str(value) for value in template_chain.get("routeIds") or [] if str(value)}
    template_routes = [
        route for route in (workflow.get("routes", []) if isinstance(workflow.get("routes"), list) else [])
        if isinstance(route, dict)
        and (str(route.get("workChainId") or "").strip() == old_chain_id or str(route.get("id") or "").strip() in old_route_ids)
    ]
    template_route = sorted(template_routes, key=lambda row: str(row.get("id") or ""))[0] if template_routes else {}
    template_nodes = [
        node for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else [])
        if isinstance(node, dict)
        and str(node.get("workChainId") or (node.get("data") or {}).get("workChainId") or "").strip() == old_chain_id
    ]
    template_node_ids = {str(node.get("id") or "").strip() for node in template_nodes if str(node.get("id") or "").strip()}
    template_edges = [
        edge for edge in (workflow.get("edges", []) if isinstance(workflow.get("edges"), list) else [])
        if isinstance(edge, dict)
        and (str((edge.get("data") if isinstance(edge.get("data"), dict) else {}).get("workChainId") or "").strip() == old_chain_id
             or str(edge.get("source") or "").strip() in template_node_ids
             or str(edge.get("target") or "").strip() in template_node_ids)
    ]
    token = uuid.uuid4().hex[:10]
    chain_id = f"chain_manual_{token}"
    route_id = f"route_{chain_id}"
    segment_id = f"segment_{chain_id}"
    id_map = {
        str(node.get("id") or ""): f"{chain_id}_{index + 1:02d}"
        for index, node in enumerate(template_nodes)
        if str(node.get("id") or "").strip()
    }
    node_by_old_id = {str(node.get("id") or ""): node for node in template_nodes}
    template_y_values = [float((node.get("position") or {}).get("y") or 0) for node in template_nodes]
    existing_y_values = [float((node.get("position") or {}).get("y") or 0) for node in workflow.get("nodes", []) if isinstance(node, dict)]
    existing_max_y = max(existing_y_values) if existing_y_values else 0
    existing_chain_count = len(workflow.get("workChains", [])) if isinstance(workflow.get("workChains"), list) else 0
    base_y = (existing_max_y + 300 + max(0, order - existing_chain_count) * 300) if existing_y_values else 120 + (order - 1) * 300
    source_template_y = min(template_y_values) if template_y_values else 0
    y_delta = base_y - source_template_y
    new_nodes: list[dict[str, Any]] = []
    for old_id, old_node in node_by_old_id.items():
        node = copy.deepcopy(old_node)
        node["id"] = id_map[old_id]
        node["workChainId"] = chain_id
        node["routeId"] = route_id
        node["segmentId"] = segment_id
        node["position"] = {
            **(node.get("position") if isinstance(node.get("position"), dict) else {}),
            "y": float((node.get("position") or {}).get("y") or 0) + y_delta,
        }
        old_node_data = old_node.get("data") if isinstance(old_node.get("data"), dict) else {}
        node_data = _source_split_reset_node_data(old_node_data, str(node.get("type") or ""), text)
        node_data.update({"workChainId": chain_id, "routeId": route_id, "segmentId": segment_id})
        node["data"] = node_data
        node["status"] = node_data.get("status")
        if node_data.get("resultOfNodeId"):
            node_data["resultOfNodeId"] = id_map.get(str(node_data["resultOfNodeId"]), node_data["resultOfNodeId"])
        if node_data.get("sourceNodeId"):
            node_data["sourceNodeId"] = id_map.get(str(node_data["sourceNodeId"]), node_data["sourceNodeId"])
        if node.get("resultOfNodeId"):
            node["resultOfNodeId"] = id_map.get(str(node["resultOfNodeId"]), node["resultOfNodeId"])
        _ensure_saved_workflow_node_contract(node)
        new_nodes.append(node)

    new_edges: list[dict[str, Any]] = []
    input_link_id_map: dict[str, str] = {}
    for index, old_edge in enumerate(template_edges):
        source_id = str(old_edge.get("source") or "").strip()
        target_id = str(old_edge.get("target") or "").strip()
        mapped_source = id_map.get(source_id, source_node_id if source_id == source_node_id else "")
        mapped_target = id_map.get(target_id, "")
        if not mapped_source or not mapped_target:
            continue
        edge = copy.deepcopy(old_edge)
        edge["id"] = f"{chain_id}_edge_{index + 1:02d}"
        edge["source"] = mapped_source
        edge["target"] = mapped_target
        edge_data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        edge_data = copy.deepcopy(edge_data)
        edge_data.update({"workChainId": chain_id, "routeId": route_id, "segmentId": segment_id})
        if edge_data.get("inputLinkId"):
            previous_input_link_id = str(edge_data.get("inputLinkId") or "").strip()
            edge_data["inputLinkId"] = f"{edge['id']}_input"
            input_link_id_map[previous_input_link_id] = edge_data["inputLinkId"]
        edge["data"] = edge_data
        new_edges.append(edge)

    for node in new_nodes:
        old_node = node_by_old_id.get(next((old_id for old_id, mapped_id in id_map.items() if mapped_id == node.get("id")), ""))
        old_data = old_node.get("data") if isinstance(old_node, dict) and isinstance(old_node.get("data"), dict) else {}
        old_links = old_data.get("inputLinks") if isinstance(old_data.get("inputLinks"), list) else []
        mapped_links: list[dict[str, Any]] = []
        for link_index, raw_link in enumerate(old_links):
            if not isinstance(raw_link, dict):
                continue
            link = copy.deepcopy(raw_link)
            source_id = str(link.get("sourceNodeId") or link.get("source_node_id") or "").strip()
            target_id = str(link.get("targetNodeId") or link.get("target_node_id") or node.get("id") or "").strip()
            mapped_source = id_map.get(source_id, source_node_id if source_id == source_node_id else "")
            mapped_target = id_map.get(target_id, str(node.get("id") or "").strip())
            if not mapped_source or not mapped_target:
                continue
            link["id"] = input_link_id_map.get(str(link.get("id") or "").strip(), f"{node['id']}_input_{link_index + 1:02d}")
            link["sourceNodeId"] = mapped_source
            link["targetNodeId"] = mapped_target
            link["workChainId"] = chain_id
            link["routeId"] = route_id
            link["segmentId"] = segment_id
            link["status"] = "pending_generation"
            for key in ("sourceVersionId", "source_version_id", "mediaVersionId", "media_version_id", "versionId", "version_id", "mediaId", "media_id", "path"):
                link.pop(key, None)
            mapped_links.append(link)
        node.setdefault("data", {})["inputLinks"] = mapped_links

    script_nodes = [node for node in new_nodes if str(node.get("type") or "") == "prompt.storyboard"]
    if script_nodes and not any(str(edge.get("source") or "") == source_node_id for edge in new_edges):
        script_node = script_nodes[0]
        new_edges.insert(0, {
            "id": f"{chain_id}_source_to_script",
            "source": source_node_id,
            "sourceHandle": "output",
            "target": script_node["id"],
            "targetHandle": "story",
            "data": {
                "kind": "dependency", "role": "context", "sourceNodeType": "source.text",
                "targetNodeType": "prompt.storyboard", "workChainId": chain_id,
                "routeId": route_id, "segmentId": segment_id,
            },
        })

    route = copy.deepcopy(template_route) if template_route else {
        "strategy": "storyboard_multi_shot", "status": "draft", "shotIds": [],
    }
    route.update({"id": route_id, "workChainId": chain_id, "segmentId": segment_id, "shotIds": [], "shotCount": 0, "status": "draft", "laneIndex": order - 1})
    _ensure_saved_workflow_route_contract({"nodes": new_nodes}, route, order - 1, {route_id: chain_id})
    chain = copy.deepcopy(template_chain)
    chain.update({
        "id": chain_id,
        "label": f"{label_prefix} {order}",
        "title": f"{label_prefix} {order}",
        "origin": {"kind": origin_kind, "sourceNodeId": source_node_id},
        "segmentIds": [segment_id], "shotIds": [], "routeIds": [route_id],
        "order": order, "status": "draft",
        "layout": {**(template_chain.get("layout") if isinstance(template_chain.get("layout"), dict) else {}), "y": base_y},
    })
    _ensure_saved_workflow_chain_contract(chain, order - 1)
    return chain, route, new_nodes, new_edges


def _apply_source_segments(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
    *,
    independent: bool,
) -> dict[str, Any]:
    params = payload if isinstance(payload, dict) else {}
    source_node_id = params.get("sourceNodeId")
    if not isinstance(source_node_id, str) or not source_node_id.strip():
        raise ValueError("缺少 sourceNodeId")
    _assert_canvas_mutation_does_not_return_workflow(params, "应用原文拆分")
    if independent and not all(isinstance(params.get(key), str) for key in ("sourceText", "expectedSourceText")):
        raise ValueError("独立原文应用需要 sourceText 和 expectedSourceText")
    raw_segments = params.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("请至少保留一条原文拆分内容")
    if len(raw_segments) > 30:
        raise ValueError("原文拆分最多支持 30 条")
    segment_texts: list[str] = []
    for index, row in enumerate(raw_segments, start=1):
        text = row.get("text") if isinstance(row, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"第 {index} 条原文不能为空")
        segment_texts.append(text)

    def mutate() -> dict[str, Any]:
        workflow = get_canvas_workflow_projection(project_id, episode_id, {"detail": "full"})
        source_node = next(
            (
                node for node in workflow.get("nodes", []) if isinstance(node, dict)
                and str(node.get("id") or "").strip() == source_node_id
                and str(node.get("type") or "").strip() == "source.text"
            ),
            None,
        )
        if not source_node:
            raise ValueError("当前画布缺少分集原文")
        source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
        is_independent = source_data.get("sourceMode") == "independent"
        if is_independent != independent:
            raise ValueError("请选择独立原文" if independent else "请选择分集原文")
        origin_kind = "independent_source" if is_independent else "source_split"
        label_prefix = "独立剧情段落" if is_independent else "原文事实段落"
        if not is_independent and workflow.get("canvasKind") == "custom":
            raise ValueError("自定义画布不支持原文工作链拆分调整")
        if is_independent:
            if _source_split_is_explicit_user_lock(source_node):
                raise ValueError("独立原文已锁定，请先解锁后再应用")
            if params["expectedSourceText"] != source_data.get("sourceText", ""):
                raise ValueError("独立原文已变化，请重新打开编辑器后再应用")
            source_text = params["sourceText"]
        else:
            source_detail = get_episode_source_text(project_id, episode_id)
            if not source_detail.get("available"):
                raise ValueError("当前分集原文不可用")
            source_text = source_detail["text"]
        if "".join(segment_texts) != source_text:
            label = "独立原文内容" if is_independent else "分集原文"
            raise ValueError(f"拆分结果与当前{label}不一致，请先保存原文或重新打开编辑器")
        source_node["data"] = {**source_data, "sourceText": source_text}
        if is_independent:
            source_node["data"]["status"] = "ready" if source_text.strip() else "draft"

        chains = _source_split_chain_rows(workflow, source_node_id, origin_kind)
        if params.get("workChainIds") != [str(chain["id"]) for chain in chains]:
            raise ValueError("工作链结构已变化，请重新打开编辑器后再保存")
        if not chains and not is_independent:
            raise ValueError("当前画布没有可调整的原文工作链")
        target_count = len(segment_texts)
        if chains:
            mappings = _source_split_segment_mapping(chains, raw_segments)
        else:
            if any(row.get("workChainId") or row.get("templateWorkChainId") for row in raw_segments):
                raise ValueError("工作链结构已变化，请重新打开编辑器后再保存")
            mappings = [{"oldIndex": None, "templateIndex": 0} for _ in raw_segments]
        # 新增独立段落始终使用空工作链，避免复制用户为旧段落关联的资产。
        independent_template = build_independent_work_chain(
            f"chain_template_{uuid.uuid4().hex[:10]}", {"x": 0, "y": 0},
        ) if is_independent else None
        if independent_template is not None:
            _ensure_saved_workflow_contract(independent_template)
        reused_old_indexes = {
            mapping["oldIndex"]
            for mapping in mappings
            if mapping.get("oldIndex") is not None
        }
        removed_chains = [
            chains[index]
            for index in range(len(chains))
            if index not in reused_old_indexes
        ]
        removed_chain_ids = {str(chain.get("id") or "").strip() for chain in removed_chains if str(chain.get("id") or "").strip()}
        removed_node_ids = {
            str(node.get("id") or "").strip()
            for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else [])
            if isinstance(node, dict) and str(node.get("workChainId") or (node.get("data") or {}).get("workChainId") or "").strip() in removed_chain_ids
        }
        if removed_chain_ids:
            for chain in removed_chains:
                if _source_split_is_explicit_user_lock(chain):
                    raise ValueError("待删除工作链中有用户锁定内容，请先解锁")
            for node in workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else []:
                if str(node.get("id") or "").strip() in removed_node_ids and _source_split_is_explicit_user_lock(node):
                    raise ValueError("待删除工作链中有用户锁定卡片，请先解锁")
            for edge in workflow.get("edges", []) if isinstance(workflow.get("edges"), list) else []:
                if not isinstance(edge, dict):
                    continue
                if (
                    str(edge.get("source") or "").strip() in removed_node_ids
                    or str(edge.get("target") or "").strip() in removed_node_ids
                ) and _source_split_is_explicit_user_lock(edge):
                    raise ValueError("待删除工作链中有用户锁定链接，请先解锁")
            from .task_lifecycle import _background_storyboard_task_has_running_thread
            from .task_storage import _load_tasks_for_project
            for task in _load_tasks_for_project(project_id):
                if str(task.get("episodeId") or "") != episode_id:
                    continue
                task_node_ids = {str(task.get(key) or "") for key in ("nodeId", "taskNodeId", "generationTaskNodeId", "resultNodeId", "versionNodeId")}
                if not task_node_ids.intersection(removed_node_ids):
                    continue
                if task.get("status") in {"created", "queued", "pending", "running", "cancelling"} or _background_storyboard_task_has_running_thread(task):
                    raise ValueError("待删除工作链仍有任务执行，请等待任务结束后再试")

        current_nodes = [
            copy.deepcopy(node)
            for node in (workflow.get("nodes", []) if isinstance(workflow.get("nodes"), list) else [])
            if isinstance(node, dict)
            and str(node.get("workChainId") or (node.get("data") or {}).get("workChainId") or "").strip()
            not in removed_chain_ids
        ]

        current_routes = [
            copy.deepcopy(route)
            for route in (workflow.get("routes", []) if isinstance(workflow.get("routes"), list) else [])
            if isinstance(route, dict) and str(route.get("workChainId") or "").strip() not in removed_chain_ids
        ]
        current_edges = [
            copy.deepcopy(edge)
            for edge in (workflow.get("edges", []) if isinstance(workflow.get("edges"), list) else [])
            if isinstance(edge, dict)
            and str(edge.get("source") or "").strip() not in removed_node_ids
            and str(edge.get("target") or "").strip() not in removed_node_ids
            and str((edge.get("data") or {}).get("workChainId") or "").strip() not in removed_chain_ids
        ]
        current_chains = [
            copy.deepcopy(chain)
            for chain in (workflow.get("workChains", []) if isinstance(workflow.get("workChains"), list) else [])
            if isinstance(chain, dict) and str(chain.get("id") or "").strip() not in removed_chain_ids
        ]
        current_chain_by_id = {
            str(chain.get("id") or "").strip(): chain
            for chain in current_chains
            if str(chain.get("id") or "").strip()
        }
        for index, mapping in enumerate(mappings):
            old_index = mapping.get("oldIndex")
            if old_index is not None:
                chain = chains[old_index]
                chain_id = str(chain.get("id") or "").strip()
                current_chain = current_chain_by_id.get(chain_id)
                if current_chain is not None:
                    current_chain["order"] = index + 1
                    current_chain["label"] = f"{label_prefix} {index + 1}"
                    current_chain["title"] = f"{label_prefix} {index + 1}"
                scripts = _source_split_script_nodes(workflow, chain_id)
                if scripts:
                    _source_split_set_script_text(scripts[0], segment_texts[index])
                    for cursor, current in enumerate(current_nodes):
                        if str(current.get("id") or "") == str(scripts[0].get("id") or ""):
                            current_nodes[cursor] = scripts[0]
                            break
        new_chain_ids: set[str] = set()
        for order, mapping in enumerate(mappings, start=1):
            if mapping.get("oldIndex") is not None:
                continue
            template_workflow = independent_template if is_independent else workflow
            template_chain = independent_template["workChains"][0] if is_independent else chains[mapping["templateIndex"]]
            new_chain, new_route, new_nodes, new_edges = _source_split_clone_chain(
                template_workflow, template_chain, segment_texts[order - 1], order, source_node_id,
                origin_kind=origin_kind, label_prefix=label_prefix,
            )
            current_chains.append(new_chain)
            current_routes.append(new_route)
            current_nodes.extend(new_nodes)
            current_edges.extend(new_edges)
            new_chain_ids.add(str(new_chain.get("id") or "").strip())

        source_chain_ids = {
            *{
                str(chain.get("id") or "").strip()
                for chain in chains
                if str(chain.get("id") or "").strip()
            },
            *new_chain_ids,
        }
        original_chains = [chain for chain in (workflow.get("workChains", []) if isinstance(workflow.get("workChains"), list) else []) if isinstance(chain, dict)]
        first_source_index = next((index for index, chain in enumerate(original_chains) if str(chain.get("id") or "").strip() in source_chain_ids), len(original_chains))
        non_source_chains = [chain for chain in current_chains if str(chain.get("id") or "").strip() not in source_chain_ids]
        next_source_chains = [chain for chain in current_chains if str(chain.get("id") or "").strip() in source_chain_ids]
        next_source_chains.sort(key=lambda chain: int(chain.get("order") or 999999))
        prefix_count = sum(1 for chain in original_chains[:first_source_index] if str(chain.get("id") or "").strip() not in source_chain_ids)
        current_chains = non_source_chains[:prefix_count] + next_source_chains + non_source_chains[prefix_count:]
        # Use the generation layout on the affected source chains only. These are
        # references to the records below, so node, route and chain positions agree.
        layout_nodes = [
            node for node in current_nodes
            if node.get("workChainId") in source_chain_ids or node.get("id") == source_node_id
        ]
        layout_routes = [route for route in current_routes if route.get("workChainId") in source_chain_ids]
        layout_node_ids = {node["id"] for node in layout_nodes}
        layout_edges = [edge for edge in current_edges if edge.get("source") in layout_node_ids and edge.get("target") in layout_node_ids]
        layout_source = next(node for node in layout_nodes if node.get("id") == source_node_id)
        source_position = dict(layout_source.get("position") or {})
        _layout_workflow_by_work_chain(layout_nodes, layout_routes, next_source_chains, layout_edges)
        _translate_workflow_layout(
            {"nodes": layout_nodes, "routes": layout_routes, "workChains": next_source_chains},
            float(source_position.get("x") or 0) - layout_source["position"]["x"],
            float(source_position.get("y") or 0) - layout_source["position"]["y"],
        )
        workflow["nodes"] = current_nodes
        workflow["edges"] = current_edges
        workflow["routes"] = current_routes
        workflow["workChains"] = current_chains
        workflow["state"] = dict(workflow.get("state") or {})
        workflow["state"]["nextAction"] = "run_workflow"
        result = replace_canvas_records_from_workflow_projection_v4(
            project_id,
            episode_id,
            workflow,
            op_type="structure_patch",
            expected_revision=workflow.get("version"),
        )
        _touch_project_meta(project_id)
        return {
            "success": True,
            "episodeId": episode_id,
            "sourceNodeId": source_node_id,
            "segmentCount": target_count,
            "workflowVersion": result["workflowVersion"],
            "projectChanged": True,
            **_workflow_mutation_event_fields(result, ["canvas_node", "canvas_edge", "canvas_route", "canvas_work_chain"]),
        }

    return retry_canvas_mutation_v4(mutate)


def adjust_source_split_workflow(project_id: str, episode_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _apply_source_segments(project_id, episode_id, payload, independent=False)
def create_manual_workflow_chain(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not episode_id:
        raise ValueError("缺少 episodeId")
    payload = payload if isinstance(payload, dict) else {}
    _assert_canvas_mutation_does_not_return_workflow(payload, "创建工作链")
    context = get_canvas_context_v4(project_id, episode_id)
    if context["canvasKind"] != "custom" and not context["autoWorkflowInitialized"]:
        raise ValueError("请先完成当前工作链画布的自动初始化")
    position = payload.get("position") or {"x": 0, "y": 0}
    try:
        target_x, target_y = float(position["x"]), float(position["y"])
        if not math.isfinite(target_x) or not math.isfinite(target_y):
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("工作链位置必须是有效的画布坐标") from None
    work_chain_id = str(payload.get("workChainId") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", work_chain_id):
        raise ValueError("缺少有效的 workChainId")
    workflow = build_independent_work_chain(work_chain_id, {"x": target_x, "y": target_y})
    workflow.update(context)
    _ensure_saved_workflow_contract(workflow)
    script = workflow["nodes"][0]
    segment_id = script["segmentId"]
    result = write_canvas_records_v4(
        project_id, episode_id, nodes=workflow["nodes"], edges=workflow["edges"],
        routes=workflow["routes"], work_chains=workflow["workChains"],
        op_type="structure_patch", create_only=True,
    )
    _touch_project_meta(project_id)
    return {
        **result,
        "workChainId": work_chain_id, "segmentId": segment_id, "projectChanged": True,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": script["id"]},
    }


def create_independent_source_card(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """创建只保存原文、等待用户应用后再生成工作链的独立原文。"""
    if not episode_id:
        raise ValueError("缺少 episodeId")
    params = payload if isinstance(payload, dict) else {}
    position = params.get("position") or {"x": 0, "y": 0}
    try:
        target_x, target_y = float(position["x"]), float(position["y"])
        if not math.isfinite(target_x) or not math.isfinite(target_y):
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("分集原文位置必须是有效的画布坐标") from None
    title = str(params.get("title") or "独立原文").strip()[:120] or "独立原文"
    source_node_id = f"source_independent_{uuid.uuid4().hex[:12]}"
    node = {
        "id": source_node_id,
        "type": "source.text",
        "position": {"x": target_x, "y": target_y},
        "data": {
            "title": title,
            "sourceText": "",
            "summary": "",
            "status": "draft",
            "sourceMode": "independent",
            "episodeId": episode_id,
            "cardState": {"state": "draft", "scriptState": "draft"},
        },
        "status": "draft",
    }
    context = get_canvas_context_v4(project_id, episode_id)
    if context["canvasKind"] != "custom" and not context["autoWorkflowInitialized"]:
        raise ValueError("请先完成当前画布的自动初始化，或在自定义画布创建独立原文")
    _ensure_saved_workflow_node_contract(node)
    result = write_canvas_records_v4(
        project_id, episode_id, nodes=[node], op_type="structure_patch", create_only=True,
    )
    _touch_project_meta(project_id)
    return {
        **result,
        "episodeId": episode_id,
        "sourceNodeId": source_node_id,
        "node": node,
        "projectChanged": True,
        "focusTarget": {"section": "episode", "episodeId": episode_id, "nodeId": source_node_id},
    }


def apply_independent_source_workflow(
    project_id: str,
    episode_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return _apply_source_segments(project_id, episode_id, payload, independent=True)




__all__ = (
    "_source_split_chain_rows",
    "_source_split_is_explicit_user_lock",
    "_source_split_segment_mapping",
    "_source_split_script_nodes",
    "_source_split_set_script_text",
    "_source_split_reset_node_data",
    "_source_split_clone_chain",
    "adjust_source_split_workflow",
    "create_independent_source_card",
    "apply_independent_source_workflow",
    "_translate_workflow_layout",
    "create_manual_workflow_chain",
)
