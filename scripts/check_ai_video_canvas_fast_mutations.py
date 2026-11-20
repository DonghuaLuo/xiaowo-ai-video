from __future__ import annotations

import re
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
STORYBOARD = PLUGIN_ROOT / "frontend/src/features/storyboard/storyboard-workflow.tsx"
BACKEND_TS = PLUGIN_ROOT / "frontend/src/backend.ts"
WORKFLOWS_PY = PLUGIN_ROOT / "backend/project_store_services/workflows.py"
PREFLIGHT_PY = PLUGIN_ROOT / "backend/project_store_services/generation_preflight.py"

FRONTEND_MUTATIONS = (
    "importWorkflowMedia",
    "linkWorkflowInput",
    "unlinkWorkflowInput",
    "createWorkflowTaskCard",
    "addWorkflowAssetNodes",
    "updateWorkflowRoute",
    "selectWorkflowVariant",
    "runWorkflowBatch",
    "uploadStoryboardImage",
    "saveVariantQualityResult",
    "preflightWorkflowNode",
    "editStoryboardImage",
)

FRONTEND_PRODUCTION_STATUS_MUTATIONS = (
    "selectWorkflowVariant",
    "runWorkflowBatch",
    "uploadStoryboardImage",
    "saveVariantQualityResult",
    "preflightWorkflowNode",
    "editStoryboardImage",
)

