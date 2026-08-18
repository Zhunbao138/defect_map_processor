# Defect-List Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add frontend pagination (10/20/50/100 per page) to the defect record table, sitting on top of the existing filter+sort pipeline so users never see empty pages.

**Architecture:** Client-side only. The `/api/records/<task_id>` endpoint still returns all rows; the table renders only the current page slice. Pagination runs last in the pipeline (`filter → sort → paginate → render`), so page count is always `Math.ceil(sortedRecords.length / pageSize)`. State lives in a single `paginationState` object next to the existing `currentSort` / `filterState` objects in `app.js`. Page resets to 1 on any data-reload or filter/sort change; pageSize change also resets page to 1.

**Tech Stack:** Vanilla JS (no framework), HTML, CSS. No new dependencies. The Flask service on port 5000 is already running and is the live target for verification (auth: `admin:zP0mRWsuXJUZ0Azv`).

## Global Constraints

These apply to every task; do not re-derive in task bodies.

- No new dependencies. No new fonts. No animations. Reuse `.btn-secondary` styling and the project primary color `#667eea`.
- PaginationState object shape: `{ page: number /* 1-based */, pageSize: number /* default 20, options 10|20|50|100 */ }`.
- All four pageSize options must work, but only 20 is the initial value.
- Page resets to 1 on: sort header click, filter apply, task switch, record load, pageSize change. Page does NOT reset on pagination controls.
- Edge: if `sortedRecords.length === 0`, hide the entire pagination bar.
- Edge: if `sortedRecords.length <= pageSize`, render the bar but disable both prev/next buttons.
- Edge: defensively clamp `page` to `[1, totalPages]` inside `getPagedRecords()`.
- Download JSON / Excel still export `sortedRecords` (filter+sort applied, but page-agnostic).
- Detail modal still opens from `recordsCache` (unaffected by pagination).
- Service is running at `http://127.0.0.1:5000` and requires Basic Auth `admin:zP0mRWsuXJUZ0Azv`. No need to restart the service for any of these tasks (Flask serves static files and templates directly); just hard-refresh the browser.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `templates/index.html` | modify | Add empty `<div class="pagination-bar">` after `<table class="record-table">` |
| `static/app.js` | modify | Add `paginationState`, refactor pipeline to add pagination step, add `getPagedRecords` / `renderPagination` / `attachPaginationEvents`, wire reset hooks |
| `static/style.css` | modify | Add `.pagination-bar` / `.page-btn` / `.page-indicator` / `.page-size-select` styles |

No new files, no new directories, no test framework added. Verification is via Playwright browser snapshots against the live service.

---

## Task 1: Add pagination bar container to the HTML

**Files:**
- Modify: `templates/index.html:130-134` (the `<table>` block) — add the empty pagination bar `<div>` immediately after the `</table>` close tag.

**Interfaces:**
- Consumes: nothing
- Produces: an empty `<div class="pagination-bar" id="pagination-bar"></div>` element with `id="pagination-bar"` (so JS can find it without querying by class). The element is initially empty; JS will fill it on first render.

- [ ] **Step 1: Add the empty container**

Open `templates/index.html`. Find the `</table>` line that closes `<table class="record-table" id="record-table">` (around line 133). Insert the following block immediately after that `</table>` and before the closing `</section>` of `.result-section`:

```html
            <div class="pagination-bar" id="pagination-bar">
                <!-- JS 渲染分页器 -->
            </div>
```

The result should look like:

```html
            </table>

            <div class="pagination-bar" id="pagination-bar">
                <!-- JS 渲染分页器 -->
            </div>
        </section>
```

Verify the file still has the same structure: `</table>` → blank line → `<div class="pagination-bar" id="pagination-bar">` → comment → `</div>` → `</section>`.

- [ ] **Step 2: Verify the page still loads**

Service is already running on port 5000 with auth. Verify the page renders without 500:

```bash
curl -s -u "admin:zP0mRWsuXJUZ0Azv" -o /tmp/idx.html -w "HTTP %{http_code}\n" http://127.0.0.1:5000/
grep -c 'id="pagination-bar"' /tmp/idx.html
```

Expected: `HTTP 200`, then `1` (the new element present in the served HTML).

- [ ] **Step 3: Commit**

```bash
cd /home/qing/桌面/中冶/defect_map_processor
git add templates/index.html
git commit -m "feat(pagination): add empty pagination-bar container after record table"
```

---

## Task 2: Add paginationState and the paginate step to the JS pipeline

**Files:**
- Modify: `static/app.js`
  - Around lines 115-189: refactor `getDisplayedRecords()` and `renderRecords()` to thread pagination through.
  - Add `paginationState` near the other state declarations (around lines 133-137 where `currentSort` and `filterState` are defined).

**Interfaces:**
- Consumes: existing `recordsCache`, `currentSort`, `filterState` (read-only).
- Produces: new `paginationState` (read/write from event handlers and from `selectTask` / `loadRecords` / sort header / filter apply). The function `getPagedRecords()` (replaces the inner `forEach` loop in `renderRecords`).

- [ ] **Step 1: Add the paginationState object**

In `static/app.js`, find the block:

```js
let currentSort = { col: null, dir: 'none' };  // 'none' | 'asc' | 'desc'

// 筛选状态: { 列名: { excluded: Set<值>, distinct: [...]全量 } }
const FILTER_COLS = ['生产厂', '钢板号', '钢种', '类别', '缺陷分析'];
const filterState = {};
```

Insert the new state object immediately after that block (after `const filterState = {};`):

```js
// 分页状态
const paginationState = {
    page: 1,        // 1-based 当前页
    pageSize: 20,   // 每页条数, 可选 10 / 20 / 50 / 100
};
```

- [ ] **Step 2: Refactor the pipeline — split getDisplayedRecords from pagination**

The current `renderRecords()` (around lines 191-206) calls `getDisplayedRecords()` and then `forEach`s over the result to build rows. We need to:

1. Keep `getDisplayedRecords()` returning the **filter+sort result** (rename concept: it's the records that will be paginated). Don't change its body — its job is still "records after filter+sort".
2. Add `getPagedRecords(records)` that takes those records, applies paginationState, and returns the slice for the current page.
3. Change `renderRecords()` to call `getPagedRecords(getDisplayedRecords())` and render the slice.

Replace the existing `renderRecords()` function (the full body, from `function renderRecords() {` to its closing `}` around line 206) with:

```js
function getPagedRecords(records) {
    const totalPages = Math.max(1, Math.ceil(records.length / paginationState.pageSize));
    // 防御性钳制: page 必须在 [1, totalPages]
    if (paginationState.page < 1) paginationState.page = 1;
    if (paginationState.page > totalPages) paginationState.page = totalPages;
    const start = (paginationState.page - 1) * paginationState.pageSize;
    return records.slice(start, start + paginationState.pageSize);
}

function renderRecords() {
    const displayed = getDisplayedRecords();           // filter + sort
    const paged = getPagedRecords(displayed);          // + paginate
    document.getElementById('record-count').textContent = displayed.length;
    const tbody = document.getElementById('record-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    paged.forEach(rec => tbody.appendChild(createRecordRow(rec)));
    updateSortIndicators();
    renderPagination(displayed.length);                 // 新增: 渲染分页器
    // 同步表头筛选按钮状态 (有筛选时高亮)
    document.querySelectorAll('.th-filter-btn').forEach(b => {
        const c = b.dataset.col;
        const excluded = filterState[c] && filterState[c].excluded.size > 0;
        b.classList.toggle('active', excluded);
        b.title = excluded ? `${c} (${filterState[c].excluded.size} 项已筛除)` : `筛选本列`;
    });
}
```

Key points:
- `displayed.length` is used for the header count (e.g. "74 条"), not `paged.length`. This is intentional — the count shows "how many match the filter", not "how many on this page".
- `renderPagination` is referenced here but defined in the next task. It will be a no-op stub initially; that's fine — this task is about the data flow, not the UI rendering of the bar.

- [ ] **Step 3: Stub `renderPagination` so the file still parses**

Without this stub, the browser will throw "renderPagination is not defined" on the first render. Add a temporary stub immediately above `getPagedRecords`:

```js
function renderPagination(displayedCount) {
    // TODO(pagination): real implementation in next task
    const bar = document.getElementById('pagination-bar');
    if (bar) bar.innerHTML = '';
}
```

The real implementation lands in Task 3. This stub keeps the page working with a hidden bar until then.

- [ ] **Step 4: Verify the page still works (no regression)**

```bash
curl -s -u "admin:zP0mRWsuXJUZ0Azv" -o /tmp/idx2.html -w "HTTP %{http_code}\n" http://127.0.0.1:5000/static/app.js
# Just confirm the JS file is served (no syntax error in build / dispatch).
# Then check it for the new symbols:
curl -s -u "admin:zP0mRWsuXJUZ0Azv" http://127.0.0.1:5000/static/app.js | grep -E "paginationState|getPagedRecords|renderPagination" | head -5
```

Expected: `HTTP 200` for the static file, then 3+ lines of grep output (the three new symbols). Open the browser to `http://127.0.0.1:5000/` in a real browser and confirm:
- A task loads (click a completed task in the top bar).
- The table shows records (still all of them — no UI yet, but the data flow is correct).
- The count badge still shows total filtered count, not page count.
- The pagination bar `<div>` is empty in DevTools.

If the page is blank or shows an error in the browser console, something is wrong in the refactor — fix before committing.

- [ ] **Step 5: Commit**

```bash
cd /home/qing/桌面/中冶/defect_map_processor
git add static/app.js
git commit -m "feat(pagination): add paginationState and paginate step in render pipeline"
```

---

## Task 3: Implement the pagination bar UI (prev/next, page indicator, pageSize select)

**Files:**
- Modify: `static/app.js` — replace the stub `renderPagination` with the real one, and add event wiring for the controls.

**Interfaces:**
- Consumes: `paginationState`, `displayedCount` (from `renderRecords`).
- Produces: HTML inside `#pagination-bar` with class `.pagination-bar` and children `.page-btn` / `.page-indicator` / `.page-size-select`. Event handlers wired to update `paginationState` and re-render.

- [ ] **Step 1: Replace the stub with the real `renderPagination`**

Find the stub:

```js
function renderPagination(displayedCount) {
    // TODO(pagination): real implementation in next task
    const bar = document.getElementById('pagination-bar');
    if (bar) bar.innerHTML = '';
}
```

Replace it with:

```js
function renderPagination(displayedCount) {
    const bar = document.getElementById('pagination-bar');
    if (!bar) return;

    // 边界: 0 条 → 隐藏整个分页器
    if (displayedCount === 0) {
        bar.innerHTML = '';
        bar.style.display = 'none';
        return;
    }
    bar.style.display = '';

    const totalPages = Math.max(1, Math.ceil(displayedCount / paginationState.pageSize));
    // 防御性钳制: 渲染时也再钳一次, 万一外部代码忘了
    if (paginationState.page < 1) paginationState.page = 1;
    if (paginationState.page > totalPages) paginationState.page = totalPages;

    const isFirst = paginationState.page <= 1;
    const isLast = paginationState.page >= totalPages;

    bar.innerHTML = `
        <button type="button" class="btn-secondary page-btn" id="page-prev" ${isFirst ? 'disabled' : ''}>« 上一页</button>
        <span class="page-indicator">第 <span class="page-current">${paginationState.page}</span> / ${totalPages} 页</span>
        <button type="button" class="btn-secondary page-btn" id="page-next" ${isLast ? 'disabled' : ''}>下一页 »</button>
        <label class="page-size-label">
            每页
            <select class="page-size-select" id="page-size-select">
                <option value="10" ${paginationState.pageSize === 10 ? 'selected' : ''}>10</option>
                <option value="20" ${paginationState.pageSize === 20 ? 'selected' : ''}>20</option>
                <option value="50" ${paginationState.pageSize === 50 ? 'selected' : ''}>50</option>
                <option value="100" ${paginationState.pageSize === 100 ? 'selected' : ''}>100</option>
            </select>
            条
        </label>
    `;

    // 翻页按钮
    document.getElementById('page-prev')?.addEventListener('click', () => {
        if (paginationState.page > 1) {
            paginationState.page -= 1;
            renderRecords();
        }
    });
    document.getElementById('page-next')?.addEventListener('click', () => {
        if (paginationState.page < totalPages) {
            paginationState.page += 1;
            renderRecords();
        }
    });

    // pageSize 变化
    document.getElementById('page-size-select')?.addEventListener('change', (e) => {
        const newSize = parseInt(e.target.value, 10);
        if ([10, 20, 50, 100].includes(newSize)) {
            paginationState.pageSize = newSize;
            paginationState.page = 1;   // 改 pageSize 必须重置到第 1 页
            renderRecords();
        }
    });
}
```

- [ ] **Step 2: Verify pagination renders**

Open `http://127.0.0.1:5000/` in a browser, log in (`admin` / `zP0mRWsuXJUZ0Azv`), and select a completed task with at least ~30 records (e.g. one of the existing `output/<task_id>/defect_records.json` runs). Confirm:

- The pagination bar shows below the table.
- "第 1 / N 页" is displayed.
- "下一页 »" is enabled; "« 上一页" is disabled.
- The pageSize dropdown shows "20" selected.
- Clicking "下一页 »" advances to page 2; row count changes to the next 20.
- At the last page, "下一页 »" becomes disabled; "« 上一页" becomes enabled.
- Switching pageSize to 10 jumps back to page 1 and the table now shows 10 rows.

If any of these fail, the wiring has a bug — debug before committing.

- [ ] **Step 3: Commit**

```bash
cd /home/qing/桌面/中冶/defect_map_processor
git add static/app.js
git commit -m "feat(pagination): render pagination bar with prev/next and pageSize select"
```

---

## Task 4: Reset page to 1 on data reloads and filter/sort changes

**Files:**
- Modify: `static/app.js`
  - `applyFilterModal()` (around line 463)
  - Sort header click handler (around line 523)
  - `selectTask()` (around line 695)
  - `loadRecords()` (around line 116)

**Interfaces:**
- All four edits insert the same one-liner: `paginationState.page = 1;` (inserted *before* the call to `renderRecords()`).

- [ ] **Step 1: Reset page in `applyFilterModal`**

Find the function `applyFilterModal` (around line 463). It currently ends with:

```js
    closeFilterModal();
    renderRecords();
}
```

Change it to:

```js
    closeFilterModal();
    paginationState.page = 1;   // 筛选后回到第 1 页
    renderRecords();
}
```

- [ ] **Step 2: Reset page in the sort header click handler**

Find the sort header click handler (around line 523):

```js
document.querySelectorAll('#record-table thead th.sortable').forEach(th => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
        const col = th.dataset.col;
        if (currentSort.col !== col) {
            currentSort = { col, dir: 'asc' };
        } else if (currentSort.dir === 'asc') {
            currentSort.dir = 'desc';
        } else {
            currentSort = { col: null, dir: 'none' };
        }
        renderRecords();
    });
});
```

Change the `renderRecords();` line to reset page first:

```js
document.querySelectorAll('#record-table thead th.sortable').forEach(th => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
        const col = th.dataset.col;
        if (currentSort.col !== col) {
            currentSort = { col, dir: 'asc' };
        } else if (currentSort.dir === 'asc') {
            currentSort.dir = 'desc';
        } else {
            currentSort = { col: null, dir: 'none' };
        }
        paginationState.page = 1;   // 排序后回到第 1 页
        renderRecords();
    });
});
```

- [ ] **Step 3: Reset page in `selectTask`**

Find `selectTask` (around line 695). It currently ends with:

```js
    // 加载该任务的记录
    try {
        const res = await fetch(`/api/records/${taskId}`);
        if (res.ok) {
            const data = await res.json();
            recordsCache = data.records;
            renderRecords();
            document.getElementById('result-section').style.display = 'block';
        }
    } catch (e) {
        console.error('Select task error:', e);
    }
}
```

Change to:

```js
    // 加载该任务的记录
    try {
        const res = await fetch(`/api/records/${taskId}`);
        if (res.ok) {
            const data = await res.json();
            recordsCache = data.records;
            paginationState.page = 1;   // 切换任务后回到第 1 页
            renderRecords();
            document.getElementById('result-section').style.display = 'block';
        }
    } catch (e) {
        console.error('Select task error:', e);
    }
}
```

- [ ] **Step 4: Reset page in `loadRecords`**

Find `loadRecords` (around line 116). It currently ends with:

```js
        recordsCache = data.records;  // 缓存
        renderRecords();
        document.getElementById('result-section').style.display = 'block';
    } catch (e) {
        console.error('Load records error:', e);
    }
}
```

Change to:

```js
        recordsCache = data.records;  // 缓存
        paginationState.page = 1;     // 任务完成后回到第 1 页
        renderRecords();
        document.getElementById('result-section').style.display = 'block';
    } catch (e) {
        console.error('Load records error:', e);
    }
}
```

- [ ] **Step 5: Verify the four reset hooks**

In the browser:

1. **Sort reset**: go to page 2, click any sortable column header → page should be 1, sort applied.
2. **Filter reset**: go to page 2, open a column filter, exclude one value, apply → page should be 1.
3. **pageSize change**: go to page 2, change pageSize to 50 → page should be 1.
4. **Task switch**: go to page 2, click another completed task in the top bar → page should be 1 in the new task.
5. **Download unaffected**: go to page 2, click "下载 JSON" → JSON should contain **all** filtered+sorted records, not just the current page (count should match `record-count` in the header).

If any reset fails, the corresponding hook is missing or in the wrong place.

- [ ] **Step 6: Commit**

```bash
cd /home/qing/桌面/中冶/defect_map_processor
git add static/app.js
git commit -m "feat(pagination): reset to page 1 on sort/filter/task/load/pageSize change"
```

---

## Task 5: Add CSS for the pagination bar

**Files:**
- Modify: `static/style.css` — append the new rules at the end of the file.

- [ ] **Step 1: Append pagination CSS at the end of `static/style.css`**

Open `static/style.css` and go to the very end. Add the following block (preserve leading blank line for readability):

```css

/* ===== 缺陷列表分页器 ===== */
.pagination-bar {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    margin-top: 1rem;
    padding: 0.75rem 1rem;
    flex-wrap: wrap;
}

.page-btn {
    /* 复用 .btn-secondary 的视觉; 仅补一些禁用态 */
    min-width: 90px;
}

.page-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

.page-indicator {
    font-size: 0.95rem;
    color: #2d3748;
    min-width: 110px;
    text-align: center;
}

.page-indicator .page-current {
    color: #667eea;
    font-weight: 600;
    font-size: 1.05rem;
}

.page-size-label {
    font-size: 0.9rem;
    color: #4a5568;
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
}

.page-size-select {
    padding: 0.35rem 0.5rem;
    border: 1px solid #cbd5e0;
    border-radius: 6px;
    font-size: 0.9rem;
    background: #fff;
    color: #2d3748;
    cursor: pointer;
}

.page-size-select:focus {
    outline: none;
    border-color: #667eea;
}
```

Notes:
- `min-width: 90px` on `.page-btn` keeps "« 上一页" / "下一页 »" the same width whether or not they have "«" arrows. Both buttons get this class.
- The disabled state uses `opacity: 0.4` (matches the project convention from `.btn-primary:disabled` line 126).
- `.page-current` uses `#667eea` (the project's accent) — same as the existing color scheme.

- [ ] **Step 2: Verify styling renders**

In the browser, refresh `http://127.0.0.1:5000/` (hard refresh, Ctrl+Shift+R, to bypass cached `app.js` / `style.css`). The pagination bar should now look:
- Centered under the table.
- Same visual weight as the existing "下载 JSON / Excel" buttons.
- The current page number is purple (`#667eea`).
- The pageSize dropdown matches the existing form input style (border `#cbd5e0`, rounded).
- Disabled prev/next buttons are faded but still readable.

Use DevTools to confirm:
- No console errors.
- The bar is hidden (display: none) when there are 0 records.
- The bar is visible and prev is disabled on the first page; next is disabled on the last.

- [ ] **Step 3: Commit**

```bash
cd /home/qing/桌面/中冶/defect_map_processor
git add static/style.css
git commit -m "style(pagination): add styles for pagination bar"
```

---

## Task 6: End-to-end verification against the spec's 8 acceptance criteria

**Files:** None modified. This task only verifies.

Use Playwright via the available `mcp__plugin_playwright_*` tools to drive the running service. Login via Basic Auth (`admin:zP0mRWsuXJUZ0Azv`). Use a task with at least 30 records so pagination actually paginates.

- [ ] **Step 1: Open the page and select a large task**

Navigate to `http://127.0.0.1:5000/`. Browser will show the auth prompt — fill `admin` / `zP0mRWsuXJUZ0Azv`. Wait for the task list to load, then click a completed task whose `count` is >= 30 (from the "· N 条" indicator in the top bar).

Confirm via `browser_snapshot`: the record table has rows AND the pagination bar shows "第 1 / N 页".

- [ ] **Step 2: Acceptance #1 — default 20 per page, prev/next work**

In the snapshot, locate `.page-current` (should be `1`) and the `record-count` text. Compute: if total is e.g. 74, total pages should be 4. Confirm `« 上一页` is disabled and `下一页 »` is enabled.

Click "下一页 »". Snapshot again. Confirm `.page-current` is now `2`, and the first row of the table is different from page 1.

- [ ] **Step 3: Acceptance #2 — pageSize 50 resets page to 1**

Go to page 2 first (already there from step 2). Change the pageSize select to 50. Snapshot. Confirm `.page-current` is `1` and total pages is now `2` (74 / 50 → ceil 2).

- [ ] **Step 4: Acceptance #3 — filter from page 2 to 5 rows resets to page 1**

Set pageSize back to 20, then click "下一页 »" to reach page 2. Click any column's `⚙` filter button (e.g. "类别"). In the modal, uncheck one value, then click "应用筛选". Snapshot. Confirm `.page-current` is `1`, both prev/next buttons may be disabled if filter reduced count below page size.

- [ ] **Step 5: Acceptance #4 — sort from page 3 resets to page 1**

Clear any active filter first: open a column's `⚙`, click "清除本列", apply. With pageSize 20 and unfiltered data, go to page 3. Click any sortable column header. Snapshot. Confirm `.page-current` is `1`.

- [ ] **Step 6: Acceptance #5 — switching tasks resets to page 1**

If there is more than one completed task in the top bar, click another. Snapshot. Confirm `.page-current` is `1` (regardless of which page you were on in the previous task).

- [ ] **Step 7: Acceptance #6 — download JSON unaffected by current page**

Go to page 2. Click "下载 JSON". Capture the downloaded blob (Playwright's `browser_network_requests` will show the request, but the actual download is client-side — alternatively, evaluate `buildExportRows().length` in the browser console to confirm it equals `record-count`, not page size). Confirm: download row count == `record-count` (e.g. 74), not 20.

- [ ] **Step 8: Acceptance #7 — 0 records hides the bar**

Apply a filter that excludes every value in some column (open the column filter, "全不选", "应用筛选"). Snapshot. Confirm:
- Table tbody is empty.
- `#pagination-bar` is hidden (`display: none` per CSS, or simply not present in the rendered tree).

- [ ] **Step 9: Acceptance #8 — refresh resets pageSize and page**

Hard refresh the browser (Ctrl+Shift+R, or `browser_navigate` to the same URL again). Log in again. Select the same large task. Snapshot. Confirm:
- `.page-current` is `1`.
- The pageSize select shows `20` selected.

Persistence is explicitly out of scope; the spec calls for these to reset on refresh.

- [ ] **Step 10: Push the commits**

All five implementation commits are on `main`. Push to GitHub:

```bash
cd /home/qing/桌面/中冶/defect_map_processor
git log --oneline -7    # sanity: should see 5 new commits on top of 1cc64b9 (spec) and 19a1a34 (initial)
git push origin main
```

Confirm with `git ls-remote --heads origin main` that the remote HEAD matches the new local HEAD.

- [ ] **Step 11: Report results**

Print a short summary:

- Which acceptance criteria passed (1-8).
- Any deviations from the spec (should be none).
- The final `git log --oneline -7` output.
- The remote URL `https://github.com/Zhunbao138/defect_map_processor`.

If any acceptance criterion failed, do NOT proceed with a celebratory report. Instead: fix the bug, re-test the failed criterion, add a fix-up commit, and re-push. Only declare success when all 8 pass.

---

## Self-Review Notes (for the planner, not the implementer)

**Spec coverage check:**
- Goal (frontend pagination 10/20/50/100) → Task 3 (pageSize select) ✅
- Non-goal "no backend change" → not in any task body, but no task touches `app.py` or `core/` ✅
- Architecture (filter→sort→paginate→render) → Task 2 (pipeline refactor) ✅
- State shape → Task 2 (paginationState) ✅
- Trigger points (sort/filter/task/load/pageSize) → Task 4 (all four hooks) ✅
- UI controls (prev/next/indicator/pageSize) → Task 3 (renderPagination) + Task 5 (CSS) ✅
- Edge: 0 records hides bar → Task 3 (`bar.style.display = 'none'`) ✅
- Edge: ≤pageSize disables both → Task 3 (`isFirst`/`isLast` based on `totalPages`) ✅
- Edge: clamp page → Task 2 (`getPagedRecords`) and Task 3 (defensive re-clamp) ✅
- Download unaffected → Task 6 step 7 verifies; no code change to `buildExportRows` needed because it already uses `getDisplayedRecords()` (filter+sort) ✅
- Detail modal unaffected → no task touches it; modal still opens from `recordsCache` ✅
- 序号 column unaffected → no task touches `createRecordRow`; it still reads `rec['序号']` ✅
- Verification → Task 6 maps every spec acceptance criterion 1:1 to a step ✅

**Placeholder scan:** No TBD/TODO in the final plan. The single `TODO(pagination)` in Task 2 step 3 is in a *stub* explicitly marked to be replaced in Task 3 step 1 — this is intentional and the replacement code is given in full immediately after.

**Type/name consistency:** `paginationState.page` / `paginationState.pageSize` used identically across Tasks 2-6. `getPagedRecords(records)` signature stable across Tasks 2 and 3. `renderPagination(displayedCount)` signature stable. The DOM id `pagination-bar` is consistent between Task 1 (HTML) and Task 3 (JS lookup).
