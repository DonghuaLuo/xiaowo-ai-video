"""Build a task Skill runtime copy with the shared result protocol inlined."""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path


_PROTOCOL_PATH = Path(__file__).resolve().parent.parent / "agent_ops" / "skills" / "task-result-protocol" / "SKILL.md"
_PROTOCOL_VERSION = "task-result-protocol@v1"
_NATIVE_SKILLS = frozenset({
    "creative-conversation",
    "episode-boundary-agent",
    "asset-range-agent",
    "asset-extraction-agent",
    "plot-splitting-agent",
    "cinematic-script-agent",
    "director-plan-agent",
    "video-prompt-agent",
})


def prune_obsolete_runtime_skills(cwd: Path) -> None:
    """Remove retired Skills from the private SDK work directory only."""
    work_dir = cwd.resolve()
    if work_dir.name != "work" or work_dir.parent.parent.name != ".agent-runtime":
        return
    skills_dir = work_dir / ".claude" / "skills"
    if not skills_dir.exists():
        return
    skills_root = skills_dir.resolve()
    if not skills_root.is_relative_to(work_dir):
        raise ValueError("Skill 安装目录超出隔离的智能体运行空间")
    for child in skills_dir.iterdir():
        if child.name in _NATIVE_SKILLS or not child.is_dir():
            continue
        resolved = child.resolve()
        if resolved.parent != skills_root:
            raise ValueError("Skill 目录超出隔离的智能体运行空间")
        shutil.rmtree(child)


def task_skill_runtime_copy(source_path: Path) -> tuple[str, str]:
    task_text = source_path.read_text(encoding="utf-8")
    protocol_text = _PROTOCOL_PATH.read_text(encoding="utf-8")
    declaration = f"resultProtocol: {_PROTOCOL_VERSION}"
    if declaration not in task_text:
        raise ValueError(f"业务 Skill 缺少 {declaration}")
    if not protocol_text.startswith("---\n") or "\n---\n" not in protocol_text[4:]:
        raise ValueError("通用结果协议 Skill 格式无效")
    protocol_body = protocol_text.split("\n---\n", 1)[1].strip()
    if not protocol_body or "# 创作结果提交协议 v1" not in protocol_body:
        raise ValueError("通用结果协议 Skill 内容不完整")
    reference_sections: list[str] = []
    for relative in dict.fromkeys(re.findall(r"\]\((references/[^)#]+\.md)\)", task_text)):
        reference_path = (source_path.parent / relative).resolve()
        if not reference_path.is_relative_to(source_path.parent.resolve()) or not reference_path.is_file():
            raise ValueError(f"业务 Skill 引用规则不存在或越界：{relative}")
        reference_text = reference_path.read_text(encoding="utf-8").strip()
        if not reference_text:
            raise ValueError(f"业务 Skill 引用规则为空：{relative}")
        reference_sections.append(f"## 已装载参考规则：{relative}\n\n{reference_text}")
    references = "\n\n".join(reference_sections)
    combined = f"{task_text.rstrip()}\n\n{references}\n\n---\n\n{protocol_body}\n" if references else f"{task_text.rstrip()}\n\n---\n\n{protocol_body}\n"
    return combined, hashlib.sha256(combined.encode("utf-8")).hexdigest()
