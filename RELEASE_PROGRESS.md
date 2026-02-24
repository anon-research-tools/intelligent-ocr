# 发布进展记录（2026-02-24）

## 已完成

- 完成 OCR 稳定性与重试体系相关改造并合入主分支。
- 完成本地 macOS 打包验证（arm64 DMG 成功生成）。
- 修复 GitHub Actions 发布阻塞问题：`release` 不再被 Intel 任务取消所阻断。
- 发布版本 `v2.0.2`：
  - commit: `0905119`
  - tag: `v2.0.2`
  - 已推送到 `origin/main` 与 `origin/v2.0.2`

## CI / 发布状态

- `Build Windows Installer`: `completed / success`
- `Create GitHub Release`: `completed / success`
- Release: `v2.0.2` 已发布（非 draft / 非 prerelease）
- 已确认包含 Windows 安装包与 macOS arm64 DMG 资产。

## 备注

- Intel macOS 构建在本次流水线中为 `cancelled`，但不再阻断正式发布。
- 后续可选优化：将 Intel 构建改为手动触发或独立 workflow，降低发布链路波动风险。
