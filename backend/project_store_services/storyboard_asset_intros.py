# -*- coding: utf-8 -*-
"""Track visible asset identities across work chains."""
from __future__ import annotations

from typing import Any

ASSET_KINDS = ("characters", "creatures", "scenes", "props")


def prior_visible_state(project_id: str, episode_id: str, work_chain_id: str) -> dict[str, Any]:
    """Read prior main-story shots in narrative order, never creation order."""
    from .agent_sessions import _project_meta_path
    from .canvas_ownership import work_chain_origin
    from .canvas_store_queries import read_canvas_workflow_projection_v4
    from .store_core import _read_json

    meta = _read_json(_project_meta_path(project_id), {})
    episode_ids = [str(row.get("id") or "") for row in meta.get("episodes") or [] if isinstance(row, dict)]
    if episode_id not in episode_ids:
        raise ValueError("当前分集不在项目叙事顺序中，无法计算资产首次出场")
    seen = {kind: set() for kind in ASSET_KINDS}
    complete = True
    for current_episode_id in episode_ids[:episode_ids.index(episode_id) + 1]:
        workflow = read_canvas_workflow_projection_v4(project_id, current_episode_id, detail="full")
        chains = workflow.get("workChains") or []
        if not chains:
            complete = False
        for chain in chains:
            if not isinstance(chain, dict):
                continue
            chain_id = str(chain.get("id") or "")
            origin = work_chain_origin(chain, workflow)
            if origin.get("kind") in {"independent", "independent_source"}:
                if current_episode_id == episode_id and chain_id == work_chain_id:
                    return {"visible": {kind: [] for kind in ASSET_KINDS},
                            "complete": True, "scope": "independent"}
                continue
            if current_episode_id == episode_id and chain_id == work_chain_id:
                return {"visible": {kind: sorted(ids) for kind, ids in seen.items()},
                        "complete": complete, "scope": "main"}
            director = next((node for node in workflow.get("nodes") or []
                             if isinstance(node, dict) and node.get("type") == "director.board"
                             and str(node.get("workChainId") or (node.get("data") or {}).get("workChainId") or "") == chain_id), None)
            data = director.get("data") if isinstance(director, dict) and isinstance(director.get("data"), dict) else {}
            shots = data.get("directorPlanShots")
            if not isinstance(shots, list) or not shots:
                complete = False
                continue
            for shot in shots:
                visible = shot.get("visibleAssets") if isinstance(shot, dict) else None
                if not isinstance(visible, dict):
                    complete = False
                    continue
                for kind in ASSET_KINDS:
                    seen[kind].update(visible.get(kind) or [])
    raise ValueError("当前分镜工作链不在项目叙事顺序中，无法计算资产首次出场")


def first_visible_assets(
    shots: list[dict[str, Any]],
    *,
    prior_visible: dict[str, set[str]] | None = None,
    prior_complete: bool = True,
    scope: str = "main",
) -> list[dict[str, Any]]:
    """The first decision is deterministic; visibility is part of the shot contract."""
    seen = {kind: set((prior_visible or {}).get(kind) or set()) for kind in ASSET_KINDS}
    result: list[dict[str, Any]] = []
    for shot in shots:
        visible = shot.get("visibleAssets")
        if not isinstance(visible, dict):
            raise ValueError(f"镜头 {shot.get('shotNo')} 缺少可见资产，无法计算首次登场")
        for kind in ASSET_KINDS:
            for asset_id in visible.get(kind) or []:
                if asset_id in seen[kind]:
                    continue
                seen[kind].add(asset_id)
                result.append({
                    "assetType": kind,
                    "assetId": asset_id,
                    "firstShotNo": shot["shotNo"],
                    "scope": "independent" if scope == "independent" else "project" if prior_complete else "provisional",
                })
    return result
