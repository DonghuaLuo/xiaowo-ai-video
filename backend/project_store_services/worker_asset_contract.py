# -*- coding: utf-8 -*-
"""资产拆分的类型、阶段规则和模型输出契约。"""
from __future__ import annotations

import os
import re
from .assets import (
    _asset_type_label,
)
from .video_input_plan import (
    VIDEO_INPUT_MODES,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
)


_ASSET_TYPES = ("characters", "creatures", "scenes", "props")


_ANALYZE_ASSETS_BLOCKING_TYPE_SEMANTIC_REVIEW_TYPES: tuple[str, ...] = _ASSET_TYPES


_ANALYZE_ASSETS_TYPE_REWORK_LIMIT = 1


_ANALYZE_ASSETS_DESIGN_BATCH_LIMITS = {
    "characters": 6,
    "creatures": 4,
    "scenes": 8,
    "props": 8,
}


_ASSET_CATALOG_LIMIT_PER_TYPE = 60


_ASSET_CATALOG_DESC_CHARS = 100


_ASSET_CATALOG_PROMPT_PREVIEW_CHARS = 80


_ASSET_CATALOG_VOICE_STYLE_CHARS = 70


_ASSET_CONTEXT_FILE_READ_MAX_CHARS = 5000


_ASSET_SOURCE_CONTEXT_READ_MAX_CHARS = 5000


_ASSET_CONTEXT_FILE_CATALOG_LIMIT = 40


_ASSET_ADJACENT_SOURCE_CHARS = 800


_ASSET_CONTEXT_SNIPPET_LIMIT = 2


_ASSET_CONTEXT_SNIPPET_CHARS = 800


_ASSET_CONTEXT_SNIPPET_TOTAL_CHARS = 1800


_ASSET_CONTEXT_TEXT_SUFFIXES = {".txt", ".md", ".json", ".yaml", ".yml", ".csv"}


_ASSET_MATERIAL_ROUTE_LIMIT_PER_TYPE = 6


_ASSET_MATERIAL_DIGEST_FILE_LIMIT_PER_TYPE = 4


_ASSET_MATERIAL_DIGEST_FILE_CHARS = 3500


_ASSET_MATERIAL_DIGEST_TOTAL_CHARS = 9000


_ASSET_REVIEW_MAX_TURNS = 2


_ANALYZE_ASSETS_PHASE_CANDIDATE_MAX_TURNS = 1


_ANALYZE_ASSETS_PHASE_DESIGN_MAX_TURNS = 1


_ANALYZE_ASSETS_EXTRA_CANDIDATE_REVIEW_ENABLED = False


_ANALYZE_ASSETS_SCENE_DESIGN_BRIEF_ENABLED = False


_ANALYZE_ASSETS_PARALLEL_TYPE_CYCLES_ENABLED = True


_ANALYZE_ASSETS_BOUNDARY_SPEC_VERSION = "asset-boundary-spec-v25"


