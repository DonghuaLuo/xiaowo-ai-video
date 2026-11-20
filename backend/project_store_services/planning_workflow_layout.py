# -*- coding: utf-8 -*-
"""工作链画布布局、卡片位置和布局分组。"""
from __future__ import annotations

from .planning_contract import (
    _CANVAS_NODE_ROLE_IMAGE_ASSET,
    _WORKFLOW_LAYOUT_ASSET_TO_MAIN_GAP_Y,
    _WORKFLOW_LAYOUT_CHAIN_GAP_Y,
    _workflow_node_default_card_size,
)
from typing import (
    Any,
)


def _layout_workflow_by_work_chain(
    nodes: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    work_chains: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None = None,
) -> None:
    route_by_id = {str(route.get("id") or ""): route for route in routes if isinstance(route, dict)}
    chain_y = 140
    chain_gap_y = _WORKFLOW_LAYOUT_CHAIN_GAP_Y
    route_gap_y = 173
    route_min_height = 600
    route_padding_y = 53
    # Leave a full image-asset lane between adjacent storyboard/video rows.
    row_gap_y = max(
        420,
        _workflow_node_default_card_size("asset.image")["height"]
        + 2 * _WORKFLOW_LAYOUT_ASSET_TO_MAIN_GAP_Y,
    )
    asset_gap_x = 80
    asset_gap_y = 56
    asset_to_main_gap_y = _WORKFLOW_LAYOUT_ASSET_TO_MAIN_GAP_Y
    main_gap_x = 240
    director_to_unit_gap_x = main_gap_x * 8 // 3  # Increase the previous 2x gap by one third.
    columns = {
        "source.text": -1040,
        "prompt.storyboard": -120,
    }
    for previous, current, previous_type in (
        ("prompt.storyboard", "director.board", "prompt.storyboard"),
        ("director.board", "storyboard.card", "director.board"),
        ("storyboard.card", "storyboard.result", "storyboard.card"),
        ("storyboard.result", "video.task", "storyboard.image"),
        ("video.task", "video.result", "video.storyboard"),
    ):
        columns[current] = (
            columns[previous]
            + _workflow_node_default_card_size(previous_type)["width"]
            + (director_to_unit_gap_x if current == "storyboard.card" else main_gap_x)
        )
    route_layout_x = columns["prompt.storyboard"] - 180
    route_layout_width = columns["video.result"] - route_layout_x + 460

    def node_data(node: dict[str, Any]) -> dict[str, Any]:
        return node.get("data") if isinstance(node.get("data"), dict) else {}

    def node_route_id(node: dict[str, Any]) -> str:
        data = node_data(node)
        return str(node.get("routeId") or data.get("routeId") or "").strip()

    def node_type(node: dict[str, Any]) -> str:
        return str(node.get("type") or "").strip()

    def primary_storyboard_result_node(node: dict[str, Any]) -> bool:
        data = node_data(node)
        return (
            node_type(node) == "storyboard.image"
            and str(data.get("canvasNodeRole") or data.get("canvas_node_role") or "").strip()
            != _CANVAS_NODE_ROLE_IMAGE_ASSET
        )

    def top_image_asset_node(node: dict[str, Any]) -> bool:
        kind = node_type(node)
        if kind in {"asset.image", "media.external"}:
            return True
        return kind == "storyboard.image" and not primary_storyboard_result_node(node)

    def int_value(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def card_size(node: dict[str, Any]) -> dict[str, int]:
        data = node_data(node)
        card_state = data.get("cardState") if isinstance(data.get("cardState"), dict) else {}
        size = card_state.get("size") if isinstance(card_state.get("size"), dict) else {}
        defaults = _workflow_node_default_card_size(node_type(node))
        return {
            "width": int(size.get("width") or defaults.get("width") or 320),
            "height": int(size.get("height") or defaults.get("height") or 260),
        }

    def route_nodes(route_id: str) -> list[dict[str, Any]]:
        return [
            node
            for node in nodes
            if isinstance(node, dict)
            and node_route_id(node) == route_id
        ]

    def stack_height(route_items: list[dict[str, Any]], *, columns_count: int = 1) -> int:
        if not route_items:
            return 0
        rows: list[int] = []
        for index, item in enumerate(route_items):
            row_index = index // max(1, columns_count)
            while len(rows) <= row_index:
                rows.append(0)
            rows[row_index] = max(rows[row_index], card_size(item)["height"])
        return sum(rows) + max(0, len(rows) - 1) * row_gap_y

    def storyboard_result_sort_key(node: dict[str, Any]) -> tuple[int, str]:
        kind = node_type(node)
        data = node_data(node)
        if data.get("shotGroupId"):
            return (int_value(data.get("shotGroupOrder"), 0), str(node.get("id") or ""))
        order = {
            "storyboard.image": 0,
        }.get(kind, 8)
        try:
            middle_index = int(data.get("middleFrameIndex") or data.get("frameIndex") or 0)
        except (TypeError, ValueError):
            middle_index = 0
        return (order * 100 + middle_index, str(node.get("id") or ""))

    workflow_edges = [edge for edge in (edges or []) if isinstance(edge, dict)]
    node_by_id = {str(node.get("id") or ""): node for node in nodes if isinstance(node, dict)}

    def edge_data(edge: dict[str, Any]) -> dict[str, Any]:
        return edge.get("data") if isinstance(edge.get("data"), dict) else {}

    def asset_group_id(node: dict[str, Any], group_ids: set[str]) -> str:
        own_group = str(node_data(node).get("shotGroupId") or "")
        if own_group in group_ids:
            return own_group
        linked_groups = {
            str(node_data(target).get("shotGroupId") or "")
            for edge in workflow_edges
            if str(edge.get("source") or "") == str(node.get("id") or "")
            and str(edge_data(edge).get("kind") or "") == "material"
            for target in [node_by_id.get(str(edge.get("target") or ""))]
            if target and str(node_data(target).get("shotGroupId") or "") in group_ids
        }
        return next(iter(linked_groups)) if len(linked_groups) == 1 else ""

    def asset_rows(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        if not items:
            return []
        row_count = (len(items) + 4) // 5
        base_count, extra_count = divmod(len(items), row_count)
        rows: list[list[dict[str, Any]]] = []
        offset = 0
        for index in range(row_count):
            row_size = base_count + (1 if index < extra_count else 0)
            rows.append(items[offset:offset + row_size])
            offset += row_size
        return rows

    def asset_rows_height(rows: list[list[dict[str, Any]]]) -> int:
        return sum(max(card_size(item)["height"] for item in row) for row in rows) + max(0, len(rows) - 1) * asset_gap_y

    def asset_anchor_center_x(node: dict[str, Any], fallback: int) -> int:
        anchors: set[int] = set()
        for edge in workflow_edges:
            if str(edge.get("source") or "") != str(node.get("id") or ""):
                continue
            if str(edge_data(edge).get("kind") or "") != "material":
                continue
            target = node_by_id.get(str(edge.get("target") or ""))
            if not target or node_route_id(target) != node_route_id(node):
                continue
            kind = node_type(target)
            column = {
                "director.board": "director.board",
                "storyboard.card": "storyboard.card",
                "video.storyboard": "video.task",
                "video.keyframe": "video.task",
            }.get(kind)
            if column:
                anchors.add(columns[column] + card_size(target)["width"] // 2)
        return next(iter(anchors)) if len(anchors) == 1 else fallback

    def asset_sections(
        items: list[dict[str, Any]], fallback_center_x: int,
    ) -> list[tuple[int, list[list[dict[str, Any]]]]]:
        groups: dict[int, list[dict[str, Any]]] = {}
        for item in items:
            anchor = asset_anchor_center_x(item, fallback_center_x)
            groups.setdefault(anchor, []).append(item)
        return [(anchor, asset_rows(group)) for anchor, group in sorted(groups.items())]

    def asset_sections_height(sections: list[tuple[int, list[list[dict[str, Any]]]]]) -> int:
        return sum(asset_rows_height(rows) for _, rows in sections) + max(0, len(sections) - 1) * asset_gap_y

    def branch_spacing(index: int, asset_reserve: int) -> int:
        return asset_reserve if index == 0 else max(row_gap_y, asset_reserve + asset_gap_y)

    def layout_route(route_id: str, route_y: int, lane_index: int) -> int:
        current_nodes = route_nodes(route_id)
        storyboard_result_nodes = [node for node in current_nodes if primary_storyboard_result_node(node)]
        storyboard_result_nodes.sort(key=storyboard_result_sort_key)
        group_cards = [
            node for node in current_nodes
            if node_type(node) == "storyboard.card" and node_data(node).get("shotGroupId")
        ]
        group_cards.sort(key=lambda node: (
            int_value(node_data(node).get("shotGroupOrder"), 0), str(node.get("id") or ""),
        ))
        group_ids = {str(node_data(node)["shotGroupId"]) for node in group_cards}
        trailing_handoff_nodes = [
            node for node in current_nodes
            if node_data(node).get("mediaPurpose") == "visual_handoff"
            and node_data(node).get("sourceType") == "visual_handoff_generation"
            and not any(
                str(edge.get("source") or "") == str(node.get("id") or "")
                and str(edge_data(edge).get("kind") or "") == "material"
                and node_type(node_by_id.get(str(edge.get("target") or "")) or {}) == "storyboard.card"
                for edge in workflow_edges
            )
        ]
        trailing_handoff_ids = {str(node.get("id") or "") for node in trailing_handoff_nodes}
        asset_nodes = [node for node in current_nodes
                       if top_image_asset_node(node) and str(node.get("id") or "") not in trailing_handoff_ids]
        asset_nodes.sort(
            key=lambda node: (
                int_value(node_data(node).get("assetLaneIndex"), 0),
                str(node.get("id") or ""),
            )
        )
        group_asset_nodes: dict[str, list[dict[str, Any]]] = {group_id: [] for group_id in group_ids}
        global_asset_nodes: list[dict[str, Any]] = []
        for node in asset_nodes:
            group_id = asset_group_id(node, group_ids)
            (group_asset_nodes[group_id] if group_id else global_asset_nodes).append(node)
        director_center_x = columns["director.board"] + _workflow_node_default_card_size("director.board")["width"] // 2
        video_center_x = columns["video.task"] + _workflow_node_default_card_size("video.storyboard")["width"] // 2
        global_asset_sections = asset_sections(global_asset_nodes, director_center_x)
        global_asset_height = asset_sections_height(global_asset_sections)

        main_nodes = [
            node
            for node in current_nodes
            if node_type(node)
            in {"prompt.storyboard", "director.board", "storyboard.card", "video.storyboard", "video.keyframe", "video.result"}
        ]
        shot_plan_nodes = [node for node in current_nodes if node_type(node) == "director.board"]
        anchor_group_height = 0
        if shot_plan_nodes:
            anchor_group_height = max(card_size(node)["height"] for node in shot_plan_nodes)
        unallocated_results = [node for node in storyboard_result_nodes if not node_data(node).get("shotGroupId")]
        result_stack_height = stack_height(unallocated_results)
        branch_areas: list[tuple[list[dict[str, Any]], list[tuple[int, list[list[dict[str, Any]]]]], int, int]] = []
        for card in group_cards:
            group_id = str(node_data(card)["shotGroupId"])
            row_nodes = [
                item for item in current_nodes
                if str(node_data(item).get("shotGroupId") or "") == group_id
                and node_type(item) in {"storyboard.card", "storyboard.image", "video.storyboard", "video.keyframe", "video.result"}
                and (node_type(item) != "storyboard.image" or primary_storyboard_result_node(item))
            ]
            row_height = max((card_size(item)["height"] for item in row_nodes), default=300)
            group_sections = asset_sections(group_asset_nodes[group_id], video_center_x)
            asset_reserve = asset_sections_height(group_sections) + asset_to_main_gap_y if group_sections else 0
            branch_areas.append((row_nodes, group_sections, row_height, asset_reserve))
        branch_height = sum(row_height for _, _, row_height, _ in branch_areas)
        branch_height += sum(
            branch_spacing(index, reserve)
            for index, (_, _, _, reserve) in enumerate(branch_areas)
        )
        main_height = max(
            max((card_size(node)["height"] for node in main_nodes), default=360),
            anchor_group_height,
            result_stack_height,
            branch_height,
        )
        trailing_handoff_height = sum(card_size(node)["height"] for node in trailing_handoff_nodes)
        trailing_handoff_height += len(trailing_handoff_nodes) * asset_to_main_gap_y
        route_height_value = max(
            route_min_height,
            route_padding_y * 2
            + global_asset_height
            + (asset_to_main_gap_y if global_asset_sections else 0)
            + main_height + trailing_handoff_height,
        )
        main_top = route_y + route_padding_y
        if global_asset_sections:
            main_top += global_asset_height + asset_to_main_gap_y
        branch_top = main_top + (main_height - branch_height) // 2
        branch_main_centers: list[int] = []
        running_branch_y = branch_top
        for index, (_, _, row_height, asset_reserve) in enumerate(branch_areas):
            running_branch_y += branch_spacing(index, asset_reserve)
            branch_main_centers.append(running_branch_y + row_height // 2)
            running_branch_y += row_height
        center_y = (
            (branch_main_centers[0] + branch_main_centers[-1]) // 2
            if branch_main_centers else main_top + main_height // 2
        )

        def set_position(node: dict[str, Any], x: int, y: int) -> None:
            if node_data(node).get("mediaPurpose") == "visual_handoff" and node_data(node).get("positionEditedByUser"):
                return
            position = node.setdefault("position", {})
            if not isinstance(position, dict):
                position = {}
                node["position"] = position
            position["x"] = x
            position["y"] = y

        def center_node(node: dict[str, Any], x: int) -> None:
            set_position(node, x, center_y - card_size(node)["height"] // 2)

        if shot_plan_nodes:
            for node in shot_plan_nodes:
                center_node(node, columns["director.board"])

        for node in current_nodes:
            kind = node_type(node)
            if kind == "director.board":
                continue
            if kind == "prompt.storyboard":
                center_node(node, columns["prompt.storyboard"])
            elif kind == "storyboard.card":
                center_node(node, columns["storyboard.card"])
            elif kind in {"video.storyboard", "video.keyframe"}:
                center_node(node, columns["video.task"])
            elif kind == "video.result":
                center_node(node, columns["video.result"])

        def position_asset_rows(
            rows: list[list[dict[str, Any]]], anchor_x: int, top: int,
            right_boundary_x: int | None = None,
        ) -> None:
            row_top = top
            for row in rows:
                row_height = max(card_size(item)["height"] for item in row)
                row_width = sum(card_size(item)["width"] for item in row) + (len(row) - 1) * asset_gap_x
                running_x = anchor_x - row_width // 2
                if right_boundary_x is not None:
                    running_x = min(running_x, right_boundary_x - row_width)
                for item in row:
                    size = card_size(item)
                    set_position(item, running_x, row_top + (row_height - size["height"]) // 2)
                    running_x += size["width"] + asset_gap_x
                row_top += row_height + asset_gap_y

        def position_asset_sections(
            sections: list[tuple[int, list[list[dict[str, Any]]]]], top: int,
            right_boundary_x: int | None = None,
        ) -> None:
            section_top = top
            for anchor_x, rows in sections:
                position_asset_rows(rows, anchor_x, section_top, right_boundary_x)
                section_top += asset_rows_height(rows) + asset_gap_y

        if global_asset_sections:
            script_nodes = shot_plan_nodes or [
                node for node in current_nodes if node_type(node) == "prompt.storyboard"
            ]
            script_top = min(
                (center_y - card_size(node)["height"] // 2 for node in script_nodes),
                default=main_top,
            )
            asset_top = script_top - asset_to_main_gap_y - global_asset_height
            storyboard_overlap = any(
                asset_top < row_center + card_size(node)["height"] // 2 + asset_gap_y
                and asset_top + global_asset_height > row_center - card_size(node)["height"] // 2 - asset_gap_y
                for row_center, (row_nodes, _, _, _) in zip(branch_main_centers, branch_areas)
                for node in row_nodes
                if node_type(node) == "storyboard.card"
            )
            storyboard_boundary = columns["storyboard.card"] - asset_gap_x if storyboard_overlap else None
            position_asset_sections(
                global_asset_sections,
                asset_top,
                storyboard_boundary,
            )

        result_top = center_y - result_stack_height // 2 if unallocated_results else center_y
        result_y = result_top
        for node in unallocated_results:
            set_position(node, columns["storyboard.result"], result_y)
            result_y += card_size(node)["height"] + row_gap_y

        if branch_areas:
            row_bottom = branch_top
            for index, (row_nodes, group_sections, row_height, asset_reserve) in enumerate(branch_areas):
                row_main_top = row_bottom + branch_spacing(index, asset_reserve)
                if group_sections:
                    position_asset_sections(group_sections, row_main_top - asset_reserve)
                for item in row_nodes:
                    column = (
                        columns["storyboard.card"] if node_type(item) == "storyboard.card"
                        else columns["storyboard.result"] if node_type(item) == "storyboard.image"
                        else columns["video.task"] if node_type(item) in {"video.storyboard", "video.keyframe"}
                        else columns["video.result"]
                    )
                    set_position(item, column, row_main_top + (row_height - card_size(item)["height"]) // 2)
                row_bottom = row_main_top + row_height

        for handoff in trailing_handoff_nodes:
            source_id = str(node_data(handoff).get("sourceNodeId") or "")
            source = node_by_id.get(source_id)
            if not source:
                continue
            source_position = source.get("position") if isinstance(source.get("position"), dict) else {}
            source_x = int_value(source_position.get("x"), columns["storyboard.card"])
            source_y = int_value(source_position.get("y"), main_top)
            set_position(
                handoff,
                source_x + (card_size(source)["width"] - card_size(handoff)["width"]) // 2,
                source_y + card_size(source)["height"] + asset_to_main_gap_y,
            )

        route = route_by_id.get(route_id)
        if route:
            route["laneIndex"] = lane_index
            route["layout"] = {
                **(route.get("layout") if isinstance(route.get("layout"), dict) else {}),
                "x": route_layout_x,
                "y": route_y,
                "width": route_layout_width,
                "height": route_height_value,
            }
        return route_height_value

    sorted_chains = sorted(
        [(index, chain) for index, chain in enumerate(work_chains) if isinstance(chain, dict)],
        key=lambda item: (int(item[1].get("order") or item[0] + 1), item[0]),
    )
    content_top_y = chain_y
    content_bottom_y = chain_y + route_min_height
    for chain_index, chain in sorted_chains:
        route_ids = [str(item) for item in chain.get("routeIds") or [] if str(item)]
        if not route_ids:
            route_ids = [
                str(route.get("id") or "")
                for route in routes
                if isinstance(route, dict) and str(route.get("workChainId") or "") == str(chain.get("id") or "")
            ]
        route_y = chain_y
        chain_height = 0
        for lane_index, route_id in enumerate(route_ids):
            current_route_height = layout_route(route_id, route_y, lane_index)
            chain_height += current_route_height
            if lane_index < len(route_ids) - 1:
                chain_height += route_gap_y
            route_y += current_route_height + route_gap_y
        chain["order"] = int(chain.get("order") or chain_index + 1)
        chain["routeIds"] = route_ids
        chain["layout"] = {
            **(chain.get("layout") if isinstance(chain.get("layout"), dict) else {}),
            "x": route_layout_x,
            "y": chain_y,
            "width": route_layout_width,
            "height": chain_height,
        }
        content_bottom_y = max(content_bottom_y, chain_y + chain_height)
        chain_y += chain_height + chain_gap_y

    source_nodes = [
        node
        for node in nodes
        if isinstance(node, dict)
        and node_type(node) == "source.text"
        and not node_route_id(node)
        and not str(node_data(node).get("workChainId") or "").strip()
    ]
    source_stack_height = (
        sum(card_size(node)["height"] for node in source_nodes)
        if source_nodes
        else 0
    )
    source_top_y = (content_top_y + content_bottom_y) // 2 - source_stack_height // 2
    running_source_y = source_top_y
    for node in source_nodes:
        position = node.setdefault("position", {})
        if not isinstance(position, dict):
            position = {}
            node["position"] = position
        position["x"] = columns["source.text"]
        position["y"] = running_source_y
        running_source_y += card_size(node)["height"]

    canvas_asset_nodes = [
        node
        for node in nodes
        if isinstance(node, dict)
        and node_type(node) in {"asset.image", "media.external"}
        and not node_route_id(node)
    ]
    canvas_asset_nodes.sort(
        key=lambda node: (
            int_value(node_data(node).get("assetLaneIndex"), 0),
            node_route_id(node),
            str(node.get("id") or ""),
        )
    )
    source_center_y = (
        source_top_y + source_stack_height // 2
        if source_nodes
        else (content_top_y + content_bottom_y) // 2
    )
    for index, node in enumerate(canvas_asset_nodes):
        size = card_size(node)
        offset_index = 0 if index == 0 else ((index + 1) // 2) * (-1 if index % 2 else 1)
        position = node.setdefault("position", {})
        if not isinstance(position, dict):
            position = {}
            node["position"] = position
        position["x"] = columns["source.text"] - asset_gap_x - size["width"]
        position["y"] = source_center_y - size["height"] // 2 + offset_index * (size["height"] + asset_gap_y)
