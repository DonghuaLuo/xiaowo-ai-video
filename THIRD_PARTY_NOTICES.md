# 依赖与许可说明

## 小蜗前端 SDK

- 名称：`xiaowo-sdk`
- 版本：`1.0.0`
- 作者：小蜗工具
- 来源：小蜗主工程 `packages/xiaowo-sdk`。
- 随附源码：`frontend/vendor/xiaowo-sdk/src/index.js`、`src/index.d.ts`。
- 许可证：MIT，全文见 [frontend/vendor/xiaowo-sdk/LICENSE](frontend/vendor/xiaowo-sdk/LICENSE)。

随附 SDK 的运行时代码及类型声明保持原样。为便于独立安装与构建，SDK 的包入口直接指向源码，移除了仅用于构建 SDK 的脚本和开发依赖；应用中的 SDK 依赖改为仓库内相对路径。

## 包管理器依赖

前端依赖及锁定版本见 `frontend/package.json`、`frontend/pnpm-lock.yaml`；后端依赖见 `manifest.json` 的 `backend.pip`。这些依赖保留各自的许可证、版权声明和分发条件，本项目的 AGPL-3.0-only 声明不替代其许可。

模型服务和扩展运行时通过应用配置获取，不包含在本仓库中，其使用条件以相应提供方的条款为准。