_ANALYZE_ASSETS_BOUNDARY_CORE_RULES = (
    "新增资产事实门槛：目标实体必须在当前 sourceText 中有清楚对象依据；依据可以来自现场或剧情内媒介。sourceEvidence 可概括多个相关片段，不要求逐字摘录；语义审查必须核对真实原文，扩展资料只能补足已出现候选的设计和连续性。",
    "资产价值正向门槛：不要求同时满足“具名、充分描述、复用价值”三项；当前 sourceText 已出现的实体只要满足任一有效组合即可进入保存判断：稳定专名/稳定身份加充分视觉或身份描述；稳定专名/稳定身份加明确复用、关系、线索或后续连续性价值；充分可视描述加明确复用、稳定取景或连续识别价值；角色/生物等非场景主体若在当前范围反复出现、反复互动或会被后续故事版稳定引用，也可保存为资产。场景还必须满足可直接作为工作链参考图的具体拍摄空间条件；道具类必须再服从 props 专属门槛，普通物件的反复使用或操作关系不等于连续识别价值。",
    "负向门槛：只被提到、清点、购买、持有、浏览、转述、一次性使用或作为信息出现，不自动成为资产；若同时没有稳定身份、没有足够描述、没有复用连续性、没有专门设计价值，应跳过、合并或留给分镜。",
    "关键生产例外：一次性出现但承载首场战斗/直接伤害、身份核验、仪式问事、技能学习或施放、交易试探、规则揭示、近景特写、主线伏笔、尾部新出场或下一段状态连续性的对象，不能仅因一次性、消耗品、信息载体、媒介内容或父级场景覆盖而静默跳过；候选/审查阶段应先保留或记录，再由读取相关资料后的身份阶段决定保存、合并或跳过。",
    "分镜归属：未通过资产价值门槛的通用对象、普通陈设、无特点物件、临时动作对象、信息承载对象、普通临时场景、父级范围、纯背景地点和世界观语境，应交给分镜提示词临场生成或仅作故事理解，不进入资产库，不生成临时资产或锚点。",
    "正文边界：只拆当前故事正文中的可视资产；作者话、广告、预告、其他作品简介、目录标签、文案说明和非剧情元信息不得生成资产，除非用户明确要求把这些内容也当作剧情处理。",
    "二级内容边界：屏幕画面、直播/新闻/短视频、榜单表格、资料条目、历史回放、传闻或他人转述是剧情内证据载体，不是自动删除理由；其中出现的人物、空间、生物或物件若满足正向门槛，应按真实资产评估；只承担临时信息展示且缺少稳定身份、描述和复用价值的内容才交给分镜。",
    "扩展资料边界：扩展资料可为当前 sourceText 已清楚出现的候选补足身份关系、外观方向、设定限制、后续复用价值和设计依据；不能凭扩展资料凭空新增当前 sourceText 没有出现的资产，也不能把没有候选指向的通用设定库整体拆成资产。",
    "覆盖策略：候选阶段以防漏为第一目标；候选审查只补漏、改类或合并明确同指的重复项，不在读取相关资料前裁决资产价值。最终新增、复用、合并或跳过统一由身份阶段决定，设计阶段不改变候选处置。纯信息内容、抽象资源概念、局部位置和临时状态不能因为被提到就成为独立资产。",
    "同一性：同一人/生物/空间/物件的精确名、概略名、关系称呼、别名、状态名、局部名只保留一个最清晰本体；服装、形态、损毁、成长、战斗、破损等变化不生成新资产或版本标注字段。",
)


_ANALYZE_ASSETS_PROP_RETENTION_RULES = (
    "保留门槛：正文或相关资料须支持独立专属身份、独特可视设计、脱离所属整体仍需连续识别的核心线索价值，或必须按同一外观管理的生产需要；这些需要不能由角色、场景母版或分镜临场生成充分承载。类型母版不要求唯一实物，但须有稳定且值得复用的视觉体系；关键道具不因仅出现一次或未写全外貌而排除。",
    "跳过门槛：普通生活/工作用品、通用设备、工具、陈设及临时动作载体，若主要承担日常使用、收纳、信息传递、资源消耗或环境填充，应并入角色、场景或分镜。反复出现、被同一角色长期使用、参与日常情节、承载情绪或局部特写，都不自动构成独立建卡理由；以持有人命名也不等于独立专属身份。只有满足上述保留门槛才例外，不能按物品类别或出现媒介一律排除。",
)


