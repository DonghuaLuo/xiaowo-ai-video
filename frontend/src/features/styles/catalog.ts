import type {
  CreationStyleMode,
  StyleCategory,
  StyleMode,
  StyleModeTabOption,
  StyleTemplateOption,
} from "@/features/styles/types"
import {
  GENERAL_CHARACTER_STYLE_PROMPT,
  GENERAL_CREATURE_STYLE_PROMPT,
  GENERAL_GLOBAL_STYLE_PROMPT,
  GENERAL_STYLE_TEMPLATE_ID,
} from "@/features/styles/general-style"

export const aspectOptions = ["16:9", "9:16"]

export const defaultEpisodeTargetUnits = 1000
export const defaultAssetExtractionTargetUnits = 5000
export const sourceLanguageOptions = [
  { id: "zh-CN", label: "中文" },
  { id: "zh-TW", label: "繁体" },
  { id: "en-US", label: "English" },
  { id: "vi-VN", label: "Tiếng Việt" },
]
export const videoRatioOptions = [
  {
    id: "16:9",
    name: "横屏 16:9",
    description: "适合横版屏幕、桌面端和宽画面叙事。",
  },
  {
    id: "9:16",
    name: "竖屏 9:16",
    description: "适合手机竖屏短视频和移动端浏览。",
  },
]

export const styleCategories: Array<{
  id: StyleCategory
  label: string
}> = [
  { id: "all", label: "全部" },
  { id: "general", label: "通用风格" },
  { id: "live_action", label: "真人短剧" },
  { id: "two_d", label: "2D动漫" },
  { id: "three_d", label: "3D动漫" },
]

export const creationStyleModeTabs: StyleModeTabOption<CreationStyleMode>[] = [
  { id: "template", label: "预设风格" },
  { id: "favorite", label: "收藏风格" },
  { id: "custom", label: "自定义风格" },
]

export const projectStyleModeTabs: StyleModeTabOption<StyleMode>[] = [
  { id: "template", label: "预设风格" },
  { id: "favorite", label: "收藏风格" },
  { id: "custom", label: "自定义风格" },
]

export const styleCategoryMeta: Record<
  Exclude<StyleCategory, "all" | "favorite">,
  { label: string; accent: string }
> = {
  general: {
    label: "通用风格",
    accent: "from-sky-500 via-fuchsia-500 to-amber-300",
  },
  live_action: {
    label: "真人短剧",
    accent: "from-rose-500 via-orange-400 to-amber-300",
  },
  two_d: {
    label: "2D动漫",
    accent: "from-amber-400 via-rose-500 to-pink-500",
  },
  three_d: {
    label: "3D动漫",
    accent: "from-violet-500 via-indigo-500 to-sky-400",
  },
}

export function aiVideoStyleTemplate({
  id,
  name,
  desc,
  category,
  prompt,
  assetPrompt,
  characterAssetPrompt,
  creatureAssetPrompt,
  visualTypeTags,
  defaultVisualTypeTag,
  thumbnailFile = `${id}.jpg`,
}: {
  id: string
  name: string
  desc: string
  category: Exclude<StyleCategory, "all" | "favorite">
  prompt: string
  assetPrompt?: string
  characterAssetPrompt?: string
  creatureAssetPrompt?: string
  visualTypeTags?: string[]
  defaultVisualTypeTag?: string
  thumbnailFile?: string
}): StyleTemplateOption {
  const meta = styleCategoryMeta[category]
  return {
    id,
    name,
    desc,
    category,
    categoryLabel: meta.label,
    accent: meta.accent,
    thumbnailFile,
    thumbnail_file: thumbnailFile,
    prompt,
    assetPrompt: assetPrompt ?? prompt,
    asset_prompt: assetPrompt ?? prompt,
    characterAssetPrompt,
    character_asset_prompt: characterAssetPrompt,
    creatureAssetPrompt,
    creature_asset_prompt: creatureAssetPrompt,
    visualTypeTags,
    visual_type_tags: visualTypeTags,
    defaultVisualTypeTag,
    default_visual_type_tag: defaultVisualTypeTag,
    source: "preset",
  }
}

