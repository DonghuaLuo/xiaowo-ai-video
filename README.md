# 小蜗 AI Video

小蜗桌面应用中的 AI 视频创作工具，支持项目与分集规划、剧情拆分、剧本、视觉资产、分镜、图片和视频生成，以及画布工作流与创作智能体。

当前源码版本：**1.87**。

- GitHub：[DonghuaLuo/xiaowo-ai-video](https://github.com/DonghuaLuo/xiaowo-ai-video)
- Gitee：[donghuax/xiaowo-ai-video](https://gitee.com/donghuax/xiaowo-ai-video)
- 小蜗：[www.xiaowoai.com](https://www.xiaowoai.com/)

## 运行环境

本应用运行在小蜗桌面宿主中，前后端通过小蜗 SDK 通信。窗口、IPC、文件访问和应用管理等能力由宿主提供。图片、视频和文本模型需要自行配置相应服务及凭据。

前端开发使用 Node.js 20 或更新版本和 pnpm 10.33 或更新版本；后端使用 Python 3.10 或更新版本。Python 依赖及扩展运行时配置见 `manifest.json` 中的 `backend.pip` 和 `extmodels`；媒体处理功能还依赖相应运行时中的图像处理库及 FFmpeg 等工具。

## 获取与开发

```sh
git clone https://github.com/DonghuaLuo/xiaowo-ai-video.git ai-video
cd ai-video/frontend
pnpm install --frozen-lockfile
pnpm dev
```

也可以从 Gitee 克隆：

```sh
git clone https://gitee.com/donghuax/xiaowo-ai-video.git ai-video
```

按小蜗的应用开发流程导入应用目录。目录名应与 `manifest.json` 中的应用 ID `ai-video` 一致，当前开发者账号也需要对应的在线应用记录。需要指定本机 Python 时，在 `dev.backend` 中配置自己的 `runtime`；仓库默认继承宿主管理的运行时配置。

浏览器开发服务器可用于界面开发，完整业务交互需要在小蜗宿主中运行。API Key 和项目数据通过应用配置管理，保存在运行时数据目录中。

构建前端：

```sh
cd frontend
pnpm build
```

构建结果写入 `frontend/dist`。仓库保留了这一目录，供宿主按 `frontend.entry` 加载。需要修改界面时，应编辑 `frontend/src` 后重新构建。

现有画布接口检查：

```sh
python scripts/check_ai_video_canvas_fast_mutations.py
```

## 源码范围

本仓库依据 1.87 版本的 `release_rules.json` 整理，包含：

- `backend/main.py`、`backend/handlers.py`：后端入口和 IPC handler。
- `backend/project_store_services`、`backend/utils`：业务服务、模型接入与公共工具。
- `backend/agent_ops`：创作智能体 Skill、导演规则和权限配置。
- `backend/public`：随应用分发的静态资源。
- `frontend/src`、`frontend/public`、`frontend/dist`：前端源码、资源和构建产物。
- 前端构建配置、依赖锁文件及应用清单。

同时附带前端所需的小蜗 SDK 源码（`frontend/vendor/xiaowo-sdk`），依赖引用已调整到仓库内。后端源码以普通目录保存，克隆时无需配置外部符号链接。

本地项目数据、模型服务凭据、提示词运行日志、诊断产物、缓存和 `node_modules` 不随源码上传。`release_rules.json` 保留发布选择，并补充许可证、版权说明和 SDK 源码，便于后续分发时保留这些材料。

## 许可证

本项目原创代码采用 **GNU Affero General Public License v3.0 only（AGPL-3.0-only）**，许可证全文见 [LICENSE](LICENSE)，程序版权与许可声明见 [COPYRIGHT](COPYRIGHT)。

随附的小蜗 SDK 保留 MIT 许可证。其他依赖各自的许可和归属说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
