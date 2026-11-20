# -*- coding: utf-8 -*-
"""Generic storyboard sheet template rules used by planning and generation."""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from .catalogs import GLOBAL_DIR
from .production_specs import storyboard_panel_rows
from .store_core import _now, _read_json, _write_json, ensure_store


STORYBOARD_TEMPLATE_NARRATIVE = "narrative_storyboard"
STORYBOARD_TEMPLATE_BLOCKING = "blocking_storyboard"
STORYBOARD_TEMPLATE_IMAGE_GRID = "image_grid_storyboard"
STORYBOARD_TEMPLATE_NUMBERED_GRID = "numbered_grid_storyboard"
STORYBOARD_TEMPLATE_FILMSTRIP = "filmstrip_storyboard"
STORYBOARD_TEMPLATE_DEFAULT = STORYBOARD_TEMPLATE_IMAGE_GRID
GLOBAL_STORYBOARD_TEMPLATES_PATH = GLOBAL_DIR / "storyboard_templates.json"

_STORYBOARD_REFERENCE_BRIEFS = {
    STORYBOARD_TEMPLATE_NARRATIVE: "叙事故事版。左侧为镜头画面，右侧为辅助关系图，仅帮助理解空间、观察关系和首尾状态，不作为镜头画面。",
    STORYBOARD_TEMPLATE_BLOCKING: "调度故事版。上方为镜头画面，下方为辅助调度图，仅帮助理解站位、路线、视线和机位关系，不作为镜头画面。",
    STORYBOARD_TEMPLATE_IMAGE_GRID: "镜头画格宫格图。按从左到右、从上到下对应各镜头，仅参考各画格内的画面。",
    STORYBOARD_TEMPLATE_NUMBERED_GRID: "编号宫格图。编号用于对应镜头，仅参考各画格内的画面。",
    STORYBOARD_TEMPLATE_FILMSTRIP: "胶片条故事版。按从左到右、从上到下对应各镜头，仅参考取景窗内的画面，胶片边带和齿孔不属于镜头内容。",
}


def storyboard_template_layout_kind(template_id: str) -> str:
    """自定义模板不继承来源预设的空间分区。"""
    return template_id if template_id in _STORYBOARD_REFERENCE_BRIEFS else "custom"


def storyboard_reference_brief(prompt_spec: dict[str, Any]) -> str:
    """只使用实际图片版本记录的版式，不读取当前模板配置。"""
    if prompt_spec.get("format") == "single_storyboard_panel":
        return "单镜头画面参考，用于对应镜头的构图、主体站位和空间关系。"
    return _STORYBOARD_REFERENCE_BRIEFS.get(
        prompt_spec.get("layoutKind"),
        "仅参考与镜头正文对应的画面；如有辅助示意区域，仅用于理解关系，不作为镜头画面。",
    )


