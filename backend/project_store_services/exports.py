# -*- coding: utf-8 -*-
"""项目规划导出、剪映指南、路线质量报告和项目目录复制。"""

from __future__ import annotations
from .canvas_ownership import is_video_task_type

import base64
import copy
import hashlib
import json
import random
import re
import shutil
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.agent_context import (
    AGENT_CONTEXT_MESSAGE_TEXT_LIMIT,
    AGENT_CONTEXT_RECENT_WINDOW,
    AGENT_CONTEXT_SUMMARY_CHARS,
    build_agent_conversation_context,
)
from utils import agent_sdk_runtime
from utils.agent_session_service import AgentSessionService
from utils.aspect_size import (
    IMAGE_TIER_SHORT_EDGE,
    VIDEO_TIER_SHORT_EDGE,
    aspect_size,
    parse_aspect_ratio,
    resolution_to_short_edge,
)
from utils.image_pipeline import (
    convert_image_bytes_to_png,
    data_url_from_bytes,
    prepare_provider_image_bytes,
    prepare_provider_image_data_uri,
    save_project_image,
    save_provider_output_image,
)
from utils.media_backends import (
    cancel_video_media_job,
    endpoint_supports_media_generation,
    infer_model_endpoint,
    media_endpoint_type,
    normalize_media_endpoint,
    generate_image_media,
    generate_video_media,
    poll_video_media_job,
    provider_supports_media_generation,
    submit_video_media_job,
)

from .workflow_projection import _workflow_versions_path
from .task_control import create_task
from .task_storage import _load_tasks_for_project  # noqa: F401,F403
from .canvas_store_queries import read_episode_card_results

from .store_core import _now
from .store_core import _read_json
from .store_core import _write_json

def _export_episode_rows(project_id: str, episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from .workflow_projection import get_canvas_workflow_projection
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        episode_id = str(episode.get("id") or "").strip()
        if not episode_id:
            continue
        workflow = get_canvas_workflow_projection(project_id, episode_id)
        versions = read_episode_card_results(project_id, episode_id)
        workflow_versions = _read_json(_workflow_versions_path(project_id, episode_id), [])
        if not isinstance(workflow_versions, list):
            workflow_versions = []
        rows.append(
            {
                "episode": episode,
                "workflow": workflow,
                "versions": versions,
                "workflowVersions": workflow_versions,
            }
        )
    return rows


def _has_export_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _first_export_value(*values: Any) -> Any | None:
    for value in values:
        if _has_export_value(value):
            return value
    return None


def _mapping_export_value(mapping: Any, keys: list[str]) -> Any | None:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if _has_export_value(value):
            return value
    return None


def _node_export_context(episode_id: str, node: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    return {
        "episodeId": episode_id,
        "nodeId": str(node.get("id") or data.get("nodeId") or ""),
        "nodeType": str(node.get("type") or data.get("type") or ""),
        "routeId": _first_export_value(node.get("routeId"), data.get("routeId")),
        "segmentId": _first_export_value(node.get("segmentId"), data.get("segmentId")),
        "strategy": _first_export_value(node.get("strategy"), data.get("strategy")),
        "title": _first_export_value(data.get("title"), node.get("title")),
    }


def _append_node_plan_entry(items: list[dict[str, Any]], context: dict[str, Any], key: str, value: Any) -> None:
    if not _has_export_value(value):
        return
    entry = {**context, key: copy.deepcopy(value)}
    items.append({item_key: item_value for item_key, item_value in entry.items() if _has_export_value(item_value)})


def _collect_asset_definition_exports(assets: dict[str, Any]) -> list[dict[str, Any]]:
    from .assets import _default_asset_design_prompt
    rows: list[dict[str, Any]] = []
    for asset_type in ["characters", "creatures", "scenes", "props", "styles"]:
        for asset in assets.get(asset_type) or []:
            if not isinstance(asset, dict):
                continue
            desc = str(asset.get("desc") or asset.get("description") or "").strip()
            design_prompt = _default_asset_design_prompt(asset_type, asset)
            voice_style = (
                str(asset.get("voiceStyle") or asset.get("voice_style") or "").strip()
                if asset_type in {"characters", "creatures"}
                else ""
            )
            if not any(_has_export_value(value) for value in [desc, design_prompt, voice_style]):
                continue
            rows.append(
                {
                    "assetType": asset_type,
                    "assetId": asset.get("id"),
                    "name": _first_export_value(asset.get("name"), asset.get("title")),
                    "desc": desc,
                    "prompts": {"assetImagePrompt": design_prompt} if design_prompt else {},
                    "voiceStyle": voice_style,
                }
            )
    return [
        {key: value for key, value in row.items() if _has_export_value(value)}
        for row in rows
    ]


def _route_quality_issue(
    severity: str,
    category: str,
    message: str,
    *,
    node_id: str = "",
    node_type: str = "",
) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "severity": severity,
            "category": category,
            "message": message,
            "nodeId": node_id,
            "nodeType": node_type,
        }.items()
        if _has_export_value(value)
    }


