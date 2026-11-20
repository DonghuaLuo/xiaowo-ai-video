# ai-video 前端功能定位图

用于按前端页面和用户描述快速定位文件，避免每次从全局搜索开始。

## 页面入口

- 首页 / 项目库 / 当前项目卡片：`pages/ProjectsPage.tsx`，项目卡片在 `features/projects/project-cards.tsx`
- 工作台 / 当前项目内部页面：`pages/WorkspacePage.tsx`
- 全局资产库：`pages/AssetLibraryPage.tsx`
- 项目设置：`pages/ProjectSettingsPage.tsx`
- 全局设置：`pages/SettingsPage.tsx`

## 业务功能

- 创建项目弹窗 / 自定义视觉风格上传与分析：`features/projects/creation-wizard.tsx`
- 项目中角色 / 场景 / 道具列表：`features/assets/asset-gallery.tsx`
- 全局资产库人物 / 场景 / 道具 / 收藏风格：`features/assets/asset-gallery.tsx`
- 资产列表加载 / 缓存合并 / 下线筛选 / 任务与项目事件：`features/assets/use-asset-gallery-records.ts`
- 资产编辑 / 图片上传与生成 / 版本操作 / 加入全局库：`features/assets/use-asset-gallery-actions.ts`
- 资产新增与批量弹窗：`features/assets/asset-form-dialogs.tsx`；全局资产选择：`asset-library-picker-dialog.tsx`；详情与版本弹窗：`asset-detail-dialogs.tsx`
- 收藏风格列表及加载 / 删除状态：`features/assets/favorite-style-gallery.tsx`
- 收藏风格编辑 / 删除确认 / 重名校验：`features/styles/favorite-style-dialogs.tsx`
- 视觉风格目录 / 预设风格：`features/styles/catalog.ts`
- 项目设置数据模型 / 保存 payload / 风格归一化：`features/project-settings/model.ts`
- 项目设置加载 / 基础配置 / 封面 / dirty 快照 / 单次保存：`features/project-settings/use-project-settings.ts`
- 项目视觉风格草稿 / 分析 / 收藏与阶段配置：`features/project-settings/use-project-style-editor.ts`；视图：`project-style-settings.tsx`；项目激活隔离：`use-project-settings-lifetime.ts`
- 分镜 / 故事板工作流画布：`features/storyboard/storyboard-workflow.tsx`
- 画布节点 / 连线 / 修订 / 事务去重的唯一状态：`features/storyboard/workflow-canvas-document.ts`，React 订阅在 `use-workflow-canvas-document.ts`
- 画布快照读取 / 增量回补 / 参考素材同步：`features/storyboard/use-workflow-document-sync.ts`
- 后端变更记录应用到画布：`features/storyboard/use-workflow-document-mutations.ts`
- 画布后端事件 / 任务结果投影：`features/storyboard/use-workflow-canvas-events.ts`
- 内联编辑队列 / 图片编辑 / 活动版本切换：`features/storyboard/use-workflow-node-editing.ts`
- 视频与图片生成 / 预检 / 跨分集请求保护：`features/storyboard/use-workflow-node-generation.ts`、`use-workflow-generation-preflight.ts`、`use-workflow-stage-generation.ts`
- 模型配置解析 / 供应商 / 参数预设 / 能力限制 / 默认视频时长：`features/storyboard/workflow-model-capabilities.ts`；画布、生成控件与预检直接复用，避免复制规则
- 工作链与任务节点创建 / 复制 / 删除：`features/storyboard/use-workflow-structure-actions.ts`
- 项目资产重命名 / 加入资产库 / 失败回滚：`features/storyboard/use-workflow-project-assets.ts`
- 自定义资产选择与导入 / 媒体复制粘贴：`features/storyboard/use-workflow-asset-picker.ts`、`use-workflow-asset-imports.ts`、`use-workflow-media-exchange.ts`
- 视频剪辑窗口编排：`features/storyboard/workflow-video-clip.tsx`；视频时间、裁剪和媒体结果契约：`video-clip-model.ts`
- 视频剪辑播放器 / 信息读取 / 时间和裁剪草稿 / 帧预览：`features/storyboard/use-video-clip-editor.ts`，视图在 `video-clip-player.tsx`、`video-clip-controls.tsx`
- 剪辑结果列表 / 剪切与截帧提交 / 删除互斥：`features/storyboard/use-video-clip-results.ts`，视图在 `video-clip-result-gallery.tsx`
- 剪辑结果拖回画布 / 指针取消和清理：`features/storyboard/use-video-clip-result-drag.ts`；源视频异步生命周期：`use-video-clip-activation.ts`
- 节点详情读取 / 撤销恢复 / 后台任务生命周期：`features/storyboard/use-workflow-canvas-details.ts`、`use-workflow-edit-history.ts`、`use-workflow-task-lifecycle.ts`
- 右侧智能体对话框 / 会话 / 消息 / 附件：`features/assistant/assistant-panel.tsx`
- 智能体会话加载 / 切换 / 发送 / 问答 / 中断与快照归并：`features/assistant/use-assistant-session.ts`
- 会话内并行文本智能体任务 / 顶部运行任务切换：`features/assistant/assistant-canvas-tasks.tsx`；剧本、分镜脚本、生成或优化视频提示词通过 `run_canvas_agent_task` 创建一次性独立执行上下文，按发起会话隔离，执行中无新增问答流程；单任务隐藏列表，超过五项滚动并显示总数；图片和视频沿用右上角任务栏
- 同一会话消息流 / 原有结果交互：`features/assistant/use-assistant-canvas-timeline.ts`、`assistant-canvas-task-model.ts`；后端按完成顺序将原结果和推荐操作写入所属普通会话，前端只读取该会话历史；任务结束自动移出顶部列表，后续修改另起一轮。执行标题见 `assistant-dispatch-panel.tsx`，约定见 `docs/parallel-canvas-agent-tasks.md`
- 智能体输入 / 附件 / 技能菜单和发送草稿：`features/assistant/use-assistant-composer.ts`，视图在 `assistant-composer.tsx`；项目级智能体模型与推理能力：`use-assistant-model-selection.ts`、`assistant-model-reasoning-picker.tsx`
- 智能体实时调度：`features/assistant/assistant-dispatch-panel.tsx`；最终回复渲染等待：`use-assistant-completion.ts`
- 工作台项目概述是否完成：`features/workspace/project-readiness.ts`
- 工作台概览展示 / 重新分析弹窗：`features/workspace/workspace-overview.tsx`
- 项目概述分析状态 / 同项目请求去重：`features/workspace/project-overview-analysis.ts`
- 工作台原文导入入口：`features/workspace/workspace-source-gate.tsx`
- 原文文件解码 / 总文件和片段映射：`features/workspace/workspace-source-model.ts`
- 工作台侧栏 / 分集和原文管理：`features/workspace/workspace-sidebar.tsx`
- 工作台任务面板 / 任务详情：`features/workspace/workspace-task-dock.tsx`
- 任务状态展示 / 任务定位规则：`features/workspace/workspace-task-model.ts`
- 工作台后端事件分类 / 资源更新判断：`features/workspace/workspace-events.ts`
- 工作台导航状态 / 本地存储键：`features/workspace/workspace-navigation.ts`
- 工作台页头 / 滚动容器 / 空画布：`features/workspace/workspace-layout.tsx`
- 工作台分集列表：`features/workspace/episodes.ts`
- 全局设置 - 模型配置：`features/settings/model-config.tsx`
- 全局设置 - 供应商配置：`features/settings/providers.tsx`
- 全局设置 - 改写模板与替换规则：`features/settings/script-adaptation-settings.tsx`、`text-replacement-settings.tsx`
- 通用模板工具与自适应文本框：`features/settings/shared-template.ts`、`auto-resize-textarea.tsx`；风格选择与编辑：`style-editors.tsx`
- 全局设置 - 导演规则：`features/settings/director-rules.tsx`

## 共享层

- 前后端调用封装：`hooks/useBackend.ts`
- 后端 API 类型和 helper：`backend.ts`
- 图片选择 / 图片 payload：`shared/image-picker.ts`、`shared/media.ts`
- 统一图片预览框：`shared/unified-media-frame.tsx`
- 通用确认弹窗：`shared/confirm-dialog.tsx`
- 应用路由和 view state 类型：`navigation.ts`
