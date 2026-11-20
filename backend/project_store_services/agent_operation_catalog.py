# -*- coding: utf-8 -*-
"""智能体待确认操作的结构化协议目录。

这个模块只保存后端协议字段，不承担用户自然语言意图识别。
"""

from __future__ import annotations

from typing import Any


AGENT_OPERATION_CATALOG: dict[str, dict[str, Any]] = {
    "asset_range": {
        "operationTypes": {"commit_asset_range"},
        "taskType": "asset_range_commit",
        "label": "需要确认",
        "title": "确认保存当前资产范围",
        "description": "回复“确认”后，我会保存当前资产范围。资产拆分需要另行发起。",
        "reply": "确认",
        "expectedNextTool": "commit_asset_range",
        "operationLabel": "资产范围提案",
        "staleReason": "当前会话的资产范围候选已变化、失效或已提交，需要重新读取资产范围资料并规划候选。",
        "interactionPolicy": {
            "canConfirm": True,
            "canCancel": True,
            "canExplain": True,
            "canRevise": True,
            "revisionMode": "fresh_proposal_with_current_user_instruction",
            "contextCarryPolicy": "current_user_instruction_only",
            "confirmTool": "commit_asset_range",
            "userReplyPolicy": "确认时提交当前提案；修改意见会取消当前待确认提案，并只携带本轮用户原话重新生成资产范围提案。",
        },
    },
    "episode_boundary": {
        "operationTypes": {"commit_episode_boundary"},
        "taskType": "episode_boundary_confirmation",
        "label": "需要确认",
        "title": "确认保存当前断点",
        "description": "回复“确认”后，我会把当前断点保存为下一集分集原文。",
        "reply": "确认",
        "expectedNextTool": "commit_episode_boundary",
        "operationLabel": "分集断点提案",
        "staleReason": "分集候选已变化或已提交，需要重新读取项目进度。",
        "interactionPolicy": {
            "canConfirm": True,
            "canCancel": True,
            "canExplain": True,
            "canRevise": True,
            "revisionMode": "fresh_proposal_with_current_user_instruction",
            "contextCarryPolicy": "current_instruction_and_pending_proposal",
            "confirmTool": "commit_episode_boundary",
            "userReplyPolicy": "确认时提交当前提案；修改意见连同当前待确认提案和会话上下文交给智能体修订，新提案仍需重新确认。",
        },
    },
    "plot_split": {
        "operationTypes": {"commit_plot_split"},
        "taskType": "work_chain_plan_save",
        "label": "需要确认",
        "title": "确认剧情拆分",
        "description": "回复“确认”后，我会按当前拆分结果创建工作链；片段剧本需在后续环节生成。如需调整，直接说明修改意见。",
        "reply": "确认",
        "expectedNextTool": "commit_plot_split",
        "operationLabel": "剧情拆分结果",
        "staleReason": "剧情拆分结果已失效，需要重新拆分。",
        "interactionPolicy": {
            "canConfirm": True,
            "canCancel": True,
            "canExplain": True,
            "canRevise": True,
            "revisionMode": "rerun_model_with_latest_result",
            "contextCarryPolicy": "latest_result_and_effective_revision_requirements",
            "confirmTool": "commit_plot_split",
            "userReplyPolicy": (
                "确认时提交 latestResult；修改时只携带上一轮拆分结果、本轮用户修改意见、"
                "已累计的有效修改要求和原文引用重新请求拆分模型。"
            ),
        },
    },
    "project_asset_cleanup": {
        "operationTypes": {"confirm_project_asset_cleanup", "project_asset_cleanup_confirm"},
        "taskType": "project_cleanup",
        "label": "需要确认",
        "title": "确认清空全部资产",
        "description": "点击此卡片的确认按钮后，清空当前项目全部已拆分资产和资产拆分记录。",
        "reply": "确认清空",
        "expectedNextTool": "delete_all_project_assets",
        "operationLabel": "清空项目资产确认",
        "staleReason": "项目资产或资产范围记录已变化，需要重新确认清空影响。",
        "highRisk": True,
        "interactionPolicy": {
            "canConfirm": True,
            "canCancel": True,
            "canExplain": True,
            "canRevise": False,
            "revisionMode": "never",
            "contextCarryPolicy": "strict_destructive_confirmation_only",
            "confirmTool": "delete_all_project_assets",
            "userReplyPolicy": "高风险删除只接受明确确认或取消，不接受泛化继续和修改重跑。",
        },
    },
    "latest_asset_range_delete": {
        "operationTypes": {"confirm_latest_asset_range_delete", "latest_asset_range_delete_confirm"},
        "taskType": "asset_range_delete_latest",
        "label": "需要确认",
        "title": "确认删除最新资产拆分",
        "description": "点击此卡片的确认按钮后，删除最新一组资产拆分，并把资产拆分游标回退到该组起点。",
        "reply": "确认删除",
        "expectedNextTool": "delete_latest_asset_range",
        "operationLabel": "删除最新资产拆分确认",
        "staleReason": "最新资产范围已变化，只能重新确认当前最新一组。",
        "highRisk": True,
        "interactionPolicy": {
            "canConfirm": True,
            "canCancel": True,
            "canExplain": True,
            "canRevise": False,
            "revisionMode": "never",
            "contextCarryPolicy": "strict_destructive_confirmation_only",
            "confirmTool": "delete_latest_asset_range",
            "userReplyPolicy": "高风险删除只接受明确确认或取消，不接受泛化继续和修改重跑。",
        },
    },
    "current_canvas_clear": {
        "operationTypes": {"confirm_current_canvas_clear", "current_canvas_clear_confirm"},
        "taskType": "project_cleanup",
        "label": "需要确认",
        "title": "确认清空当前集画布",
        "description": "点击此卡片的确认按钮后，删除该集画布和工作链派生结果，保留分集原文和项目资产。",
        "reply": "确认清空",
        "expectedNextTool": "delete_project_planning_outputs",
        "operationLabel": "清空当前集画布确认",
        "staleReason": "当前集画布清空确认已失效，需要重新确认影响。",
        "highRisk": True,
        "interactionPolicy": {
            "canConfirm": True,
            "canCancel": True,
            "canExplain": True,
            "canRevise": False,
            "revisionMode": "never",
            "contextCarryPolicy": "strict_destructive_confirmation_only",
            "confirmTool": "delete_project_planning_outputs",
            "userReplyPolicy": "高风险清空只接受明确确认或取消，不接受泛化继续和修改重跑。",
        },
    },
    "episode_source_delete": {
        "operationTypes": {"confirm_episode_source_delete", "episode_source_delete_confirm"},
        "taskType": "project_cleanup",
        "label": "需要确认",
        "title": "确认删除最新分集",
        "description": "点击此卡片的确认按钮后，删除该集分集原文和对应工作链画布数据，保留原始导入小说文本和项目资产。",
        "reply": "确认删除",
        "expectedNextTool": "delete_project_planning_outputs",
        "operationLabel": "删除最新分集确认",
        "staleReason": "分集原文范围已变化，需要重新确认当前最新分集。",
        "highRisk": True,
        "interactionPolicy": {
            "canConfirm": True,
            "canCancel": True,
            "canExplain": True,
            "canRevise": False,
            "revisionMode": "never",
            "contextCarryPolicy": "strict_destructive_confirmation_only",
            "confirmTool": "delete_project_planning_outputs",
            "userReplyPolicy": "高风险删除只接受明确确认或取消，不接受泛化继续和修改重跑。",
        },
    },
    "direct_asset_delete": {
        "operationTypes": {"confirm_direct_asset_delete"},
        "taskType": "project_cleanup",
        "label": "需要确认",
        "title": "确认删除资产",
        "description": "确认后才会删除指定资产。",
        "reply": "确认删除",
        "expectedNextTool": "delete_asset",
        "operationLabel": "删除资产确认",
        "staleReason": "资产已变化，请重新提出删除请求。",
        "highRisk": True,
        "interactionPolicy": {"canConfirm": True, "canCancel": True, "canExplain": True,
                              "canRevise": False, "confirmTool": "delete_asset"},
    },
    "direct_workflow_delete": {
        "operationTypes": {"confirm_direct_workflow_delete"},
        "taskType": "project_cleanup",
        "label": "需要确认",
        "title": "确认删除画布内容",
        "description": "确认后才会删除指定画布内容及其关联。",
        "reply": "确认删除",
        "expectedNextTool": "delete_workflow_node",
        "operationLabel": "删除画布内容确认",
        "staleReason": "画布已变化，请重新提出删除请求。",
        "highRisk": True,
        "interactionPolicy": {"canConfirm": True, "canCancel": True, "canExplain": True,
                              "canRevise": False, "confirmTool": "delete_workflow_node"},
    },
    "direct_workflow_unlink": {
        "operationTypes": {"confirm_direct_workflow_unlink"},
        "taskType": "project_cleanup",
        "label": "需要确认",
        "title": "确认移除画布输入关联",
        "description": "确认后才会移除指定输入关联。",
        "reply": "确认移除",
        "expectedNextTool": "unlink_workflow_input",
        "operationLabel": "移除画布输入关联确认",
        "staleReason": "画布已变化，请重新提出移除请求。",
        "highRisk": True,
        "interactionPolicy": {"canConfirm": True, "canCancel": True, "canExplain": True,
                              "canRevise": False, "confirmTool": "unlink_workflow_input"},
    },
}