_ANALYZE_ASSETS_BOUNDARY_TYPE_RULES: dict[str, tuple[str, ...]] = {
    "characters": (
        "角色：人类和具有人物身份、稳定人格或明确个体边界的人形主体；人形灵体、鬼魂、妖魔、机械生命等只要人物边界成立也归角色。",
        "角色保存条件：当前范围有可拍人形本体、现场行动、现场对话、持续同行、承担当前画面关系，或有共享视觉系统并会复用的人形群体。稳定具名/身份的主体，若有充分身份/视觉描述、明确关系作用、反复交互或后续复用需要中的任一项，也满足保存条件；身份阶段确认同一性后应复用或新增，不再附加必须现场出镜、必须有外貌或必须已知后续剧情的门槛。聊天、电话、头像、档案、直播、书信、回忆和转述只是出现方式，不降低满足上述条件的主体价值。",
        "角色跳过：一次性名单、背景提及、称呼标签、旁白举例或媒介临时人物，只有不满足任何角色保留条件时才跳过；缺少外貌描述、现场行动或后续复用信息，不能否定已有的稳定身份和明确关系作用。合并仅表示同一主体或同一群体母版，关系相近、共同背景、共同职能不表示身份相同。",
        "媒介人物边界：媒介内出现不是删除理由；若屏幕、直播、新闻、短视频、资料画面、历史影像或他人转述中的人形主体拥有稳定姓名/身份，并有充分描述或后续关系/复用价值，应按角色资产评估。匿名、无描述、无连续性的临时人物才交给分镜临场生成。",
        "角色群体：仅在群体有共享职业/阵营/组织视觉系统且需要复用时保留；设计对象是服饰体系、装备层级、身份标识、色彩材质和整体秩序，不固定单个成员脸型、五官、年龄或唯一长相。",
    ),
    "creatures": (
        "生物：非人形活体、非人形灵体或非人形群体等可视非人形主体；有人形一面且人物身份成立的主体归角色。",
        "生物保留：当前范围出现独立非人形本体、行动/感知/攻击/交流/异常活体化/灵体化，或会影响后续视觉连续性的稳定个体/群体。",
        "关键一次性生物：若非人形活体承担首场战斗、直接造成伤害、暴露世界规则、触发主角状态变化，或原文给出完整外观与动作闭环，应先保留为生物候选；身份阶段结合资料判断是保存物种母版、合并到同一群体，还是跳过并说明归属。",
        "生物跳过/合并：普通生态、材料性生命、背景生命群落只作环境或资源；宠物、伴生或饲养关系中的非人形活体，只有具备稳定归属、独立生活空间、独立行为，或解释核心状态并影响连续性时才保留。",
        "过场威胁边界：非人形活体若只是普通一次性冲出、经过、被击退、被杀死、制造危险或作为背景怪物出现，且没有独特身份、持续追踪、反复引用、关键生产作用或可复用物种母版价值，应交给分镜动作生成，不保存为生物资产。",
        "生物群体：同一物种群体或同一来源群体不因地点、数量、显隐、攻击动作、成长或变异状态拆成多份；泛称威胁、普通怪群、背景动物群或只表示危险来源的混合群体，若原文与相关资料均不支持共同物种/来源、稳定外观锚点和复用母版价值，身份阶段应跳过并说明场景归属，不能由设计阶段勉强包装。",
        "宠物边界：仅被饲养、喂养、提到归属、放在笼舍/饲养空间中，或作为主题类比的普通宠物，不自动保存为生物资产；只有当前范围给出可辨识独特外观、姓名/身份、独立行动连续性、长期陪伴关系或后续分镜必须稳定引用时才保留，否则并入其生活空间或镜头提示词。",
    ),
    "scenes": (
        "场景：可直接作为工作链参考图的具体拍摄空间；名称必须指向可进入、可取景、可生成空场景母版的空间本体。",
        "场景保留：独立房间、完整室内外空间、明确切换并承载关键事件/对话/行动转折/任务规则的具体空间，可按归属、父空间、功能或方位命名；保存前必须确认它不是纯背景地点，而是后续分镜能直接引用的拍摄空间。",
        "普通命名空间：具体完整空间承载明确行动段落、关键对话或冲突时，即使只出现一次、建筑普通、外观描写少，也有跨镜头保持空间一致的价值，应保留并克制补全环境。仅作为地理定位、关系范围、无行动展开的一次经过时可跳过；事件临时不等于空间不存在。",
        "独立空间单元：大型环境中若出现可进入、可安置、可停留或可反复引用的独立空间单元，且具备独立功能、规则边界或稳定可见形态，不能被父级大场景吞掉；父级只提供归属或世界观语境时不保存为场景资产。",
        "规则空间单元：具备庇护、驻扎、居住、停留、关押、交易、管理、系统分配或组织分配等稳定规则的可进入空间单元或同类空间组，只有后续分镜需要直接参考其空间母版时才进入场景候选评估。",
        "空间类型归属：可进入、可居住、可停留、可管理或由规则分配的空间单元，即使名称像物品，也优先按场景评估；只有不可进入且作为实体器物被长期持握/操作时，才考虑道具。",
        "同类空间组：多个同类空间单元若共享稳定外观类型、规则功能或管理边界，并需要后续工作链直接引用，可以保存为类型母版或群体场景；普通无特点重复背景、父级范围或世界观区域不保存为场景资产。",
        "物件尺度空间：笼舍、箱体、柜体、设备仓、展示柜、容器、家具内区等物件尺度空间，若只是房间内陈设、饲养/储物/展示附属功能或一次性近景，不作为场景资产；只有它是后续反复进入、操作、管理或取景的核心空间母版时才保留，否则并入父级房间或镜头提示词。",
        "普通附属房间：从属于已保存父级居住/工作空间的普通功能间，若只因一次日常动作、路过、打开、取放或一句功能描述出现，且缺少独立结构、独特陈设、反复行动或后续稳定取景价值，应并入父级空间；只有承担明确行动段落、稳定物资/设备体系或后续反复引用时才单独保存。",
        "场景跳过/合并：局部功能区、角落、墙面、床边、门口、柜台、设备界面、媒介画面、临时停留点、父级范围、组织/社会范围、世界观地理背景和纯语境地点，没有直接拍摄空间母版价值时不进入 scenes。",
        "场景层级：父级地点只作归属、外墙、入口、远景、势力范围、背景定位或世界观语境时，不重复保存；相邻自然边界若只是经过/瞥见/说明分隔，缺少独立行动或反复取景功能，应并入相邻完整空间。",
        "场景命名：不得把人物状态、动作、受伤、昏迷、躲藏、战斗、救援、临时用途、事件结果、行政/势力归属或关系语境写成空间名或长期功能。",
    ),
    "props": (
        "道具：具有独立视觉管理需要的实体器物或稳定类型母版，不是所有可见、反复使用物件的清单。",
        "事实与价值分开判断：当前 sourceText 必须确实出现该对象；已匹配的扩展资料可补足其身份、外观、设定限制和后续连续性。不能要求正文独自写全外观，也不能用资料新增正文未出现的对象。",
        *_ANALYZE_ASSETS_PROP_RETENTION_RULES,
        "承载边界：所属角色、场景或器物母版能够承载的结构、标记、穿戴、陈设及普通附属载体，用 part_of 记录所属候选而不另建卡；没有所属候选且无需独立母版时用 skip 留给分镜。可单独操作、替换或交换只是使用方式，须满足保留门槛才独立建卡；重要识别细节和局部特写也可由整体母版承载。",
        "因果依据：同处一个空间、出现在相邻句子或常识上能用于某件事，不证明该物件实际参与了关键行动；不能把用途猜测升级为核心剧情作用、独立身份或连续性。保留理由须指出原文或资料实际支持的独立生产需要，而非仅称它有功能、可设计或有辨识度。",
        "粒度与身份：同一个实物的持有人、位置、状态变化通常复用；同类但有独立身份和连续性的实物须区分。功能、数量或等级变化不自动拆新资产，同一体系的类型母版与具体实例不可重复保存。",
        "设计约束：保留理由必须在设计前由原文或相关资料成立；能补出外观不等于需要独立资产。未写明的外观允许做一致、克制的影视化设计，但不得把推断写成已发生剧情事实，也不能靠拟补的纹理、磨损、结构、稀有度、能力、历史或后续情节反过来证明保留。",
    ),
}


