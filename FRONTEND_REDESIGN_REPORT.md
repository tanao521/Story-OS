# Story OS 前端重构交付报告

## 目标与范围

本次重构将现有 FastAPI/Jinja2 控制台统一为 Editorial Writing Studio × AI Narrative IDE 风格；未更换框架，未引入大型 UI 依赖，且未改动 API 契约。

## 设计系统与页面

- 统一深色设计 tokens、焦点、状态、减少动画与桌面响应式规则。
- 工作台、章节管理、沉浸式编辑器、故事蓝图、大纲、写作约束、版本记录、日志和错误中心均保留真实数据入口。
- 版本记录只呈现当前支持的查看、比较、选择与归档；不呈现恢复版本。

## 接口与数据保护

前端继续使用既有 `/api/status`、`/api/versions`、`/api/versions/content`、`/api/versions/diff`、`/api/project-assets`、`/api/writing-constraints`、`/api/manual/save` 和 `/api/run-chapter`。未更改路径、HTTP 方法、载荷、返回字段、章节格式、蓝图结构或 pipeline 数据结构。

## 交互、响应式与性能

- 统一可见键盘焦点、禁用状态、120/160ms 交互和 reduced-motion。
- 窄桌面优先隐藏检查器、收窄导航；章节表格保持局部滚动，编辑器保持内容宽度。
- 日志前端显示有上限且仅追加；清空只清除页面显示。
- Ctrl/Cmd+S 覆盖正文、蓝图、大纲和写作约束现有保存入口；Esc 关闭弹窗并约束弹窗 Tab 焦点。

## 已验证流程

- API 路径健康检查：`/api/status`、`/api/project-assets` 均返回 200。
- 项目资产、写作约束、章节归档和 Web 路由回归测试已执行。
- 浏览器检查确认版本三栏、质量样式加载，控制台无新增页面错误。

## 已知限制

- 后端未提供下一章大纲的独立 Web 读写接口；页面只编辑蓝图既有 `chapter_plan`，不会伪造临时计划。
- 当前接口不提供版本恢复或文件修改时间，因此界面不显示虚构恢复操作或时间。
- 工作区存在大量早于本阶段的后端、测试和配置改动；为避免破坏用户工作，未执行 Git 回滚。完整测试集的剩余失败需按其所属后端改动分别处理。

## 维护方式

运行 `python main.py web` 启动本地控制台，使用 `pytest` 执行回归。新增页面应复用 `design-system.css` tokens，并仅接入已有 API。