def agent_operation_kind(operation_type_or_kind: str | None) -> str:
    value = str(operation_type_or_kind or "").strip()
    if not value:
        return ""
    if value in AGENT_OPERATION_CATALOG:
        return value
    for kind, config in AGENT_OPERATION_CATALOG.items():
        if value in config.get("operationTypes", set()):
            return kind
    return ""


def agent_operation_types(kind: str | None) -> set[str]:
    config = AGENT_OPERATION_CATALOG.get(str(kind or "").strip()) or {}
    values = config.get("operationTypes")
    return set(values) if isinstance(values, set) else set()


def agent_operation_task_type(operation_type_or_kind: str | None) -> str:
    kind = agent_operation_kind(operation_type_or_kind)
    return str((AGENT_OPERATION_CATALOG.get(kind) or {}).get("taskType") or "project_status")


def agent_operation_label(kind: str | None) -> str:
    return str((AGENT_OPERATION_CATALOG.get(str(kind or "").strip()) or {}).get("operationLabel") or "待确认操作")


def agent_operation_action_footer(operation_type_or_kind: str | None) -> dict[str, str]:
    kind = agent_operation_kind(operation_type_or_kind)
    config = AGENT_OPERATION_CATALOG.get(kind) or {}
    footer = {
        "label": str(config.get("label") or "").strip(),
        "title": str(config.get("title") or "").strip(),
        "description": str(config.get("description") or "").strip(),
        "reply": str(config.get("reply") or "").strip(),
    }
    return {key: value for key, value in footer.items() if value}