CANVAS_LOCAL_PROJECT_CHANGED_ACTIONS = (
    "workflow_input_linked",
    "workflow_input_unlinked",
    "workflow_media_imported",
    "workflow_asset_nodes_added",
    "workflow_task_card_created",
    "workflow_route_updated",
    "workflow_item_deleted",
    "workflow_node_layout_updated",
    "workflow_node_inline_saved",
    "storyboard_image_edited",
    "storyboard_result_version_activated",
    "workflow_variant_selected",
    "storyboard_version_deleted",
    "workflow_batch_generated",
    "variant_quality_result_saved",
    "workflow_node_preflight_checked",
    "episode_production_status_updated",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def find_matching_paren(text: str, open_index: int) -> int:
    depth = 0
    quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    index = open_index
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char in {'"', "'", "`"}:
            quote = char
            index += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError(f"unmatched parenthesis at {open_index}")


def call_blocks(text: str, name: str) -> list[str]:
    blocks: list[str] = []
    start = 0
    needle = f"{name}("
    while True:
        index = text.find(needle, start)
        if index < 0:
            return blocks
        open_index = index + len(name)
        close_index = find_matching_paren(text, open_index)
        blocks.append(text[index : close_index + 1])
        start = close_index + 1


def function_block(text: str, signature: str) -> str:
    index = text.find(signature)
    if index < 0:
        raise AssertionError(f"missing {signature}")
    next_definition = re.search(
        r"\n(?:def |(?:export )?(?:async )?function |export (?:type|interface|const) )",
        text[index + len(signature):],
    )
    end = index + len(signature) + next_definition.start() if next_definition else len(text)
    return text[index:end]


def assert_storyboard_calls() -> list[str]:
    domain_paths = sorted(
        path for path in STORYBOARD.parent.iterdir() if path.suffix in {".ts", ".tsx"}
    )
    text = "\n\n".join(read(path) for path in domain_paths)
    errors: list[str] = []
    local_actions = re.search(r"const CANVAS_LOCAL_PROJECT_CHANGED_ACTIONS = new Set\(\[([\s\S]*?)\]\)", text)
    if not local_actions:
        errors.append(f"{STORYBOARD}: missing local project_changed skip list")
    for action in CANVAS_LOCAL_PROJECT_CHANGED_ACTIONS:
        if not local_actions or f'"{action}"' not in local_actions.group(1):
            errors.append(f"{STORYBOARD}: project_changed must not reload for {action}")
    if "CANVAS_LOCAL_PROJECT_CHANGED_ACTIONS.has(action)" not in text:
        errors.append(f"{STORYBOARD}: project_changed refresh must skip local canvas actions")
    if "applyWorkflowDocument" in text:
        errors.append(f"{STORYBOARD}: canvas mutations must not replace the whole workflow document")
    # Full rebuilds can return snapshots; only the mutations below use fast paths.
    for name in FRONTEND_MUTATIONS:
        blocks = call_blocks(text, name)
        # Some mutations are owned by child components, not the canvas page.
        for block in blocks:
            if re.search(r"\b(?:returnWorkflow|return_workflow|includeWorkflow|include_workflow)\s*:", block):
                first_line = block.splitlines()[0].strip()
                errors.append(f"{STORYBOARD}: {first_line} must not request a whole workflow")
    for name in FRONTEND_PRODUCTION_STATUS_MUTATIONS:
        blocks = call_blocks(text, name)
        for block in blocks:
            if re.search(r"\breturn(?:ProductionStatus|_production_status)\s*:\s*true\b", block):
                first_line = block.splitlines()[0].strip()
                errors.append(
                    f"{STORYBOARD}: {first_line} must not request production status"
                )
    return errors


def assert_backend_ts_defaults() -> list[str]:
    text = read(BACKEND_TS)
    errors: list[str] = []
    payload_block = function_block(text, "function canvasMutationPayload")
    for flag in ("returnWorkflow", "return_workflow", "includeWorkflow", "include_workflow"):
        if f"delete next.{flag}" not in payload_block:
            errors.append(f"{BACKEND_TS}: canvasMutationPayload must strip {flag}")
    for name in (*FRONTEND_MUTATIONS, "saveWorkflowNodeInlineEdit"):
        signature = f"export async function {name}"
        block = function_block(text, signature)
        if "canvasMutationPayload(payload)" not in block:
            errors.append(f"{BACKEND_TS}: {signature} must sanitize canvas mutation flags")
    for name in (*FRONTEND_PRODUCTION_STATUS_MUTATIONS, "importWorkflowMedia", "saveWorkflowNodeInlineEdit"):
        signature = f"export async function {name}"
        block = function_block(text, signature)
        if not re.search(r"const returnProductionStatus\s*=[\s\S]*?\?\?\s*false\b", block):
            errors.append(
                f"{BACKEND_TS}: {signature} must default returnProductionStatus to false"
            )
    return errors


def assert_backend_py_fast_path() -> list[str]:
    # Guard the owning domain implementations and the public facade.
    # Extraction must not make the canvas mutation contract checks disappear.
    domain_paths = [WORKFLOWS_PY, *sorted(WORKFLOWS_PY.parent.glob("workflow_*.py"))]
    text = "\n\n".join(read(path) for path in domain_paths)
    errors: list[str] = []
    for required in (
        "def _workflow_mutation_returns_workflow",
        "def _workflow_mutation_returns_production_status",
        "def _assert_workflow_input_v4_mutation",
    ):
        if required not in text:
            errors.append(f"{WORKFLOWS_PY}: missing {required}")
    returns_block = function_block(text, "def _workflow_mutation_returns_workflow")
    if "return False" not in returns_block:
        errors.append(f"{WORKFLOWS_PY}: workflow mutation return default must be False")

    import_block = function_block(text, "def import_workflow_media")
    link_block = function_block(text, "def link_workflow_input")
    unlink_block = function_block(text, "def unlink_workflow_input")
    quality_block = function_block(text, "def _save_variant_quality_result")
    batch_block = function_block(text, "def run_workflow_batch")
    create_task_block = function_block(text, "def create_workflow_task_card")
    add_asset_block = function_block(text, "def add_workflow_asset_nodes")
    route_block = function_block(text, "def update_workflow_route")
    inline_block = function_block(text, "def save_workflow_node_inline_edit")
    delete_item_block = function_block(text, "def delete_workflow_item")
    select_unlocked_block = function_block(text, "def _select_workflow_variant_unlocked")
    select_block = function_block(text, "def select_workflow_variant")
    upload_block = function_block(text, "def upload_storyboard_image")
    edit_image_block = function_block(text, "def edit_storyboard_image")

    for name, block in (("link_workflow_input", link_block), ("unlink_workflow_input", unlink_block)):
        if "_assert_workflow_input_v4_mutation(payload," not in block:
            errors.append(f"{WORKFLOWS_PY}: {name} must enforce the v4 input contract")
    input_guard = function_block(text, "def _assert_workflow_input_v4_mutation")
    mutation_guard = function_block(text, "def _assert_canvas_mutation_does_not_return_workflow")
    for block in (input_guard, mutation_guard):
        if "if _workflow_mutation_returns_workflow(payload):" not in block or "raise ValueError" not in block:
            errors.append(f"{WORKFLOWS_PY}: mutations must reject whole workflow requests")
    for name, block in (
        ("import_workflow_media", import_block),
        ("create_workflow_task_card", create_task_block),
        ("add_workflow_asset_nodes", add_asset_block),
        ("update_workflow_route", route_block),
        ("delete_workflow_item", delete_item_block),
        ("_select_workflow_variant_unlocked", select_unlocked_block),
        ("save_workflow_node_inline_edit", inline_block),
        ("save_variant_quality_result", quality_block),
        ("run_workflow_batch", batch_block),
        ("upload_storyboard_image", upload_block),
        ("edit_storyboard_image", edit_image_block),
    ):
        if "_assert_canvas_mutation_does_not_return_workflow(payload," not in block:
            errors.append(f"{WORKFLOWS_PY}: {name} must reject whole workflow requests")
    if "_workflow_mutation_returns_production_status(payload)" not in import_block:
        errors.append(f"{WORKFLOWS_PY}: import_workflow_media must gate production status")
    if "_workflow_mutation_returns_production_status(payload)" not in select_unlocked_block:
        errors.append(
            f"{WORKFLOWS_PY}: _select_workflow_variant_unlocked must gate production status"
        )
    for name, block in (
        ("save_variant_quality_result", quality_block),
        ("run_workflow_batch", batch_block),
        ("upload_storyboard_image", upload_block),
        ("edit_storyboard_image", edit_image_block),
    ):
        if "_workflow_mutation_returns_production_status(payload)" not in block:
            errors.append(f"{WORKFLOWS_PY}: {name} must gate production status")
    if "_select_workflow_variant_unlocked" not in select_block or "payload" not in select_block:
        errors.append(f"{WORKFLOWS_PY}: select_workflow_variant must pass payload to unlocked helper")
    return errors


def assert_preflight_py_fast_path() -> list[str]:
    text = read(PREFLIGHT_PY)
    errors: list[str] = []
    for required in (
        "def _canvas_mutation_returns_workflow",
        "def _canvas_mutation_returns_production_status",
    ):
        if required not in text:
            errors.append(f"{PREFLIGHT_PY}: missing {required}")
    block = function_block(text, "def preflight_workflow_node")
    if "_assert_canvas_mutation_does_not_return_workflow(payload," not in block:
        errors.append(f"{PREFLIGHT_PY}: preflight_workflow_node must reject whole workflow requests")
    if "_canvas_mutation_returns_production_status(payload)" not in block:
        errors.append(
            f"{PREFLIGHT_PY}: preflight_workflow_node must gate production status"
        )
    if '"workflow": saved_workflow' in block:
        errors.append(f"{PREFLIGHT_PY}: preflight_workflow_node must not return workflow unconditionally")
    if '"productionStatus": production_status' in block and "if return_production_status" not in block:
        errors.append(
            f"{PREFLIGHT_PY}: preflight_workflow_node must not return production status unconditionally"
        )
    return errors


def main() -> int:
    errors = [
        *assert_storyboard_calls(),
        *assert_backend_ts_defaults(),
        *assert_backend_py_fast_path(),
        *assert_preflight_py_fast_path(),
    ]
    if errors:
        print("ai-video canvas fast mutation contract failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("ai-video canvas fast mutation contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