def _generation_models_from_config(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    models: dict[str, Any] = {}
    for media_type in ("image", "video"):
        section = value.get(media_type) if isinstance(value.get(media_type), dict) else value
        if not isinstance(section, dict):
            continue
        model_id = section.get("modelId") or section.get("model_id")
        provider = (
            section.get("providerId")
            or section.get("provider_id")
            or section.get("preferredProvider")
            or section.get("provider")
        )
        if model_id or provider:
            models[media_type] = {
                key: item
                for key, item in {
                    "modelId": model_id,
                    "provider": provider,
                    "resolution": section.get("resolution") or section.get("size"),
                    "durationSeconds": section.get("durationSeconds") or section.get("duration_seconds"),
                }.items()
                if _has_export_value(item)
            }
    return models


def _route_quality_reports(episode_id: str, workflow: dict[str, Any]) -> list[dict[str, Any]]:
    from .splitting_templates import _string_list
    reports: dict[str, dict[str, Any]] = {}
    for route in workflow.get("routes") or []:
        if not isinstance(route, dict):
            continue
        route_id = str(route.get("id") or route.get("routeId") or "").strip()
        if not route_id:
            continue
        reports[route_id] = {
            "episodeId": episode_id,
            "routeId": route_id,
            "segmentId": route.get("segmentId"),
            "label": route.get("label"),
            "strategy": route.get("strategy"),
            "status": "ready",
            "nodeCount": 0,
            "runnableNodeCount": 0,
            "strategies": [],
            "models": {},
            "issues": [],
        }

    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        route_id = str(node.get("routeId") or data.get("routeId") or "").strip()
        if not route_id:
            continue
        report = reports.setdefault(
            route_id,
            {
                "episodeId": episode_id,
                "routeId": route_id,
                "status": "ready",
                "nodeCount": 0,
                "runnableNodeCount": 0,
                "strategies": [],
                "models": {},
                "issues": [],
            },
        )
        node_id = str(node.get("id") or data.get("nodeId") or "")
        node_type = str(node.get("type") or data.get("type") or "")
        strategy = str(node.get("strategy") or data.get("strategy") or "").strip()
        report["nodeCount"] = int(report.get("nodeCount") or 0) + 1
        if strategy and strategy not in report["strategies"]:
            report["strategies"].append(strategy)
        task_node_owns_generation_config = node_type == "prompt.storyboard" or is_video_task_type(node_type)
        if task_node_owns_generation_config:
            report["runnableNodeCount"] = int(report.get("runnableNodeCount") or 0) + 1

        generation_config = data.get("generationConfig")
        resolved_config = data.get("resolvedConfig")
        if task_node_owns_generation_config:
            models = _generation_models_from_config(generation_config)
            for media_type, model_data in models.items():
                if media_type not in report["models"]:
                    report["models"][media_type] = model_data

        quality = data.get("quality") if isinstance(data.get("quality"), dict) else {}
        preflight = quality.get("modelPreflight") if isinstance(quality.get("modelPreflight"), dict) else {}
        for item in preflight.get("blockingIssues") or []:
            report["issues"].append(
                _route_quality_issue("blocking", "model_capability", str(item), node_id=node_id, node_type=node_type)
            )
        for item in preflight.get("warnings") or []:
            report["issues"].append(
                _route_quality_issue("warning", "model_capability", str(item), node_id=node_id, node_type=node_type)
            )

        if task_node_owns_generation_config and not _has_export_value(data.get("assetRefs")):
            report["issues"].append(
                _route_quality_issue("warning", "asset_refs", "缺少角色/生物/场景/道具资产引用", node_id=node_id, node_type=node_type)
            )
        if is_video_task_type(node_type):
            reference_ids = _string_list(
                data.get("referenceMediaIds")
                or (
                    generation_config.get("referenceMediaIds")
                    if isinstance(generation_config, dict)
                    else []
                )
            )
            if strategy == "storyboard_multi_shot" and not reference_ids:
                report["issues"].append(
                    _route_quality_issue("warning", "reference_plan", "建议绑定故事版分镜图参考", node_id=node_id, node_type=node_type)
                )
            if not _has_export_value(data.get("audioPlan")):
                report["issues"].append(
                    _route_quality_issue("warning", "audio_plan", "缺少音频/旁白/后期边界计划", node_id=node_id, node_type=node_type)
                )

    normalized: list[dict[str, Any]] = []
    for report in reports.values():
        issues = report.get("issues") if isinstance(report.get("issues"), list) else []
        blocking_count = sum(1 for item in issues if isinstance(item, dict) and item.get("severity") == "blocking")
        warning_count = sum(1 for item in issues if isinstance(item, dict) and item.get("severity") == "warning")
        report["blockingIssueCount"] = blocking_count
        report["warningCount"] = warning_count
        report["status"] = "blocking" if blocking_count else ("warning" if warning_count else "ready")
        normalized.append({key: value for key, value in report.items() if _has_export_value(value)})
    return normalized


def _route_comparison_groups(route_quality: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for route in route_quality:
        episode_id = str(route.get("episodeId") or "")
        segment_id = str(route.get("segmentId") or "unassigned")
        group_id = f"{episode_id}:{segment_id}"
        group = groups.setdefault(
            group_id,
            {
                "episodeId": episode_id,
                "segmentId": segment_id,
                "candidates": [],
            },
        )
        group["candidates"].append(
            {
                key: value
                for key, value in {
                    "routeId": route.get("routeId"),
                    "label": route.get("label"),
                    "strategy": route.get("strategy") or route.get("strategies"),
                    "status": route.get("status"),
                    "models": copy.deepcopy(route.get("models")),
                    "blockingIssueCount": route.get("blockingIssueCount"),
                    "warningCount": route.get("warningCount"),
                }.items()
                if _has_export_value(value)
            }
        )
    return [
        group
        for group in groups.values()
        if len(group.get("candidates") or []) > 1
    ]


def _project_planning_export_bundle(
    project_id: str,
    episode_rows: list[dict[str, Any]],
    assets: dict[str, Any],
) -> dict[str, Any]:
    from .episode_plan_documents import _planning_episode_boundary_export
    from .agent_sessions import _project_dir
    project_dir = _project_dir(project_id)
    story_world = _read_json(project_dir / "story_world.json", {})
    boundary_plan = _planning_episode_boundary_export(project_id)
    work_chain_plans: dict[str, Any] = {}
    workflow_routes: list[dict[str, Any]] = []
    dialogue_tracks: list[dict[str, Any]] = []
    audio_plans: list[dict[str, Any]] = []
    subtitle_drafts: list[dict[str, Any]] = []
    narration_drafts: list[dict[str, Any]] = []
    bgm_advice: list[dict[str, Any]] = []
    jianying_notes: list[dict[str, Any]] = []
    post_production_notes: list[dict[str, Any]] = []
    generation_configs: list[dict[str, Any]] = []
    route_quality: list[dict[str, Any]] = []

    for row in episode_rows:
        episode = row.get("episode") if isinstance(row.get("episode"), dict) else {}
        episode_id = str(episode.get("id") or "").strip()
        if not episode_id:
            continue
        work_chain_plan = _read_json(project_dir / "episodes" / episode_id / "work_chain_plan.json", {})
        if _has_export_value(work_chain_plan):
            work_chain_plans[episode_id] = work_chain_plan
        workflow = row.get("workflow") if isinstance(row.get("workflow"), dict) else {}
        route_quality.extend(_route_quality_reports(episode_id, workflow))
        for route in workflow.get("routes") or []:
            if not isinstance(route, dict):
                continue
            route_row = copy.deepcopy(route)
            route_row["episodeId"] = episode_id
            route_row["routeId"] = route_row.get("routeId") or route_row.get("id")
            workflow_routes.append(
                {key: value for key, value in route_row.items() if _has_export_value(value)}
            )
        for node in workflow.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            context = _node_export_context(episode_id, node, data)
            audio_plan = data.get("audioPlan")
            post_production = data.get("postProduction")
            screenplay = data.get("screenplay")
            generation_config = data.get("generationConfig")
            resolved_config = data.get("resolvedConfig")
            node_type = str(node.get("type") or data.get("eyebrow") or "").strip()
            task_node_owns_generation_config = node_type == "prompt.storyboard" or is_video_task_type(node_type)
            _append_node_plan_entry(dialogue_tracks, context, "dialogue", data.get("dialogue"))
            if _has_export_value(audio_plan):
                audio_entry = {
                    **context,
                    "audioPlan": copy.deepcopy(audio_plan),
                    "nativeAudioStrategy": _mapping_export_value(
                        audio_plan,
                        ["nativeAudioStrategy", "nativeAudio", "audioStrategy", "providerAudio"],
                    ),
                    "ambient": _mapping_export_value(audio_plan, ["ambient", "ambience", "atmosphere"]),
                    "foley": _mapping_export_value(audio_plan, ["foley", "soundEffects", "sfx"]),
                }
                audio_plans.append(
                    {key: value for key, value in audio_entry.items() if _has_export_value(value)}
                )
            subtitle_value = _first_export_value(
                _mapping_export_value(audio_plan, ["subtitleDraft", "subtitles", "subtitleText", "subtitle"]),
                _mapping_export_value(post_production, ["subtitleDraft", "subtitles", "subtitleText", "subtitle"]),
            )
            narration_value = _first_export_value(
                _mapping_export_value(audio_plan, ["narrationDraft", "narration", "voiceover", "voiceOver"]),
                _mapping_export_value(post_production, ["narrationDraft", "narration", "voiceover", "voiceOver"]),
                _mapping_export_value(screenplay, ["narrationDraft", "narration", "voiceover", "voiceOver"]),
            )
            bgm_value = _first_export_value(
                _mapping_export_value(audio_plan, ["bgmAdvice", "bgm", "musicAdvice", "music", "score"]),
                _mapping_export_value(post_production, ["bgmAdvice", "bgm", "musicAdvice", "music", "score"]),
            )
            jianying_value = _first_export_value(
                _mapping_export_value(post_production, ["jianyingNotes", "jianying", "editingNotes", "cutNotes", "timelineNotes"]),
                _mapping_export_value(audio_plan, ["jianyingNotes", "jianying", "editingNotes", "cutNotes", "timelineNotes"]),
            )
            _append_node_plan_entry(subtitle_drafts, context, "subtitleDraft", subtitle_value)
            _append_node_plan_entry(narration_drafts, context, "narrationDraft", narration_value)
            _append_node_plan_entry(bgm_advice, context, "bgmAdvice", bgm_value)
            _append_node_plan_entry(jianying_notes, context, "jianyingNotes", jianying_value)
            _append_node_plan_entry(post_production_notes, context, "postProduction", post_production)
            if task_node_owns_generation_config and (
                _has_export_value(generation_config) or _has_export_value(resolved_config)
            ):
                generation_configs.append(
                    {
                        key: value
                        for key, value in {
                            **context,
                            "generationConfig": copy.deepcopy(generation_config),
                            "resolvedConfig": copy.deepcopy(resolved_config),
                        }.items()
                        if _has_export_value(value)
                    }
                )

    return {
        "storyWorld": story_world if _has_export_value(story_world) else {},
        "episodeBoundaryPlan": boundary_plan if _has_export_value(boundary_plan) else {},
        "workChainPlans": work_chain_plans,
        "workflowRoutes": workflow_routes,
        "assetDefinitions": _collect_asset_definition_exports(assets),
        "dialogueTracks": dialogue_tracks,
        "audioPlans": audio_plans,
        "subtitleDrafts": subtitle_drafts,
        "narrationDrafts": narration_drafts,
        "bgmAdvice": bgm_advice,
        "jianyingNotes": jianying_notes,
        "postProductionNotes": post_production_notes,
        "generationConfigs": generation_configs,
        "routeQuality": route_quality,
        "routeComparison": _route_comparison_groups(route_quality),
    }


def _jianying_cut_guide(manifest: dict[str, Any]) -> str:
    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    return "\n".join(
        [
            f"# {project.get('title') or project.get('name') or manifest.get('projectId') or 'ai-video 项目'} 剪映编辑素材包",
            "",
            "这个导出包用于把 ai-video 生成的小说拆分、角色、生物、场景、道具、分镜和视频任务索引带到剪映里继续人工编辑。",
            "",
            "## 文件说明",
            "",
            "- `manifest.json`：完整导出清单，包含项目、素材、分集、工作流、版本和任务摘要。",
            "- `assets.json`：角色、生物、场景、道具和风格资产。",
            "- `episodes.json`：分集、工作流节点、分镜版本和视频版本索引。",
            "- `planning.json`：世界观、分集边界、镜头计划、路线、对白、音频和剪映备注。",
            "- `sources.json`：源小说文件索引。",
            "- `tasks.json`：生成任务历史，便于回看图片/视频生成状态。",
            "",
            "## 建议流程",
            "",
            "1. 在 ai-video 中确认角色、生物、场景、道具和分镜图/视频版本。",
            "2. 打开剪映，新建项目。",
            "3. 先参考 `planning.json` 的路线、对白、字幕、旁白、BGM 和环境音建议搭建粗剪时间线。",
            "4. 根据 `episodes.json` 逐集导入对应图片、视频素材，并参考分镜标题、摘要和提示词排布时间线。",
            "5. 在剪映内补字幕、音频、转场和最终剪辑。",
            "",
            "## 导出统计",
            "",
            f"- 角色：{counts.get('characters', 0)}",
            f"- 生物：{counts.get('creatures', 0)}",
            f"- 场景：{counts.get('scenes', 0)}",
            f"- 道具：{counts.get('props', 0)}",
            f"- 分集：{counts.get('episodes', 0)}",
            f"- 路线：{counts.get('routes', 0)}",
            f"- 画布版本：{counts.get('workflowVersions', 0)}",
            f"- 对白段：{counts.get('dialogueTracks', 0)}",
            f"- 音频计划：{counts.get('audioPlans', 0)}",
            f"- 任务：{counts.get('tasks', 0)}",
            "",
        ]
    )


def export_project_assets(project_id: str, scopes: list[str]) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    from .agent_sessions import _project_meta_path
    from .projects import _project_row
    from .task_control import _update_task_fields
    from .assets import list_assets
    from .source_text_store import list_sources
    normalized_scopes = [str(item).strip() for item in scopes if str(item).strip()]
    if not normalized_scopes:
        normalized_scopes = ["overview", "sources", "characters", "creatures", "scenes", "props", "episodes", "storyboard", "tasks"]
    task = create_task("export", project_id=project_id, message="剪映编辑素材包已导出。")
    export_dir = _project_dir(project_id) / "exports" / task["id"]
    export_dir.mkdir(parents=True, exist_ok=True)
    meta = _read_json(_project_meta_path(project_id), {})
    project = _project_row(project_id, meta if isinstance(meta, dict) else {})
    assets = list_assets("project", project_id, hydrate=True)
    sources = list_sources(project_id).get("sources") if "sources" in normalized_scopes else []
    episodes = project.get("episodes") if isinstance(project.get("episodes"), list) else []
    episode_rows = _export_episode_rows(project_id, episodes) if {"episodes", "storyboard"} & set(normalized_scopes) else []
    tasks = _load_tasks_for_project(project_id) if "tasks" in normalized_scopes else []
    tasks = [
        task_row
        for task_row in (tasks if isinstance(tasks, list) else [])
        if isinstance(task_row, dict) and str(task_row.get("projectId") or "") == project_id
    ]
    planning = _project_planning_export_bundle(project_id, episode_rows, assets)
    manifest = {
        "projectId": project_id,
        "createdAt": _now(),
        "format": "ai-video-jianying-edit-package",
        "scopes": normalized_scopes,
        "project": project,
        "sources": sources if isinstance(sources, list) else [],
        "assets": {
            key: value
            for key, value in assets.items()
            if key in {"characters", "creatures", "scenes", "props", "styles"} and isinstance(value, list)
        },
        "episodes": episode_rows,
        "planning": planning,
        "tasks": tasks,
        "counts": {
            "characters": len(assets.get("characters") or []),
            "creatures": len(assets.get("creatures") or []),
            "scenes": len(assets.get("scenes") or []),
            "props": len(assets.get("props") or []),
            "episodes": len(episode_rows),
            "routes": len(planning.get("workflowRoutes") or []),
            "workflowVersions": sum(len(row.get("workflowVersions") or []) for row in episode_rows),
            "dialogueTracks": len(planning.get("dialogueTracks") or []),
            "audioPlans": len(planning.get("audioPlans") or []),
            "tasks": len(tasks),
        },
    }
    _write_json(export_dir / "manifest.json", manifest)
    _write_json(export_dir / "assets.json", manifest["assets"])
    _write_json(export_dir / "episodes.json", episode_rows)
    _write_json(export_dir / "planning.json", planning)
    _write_json(export_dir / "sources.json", manifest["sources"])
    _write_json(export_dir / "tasks.json", tasks)
    guide_path = export_dir / "jianying-cut-guide.md"
    with guide_path.open("w", encoding="utf-8", newline="\n") as fp:
        fp.write(_jianying_cut_guide(manifest))
    files = [
        "manifest.json",
        "assets.json",
        "episodes.json",
        "planning.json",
        "sources.json",
        "tasks.json",
        "jianying-cut-guide.md",
    ]
    updated_task = _update_task_fields(
        task["id"],
        message="剪映编辑素材包已导出。",
        exportDir=str(export_dir),
        exportFiles=files,
    ) or task
    return {"success": True, "task": updated_task, "exportDir": str(export_dir), "files": files, "manifest": manifest}
def copy_project_tree(project_id: str, target_dir: str) -> dict[str, Any]:
    from .agent_sessions import _project_dir
    source = _project_dir(project_id)
    if not source.exists():
        raise FileNotFoundError("项目不存在")
    target = Path(target_dir)
    if target.exists():
        raise FileExistsError("目标目录已存在")
    shutil.copytree(source, target)
    return {"success": True, "path": str(target)}

__all__ = (
    '_export_episode_rows', '_has_export_value', '_first_export_value', '_mapping_export_value',
    '_node_export_context', '_append_node_plan_entry', '_collect_asset_definition_exports', '_route_quality_issue',
    '_generation_models_from_config', '_route_quality_reports', '_route_comparison_groups',
    '_project_planning_export_bundle', '_jianying_cut_guide', 'export_project_assets', 'copy_project_tree'
)