_ANALYZE_ASSETS_NATURAL_LANGUAGE_FIELDS = ("desc", "assetImagePrompt", "voiceStyle", "designRationale")


_NATURAL_LANGUAGE_FORBIDDEN_LATIN_RE = re.compile(r"(?<![A-Za-z])(?=[A-Za-z]{3,}\b)[A-Za-z]*[a-z][A-Za-z]*(?![A-Za-z])")


_ANALYZE_ASSETS_KEEP_DECISIONS = {
    "keep",
    "keep_new",
    "reuse_existing",
    "reuse",
    "保留",
    "新增",
    "复用",
    "复用已有",
}


_ANALYZE_ASSETS_NEW_DESIGN_DECISIONS = {
    "keep",
    "keep_new",
    "new",
    "create_new",
    "新增",
    "保留",
}


_ANALYZE_ASSETS_REUSE_DECISIONS = {
    "reuse_existing",
    "reuse",
    "existing",
    "merge_existing",
    "same_as_existing",
    "duplicate",
    "复用",
    "复用已有",
    "合并已有",
    "同一资产",
}


_ANALYZE_ASSETS_SKIP_DECISIONS = {
    "skip",
    "skipped",
    "remove",
    "drop",
    "delete",
    "ignored",
    "ignore",
    "跳过",
    "删除",
    "移除",
    "不保留",
}


_ANALYZE_ASSETS_MERGE_DECISIONS = {
    "merge",
    "merged",
    "merge_same_range",
    "same_range_merge",
    "合并",
    "并入",
}


_ANALYZE_ASSETS_AUDIT_PLACEHOLDER_MARKERS = (
    "候选 ID",
    "候选 id",
    "candidate id",
    "相关候选",
    "被评估提及",
    "被合并候选",
    "原候选名或别名",
    "合并到的规范资产名",
    "被跳过候选",
    "被跳过提及",
    "如来自候选清单可填写",
    "character|creature|scene|prop",
    "keep_new|merge|skip|unresolved",
    "极短理由",
)


_ALLOWED_SHOT_GENERATION_STRATEGIES = (
    "storyboard_multi_shot",
)