def agent_operation_expected_tool(operation_type_or_kind: str | None) -> str:
    kind = agent_operation_kind(operation_type_or_kind)
    return str((AGENT_OPERATION_CATALOG.get(kind) or {}).get("expectedNextTool") or "").strip()


def agent_operation_reply(operation_type_or_kind: str | None) -> str:
    kind = agent_operation_kind(operation_type_or_kind)
    return str((AGENT_OPERATION_CATALOG.get(kind) or {}).get("reply") or "").strip()


def agent_operation_interaction_policy(operation_type_or_kind: str | None) -> dict[str, Any]:
    kind = agent_operation_kind(operation_type_or_kind)
    policy = (AGENT_OPERATION_CATALOG.get(kind) or {}).get("interactionPolicy")
    return dict(policy) if isinstance(policy, dict) else {
        "canConfirm": False,
        "canCancel": False,
        "canExplain": False,
        "canRevise": False,
        "revisionMode": "unknown",
        "contextCarryPolicy": "none",
        "confirmTool": "",
        "userReplyPolicy": "未知待确认操作不能自动执行。",
    }


def agent_operation_high_risk(operation_type_or_kind: str | None) -> bool:
    kind = agent_operation_kind(operation_type_or_kind)
    return bool((AGENT_OPERATION_CATALOG.get(kind) or {}).get("highRisk"))


def agent_operation_stale_reason(operation_type_or_kind: str | None) -> str:
    kind = agent_operation_kind(operation_type_or_kind)
    return str((AGENT_OPERATION_CATALOG.get(kind) or {}).get("staleReason") or "").strip()


PROJECT_ASSET_CLEANUP_OPERATION_TYPES = agent_operation_types("project_asset_cleanup")
LATEST_ASSET_RANGE_DELETE_OPERATION_TYPES = agent_operation_types("latest_asset_range_delete")
CURRENT_CANVAS_CLEAR_OPERATION_TYPES = agent_operation_types("current_canvas_clear")
EPISODE_SOURCE_DELETE_OPERATION_TYPES = agent_operation_types("episode_source_delete")
AGENT_DESTRUCTIVE_OPERATION_TYPES = (
    PROJECT_ASSET_CLEANUP_OPERATION_TYPES
    | LATEST_ASSET_RANGE_DELETE_OPERATION_TYPES
    | CURRENT_CANVAS_CLEAR_OPERATION_TYPES
    | EPISODE_SOURCE_DELETE_OPERATION_TYPES
    | agent_operation_types("direct_asset_delete")
    | agent_operation_types("direct_workflow_delete")
    | agent_operation_types("direct_workflow_unlink")
)


__all__ = [
    "AGENT_OPERATION_CATALOG",
    "AGENT_DESTRUCTIVE_OPERATION_TYPES",
    "ASSET_RANGE_RETRY_OPERATION_TYPES",
    "CURRENT_CANVAS_CLEAR_OPERATION_TYPES",
    "EPISODE_SOURCE_DELETE_OPERATION_TYPES",
    "LATEST_ASSET_RANGE_DELETE_OPERATION_TYPES",
    "PROJECT_ASSET_CLEANUP_OPERATION_TYPES",
    "agent_operation_action_footer",
    "agent_operation_expected_tool",
    "agent_operation_high_risk",
    "agent_operation_interaction_policy",
    "agent_operation_kind",
    "agent_operation_label",
    "agent_operation_reply",
    "agent_operation_stale_reason",
    "agent_operation_task_type",
    "agent_operation_types",
]
