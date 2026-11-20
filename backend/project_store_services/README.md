# 后端业务定位

handler 协议保持在后端根目录。这个包按业务职责提供实现。修改实现时优先找到下表中的实际所有者，避免增加转发函数、星号导入或新的命名空间注入。

| 修改内容 | 主要实现 |
| --- | --- |
| 工作流输入关联和解析 | `workflow_input_links.py`、`workflow_input_resolution.py` |
| 工作流投影与跨分集交接 | `workflow_projection.py`、`workflow_visual_handoff.py` |
| 节点创建、复制、布局/身份更新、删除 | `workflow_canvas_creation.py`、`workflow_canvas_asset_copy.py`、`workflow_canvas_updates.py`、`workflow_canvas_deletion.py` |
| 节点历史记录与内联编辑/恢复 | `workflow_edit_history.py`、`workflow_inline_editing.py` |
| 画布资产解析与材料绑定 | `workflow_asset_resolution.py`、`workflow_material_bindings.py` |
| 任务视图、质量评估与影视文本 | `workflow_task_queries.py`、`workflow_variant_quality.py`、`workflow_cinematic_script.py` |
| 分镜/视频生成上下文 | `workflow_generation_context.py` |
| 智能体分镜脚本资料读取、校验与提交 | `agent_director_plan_tools.py`、`director_plan_contract.py`、`storyboard_allocation.py` |
| 分镜提示词、资产语气与生成上下文组装 | `workflow_storyboard_prompts.py` |
| 分镜图片、视觉交接与视频生成编排 | `workflow_media_generation.py` |
| 生成配置、能力与预检 | `generation_config.py`、`generation_reference_validation.py`、`generation_preflight.py` |
| 视频生成节点的来源、参考资产、提示词、写回 | `video_task_card_context.py`、`video_task_card_references.py`、`video_task_card_prompts.py`、`video_task_cards.py` |
| 工作链规划投影 | `planning_workflow_builder.py` 及同前缀领域模块 |
| 文本模型协议与结构化输出 | `model_text_client.py` |
| 模型选择与生成契约 | `model_provider_config.py`、`model_generation_contract.py` |
| 风格模型分析 | `model_style_analysis.py` |
| 图片/视频引用媒体准备 | `provider_reference_media.py`、`video_provider_references.py` |
| 图片生成、重试与保存 | `storyboard_image_generation.py` |
| 视频提示词与供应商请求 | `video_generation_prompt.py`、`storyboard_video_generation.py` |
| 任务持久化、取消、结果提交保护 | `task_storage.py`、`task_control.py` |
| 任务生命周期、事件、查询 | `task_lifecycle.py`、`task_events.py`、`task_queries.py` |
| 视频任务输入、提交、轮询、恢复 | `video_task_requests.py`、`video_task_submission.py`、`video_task_execution.py`、`video_task_provider.py` |
| 分镜图片的一次性任务调度 | `storyboard_task_execution.py` |
| 智能体会话、任务运行与结构化任务路由 | `agent_native_chat.py`、`agent_run_store.py`、`agent_skill_protocol.py` |
| 智能体业务数据读取、校验与提交 | `agent_*_tools.py`、`agent_native_episode.py` |
| 智能体单回合模型调用与流处理 | `agent_native_chat.py`、`agent_turn_stream.py`、`utils/agent_sdk_runtime.py` |
| 智能体工具分派与返回值 | `agent_turn_tools.py`、`agent_tool_results.py` |
| 智能体回合后业务路由 | `agent_session_lifecycle.py` 及动作所属控制器 |
| 资产结果校验与事务写入 | `worker_asset_validation.py`、`asset_analysis_commit.py` |
| 原文文件导入与读写、索引 | `source_text_store.py`、`source_index.py` |
| 原文覆盖账本、资产批次材料、边界契约 | `source_coverage.py`、`source_asset_batches.py`、`source_boundary_contract.py` |
| 分集/资产范围提议与提交 | `episode_boundary_planning.py`、`asset_range_planning.py` |
| 项目资源修订与概览分析 | `project_resource_revisions.py`、`project_overview.py` |
| 资产文本契约、范围绑定、入库 | `asset_text_contract.py`、`asset_range_bindings.py`、`asset_text_ingestion.py` |
| 资产/原文引用范围与计划文档 | `asset_reference_scope.py`、`source_reference_scope.py`、`episode_plan_documents.py` |
| 镜头修订同步到提示词 | `shot_prompt_updates.py` |

## 画布存储

| 职责 | 文件 |
| --- | --- |
| SQLite schema、连接、写锁、修订事务 | `canvas_store_database.py` |
| 行记录编解码、摘要、签名与变更结果结构 | `canvas_store_records.py` |
| 来源/版本引用索引 | `canvas_store_indexes.py` |
| 快照、邻域、卡片、任务上下文只读查询 | `canvas_store_queries.py` |
| 调用者事务内的 SQL 写入步骤 | `canvas_store_rows.py` |
| 文档与任务记录事务 | `canvas_store_documents.py` |
| 画布结构、节点增删、卡片补丁完整事务 | `canvas_store_mutations.py` |
| 结果版本提交、激活与删除事务 | `canvas_store_results.py` |

写入口统一使用数据库域的同一把锁。`_in_conn` 函数接受调用者传入的 SQLite 连接，不自行开启另一条连接或提前提交；一次业务变更中的修订、节点、版本与变更记录应保持同一事务。图像生成与任务执行的阶段对象属于单次请求，不承载跨任务共享状态。

## 模块边界与验证

`workflows.py`、`sources.py`、`planning.py`、`tasks.py`、`model_clients.py`、`canvas_runtime_store_v4.py` 是当前调用方使用的具名导出入口。新业务代码直接依赖实际实现模块，不通过这些入口查找另一模块的依赖。这里的导出是代码模块边界，不代表支持旧项目数据或旧智能体流程。

包 `__init__.py` 的公共出口以显式导入和静态表声明。导入依赖时应保持实际函数、锁和配置对象的归属。跨领域操作存在初始化顺序依赖时，可以在实际消费函数内使用具名导入，不能引入循环代理或通配导入。

测试应在实际消费依赖的模块 patch，不能仅 patch 旧入口后认为新实现已被截获。以插件 manifest 合并后的开发后端配置选择 Python；开发验收保留 `dev_mode: true`，前端核实 Vite 实时入口。当前模块边界以正式代码和测试为准；具体运行报告保存在插件内 `backend/artifacts/`，不以历史测试数量代替本轮验收。