_ALLOWED_VIDEO_INPUT_MODES = VIDEO_INPUT_MODES


_STORYBOARD_PLOT_MIN_COUNT = 1


_STORYBOARD_SEGMENT_MIN_SHOTS = 1


_STORYBOARD_SEGMENT_MAX_SHOTS = 5


_BACKEND_ROOT = Path(os.getcwd()).resolve()






_DISALLOWED_WORKER_OUTPUT_KEYS = {
    "episode",
    "episodes",
    "shotPlan",
    "shot_plan",
    "episodeShotPlan",
    "episode_shot_plan",
    "workflow",
    "canvasWorkflow",
    "canvas_workflow",
    "generationConfig",
    "generation_config",
    "generation",
    "existingAssets",
    "skippedExisting",
}


_DISALLOWED_ASSET_ITEM_KEYS = {
    "prompts",
    "prompt",
    "asset_image_prompt",
    "imagePrompt",
    "image_prompt",
    "visualSpec",
    "visual_spec",
    "continuity",
    "generation",
    "generationConfig",
    "generation_config",
    "tag",
    "tags",
    "stateTag",
    "state_tag",
    "stateTags",
    "state_tags",
}


_SCENE_REFERENCE_ROLE_WORK_CHAIN = "work_chain_reference"


_SCENE_REFERENCE_ROLE_CONTEXT_ONLY = "context_only"


_SCENE_REFERENCE_ROLE_VALUES = {
    _SCENE_REFERENCE_ROLE_WORK_CHAIN,
    _SCENE_REFERENCE_ROLE_CONTEXT_ONLY,
}


_SHOT_DISALLOWED_KEYS = {
    "characters",
    "scenes",
    "props",
    "assets",
    "assetBatch",
    "asset_batch",
    "workflow",
    "canvasWorkflow",
    "canvas_workflow",
    "generation",
    "generationConfig",
    "generation_config",
    "generationTasks",
    "generation_tasks",
    "generationRequests",
    "generation_requests",
    "imageGeneration",
    "image_generation",
    "videoGeneration",
    "video_generation",
    "mediaGeneration",
    "media_generation",
}










_WORKER_WORK_DEFINITIONS: dict[str, dict[str, Any]] = {
    "analyze-assets": {
        "workType": "asset_extraction",
        "label": "资产拆分",
        "description": "理解已提交原文范围及必要故事上下文，拆分并设计可用于 AI 视频生成的角色、生物、场景和道具资产。",
        "constraintFocus": [
            "角色、生物、场景、道具的拆分口径",
            "哪些内容应跳过、合并或保留",
            "角色阶段、场景空间和关键道具的连续性",
            "命名、视觉设计、资产母版提示词和角色声线设计的个人偏好",
            "遗漏检查、重复资产合并和设计合理性要求",
        ],
    },

}






def _analyze_assets_boundary_spec_text(
    *,
    stage: str = "",
    asset_types: tuple[str, ...] | list[str] | None = None,
) -> str:
    selected = [asset_type for asset_type in (asset_types or _ASSET_TYPES) if asset_type in _ASSET_TYPES]
    if not selected:
        selected = list(_ASSET_TYPES)
    lines = [f"asset_boundary_spec: {_ANALYZE_ASSETS_BOUNDARY_SPEC_VERSION}", "通用边界："]
    lines.extend(f"- {rule}" for rule in _ANALYZE_ASSETS_BOUNDARY_CORE_RULES)
    lines.append("类型边界：")
    for asset_type in selected:
        label = _asset_type_label(asset_type)
        lines.append(f"{label}（{asset_type}）：")
        lines.extend(f"- {rule}" for rule in _ANALYZE_ASSETS_BOUNDARY_TYPE_RULES.get(asset_type, ()))
    if stage:
        lines.append(f"本阶段必须服从以上统一规范；stage={stage}。")
    return "\n".join(lines)


def _scene_reference_role(row: dict[str, Any]) -> str:
    if not isinstance(row, dict):
        return ""
    role = str(row.get("sceneReferenceRole") or row.get("scene_reference_role") or "").strip().lower()
    return role if role in _SCENE_REFERENCE_ROLE_VALUES else ""


def _apply_scene_reference_role(item: dict[str, Any], row: dict[str, Any]) -> str:
    role = _scene_reference_role(row)
    if role:
        item["sceneReferenceRole"] = role
    else:
        item.pop("sceneReferenceRole", None)
    return role
