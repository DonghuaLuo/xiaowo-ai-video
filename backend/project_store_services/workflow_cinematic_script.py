# -*- coding: utf-8 -*-
"""工作流领域实际实现。"""
from __future__ import annotations

from typing import Any

from utils.cinematic_script_context import load_episode_sample

from .canvas_store_mutations import write_canvas_card_records_v4
from .canvas_store_queries import read_workflow_card_neighborhood_v4
from .canvas_store_queries import read_canvas_card_record_v4
from .canvas_store_queries import read_previous_cinematic_script_text_v4
from .canvas_ownership import work_chain_origin
from .director_plan_contract import _normalize_multiline_text
from .projects import _find_template
from .projects import _touch_project_meta
from .planning_contract import _is_user_locked_item
from .settings_loaders import load_script_adaptation_templates
from .source_text_store import _compact_text
from .store_core import _JSON_WRITE_LOCK
from .store_core import _now
from .storyboard_prompt_content import _storyboard_source_fact_text_from_data
from .workflow_contract import _workflow_node
from .workflow_contract import _workflow_node_type_value
from .workflow_edit_history import record_workflow_node_edit_history
from .work_chain_context import script_narrative_mode
import copy
import hashlib
import re
import traceback


def _script_adaptation_template_summary(template: dict[str, Any] | None) -> dict[str, str]:
    row = template if isinstance(template, dict) else {}
    template_id = str(row.get("id") or "").strip()
    name = str(row.get("name") or row.get("label") or template_id).strip()
    description = str(row.get("desc") or row.get("description") or "").strip()
    result: dict[str, str] = {}
    if template_id:
        result["id"] = template_id
    if name:
        result["label"] = name
        result["name"] = name
    if description:
        result["description"] = description
    return result


def _workflow_script_story_text_hash(*values: Any) -> str:
    normalized = "\n".join(
        re.sub(r"\s+", " ", str(value or "").replace("@", "").replace("＠", "")).strip()
        for value in values
    ).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cinematic_script_context_hash(value: Any) -> str:
    return hashlib.sha256(_normalize_multiline_text(value).encode("utf-8")).hexdigest()


def _script_card_generation_state(data: dict[str, Any]) -> dict[str, Any]:
    """只比较生成输入和已有剧本；进度、布局及其他卡片字段不构成编辑冲突。"""
    keys = (
        "sourceFactText", "source_fact_text", "cinematicStoryText", "cinematic_story_text",
        "scriptManualEdited", "script_manual_edited", "scriptGeneratedAt", "scriptStoryTextHash",
        "scriptTemplateId", "narrativeMode",
        "scriptUserInstruction", "script_user_instruction",
    )
    return {
        location: {key: copy.deepcopy(source[key]) for key in keys if key in source}
        for location, source in [
            ("data", data),
            *((key, data[key] if isinstance(data.get(key), dict) else {}) for key in ("prompt", "storyboardTaskCard", "cardState")),
        ]
    }


