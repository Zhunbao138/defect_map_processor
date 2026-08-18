# 缺陷列表分页功能 — 设计

日期: 2026-07-02
状态: 已批准, 待实施

## 目标

为"缺陷记录表格"增加分页控件, 让用户可以在 10/20/50/100 条/页之间切换,
避免在样本量大的任务中一次性渲染所有行(目前 70+ 条已经开始拖累交互)。

## 非目标

- 不做后端分页。本次改动仅前端 —— 后端 `/api/records/<task_id>` 仍返回全量。
- 不做"分页 + 无限滚动"混合模式。
- 不改变现有筛选/排序/下载的对外行为, 仅在它们之后多一层分页。
- 不做 page-size 持久化(刷新页面回到默认 20)。

## 架构: 数据流水线

`recordsCache` 已经在客户端完整缓存, 所有变换都在前端:

```
recordsCache
  →  filter       (按 5 个可筛选列排除)
filteredRecords
  →  sort         (按当前 sort.col / sort.dir 排序)
sortedRecords
  →  paginate     (按 pageSize 切出当前页的 slice)
pagedRecords
  →  render       (清空 tbody, 渲染 pagedRecords)
```

关键不变量: **分页永远是流水线最后一步**, 作用在"用户实际看到的那批数据"上。
分页器不显示"分页后的页数", 而显示 `Math.ceil(sortedRecords.length / pageSize)`。
这样筛选/排序后表格里永远不会出现"空页"。

## 状态

```js
const paginationState = {
    page: 1,        // 1-based
    pageSize: 20,   // 默认 20
};
```

挂在 `app.js` 已有状态旁边(`currentTaskId` / `currentSort` / `filterState`)。

## 触发点

| 动作                                  | page 动作 |
|---------------------------------------|-----------|
| 表格表头点击排序                       | 重置 1   |
| 筛选模态框点击"应用"                  | 重置 1   |
| 切换任务 (`selectTask`)                | 重置 1   |
| 任务数据加载完成 (`loadRecords`)       | 重置 1   |
| 改变 pageSize (下拉的 `change` 事件)  | 重置 1   |
| 翻页(上一页/下一页)                   | 仅改 page |

## UI 控件

表格下方一行, 居中显示:

```
┌──────────────────────────────────────────────────────────────┐
│  « 上一页  │  第 3 / 8 页  │  下一页 »  │   每页 [20 ▾] 条  │
└──────────────────────────────────────────────────────────────┘
```

- **« 上一页**: `<button>`, 当前页 = 1 时 `disabled`
- **第 X / Y 页**: 纯文字, 当前页数字用项目主色高亮
- **下一页 »**: `<button>`, 当前页 = 总页数时 `disabled`
- **每页 [N ▾] 条**: `<select>`, 选项 `10 / 20 / 50 / 100`, 默认 20

容器放在 `<table class="record-table">` 之后, 仍在 `.result-section` 内部。
视觉风格沿用项目现有 `.btn-secondary` + 项目主色 `--accent-color` (#667eea)。
不引入新字体, 不引入动画, 沿用原生 `<select>`。

## 边界行为

| 情况                                          | 行为 |
|-----------------------------------------------|------|
| 筛选后 `sortedRecords.length === 0`           | 表格 tbody 空态(沿用现有), **分页器整体隐藏** |
| 筛选后 `sortedRecords.length <= pageSize`     | 分页器显示, 但两个翻页按钮都 `disabled` |
| 翻页到超出范围(防御)                          | `getPagedRecords()` 入口把 `page` 钳到 `[1, totalPages]` 后再 slice |
| 当前在第 5 页, 用户把 pageSize 改成 100       | 触发 pageSize 变化时重置到 1(避免"新 size 下第 5 页无意义") |

## 与现有功能的关系

- **下载 JSON / Excel**: 不变, 仍导出 `sortedRecords`(筛选+排序后全部), 不受分页影响。
- **筛选**: 现有 5 列筛选行为不变, 仅在 `applyFilterModal()` 末尾加一行 `paginationState.page = 1`。
- **排序**: 现有表头点击排序不变, 仅在 `renderRecords()` 调用前重置 page(实际上排序和筛选的渲染入口已统一, 改一处即可)。
- **`loadRecords` 与 `selectTask` 的关系**: `selectTask` 内部会 `await fetch /api/records/<task_id>`, 然后调用 `renderRecords()`; `loadRecords` 是任务刚完成时的独立入口(也调用 `renderRecords`)。两者都触发重置 page, 是有意为之 —— 任何"数据被重新装载"的路径都重置,避免遗漏入口。
- **详情弹窗**: 不变, 详情弹窗打开的是 `recordsCache` 中的原始记录, 不受分页影响。
- **每条记录的 `序号` 列**: 是原始 Excel 里的"序号"字段, 不受分页影响(不是"第 N 条")。

## 修改的文件

- `static/app.js`: 加 `paginationState`, 改 `getDisplayedRecords()` 拆出 `getPagedRecords()`, 新增 `renderPagination()`, 翻页控件事件, pageSize select 事件, 排序/筛选/selectTask/loadRecords 末尾重置 page。
- `templates/index.html`: 在 `<table class="record-table">` 之后加 `<div class="pagination-bar">` 容器(空, JS 渲染) + 一个隐藏的 `<template>` 或直接在 JS 里 innerHTML 生成(选 innerHTML, 与现有代码风格一致)。
- `static/style.css`: 加 `.pagination-bar` / `.page-btn` / `.page-indicator` / `.page-size-select` 等少量样式, 全部沿用现有色板和间距。

## 验收

1. 默认 20 条/页, 加载 70+ 条记录的任务时分页器显示"第 1 / 4 页", 翻页按钮工作。
2. 改 pageSize 到 50, 总页数重算成 2 页, page 重置到 1。
3. 在第 2 页时, 应用一个筛选把记录筛到 5 条 —— 自动回到第 1 页, 分页器显示"第 1 / 1 页", 翻页按钮 disabled。
4. 在第 3 页时, 点表头排序 —— 自动回到第 1 页。
5. 切换任务, page 重置到 1。
6. 下载 JSON / Excel 仍然导出筛选+排序后的全部, 不受当前页影响。
7. 筛选到 0 条时, 表格空态, 分页器不显示。
8. 浏览器原生刷新, pageSize 回到默认 20, page 回到 1(不要求持久化)。