export const styleTemplateOptions: StyleTemplateOption[] = [
  aiVideoStyleTemplate({
    id: "urban_boss_romance_drama",
    name: "现代都市 · 柔光真人",
    desc: "真人 / 现代都市 / 商业短剧质感",
    category: "live_action",
    prompt:
      "现代都市时代背景，真人影视短剧风格，现代商业影像质感，精致柔和布光，低对比暖色调，浅景深，高清电视剧画质，整体时代设定保持现代都市语境",
    thumbnailFile: "1.jpg",
  }),
  aiVideoStyleTemplate({
    id: "urban_workplace_comeback_drama",
    name: "现代都市 · 商务真人",
    desc: "真人 / 现代都市 / 明亮现实质感",
    category: "live_action",
    prompt:
      "现代都市商务时代背景，真人电视剧风格，干净高级商业影像质感，明亮柔和布光，低饱和自然调色，真实自然材质表现，高清写实画质，整体时代设定保持现代都市语境",
    thumbnailFile: "2.jpg",
  }),
  aiVideoStyleTemplate({
    id: "urban_marriage_reality_drama",
    name: "现代都市 · 生活真人",
    desc: "真人 / 现代生活 / 自然电视剧质感",
    category: "live_action",
    prompt:
      "现代都市生活时代背景，真人电视剧画风，柔和自然光，真实影像质感，细腻材质表现，低对比电影调色，高清写实画质，整体时代设定保持现代都市语境",
    thumbnailFile: "3.jpg",
  }),
  aiVideoStyleTemplate({
    id: "costume_palace_power_drama",
    name: "古代宫廷 · 厚重真人",
    desc: "真人 / 架空古代 / 古典电影质感",
    category: "live_action",
    prompt:
      "架空古代宫廷时代背景，真人古装影视风格，厚重古典美术质感，戏剧化光影，低饱和电影调色，精致布光，高清电影画质，整体时代设定保持古代宫廷语境",
    thumbnailFile: "4.jpg",
  }),
  aiVideoStyleTemplate({
    id: "costume_general_revenge_epic",
    name: "古代边塞 · 冷色真人",
    desc: "真人 / 架空古代 / 精致冷色影视感",
    category: "live_action",
    prompt:
      "架空古代边塞时代背景，真人古装影视风格，冷色高级调色，精致服化道质感，清晰明暗层次，自然柔和光影，高清影视画质，整体时代设定保持古代边塞语境",
    thumbnailFile: "5.jpg",
  }),
  aiVideoStyleTemplate({
    id: "costume_wuxia_heroine",
    name: "古代江湖 · 暗调真人",
    desc: "真人 / 古代江湖 / 港式武侠感",
    category: "live_action",
    prompt:
      "架空古代江湖时代背景，真人古装武侠影视风格，港式武侠电影质感，冷暖交错光影，飘逸材质表现，高反差暗调调色，高清电影画质，整体时代设定保持古代江湖语境",
    thumbnailFile: "6.jpg",
  }),
  aiVideoStyleTemplate({
    id: "xianxia_cultivation_sect",
    name: "古装玄幻 · 清亮2D",
    desc: "2D / 古代修仙 / 国风幻想插画",
    category: "two_d",
    prompt:
      "架空古代修仙玄幻时代背景，2D国风数字插画风格，东方高幻想美术气质，清亮柔和滤镜，轻盈飘逸材质感，细腻笔触，冷暖柔和光影，高清插画画质，整体时代设定保持古代玄幻语境",
    thumbnailFile: "7.jpg",
  }),
  aiVideoStyleTemplate({
    id: "xianxia_gods_demons_epic",
    name: "古装玄幻 · 厚涂2D",
    desc: "2D / 东方玄幻 / 史诗概念插画",
    category: "two_d",
    prompt:
      "架空古代东方玄幻时代背景，2D厚涂概念插画风格，国风高幻想美术体系，金色与冷蓝对比光，华丽材质层次，高密度细节表现，高清插画画质，整体时代设定保持古代玄幻语境",
    thumbnailFile: "8.jpg",
  }),
  aiVideoStyleTemplate({
    id: "xianxia_spirit_beast_shanhai",
    name: "上古山海 · 水墨2D",
    desc: "2D / 上古神话 / 水墨重彩国风",
    category: "two_d",
    prompt:
      "上古东方神话时代背景，2D水墨重彩国风插画风格，青金色调，水墨肌理与重彩层次融合，清透高质量画面，东方神话美术体系，高清插画画质，整体时代设定保持上古神话语境",
    thumbnailFile: "9.jpg",
  }),
  aiVideoStyleTemplate({
    id: "folk_strange_village",
    name: "近现代乡村 · 民俗真人",
    desc: "真人 / 近现代乡村 / 自然民俗影视质感",
    category: "live_action",
    prompt:
      "近现代中式乡村时代背景，真人民俗影视风格，自然低饱和色调，柔和冷暖光，干净细腻材质表现，生活化但画面精致，高清影视画质，整体时代设定保持近现代中式乡村语境",
    thumbnailFile: "10.jpg",
  }),
  aiVideoStyleTemplate({
    id: "folk_ghost_marriage_paper",
    name: "近现代民俗 · 低照度真人",
    desc: "真人 / 中式民俗 / 精致民俗影视质感",
    category: "live_action",
    prompt:
      "近现代中式民俗时代背景，真人民俗影视风格，暗色低饱和画面，低照度暖冷对比，细腻真实材质，柔和暗部层次，高清影视画质，整体时代设定保持近现代中式民俗语境",
    thumbnailFile: "11.jpg",
  }),
  aiVideoStyleTemplate({
    id: "folk_detective_revenge",
    name: "民国小镇 · 冷青真人",
    desc: "真人 / 民国近现代 / 冷青电影质感",
    category: "live_action",
    prompt:
      "民国或近现代中式小镇时代背景，真人电影风格，冷青低饱和电影调色，局部冷光照明，高反差暗部层次，真实质感滤镜，高清电影画质，整体时代设定保持近现代中式语境",
    thumbnailFile: "12.jpg",
  }),
  aiVideoStyleTemplate({
    id: "scifi_apocalypse_wasteland",
    name: "末世废土 · 真人电影",
    desc: "真人 / 末世废土 / 精致工业科幻感",
    category: "live_action",
    prompt:
      "末世废土时代背景，真人科幻影视风格，冷硬低饱和科幻调色，强逆光，精密工业材质，清晰硬朗暗部层次，高级大片质感，高清影视画质，整体世界观保持末世废土语境",
    thumbnailFile: "13.jpg",
  }),
  aiVideoStyleTemplate({
    id: "scifi_mecha_future_war",
    name: "末世机甲 · 3D电影",
    desc: "3D / 末世机甲 / 硬表面CG",
    category: "three_d",
    prompt:
      "末世机甲时代背景，3D硬表面科幻CG电影风格，冷硬工业色调，精密机械材质语言，高对比边缘光，体积光与真实材质渲染，影视级科幻画质，整体世界观保持末世机甲语境",
    thumbnailFile: "14.jpg",
  }),
  aiVideoStyleTemplate({
    id: "scifi_power_wasteland_future",
    name: "末世高武 · 科幻3D",
    desc: "3D / 末世高武 / 科幻CG质感",
    category: "three_d",
    prompt:
      "末世高武时代背景，3D动漫科幻CG风格，冷硬科幻美术体系，高对比冷暖光，锐利高光层次，真实材质渲染，高清科幻电影画质，整体世界观保持末世高武语境",
    thumbnailFile: "15.jpg",
  }),
  aiVideoStyleTemplate({
    id: "cyber_neon_city",
    name: "未来赛博 · 霓虹真人",
    desc: "真人 / 未来都市 / 赛博霓虹光色",
    category: "live_action",
    prompt:
      "未来赛博都市时代背景，真人科幻电影风格，高反光材质表现，紫蓝粉霓虹调色，全息感光影，高对比未来色彩，极致高清画质，整体世界观保持赛博都市语境",
    thumbnailFile: "16.jpg",
  }),
  aiVideoStyleTemplate({
    id: "cyber_underworld_night_city",
    name: "未来赛博 · 黑色真人",
    desc: "真人 / 未来都市 / 金属冷光电影",
    category: "live_action",
    prompt:
      "未来赛博都市时代背景，真人黑色电影风格，霓虹暗调，金属冷光质感，红蓝对比光，硬朗影像质感，真实质感滤镜，高清电影画质，整体世界观保持赛博都市语境",
    thumbnailFile: "17.jpg",
  }),
  aiVideoStyleTemplate({
    id: "cyber_tech_suspense",
    name: "近未来科技 · 冷光真人",
    desc: "真人 / 近未来科技 / 蓝绿冷光质感",
    category: "live_action",
    prompt:
      "近未来科技都市时代背景，真人科幻电影风格，冷白与蓝绿色科技光，透明感冷光材质，高反差暗部层次，干净锐利画面，精密光线控制，高清电影画质，整体世界观保持近未来科技语境",
    thumbnailFile: "18.jpg",
  }),
  aiVideoStyleTemplate({
    id: "comic_korean_romance_webtoon",
    name: "现代都市 · 韩漫2D",
    desc: "2D / 现代都市 / 半写实条漫",
    category: "two_d",
    prompt:
      "现代都市时代背景，2D韩式网络漫画风格，半写实动漫画风，简洁柔和线条，流畅渐变阴影，细腻高光质感，柔色调色彩方案，高清条漫画质，整体时代设定保持现代都市语境",
    thumbnailFile: "19.jpg",
  }),
  aiVideoStyleTemplate({
    id: "comic_jp_campus_youth",
    name: "现代校园 · 日系2D",
    desc: "2D / 现代校园 / 柔光赛璐珞",
    category: "two_d",
    prompt:
      "现代校园时代背景，2D日系动画风格，柔和光影效果，轻柔赛璐珞上色，柔和漫射光线，清晰干净的细轮廓线条，明亮温和色彩，高清动画画质，整体时代设定保持现代校园语境",
    thumbnailFile: "20.jpg",
  }),
  aiVideoStyleTemplate({
    id: "comic_cn_storyboard_webtoon",
    name: "古代江湖 · 国漫2D",
    desc: "2D / 古代江湖 / 条漫视觉质感",
    category: "two_d",
    prompt:
      "架空古代江湖时代背景，2D国漫条漫风格，清晰线稿，鲜明色块，分镜式视觉语言，利落线条节奏，适度光效层次，高清漫画质感，整体时代设定保持古代江湖语境",
    thumbnailFile: "21.jpg",
  }),
  aiVideoStyleTemplate({
    id: "guoman_3d_xuanhuan",
    name: "古装玄幻 · 国风3D",
    desc: "3D / 古装玄幻 / 精致国漫质感",
    category: "three_d",
    prompt:
      "架空古代玄幻修仙时代背景，国风3D动漫风格，影视级虚幻引擎渲染，精致3D建模，华丽东方材质感，电影级光影，高质量国漫画质，整体时代设定保持古代玄幻语境",
    thumbnailFile: "22.jpg",
  }),
  aiVideoStyleTemplate({
    id: "guoman_cel_shaded_battle",
    name: "现代高武 · 三渲二3D",
    desc: "3D / 现代高武 / 高饱和CG",
    category: "three_d",
    prompt:
      "现代高武时代背景，次世代高精三渲二3D动漫风格，干净赛璐璐线条，平滑3D线面表现，高饱和色彩，精细明暗层次，高质量游戏CG画质，整体时代设定保持现代高武语境",
    thumbnailFile: "23.jpg",
  }),
  aiVideoStyleTemplate({
    id: "guoman_unreal_game_cg",
    name: "古装玄幻 · 写实3D",
    desc: "3D / 古装玄幻 / 虚幻引擎CG",
    category: "three_d",
    prompt:
      "架空古代玄幻时代背景，写实3D游戏CG动画风格，影视级虚幻引擎渲染，真实材质与体积光，精细东方幻想材质层次，景深与电影级光影，高规格CG画质，整体时代设定保持古代玄幻语境",
    thumbnailFile: "24.jpg",
  }),
  aiVideoStyleTemplate({
    id: GENERAL_STYLE_TEMPLATE_ID,
    name: "通用风格",
    desc: "选择风格分类，主题视觉由小说概述自动分析",
    category: "general",
    prompt: GENERAL_GLOBAL_STYLE_PROMPT,
    assetPrompt: GENERAL_GLOBAL_STYLE_PROMPT,
    characterAssetPrompt: GENERAL_CHARACTER_STYLE_PROMPT,
    creatureAssetPrompt: GENERAL_CREATURE_STYLE_PROMPT,
    defaultVisualTypeTag: "",
    thumbnailFile: "25.jpg",
  }),
]