def storyboard_image_prompt_spec(
    media: dict[str, Any] | None,
    version: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """有版本时以版本载荷为准；无版本的独立媒体使用自己的版式快照。"""
    if version is not None:
        source = version.get("payload")
    else:
        source = media
    spec = source.get("storyboardPromptSpec") if isinstance(source, dict) else None
    return copy.deepcopy(spec) if isinstance(spec, dict) else {}


_REQUIRED_STORYBOARD_SECTIONS = [
    "镜头画面区",
    "辅助视觉调度区",
    "镜头运动/转场标记区",
    "少量文字标注区",
]

_STORYBOARD_TEMPLATE_BASE_CONTRACT = (
    "不可覆盖的故事板基础合同：分镜脚本决定镜头数量、顺序、静态画面、景别/机位、主体、站位、关键动作和画面落点；"
    "分镜图版式规则只决定故事版工作页的空间组织方式、主要镜头画格排列方式、辅助视觉信息、短标签和版式元素呈现方式；"
    "不得重写分镜脚本，不得重新决定景别、机位、构图、站位、关键动作、结尾画面或镜头数量。"
    "主要镜头画格负责把分镜脚本中的可见信息画清楚，包括主体外观、相对位置、视线/银幕方向、关键道具位置和关键姿态；"
    "版式元素不得替代主要镜头画格或新增剧情。"
    "每个主要镜头画格须与项目目标视频的横竖屏方向一致，单格不必逐像素等于视频宽高比；连续镜头画格遵守分镜脚本中已建立的空间方向，"
    "保持视线、动作接点、银幕方向、道具、服装和光线连续；不得用版式规则制造新的越轴、换位或剧情跳变。"
    "项目画幅与语言、版式空间分配、资产绑定和安全约束由各自专属区块提供；版式规则不得重复定义或覆盖。"
    "自定义版式可以在不改变分镜脚本、项目画幅、资产事实和本次生成要求的前提下，定义自身的版面组织及版式表达方式。"
)

_STORYBOARD_TEMPLATE_NARRATIVE_PROMPT_RULES = (
    "版式定位：叙事故事版用于把分镜脚本转成连续可读的主要镜头画格，重点表达情绪推进、信息释放、动作落点和首尾状态变化。\n"
    "版式结构：完整叙事故事版由左侧主镜头画格区和右侧独立辅助视觉窄栏共同组成；右侧辅助视觉窄栏是整组镜头的关系图示区域，有独立边界，不参与主镜头画格网格，不占用任何主镜头画格位置，视觉重量必须低于主要镜头画格。\n"
    "主镜头区域：逐条把分镜脚本中的分镜画面转成清楚的主要镜头画格，画格顺序必须等于镜头顺序；每个画格只承载一个镜头，不合并、不拆分、不额外补镜头。\n"
    "主镜头信息：每个主要镜头画格用镜头编号加极短镜头标题或场面锚点标明该格的画面重点，标题只概括景别、主体、动作落点或场景状态，并且只属于对应主要镜头画格。\n"
    "画面方法：当分镜脚本要求人物关系、视线、反应或关键道具落点时，主要镜头画格用清晰主体层级、空间方向和前后景关系承载，不用装饰性空镜重复同一信息。\n"
    "辅助区域：右侧辅助视觉窄栏只服务整组镜头的空间连续性，以一张通用的节点化空间关系图为核心。它用位置节点、镜头编号节点、视线/行动方向线和首尾状态标记表达场景边界、人物/生物与关键道具在整组镜头中的相对位置、视线或行动方向、镜头关系和首尾状态变化；当导演镜头包含多个空间层级、间接观看对象、反射/回忆/想象/梦境等非当前物理空间，或任何由媒介/界面承载的画面时，用抽象空间节点、小分区、连线或方向标记表达当前空间、观察者、被观察对象/空间和对应镜头编号的关系；当前提供的场景图或分镜脚本明确给出、且确实影响连续性或行动方向的门、通道等空间开口，才标注其位置；镜头编号、对象短编号和方向标记直接贴近对应的位置、路线节点或关系节点，不另拆图例栏、说明栏或素材栏。主要镜头画面、镜头顺序和短标题由主镜头区域承担；辅助区只画空间关系、观察关系和首尾状态关系，不用完整画面复刻、主镜头缩略图或素材卡填充辅助区，不另设独立素材栏、角色头像栏、场景缩略图栏、道具缩略图栏或关键元素参考栏；资产参考图只用于约束对应对象在空间示意中的外观与位置。\n"
    "版式标注规则：每个主要镜头画格用镜头编号和极短标题标识；必要的对象短编号、方向或极短动作词服务于调度阅读，保持紧凑并避让关键画面。镜头内可见文字按分镜脚本呈现。"
)

_STORYBOARD_TEMPLATE_BLOCKING_PROMPT_RULES = (
    "版式定位：调度故事版用于讲清站位、路线、视线、机位侧、轴线、镜头运动方向和关键道具空间关系，适合空间调度与镜头方向影响理解的镜头。\n"
    "版式结构：完整调度故事版由上方主镜头画格区和下方独立辅助调度条共同组成；下方辅助调度条是整组镜头的调度图示区域，有独立边界，不参与主镜头画格网格，不占用任何主镜头画格位置，视觉重量必须低于主要镜头画格。\n"
    "主镜头区域：主要镜头画格严格遵守分镜脚本中的分镜画面，先画清每个镜头的可见画面、主体层级、构图、站位和关键动作落点。\n"
    "辅助区域：下方辅助调度条只服务整组镜头的空间调度关系，以一张横向通用节点化调度关系图为核心。它用站位节点、镜头编号节点、机位/朝向标记、视线/轴线、行动路线、首尾状态标记和必要的空间分区，表达场景边界、人物/生物与关键道具位置、镜头位置与朝向、空间连接关系和镜头关系；当导演镜头包含多个空间层级、间接观看对象、反射/回忆/想象/梦境等非当前物理空间，或任何由媒介/界面承载的画面时，用抽象空间节点、小分区、连线或方向标记表达当前空间、观察者、被观察对象/空间和对应镜头编号的关系；当前提供的场景图或分镜脚本明确给出、且确实影响路线或镜头连续性的门、通道等空间开口，才标注其位置；镜头编号、对象短编号、机位标记和方向线直接贴近对应的站位、机位、路线节点或关系节点，不另拆图例栏、说明栏或素材栏。主要镜头画面、镜头顺序和短标题由主镜头区域承担；辅助区只画空间调度关系、观察关系和首尾状态关系，不用完整画面复刻、主镜头缩略图或素材卡填充辅助区，不另设独立素材栏、角色头像栏、场景缩略图栏、道具缩略图栏或关键元素参考栏；资产参考图只用于约束对应对象在调度示意中的外观与位置。\n"
    "多空间规则：当导演镜头同时包含当前场所、外部环境、另一地点、被观察对象、记忆/想象/梦境/预示等多层空间时，辅助区用抽象分区和关系线表达各空间边界、观察方向、主体位置、关键道具位置以及空间之间的观看/连接关系。\n"
    "符号规则：箭头和线条只用于区分人物/生物或道具行动、视线/轴线、镜头方向和必要的空间连接；需要图例时只解释符号含义。\n"
    "边界规则：辅助区域服务主要镜头画格，不替代、改写或压过主要镜头画格；只呈现分镜脚本需要的空间调度与镜头组织信息，不设置整页标题、片名、章节名或装饰性题字。"
)

_STORYBOARD_TEMPLATE_IMAGE_GRID_PROMPT_RULES = (
    "版式定位：镜头画格宫格图用于检查镜头画面与空间连续性；不添加版式编号，镜头画面内的文字按分镜脚本呈现。\n"
    "主画格组织：主要镜头画格按自然阅读顺序排列；每个画格保持项目目标视频的横竖屏方向。本次请求明确指定排列时按该排列绘制。\n"
    "版式构成：整张工作页只由与镜头数一致的主要画格、干净留白或极细分隔组成；留白不得形成看似额外镜头的空画格。\n"
    "画面文字：属于镜头画面的可见文字按分镜脚本确定的内容与出现时机呈现。\n"
    "画面边界：每个画格只呈现分镜脚本中该镜头的画面。"
)

_STORYBOARD_TEMPLATE_NUMBERED_GRID_PROMPT_RULES = (
    "版式定位：编号宫格图用于按顺序检查多镜头画面，在保留纯画面可读性的同时，用极小编号帮助确认镜头顺序。\n"
    "主画格组织：主要镜头画格按从左到右、从上到下的自然阅读顺序排列；每个画格保持项目目标视频的横竖屏方向。\n"
    "版式构成：整张工作页由主要镜头画格、间隔和小号镜头编号组成；每个编号放在对应画格角落，避开人物、道具和画面落点。\n"
    "画面文字：镜头内可见文字按分镜脚本呈现；小号镜头编号是额外添加的唯一版式文字。\n"
    "画面边界：每个画格只呈现分镜脚本中该镜头的画面。"
)

_STORYBOARD_TEMPLATE_FILMSTRIP_PROMPT_RULES = (
    "版式定位：胶片条故事版用于把镜头组织成胶片接触片式的连续时间条，重点表达镜头先后、动作接点、视线接点、转场方向和视觉节奏。\n"
    "画格组织：主要镜头画格嵌入连续横向胶片带；镜头较少时使用单条胶片带，镜头较多时使用上下多条横向胶片带换行，换行后仍按从左到右、从上到下阅读；每个主要镜头画格保持项目目标视频的横竖屏方向，且同一张工作页内主要取景窗尺寸尽量一致。\n"
    "版式识别：工作页应能一眼看出胶片带结构，用上下连续边带、轻量齿孔、细窄轨道或贯通边框把同一行画格连接成一条胶片带；这些版式元素只位于画格外缘，不进入镜头画面内部。\n"
    "节奏规则：画格之间保留统一间距，用连续条带和相邻画格关系体现动作接点、方向延续或转场节拍；末行只绘制实际镜头的取景窗，不补空取景窗或额外镜头。\n"
    "标注规则：每个主要镜头画格必须带一个极小镜头编号；编号可放在胶片带边缘或画格角落，不遮挡人物、关键道具和画面落点；除此之外只允许必要的极短方向标记。\n"
    "边界规则：胶片带外观只服务时间顺序和节奏阅读；主要镜头画格内容完全来自分镜脚本中的分镜画面。"
)

_STORYBOARD_SINGLE_PANEL_NARRATIVE_PROMPT_RULES = (
    "叙事故事版单镜头画格：只呈现当前指定镜头的代表性静态画面，突出该镜头的情绪、信息、动作落点或状态变化；"
    "整张工作页仍保留右侧独立辅助视觉窄栏，不增加其他正式镜头。"
)

_STORYBOARD_SINGLE_PANEL_BLOCKING_PROMPT_RULES = (
    "调度故事版单镜头画格：只呈现当前指定镜头的代表性静态画面，清楚表达该镜头要求的人物/生物站位、"
    "关键道具位置、视线或行动方向；整张工作页仍保留下方独立辅助调度条，不增加其他正式镜头。"
)

_STORYBOARD_SINGLE_PANEL_IMAGE_GRID_PROMPT_RULES = (
    "镜头画格宫格图单镜头画格：只呈现当前指定镜头的起始画面；仅绘制起始可见的场景载体文字和有据的特殊事件短标识。"
    "版式层只呈现这一个主要画格。"
)

_STORYBOARD_SINGLE_PANEL_NUMBERED_GRID_PROMPT_RULES = (
    "编号宫格图单镜头画格：只呈现当前指定镜头的画面，并在画格角落放一个极小镜头编号；"
    "画面内可见文字按分镜脚本呈现，编号是唯一的版式文字。"
)

_STORYBOARD_SINGLE_PANEL_FILMSTRIP_PROMPT_RULES = (
    "胶片条故事版单镜头画格：只呈现当前指定镜头的主要画面，可保留胶片带外缘的轻量识别结构和一个极小镜头编号；"
    "不生成多镜头胶片带、不生成其他镜头或辅助区域，版式元素不得遮挡画面主体。"
)


def _storyboard_layout_policy_prompt(template_id: str | None = None) -> str:
    resolved_id = str(template_id or STORYBOARD_TEMPLATE_DEFAULT).strip() or STORYBOARD_TEMPLATE_DEFAULT
    if resolved_id == STORYBOARD_TEMPLATE_IMAGE_GRID:
        return (
            "【版式空间分配规则】\n"
            "主要镜头画格区约占整张工作页 100%。"
        )
    if resolved_id == STORYBOARD_TEMPLATE_NUMBERED_GRID:
        return (
            "【版式空间分配规则】\n"
            "主要镜头画格区约占整张工作页 100%。"
        )
    if resolved_id == STORYBOARD_TEMPLATE_FILMSTRIP:
        return (
            "【版式空间分配规则】\n"
            "主要镜头画格区约占整张工作页 100%。"
        )
    if resolved_id == STORYBOARD_TEMPLATE_BLOCKING:
        return (
            "【版式空间分配规则】\n"
            "空间分配固定为：上方主镜头画格区约占工作页 76%，下方独立辅助调度条约占工作页 24%；辅助区与主镜头区有清晰边界，不进入主镜头画格网格。"
        )
    return (
        "【版式空间分配规则】\n"
        "空间分配固定为：左侧主镜头画格区约占工作页 86%，右侧独立辅助视觉窄栏约占工作页 14%；辅助区与主镜头区有清晰边界，不进入主镜头画格网格。"
    )


def storyboard_panel_arrangement_rules(
    template_id: str, panel_count: int, target_orientation: str,
) -> str:
    """只安排预设版式的主要镜头画格，不改工作页或辅助区结构。"""
    kind = storyboard_template_layout_kind(storyboard_template_id(template_id))
    if kind == "custom" or panel_count not in (1, 2, 3, 4, 5, 6):
        return ""
    orientation = str(target_orientation or "").strip().lower()
    if orientation not in ("landscape", "portrait"):
        return ""

    if kind == STORYBOARD_TEMPLATE_NARRATIVE:
        region = "左侧主镜头画格区"
        auxiliary = "右侧辅助视觉窄栏仍按原版式绘制，不进入镜头画格。"
    elif kind == STORYBOARD_TEMPLATE_BLOCKING:
        region = "上方主镜头画格区"
        auxiliary = "下方辅助调度条仍按原版式绘制，不进入镜头画格。"
    else:
        region = "主要镜头画格区"
        auxiliary = ""

    rows = storyboard_panel_rows(orientation, panel_count)
    first = 1
    row_descriptions = []
    for row_number, width in enumerate(rows, start=1):
        labels = "、".join(str(index) for index in range(first, first + width))
        row_descriptions.append(f"第{row_number}行 {labels}")
        first += width
    arrangement = "；".join(row_descriptions) + "。"
    frame_rule = (
        f"全部 {panel_count} 个正式画格都保持{'横向' if orientation == 'landscape' else '竖向'}镜头方向；"
        "满列行尽量铺满主区宽度，各行合起来尽量铺满主区高度，避免大片外围空白或细长条状镜头。"
        "末行缺格时可以居中并在两侧留下无边框纸面，也可以让真实画格适度变宽；"
        "不要求逐格等宽等高，不得为凑数补画带边框的空画格。"
    )
    if orientation == "landscape" and panel_count == 3:
        frame_rule += "禁止一列三行、每行一个镜头的竖排方式。"
    filmstrip = (
        "胶片边带和齿孔继续只沿实际画格所在行绘制，不延伸成空取景窗。"
        if kind == STORYBOARD_TEMPLATE_FILMSTRIP else ""
    )
    return f"{region}内的 {panel_count} 个镜头优先按以下行序排列：{arrangement}{frame_rule}{filmstrip}{auxiliary}"


def _default_layout_spec(
    *,
    fixed_shot_slots: int = 0,
    min_shot_slots: int = 1,
    max_shot_slots: int = 0,
) -> dict[str, Any]:
    return {
        "targetWidth": 2048,
        "targetHeight": 1152,
        "defaultResolution": "2K",
        "sheetAspectRatio": "16:9",
        "aspectRatio": "16:9",
        "fixedShotSlots": fixed_shot_slots,
        "minShotSlots": min_shot_slots,
        "maxShotSlots": max_shot_slots,
    }


_STORYBOARD_TEMPLATE_ROWS: tuple[dict[str, Any], ...] = (
    {
        "id": STORYBOARD_TEMPLATE_IMAGE_GRID,
        "title": "镜头画格宫格图",
        "description": "纯画面宫格以画格位置表达镜头顺序；镜头内文字照常保留。",
        "badge": "预设",
        "source": "builtin",
        "layoutSlots": "flexible",
        "minShotSlots": 1,
        "maxShotSlots": 0,
        "fixedShotSlots": 0,
        "layoutSpec": _default_layout_spec(),
        "requiredSections": ["镜头画面区"],
        "prompt": _STORYBOARD_TEMPLATE_IMAGE_GRID_PROMPT_RULES,
    },
    {
        "id": STORYBOARD_TEMPLATE_NUMBERED_GRID,
        "title": "编号宫格图",
        "description": "主要画格按顺序排列，版式仅使用极小镜头编号；镜头内文字照常保留。",
        "badge": "预设",
        "source": "builtin",
        "layoutSlots": "flexible",
        "minShotSlots": 1,
        "maxShotSlots": 0,
        "fixedShotSlots": 0,
        "layoutSpec": _default_layout_spec(),
        "requiredSections": ["镜头画面区", "少量文字标注区"],
        "prompt": _STORYBOARD_TEMPLATE_NUMBERED_GRID_PROMPT_RULES,
    },
    {
        "id": STORYBOARD_TEMPLATE_NARRATIVE,
        "title": "叙事故事版",
        "description": "适合情绪推进、动作连续、首尾状态变化明显的剧情，用连续镜头画面讲清视觉节拍。",
        "badge": "预设",
        "source": "builtin",
        "layoutSlots": "flexible",
        "minShotSlots": 1,
        "maxShotSlots": 0,
        "fixedShotSlots": 0,
        "layoutSpec": _default_layout_spec(),
        "requiredSections": _REQUIRED_STORYBOARD_SECTIONS,
        "prompt": _STORYBOARD_TEMPLATE_NARRATIVE_PROMPT_RULES,
    },
    {
        "id": STORYBOARD_TEMPLATE_BLOCKING,
        "title": "调度故事版",
        "description": "适合站位、路线、视线、机位、运镜或道具位置影响理解的剧情，用图示化辅助区讲清空间调度和镜头方向。",
        "badge": "预设",
        "source": "builtin",
        "layoutSlots": "flexible",
        "minShotSlots": 1,
        "maxShotSlots": 0,
        "fixedShotSlots": 0,
        "layoutSpec": _default_layout_spec(),
        "requiredSections": _REQUIRED_STORYBOARD_SECTIONS,
        "prompt": _STORYBOARD_TEMPLATE_BLOCKING_PROMPT_RULES,
    },
    {
        "id": STORYBOARD_TEMPLATE_FILMSTRIP,
        "title": "胶片条故事版",
        "description": "适合动作连续、转场明显或节奏需要横向阅读的剧情，用连续胶片条展示镜头节拍。",
        "badge": "预设",
        "source": "builtin",
        "layoutSlots": "flexible",
        "minShotSlots": 1,
        "maxShotSlots": 0,
        "fixedShotSlots": 0,
        "layoutSpec": _default_layout_spec(),
        "requiredSections": ["镜头画面区", "少量文字标注区"],
        "prompt": _STORYBOARD_TEMPLATE_FILMSTRIP_PROMPT_RULES,
    },
)


def _default_storyboard_templates() -> list[dict[str, Any]]:
    return [_normalize_storyboard_template(row, source="builtin") for row in _STORYBOARD_TEMPLATE_ROWS]


def _layout_spec_from_template(
    row: dict[str, Any],
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = row.get("layoutSpec") or row.get("layout_spec")
    spec = copy.deepcopy(source) if isinstance(source, dict) else {}
    fallback_spec = copy.deepcopy(fallback) if isinstance(fallback, dict) else _default_layout_spec()
    for key, fallback_value in fallback_spec.items():
        spec.setdefault(key, fallback_value)
    for public_key, spec_key in (
        ("targetWidth", "targetWidth"),
        ("target_width", "targetWidth"),
        ("targetHeight", "targetHeight"),
        ("target_height", "targetHeight"),
        ("defaultResolution", "defaultResolution"),
        ("default_resolution", "defaultResolution"),
        ("aspectRatio", "aspectRatio"),
        ("aspect_ratio", "aspectRatio"),
        ("sheetAspectRatio", "sheetAspectRatio"),
        ("sheet_aspect_ratio", "sheetAspectRatio"),
        ("fixedShotSlots", "fixedShotSlots"),
        ("fixed_shot_slots", "fixedShotSlots"),
        ("minShotSlots", "minShotSlots"),
        ("min_shot_slots", "minShotSlots"),
        ("maxShotSlots", "maxShotSlots"),
        ("max_shot_slots", "maxShotSlots"),
    ):
        if row.get(public_key) not in (None, ""):
            spec[spec_key] = row.get(public_key)
    for key in ("targetWidth", "targetHeight", "fixedShotSlots", "minShotSlots", "maxShotSlots"):
        try:
            spec[key] = int(spec.get(key) or fallback_spec.get(key) or 0)
        except (TypeError, ValueError):
            spec[key] = int(fallback_spec.get(key) or 0)
    spec["targetWidth"] = spec["targetWidth"] or 2048
    spec["targetHeight"] = spec["targetHeight"] or 1152
    spec["minShotSlots"] = max(1, spec["minShotSlots"] or 1)
    if spec["maxShotSlots"] > 0:
        spec["maxShotSlots"] = max(spec["minShotSlots"], spec["maxShotSlots"])
    else:
        spec["maxShotSlots"] = 0
    if spec["fixedShotSlots"] < 0:
        spec["fixedShotSlots"] = 0
    spec["defaultResolution"] = str(spec.get("defaultResolution") or "2K")
    source_spec = source if isinstance(source, dict) else {}
    sheet_aspect_ratio = str(
        row.get("sheetAspectRatio")
        or row.get("sheet_aspect_ratio")
        or row.get("aspectRatio")
        or row.get("aspect_ratio")
        or source_spec.get("sheetAspectRatio")
        or source_spec.get("sheet_aspect_ratio")
        or source_spec.get("aspectRatio")
        or source_spec.get("aspect_ratio")
        or spec.get("sheetAspectRatio")
        or spec.get("aspectRatio")
        or "16:9"
    )
    spec["sheetAspectRatio"] = sheet_aspect_ratio
    spec["aspectRatio"] = sheet_aspect_ratio
    return spec


def _normalize_storyboard_template(
    raw: dict[str, Any],
    *,
    source: str | None = None,
    fallback_layout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_item = raw if isinstance(raw, dict) else {}
    template_id = str(raw_item.get("id") or "").strip()
    label = str(raw_item.get("title") or raw_item.get("label") or raw_item.get("name") or template_id or "分镜图版式").strip()
    description = str(
        raw_item.get("description")
        or raw_item.get("desc")
        or raw_item.get("summary")
        or raw_item.get("shortDescription")
        or raw_item.get("short_description")
        or ""
    ).strip()
    template_source = source or str(raw_item.get("source") or "user_generated").strip() or "user_generated"
    layout_spec = _layout_spec_from_template(raw_item, fallback_layout)
    item: dict[str, Any] = {
        "id": template_id,
        "title": label,
        "label": label,
        "name": label,
        "desc": description,
        "description": description,
        "summary": description,
        "badge": str(raw_item.get("badge") or ("预设" if template_source == "builtin" else "自定义")).strip(),
        "source": template_source,
        "layoutSlots": str(raw_item.get("layoutSlots") or raw_item.get("layout_slots") or "flexible"),
    }
    item["fixedShotSlots"] = int(layout_spec.get("fixedShotSlots") or 0)
    item["minShotSlots"] = int(layout_spec.get("minShotSlots") or 1)
    item["maxShotSlots"] = int(layout_spec.get("maxShotSlots") or 0)
    item["layoutSpec"] = layout_spec
    item["layout_spec"] = layout_spec
    raw_required_sections = _string_list(raw_item.get("requiredSections") or raw_item.get("required_sections"))
    item["requiredSections"] = raw_required_sections or list(
        _REQUIRED_STORYBOARD_SECTIONS
    )
    item["required_sections"] = item["requiredSections"]
    item["prompt"] = _storyboard_template_text_value(raw_item.get("prompt"))
    for key in ("base_template_id", "derived_from_template_id", "created_at", "updated_at"):
        if raw_item.get(key) not in (None, ""):
            item[key] = raw_item.get(key)
    effective_prompt = _storyboard_effective_prompt_text(
        item["prompt"],
        template_id,
        include_layout_policy=template_source == "builtin",
    )
    item["effectivePrompt"] = effective_prompt
    return item


def _storyboard_template_storage_rows(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in row.items() if key != "effectivePrompt"} for row in templates]


def _find_storyboard_template(
    template_id: str | None,
    templates: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    text = str(template_id or "").strip()
    if not text:
        return None
    source_templates = templates if templates is not None else load_storyboard_templates()
    for item in source_templates:
        if str(item.get("id") or "").strip() == text:
            return item
    return None


def _builtin_storyboard_prompt_rules(template_id: str) -> str:
    if template_id == STORYBOARD_TEMPLATE_NARRATIVE:
        return _STORYBOARD_TEMPLATE_NARRATIVE_PROMPT_RULES
    if template_id == STORYBOARD_TEMPLATE_BLOCKING:
        return _STORYBOARD_TEMPLATE_BLOCKING_PROMPT_RULES
    if template_id == STORYBOARD_TEMPLATE_IMAGE_GRID:
        return _STORYBOARD_TEMPLATE_IMAGE_GRID_PROMPT_RULES
    if template_id == STORYBOARD_TEMPLATE_NUMBERED_GRID:
        return _STORYBOARD_TEMPLATE_NUMBERED_GRID_PROMPT_RULES
    if template_id == STORYBOARD_TEMPLATE_FILMSTRIP:
        return _STORYBOARD_TEMPLATE_FILMSTRIP_PROMPT_RULES
    raise ValueError(f"未知预设分镜图版式：{template_id}")


def _storyboard_template_base_id(value: Any) -> str:
    template_id = storyboard_template_id(value)
    template = _find_storyboard_template(template_id)
    if template and template.get("source") != "builtin":
        return str(
            template.get("base_template_id")
            or template.get("derived_from_template_id")
            or STORYBOARD_TEMPLATE_DEFAULT
        ).strip() or STORYBOARD_TEMPLATE_DEFAULT
    return template_id


def storyboard_template_single_panel_prompt_rules(value: Any) -> str:
    template_id = _storyboard_template_base_id(value)
    rules = {
        STORYBOARD_TEMPLATE_NARRATIVE: _STORYBOARD_SINGLE_PANEL_NARRATIVE_PROMPT_RULES,
        STORYBOARD_TEMPLATE_BLOCKING: _STORYBOARD_SINGLE_PANEL_BLOCKING_PROMPT_RULES,
        STORYBOARD_TEMPLATE_IMAGE_GRID: _STORYBOARD_SINGLE_PANEL_IMAGE_GRID_PROMPT_RULES,
        STORYBOARD_TEMPLATE_NUMBERED_GRID: _STORYBOARD_SINGLE_PANEL_NUMBERED_GRID_PROMPT_RULES,
        STORYBOARD_TEMPLATE_FILMSTRIP: _STORYBOARD_SINGLE_PANEL_FILMSTRIP_PROMPT_RULES,
    }
    return rules.get(template_id, _STORYBOARD_SINGLE_PANEL_NARRATIVE_PROMPT_RULES)


def _storyboard_template_text_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return "\n".join(_string_list(value)).strip()


def _storyboard_prompt_has_base_contract(text: Any) -> bool:
    value = str(text or "")
    return "故事板基础合同" in value and "分镜图版式规则只决定" in value


def _storyboard_prompt_has_layout_policy(text: Any) -> bool:
    value = str(text or "")
    has_layout_title = "【版式空间分配规则】" in value or "【条件版式与空间分配规则】" in value
    return has_layout_title and (
        "空间分配固定为" in value
        or "主要镜头画格区约占整张工作页 100%" in value
    )


def _storyboard_effective_prompt_text(
    prompt: Any,
    template_id: str | None = None,
    *,
    include_layout_policy: bool = True,
) -> str:
    text = str(prompt or "").strip()
    if not text:
        text = _builtin_storyboard_prompt_rules(template_id or STORYBOARD_TEMPLATE_DEFAULT)
    parts: list[str] = []
    if not _storyboard_prompt_has_base_contract(text):
        parts.append(_STORYBOARD_TEMPLATE_BASE_CONTRACT)
    if include_layout_policy and not _storyboard_prompt_has_layout_policy(text):
        parts.append(_storyboard_layout_policy_prompt(template_id or STORYBOARD_TEMPLATE_DEFAULT))
    parts.append(text)
    return "\n".join(part for part in parts if part)


def load_storyboard_templates() -> list[dict[str, Any]]:
    ensure_store()
    defaults = _default_storyboard_templates()
    default_ids = {str(item.get("id") or "") for item in defaults}
    data = _read_json(GLOBAL_STORYBOARD_TEMPLATES_PATH, defaults)
    if not isinstance(data, list):
        data = []
    changed = data != defaults if not GLOBAL_STORYBOARD_TEMPLATES_PATH.exists() else False
    custom_templates: list[dict[str, Any]] = []
    defaults_by_id = {str(item.get("id") or ""): item for item in defaults}
    for raw in data:
        if not isinstance(raw, dict):
            changed = True
            continue
        template_id = str(raw.get("id") or "").strip()
        if not template_id:
            changed = True
            continue
        if template_id in default_ids:
            if raw.get("source") != "builtin":
                changed = True
            continue
        fallback_layout = None
        base_id = str(raw.get("base_template_id") or raw.get("derived_from_template_id") or "").strip()
        if base_id and base_id in defaults_by_id:
            fallback_layout = defaults_by_id[base_id].get("layoutSpec")
        custom_templates.append(
            _normalize_storyboard_template(
                raw,
                source="user_generated",
                fallback_layout=fallback_layout,
            )
        )
    merged = defaults + custom_templates
    stored = _storyboard_template_storage_rows(merged)
    if changed or data != stored:
        _write_json(GLOBAL_STORYBOARD_TEMPLATES_PATH, stored)
    return merged


def get_storyboard_templates() -> dict[str, Any]:
    return {"templates": load_storyboard_templates()}


def _custom_storyboard_template_id(name: str | None = None) -> str:
    text = str(name or "").strip()
    ascii_slug = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")
    ascii_slug = re.sub(r"_+", "_", ascii_slug)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8] if text else hashlib.sha1(_now().encode("utf-8")).hexdigest()[:8]
    suffix = ascii_slug[:32] or digest
    return f"storyboard_custom_{suffix}_{digest}"[:79]


def save_storyboard_template(payload: dict[str, Any]) -> dict[str, Any]:
    template = payload.get("template") if isinstance(payload.get("template"), dict) else payload
    if not isinstance(template, dict):
        raise ValueError("分镜图版式数据无效")
    template = dict(template)
    templates = load_storyboard_templates()
    builtin_ids = {str(item.get("id") or "") for item in _default_storyboard_templates()}
    template_id = str(template.get("id") or "").strip()
    if not template_id:
        template_id = _custom_storyboard_template_id(template.get("title") or template.get("name") or template.get("label"))
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,79}", template_id):
        raise ValueError("版式 ID 必须是小写字母、数字和下划线")
    if template_id in builtin_ids:
        raise ValueError("预设分镜图版式不能被覆盖")

    name = str(template.get("title") or template.get("name") or template.get("label") or "").strip()
    if not name:
        raise ValueError("分镜图版式标题不能为空")
    description = str(
        template.get("description")
        or template.get("desc")
        or template.get("summary")
        or template.get("shortDescription")
        or template.get("short_description")
        or ""
    ).strip()
    if not description:
        raise ValueError("分镜图版式描述不能为空")
    prompt_text = _storyboard_template_text_value(template.get("prompt"))
    if not prompt_text:
        raise ValueError("分镜图版式规则不能为空")

    normalized_name = re.sub(r"\s+", " ", name).strip().casefold()
    if any(
        re.sub(r"\s+", " ", str(item.get("name") or item.get("label") or "").strip()).casefold() == normalized_name
        and str(item.get("id") or "") != template_id
        and item.get("source") != "builtin"
        for item in templates
    ):
        raise ValueError("分镜图版式标题已存在")

    requested_base_id = str(
        template.get("base_template_id")
        or template.get("derived_from_template_id")
        or ""
    ).strip()
    if not requested_base_id:
        raise ValueError("来源分镜图版式不能为空")
    base_id = storyboard_template_id(requested_base_id)
    base = _find_storyboard_template(base_id, templates)
    if not base:
        raise ValueError("来源分镜图版式不存在")
    existing = _find_storyboard_template(template_id, templates)

    saved_template = copy.deepcopy(base)
    saved_template["id"] = template_id
    saved_template["title"] = name
    saved_template["label"] = name
    saved_template["name"] = name
    saved_template["desc"] = description
    saved_template["description"] = description
    saved_template["summary"] = description
    saved_template.pop("feature", None)
    saved_template["badge"] = "自定义"
    saved_template["source"] = "user_generated"
    saved_template["base_template_id"] = base_id if base.get("source") == "builtin" else str(base.get("base_template_id") or base_id)
    saved_template["derived_from_template_id"] = base_id
    saved_template["prompt"] = prompt_text
    saved_template["layoutSpec"] = _layout_spec_from_template(template, base.get("layoutSpec"))
    saved_template["layout_spec"] = saved_template["layoutSpec"]
    saved_template["fixedShotSlots"] = int(saved_template["layoutSpec"].get("fixedShotSlots") or 0)
    saved_template["minShotSlots"] = int(saved_template["layoutSpec"].get("minShotSlots") or 1)
    saved_template["maxShotSlots"] = int(saved_template["layoutSpec"].get("maxShotSlots") or 0)
    raw_required_sections = _string_list(
        template.get("requiredSections") or template.get("required_sections")
    )
    saved_template["requiredSections"] = raw_required_sections or list(base.get("requiredSections") or _REQUIRED_STORYBOARD_SECTIONS)
    saved_template["required_sections"] = saved_template["requiredSections"]
    saved_template["created_at"] = (existing or {}).get("created_at") or _now()
    saved_template["updated_at"] = _now()
    saved_template = _normalize_storyboard_template(
        saved_template,
        source="user_generated",
        fallback_layout=base.get("layoutSpec") if isinstance(base.get("layoutSpec"), dict) else None,
    )

    next_templates = [item for item in templates if item.get("id") != template_id]
    next_templates.append(saved_template)
    _write_json(GLOBAL_STORYBOARD_TEMPLATES_PATH, _storyboard_template_storage_rows(next_templates))
    return {"success": True, "template": saved_template, "templates": load_storyboard_templates()}


def delete_storyboard_template(template_id: str | None) -> dict[str, Any]:
    template_id = str(template_id or "").strip()
    if not template_id:
        raise ValueError("分镜图版式 ID 不能为空")
    templates = load_storyboard_templates()
    target = _find_storyboard_template(template_id, templates)
    if not target:
        raise ValueError("分镜图版式不存在")
    builtin_ids = {str(item.get("id") or "") for item in _default_storyboard_templates()}
    if template_id in builtin_ids or target.get("source") == "builtin":
        raise ValueError("预设分镜图版式不能删除")
    next_templates = [item for item in templates if item.get("id") != template_id]
    _write_json(GLOBAL_STORYBOARD_TEMPLATES_PATH, _storyboard_template_storage_rows(next_templates))
    return {"success": True, "templateId": template_id, "templates": load_storyboard_templates()}


def storyboard_template_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return STORYBOARD_TEMPLATE_DEFAULT
    templates = load_storyboard_templates()
    direct = _find_storyboard_template(text, templates)
    if direct:
        return str(direct.get("id") or text)
    return text


def storyboard_template_label(value: Any) -> str:
    template_id = storyboard_template_id(value)
    row = _find_storyboard_template(template_id)
    if row:
        return str(row.get("title") or row.get("label") or row.get("name") or "叙事故事版")
    return template_id or "叙事故事版"


def storyboard_template_catalog() -> list[dict[str, Any]]:
    return [copy.deepcopy(row) for row in load_storyboard_templates()]


def storyboard_template_selection_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in load_storyboard_templates():
        rows.append(
            {
                "id": str(row.get("id") or ""),
                "title": str(row.get("title") or row.get("label") or row.get("name") or ""),
                "description": str(row.get("description") or row.get("desc") or row.get("summary") or ""),
            }
        )
    return rows


def storyboard_template_layout_spec(value: Any) -> dict[str, Any]:
    template_id = storyboard_template_id(value)
    template = _find_storyboard_template(template_id)
    if not template and str(value or "").strip():
        raise ValueError(f"分镜图版式不存在：{template_id}")
    return _layout_spec_from_template(template or {}, _default_layout_spec())


def storyboard_template_from_mapping(*rows: dict[str, Any] | None) -> str:
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in (
            "storyboardTemplate",
            "storyboard_template",
            "template",
            "templateId",
            "template_id",
        ):
            if row.get(key):
                return storyboard_template_id(row.get(key))
    return STORYBOARD_TEMPLATE_DEFAULT


def storyboard_template_prompt_rules(value: Any) -> str:
    template_id = storyboard_template_id(value)
    template = _find_storyboard_template(template_id)
    if not template:
        raise ValueError(f"分镜图版式不存在：{template_id}")
    if template and template.get("source") != "builtin":
        custom_prompt = _storyboard_template_text_value(template.get("prompt"))
        base_id = str(template.get("base_template_id") or template.get("derived_from_template_id") or STORYBOARD_TEMPLATE_DEFAULT)
        return _storyboard_effective_prompt_text(custom_prompt, base_id, include_layout_policy=False)
    if template:
        prompt = _storyboard_template_text_value(template.get("prompt"))
        if prompt:
            return _storyboard_effective_prompt_text(prompt, template_id, include_layout_policy=True)
    return _storyboard_effective_prompt_text(
        _builtin_storyboard_prompt_rules(template_id),
        template_id,
        include_layout_policy=True,
    )


__all__ = (
    "STORYBOARD_TEMPLATE_NARRATIVE",
    "STORYBOARD_TEMPLATE_BLOCKING",
    "STORYBOARD_TEMPLATE_IMAGE_GRID",
    "STORYBOARD_TEMPLATE_NUMBERED_GRID",
    "STORYBOARD_TEMPLATE_FILMSTRIP",
    "STORYBOARD_TEMPLATE_DEFAULT",
    "GLOBAL_STORYBOARD_TEMPLATES_PATH",
    "load_storyboard_templates",
    "get_storyboard_templates",
    "save_storyboard_template",
    "delete_storyboard_template",
    "storyboard_template_id",
    "storyboard_template_label",
    "storyboard_template_catalog",
    "storyboard_template_selection_catalog",
    "storyboard_template_layout_spec",
    "storyboard_template_layout_kind",
    "storyboard_panel_arrangement_rules",
    "storyboard_reference_brief",
    "storyboard_image_prompt_spec",
    "storyboard_template_from_mapping",
    "storyboard_template_prompt_rules",
    "storyboard_template_single_panel_prompt_rules",
)

# Preserve the implementation that was previously effective through package exports.
from .splitting_templates import _string_list