class _CinematicScriptWriter:
    """保存智能体提交的剧本，并检查读取版本与当前节点是否一致。"""

    def __init__(self, project_id, episode_id, payload):
        self.project_id = project_id
        self.episode_id = episode_id
        self.payload = payload

    def _load_script_context(self):
        if not self.episode_id:
            raise ValueError("缺少 episodeId")
        self.payload = self.payload if isinstance(self.payload, dict) else {}
        self.node_id = str(self.payload.get("nodeId") or self.payload.get("node_id") or "").strip()
        if not self.node_id:
            raise ValueError("缺少 nodeId")
        self.workflow = read_workflow_card_neighborhood_v4(self.project_id, self.episode_id, self.node_id, detail="full")
        self.node = _workflow_node(self.workflow, self.node_id)
        if not self.node:
            raise ValueError("未找到片段剧本")
        node_type = _workflow_node_type_value(self.node)
        if node_type != "prompt.storyboard":
            raise ValueError("只有片段剧本支持生成影视化剧本")
        data = self.node.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            self.node["data"] = data
        self.source_fact_text = _storyboard_source_fact_text_from_data(data)
        self.narrative_mode = script_narrative_mode(data)
        if not self.source_fact_text:
            raise ValueError("当前任务缺少片段原文内容，不能生成影视化剧本")

        script_templates = load_script_adaptation_templates()
        script_template_id = (
            str(self.payload.get("scriptTemplateId") or "").strip()
            or str(data.get("scriptTemplateId") or "").strip()
            or "faithful_cinematic"
        )
        self.script_template = _find_template(script_template_id, script_templates) or _find_template("faithful_cinematic", script_templates)
        if not self.script_template:
            raise ValueError("片段剧本策略模板不存在")
        user_instruction_explicit = False
        user_instruction_value: Any = ""
        for key in ("userInstruction", "user_instruction", "instruction"):
            if key in self.payload:
                user_instruction_explicit = True
                user_instruction_value = self.payload.get(key)
                break
        if not user_instruction_explicit:
            user_instruction_value = (
                data.get("scriptUserInstruction")
                or data.get("script_user_instruction")
                or ""
            )
        self.user_instruction = _normalize_multiline_text(user_instruction_value)
        self.initial_card_state = _script_card_generation_state(data)
        chain = next((item for item in self.workflow.get("workChains", []) if item.get("id") == self.node.get("workChainId")), None)
        origin = work_chain_origin(chain, self.workflow) if chain else {}
        self.independent_source_id = origin.get("sourceNodeId") if origin.get("kind") == "independent_source" else None

    def _load_input_sample(self):
        if not self.independent_source_id:
            return load_episode_sample(
                self.project_id, self.episode_id, self.source_fact_text, self.user_instruction,
                script_template_id=self.script_template["id"],
            )
        source = read_canvas_card_record_v4(self.project_id, self.episode_id, self.independent_source_id, detail="full")
        source_data = source.get("data") or {}
        if source.get("type") != "source.text" or source_data.get("sourceMode") != "independent":
            raise ValueError("独立原文不存在或来源已改变")
        text = _normalize_multiline_text(source_data.get("sourceText"))
        fragment = _normalize_multiline_text(self.source_fact_text)
        if not text or not fragment or fragment not in text:
            raise ValueError("当前剧情片段与独立原文不一致，请重新应用原文后生成")
        return {
            "contextKind": "independent_source",
            "novelExcerpt": text,
            "fragmentText": fragment,
            "scriptTemplateId": self.script_template["id"],
            "userInstruction": self.user_instruction,
        }, []

    def _commit_script(self):
        story_text_hash = _workflow_script_story_text_hash(self.cinematic_story_text or self.source_fact_text)
        self.adaptation_style = _script_adaptation_template_summary(self.script_template)
        script_result = {
            "cinematicStoryText": self.cinematic_story_text,
            "scriptStoryTextHash": story_text_hash,
            "scriptManualEdited": False,
            "script_manual_edited": False,
        }
        data_update = {
            **script_result,
            "scriptDeliveryContract": copy.deepcopy(getattr(self, "script_delivery_contract", None)),
            "narrativeMode": getattr(self, "narrative_mode", "drama"),
            "scriptTemplateId": self.script_template["id"],
            "scriptTemplateLabel": self.script_template.get("name") or self.script_template["id"],
            "status": "ready", "summary": _compact_text(self.cinematic_story_text, 160),
            "prompt": copy.deepcopy(script_result),
            "storyboardTaskCard": {**copy.deepcopy(script_result), "state": "ready", "scriptState": "ready"},
            "adaptationStyle": copy.deepcopy(self.adaptation_style),
            "scriptGeneratedAt": _now(),
            "scriptGenerationMeta": {**copy.deepcopy(self.model_meta), "scriptTemplate": copy.deepcopy(self.adaptation_style)},
        }
        if getattr(self, "persist_user_instruction", False):
            data_update["scriptUserInstruction"] = self.user_instruction
        if hasattr(self, "expected_previous_script"):
            data_update["scriptGenerationMeta"]["continuity"] = {
                "previousScriptHash": cinematic_script_context_hash(self.expected_previous_script),
                "generatedScriptHash": cinematic_script_context_hash(self.cinematic_story_text),
            }
        with _JSON_WRITE_LOCK:
            self.workflow = read_workflow_card_neighborhood_v4(self.project_id, self.episode_id, self.node_id, detail="full")
            latest_node = _workflow_node(self.workflow, self.node_id)
            if not latest_node:
                raise ValueError("未找到片段剧本")
            if _workflow_node_type_value(latest_node) != "prompt.storyboard":
                raise ValueError("只有片段剧本支持生成影视化剧本")
            if hasattr(self, "expected_previous_script"):
                previous = read_previous_cinematic_script_text_v4(
                    self.project_id, self.episode_id, str(latest_node.get("workChainId") or ""),
                ) if latest_node.get("workChainId") else ""
                if _normalize_multiline_text(previous) != self.expected_previous_script:
                    raise ValueError("生成期间前一片段剧本已改变，请重新读取连续性上下文。")
            updates = [{"id": self.node_id}]

            def merge_result(stored_node):
                if stored_node["id"] == self.node_id:
                    return self._merge_current_script(stored_node, data_update)

            self.save_result = write_canvas_card_records_v4(
                self.project_id, self.episode_id, updates,
                op_type="result_commit", changed_resources=["canvas_node"],
                data_transform=merge_result,
            )
            _touch_project_meta(self.project_id)
            self.workflow["version"] = self.save_result.get("workflowVersion") or self.workflow.get("version")
            self.node = self.save_result["nodes"][0]
            self.patched_nodes = self.save_result["nodes"]

    def _merge_current_script(self, stored_node, data_update):
        # 此回调由画布存储在 SQLite 写锁内执行，避免读取后又被其他编辑覆盖。
        if _workflow_node_type_value(stored_node) != "prompt.storyboard":
            raise ValueError("生成期间卡片类型已改变，本次剧本未保存，请重新生成。")
        if _is_user_locked_item(stored_node):
            raise ValueError("片段剧本节点已由用户锁定，本次剧本未保存")
        data = stored_node.get("data") or {}
        if _script_card_generation_state(data) != self.initial_card_state:
            raise ValueError("生成期间原文片段、创作设置或剧本已被修改，本次剧本未保存，请重新生成。")
        if hasattr(self, "expected_asset_refs") and data.get("assetRefs") != self.expected_asset_refs:
            raise ValueError("生成期间片段关联资产已改变，本次剧本未保存，请重新读取上下文。")
        if hasattr(self, "expected_asset_bindings") and (data.get("assetBindings") or []) != self.expected_asset_bindings:
            raise ValueError("生成期间片段资产绑定已改变，本次剧本未保存，请重新读取上下文。")
        try:
            current_sample, current_episodes = self._load_input_sample()
        except (ValueError, OSError) as exc:
            raise ValueError("生成期间小说上下文已改变或无法读取，本次剧本未保存，请重新生成。") from exc
        if current_sample != self.input_sample or current_episodes != self.context_episodes:
            raise ValueError("生成期间小说上下文已改变，本次剧本未保存，请重新生成。")
        data.pop("recommendedDirectorRuleId", None)
        for key, value in data_update.items():
            data[key] = (
                {**data[key], **copy.deepcopy(value)}
                if key != "scriptDeliveryContract" and isinstance(data.get(key), dict) and isinstance(value, dict)
                else copy.deepcopy(value)
            )
        return data

    def _record_history_and_respond(self):
        from .workflow_production_sync import sync_workflow_production_after_commit

        history_result: dict[str, Any] = {"success": True, "skipped": True}
        history_items: list[dict[str, Any]] = []
        history_warnings: list[str] = []
        for patched_node in self.patched_nodes:
            try:
                history_result = record_workflow_node_edit_history(
                    self.project_id,
                    self.episode_id,
                    patched_node,
                    reason="cinematic_script_generated",
                )
                if isinstance(history_result, dict) and isinstance(history_result.get("item"), dict):
                    history_items.append(copy.deepcopy(history_result["item"]))
            except Exception as exc:
                print(traceback.format_exc(), flush=True)
                history_warnings.append(str(exc))
        changed_resources = [
            "canvas_node",
            *(
                ["node_edit_history"]
                if history_items
                else []
            ),
        ]
        result = {
            "success": True,
            "episodeId": self.episode_id,
            "nodeId": self.node_id,
            "node": copy.deepcopy(self.node),
            "nodes": self.patched_nodes,
            "editHistory": history_items[0] if history_items else None,
            "editHistoryItems": history_items,
            "editHistoryWarning": "；".join(item for item in history_warnings if item),
            "cinematicStoryText": self.cinematic_story_text,
            "scriptTemplate": self.adaptation_style,
            "txId": self.save_result.get("txId"),
            "seq": self.save_result.get("seq"),
            "revision": self.save_result.get("revision"),
            "opType": self.save_result.get("opType"),
            "records": self.save_result.get("records"),
            "workflowVersion": self.workflow.get("version"),
            "changedResources": changed_resources,
            "focusTarget": {"section": "episode", "episodeId": self.episode_id, "nodeId": self.node_id},
            "projectChanged": True,
        }
        return sync_workflow_production_after_commit(self.project_id, self.episode_id, result)
