// 缺陷图谱处理系统 - 前端 JavaScript

let currentTaskId = null;
let pollInterval = null;

// ===== 文件上传交互 =====
const fileDrop = document.getElementById('file-drop');
const fileInput = document.getElementById('file-input');
const fileName = document.getElementById('file-name');

fileDrop.addEventListener('click', () => fileInput.click());
fileDrop.addEventListener('dragover', (e) => {
    e.preventDefault();
    fileDrop.classList.add('dragover');
});
fileDrop.addEventListener('dragleave', () => {
    fileDrop.classList.remove('dragover');
});
fileDrop.addEventListener('drop', (e) => {
    e.preventDefault();
    fileDrop.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        updateFileName();
    }
});
fileInput.addEventListener('change', updateFileName);

function updateFileName() {
    if (fileInput.files.length) {
        const f = fileInput.files[0];
        fileName.textContent = `${f.name} (${(f.size/1024/1024).toFixed(2)} MB)`;
    } else {
        fileName.textContent = '未选择文件';
    }
}

// ===== 上传表单 =====
document.getElementById('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!fileInput.files.length) {
        alert('请先选择文件');
        return;
    }

    const submitBtn = document.getElementById('submit-btn');
    submitBtn.disabled = true;
    submitBtn.textContent = '上传中...';

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('enable_ocr', document.getElementById('enable-ocr').checked);
    formData.append('enable_split', document.getElementById('enable-split').checked);
    formData.append('ocr_gpu', document.getElementById('ocr-gpu').checked);

    try {
        const res = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.error) throw new Error(data.error);

        currentTaskId = data.task_id;
        showProgressSection();
        startPolling();
        refreshTaskList();
        closeUploadModal();
    } catch (err) {
        alert('上传失败: ' + err.message);
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = '开始处理';
    }
});

// ===== 进度轮询 =====
function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(async () => {
        if (!currentTaskId) return;
        try {
            const res = await fetch(`/api/progress/${currentTaskId}`);
            const task = await res.json();

            updateProgress(task);

            if (task.status === 'completed') {
                clearInterval(pollInterval);
                pollInterval = null;
                loadRecords();
                refreshTaskList();
            } else if (task.status === 'failed') {
                clearInterval(pollInterval);
                pollInterval = null;
                alert('处理失败: ' + task.message);
                refreshTaskList();
            }
        } catch (e) {
            console.error('Poll error:', e);
        }
    }, 800);
}

function showProgressSection() {
    document.getElementById('progress-section').style.display = 'block';
    document.getElementById('result-section').style.display = 'none';
}

function updateProgress(task) {
    document.getElementById('progress-stage').textContent = task.stage || '-';
    document.getElementById('progress-message').textContent = task.message || '-';
    const percent = Math.round((task.progress || 0) * 100);
    document.getElementById('progress-fill').style.width = percent + '%';
    document.getElementById('progress-percent').textContent = percent + '%';
}

// ===== 加载记录 =====
async function loadRecords() {
    if (!currentTaskId) return;
    try {
        const res = await fetch(`/api/records/${currentTaskId}`);
        const data = await res.json();
        if (data.error) {
            console.error(data.error);
            return;
        }
        recordsCache = data.records;  // 缓存
        paginationState.page = 1;     // 任务完成后回到第 1 页
        renderRecords();
        document.getElementById('result-section').style.display = 'block';
    } catch (e) {
        console.error('Load records error:', e);
    }
}

let currentSort = { col: null, dir: 'none' };  // 'none' | 'asc' | 'desc'

// 筛选状态: { 列名: { excluded: Set<值>, distinct: [...]全量 } }
const FILTER_COLS = ['生产厂', '钢板号', '钢种', '类别', '缺陷分析'];
const filterState = {};

// 分页状态
const paginationState = {
    page: 1,        // 1-based 当前页
    pageSize: 20,   // 每页条数, 可选 10 / 20 / 50 / 100
};

function rebuildFilterDistinct() {
    for (const col of FILTER_COLS) {
        const set = new Set();
        for (const rec of recordsCache) {
            const v = rec[col];
            if (v != null && v !== '') set.add(String(v));
        }
        const sorted = Array.from(set).sort((a, b) => a.localeCompare(b, 'zh-CN'));
        if (!filterState[col]) filterState[col] = { excluded: new Set(), distinct: [] };
        filterState[col].distinct = sorted;
        // 清理已不存在的排除项
        const distSet = new Set(sorted);
        for (const e of Array.from(filterState[col].excluded)) {
            if (!distSet.has(e)) filterState[col].excluded.delete(e);
        }
    }
}

function getDisplayedRecords() {
    let arr = recordsCache.slice();
    for (const col of FILTER_COLS) {
        const st = filterState[col];
        if (!st || st.excluded.size === 0) continue;
        arr = arr.filter(rec => {
            const v = rec[col];
            if (v == null || v === '') return true; // 空值不受筛选影响
            return !st.excluded.has(String(v));
        });
    }
    if (currentSort.col && currentSort.dir !== 'none') {
        const col = currentSort.col;
        const dir = currentSort.dir === 'asc' ? 1 : -1;
        arr.sort((a, b) => {
            let va = a[col], vb = b[col];
            if (va == null) va = '';
            if (vb == null) vb = '';
            if (typeof va === 'number' && typeof vb === 'number') {
                return (va - vb) * dir;
            }
            va = String(va).toLowerCase();
            vb = String(vb).toLowerCase();
            // 数字优先识别
            const na = parseFloat(va), nb = parseFloat(vb);
            if (!isNaN(na) && !isNaN(nb) && String(na) === va && String(nb) === vb) {
                return (na - nb) * dir;
            }
            return va.localeCompare(vb, 'zh-CN') * dir;
        });
    }
    return arr;
}

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

function updateSortIndicators() {
    document.querySelectorAll('#record-table thead th.sortable').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.col === currentSort.col) {
            th.classList.add(currentSort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
        }
    });
}

function buildRecordCardHTML(rec) {
    // 返回 record-card 的 HTML 字符串 (给详情弹窗复用)
    const searchText = [
        rec['钢板号'], rec['生产厂'], rec['钢种'], rec['类别'], rec['缺陷分析']
    ].join(' ').toLowerCase();

    const imgUrl1 = rec['图-1'] ? `/api/image/${currentTaskId}/${relPath(rec['图-1'])}` : null;
    const imgUrl2 = rec['图-2'] ? `/api/image/${currentTaskId}/${relPath(rec['图-2'])}` : null;

    const viewImages1 = [
        { label: '俯视图', key: '俯视图-1' },
        { label: '长边', key: '长边方向侧视图-1' },
        { label: '短边', key: '短边方向侧视图-1' },
    ];
    const viewImages2 = [
        { label: '俯视图', key: '俯视图-2' },
        { label: '长边', key: '长边方向侧视图-2' },
        { label: '短边', key: '短边方向侧视图-2' },
    ];

    const params = rec['缺陷数据'] || {};

    return `
        <div style="display:none;"><span class="record-index">#${rec['序号'] || rec['row_index']}</span></div>
<div class="record-body">
            <div class="record-images">
                <div class="image-group">
                    <div class="image-group-title">图-1</div>
                    ${imgUrl1 ? `
                        <div class="image-item" onclick="showImage('${escapeAttr(imgUrl1)}')">
                            <img src="${imgUrl1}" alt="图-1" loading="lazy">
                            <div class="image-label">原图</div>
                        </div>` : '<div class="image-missing">无图片</div>'}
                    <div class="image-grid" style="margin-top:0.4rem">
                        ${viewImages1.map(v => renderImageItem(rec[v.key], v.label, rec, '1')).join('')}
                    </div>
                </div>
                <div class="image-group">
                    <div class="image-group-title">图-2</div>
                    ${imgUrl2 ? `
                        <div class="image-item" onclick="showImage('${escapeAttr(imgUrl2)}')">
                            <img src="${imgUrl2}" alt="图-2" loading="lazy">
                            <div class="image-label">原图</div>
                        </div>` : '<div class="image-missing">无图片</div>'}
                    <div class="image-grid" style="margin-top:0.4rem">
                        ${viewImages2.map(v => renderImageItem(rec[v.key], v.label, rec, '2')).join('')}
                    </div>
                </div>
            </div>

            ${Object.keys(params).length ? `
            <div class="defect-params">
                <h4>📐 缺陷参数 (OCR)
                    <button class="btn-edit-params" onclick="openEditParams(${rec.row_index})">✏️ 编辑</button>
                </h4>
                <div class="params-grid">
                    ${params['材料尺寸'] ? `<div class="param-item"><span class="param-label">材料尺寸:</span><span class="param-value">${escapeHtml(params['材料尺寸'])}</span></div>` : ''}
                    ${params['缺陷中心X'] ? `<div class="param-item"><span class="param-label">中心X:</span><span class="param-value">${escapeHtml(params['缺陷中心X'])}</span></div>` : ''}
                    ${params['缺陷中心Y'] ? `<div class="param-item"><span class="param-label">中心Y:</span><span class="param-value">${escapeHtml(params['缺陷中心Y'])}</span></div>` : ''}
                    ${params['缺陷长度'] ? `<div class="param-item"><span class="param-label">长度:</span><span class="param-value">${escapeHtml(params['缺陷长度'])}</span></div>` : ''}
                    ${params['缺陷宽度'] ? `<div class="param-item"><span class="param-label">宽度:</span><span class="param-value">${escapeHtml(params['缺陷宽度'])}</span></div>` : ''}
                    ${params['缺陷深度'] ? `<div class="param-item"><span class="param-label">深度:</span><span class="param-value">${escapeHtml(params['缺陷深度'])}</span></div>` : ''}
                </div>
            </div>` : `
            <div class="defect-params">
                <h4>📐 缺陷参数 (OCR)
                    <button class="btn-edit-params" onclick="openEditParams(${rec.row_index})">✏️ 编辑</button>
                </h4>
                <p class="empty-params">无 OCR 数据, 可手动添加</p>
            </div>`}

            ${(rec.warnings && rec.warnings.length) ? `
            <div class="warnings">⚠ ${rec.warnings.join('; ')}</div>` : ''}
        </div>
    `;

    return card;
}

function renderImageItem(path, label, rec, imgNum) {
    if (!path) return `<div class="image-item"><div class="image-missing">-</div></div>`;
    const url = `/api/image/${currentTaskId}/${relPath(path)}`;
    return `
        <div class="image-item" onclick="showImage('${escapeAttr(url)}')">
            <img src="${url}" alt="${label}" loading="lazy">
            <div class="image-label">${label}</div>
        </div>`;
}

function relPath(absPath) {
    // 转成相对于 output_dir 的相对路径
    if (!absPath) return '';
    // 找到 /output/{task_id}/ 之后的路径
    const idx = absPath.indexOf('/output/');
    if (idx >= 0) {
        const after = absPath.indexOf('/', idx + 8);
        return absPath.substring(after + 1);
    }
    return absPath;
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function escapeAttr(str) {
    return escapeHtml(str).replace(/'/g, '&#39;');
}

// ===== 图片预览模态框 =====
function showImage(url) {
    let modal = document.getElementById('image-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'image-modal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-close" onclick="closeModal()">×</div>
            <img src="" id="modal-img">
        `;
        document.body.appendChild(modal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });
    }
    document.getElementById('modal-img').src = url;
    modal.classList.add('active');
}


// ===== 表格行 =====
function createRecordRow(rec) {
    const tr = document.createElement('tr');
    tr.dataset.searchText = [
        rec['钢板号'], rec['生产厂'], rec['钢种'], rec['类别'], rec['缺陷分析']
    ].join(' ').toLowerCase();
    tr.innerHTML = `
        <td class="col-index">#${rec['序号'] || rec['row_index']}</td>
        <td class="col-factory">${escapeHtml(rec['生产厂'] || '-')}</td>
        <td class="col-plate">${escapeHtml(rec['钢板号'] || '-')}</td>
        <td class="col-grade">${escapeHtml(rec['钢种'] || '-')}</td>
        <td><span class="col-category">${escapeHtml(rec['类别'] || '-')}</span></td>
        <td class="col-defect" title="${escapeAttr(rec['缺陷分析'] || '')}">${escapeHtml(rec['缺陷分析'] || '-')}</td>
    `;
    tr.addEventListener('click', () => openRecordDetail(rec));
    return tr;
}

// ===== 详情弹窗 =====
let detailModalEl = null;
function openRecordDetail(rec) {
    if (!detailModalEl) {
        detailModalEl = document.createElement('div');
        detailModalEl.id = 'record-detail-modal';
        detailModalEl.className = 'modal record-detail-modal';
        detailModalEl.innerHTML = `
            <div class="modal-content" onclick="event.stopPropagation()">
                <div id="record-detail-body"></div>
            </div>
        `;
        document.body.appendChild(detailModalEl);
        detailModalEl.addEventListener('click', (e) => {
            if (e.target === detailModalEl) closeRecordDetail();
        });
    }
    const body = document.getElementById('record-detail-body');
    body.innerHTML = `
        <div class="detail-top">
            <div class="detail-fields">
                <div class="detail-field"><span class="df-label">序号</span><span class="df-value">#${rec['序号'] || rec['row_index']}</span></div>
                <div class="detail-field"><span class="df-label">钢板号</span><span class="df-value">${escapeHtml(rec['钢板号'] || '-')}</span></div>
                <div class="detail-field"><span class="df-label">生产厂</span><span class="df-value">${escapeHtml(rec['生产厂'] || '-')}</span></div>
                <div class="detail-field"><span class="df-label">钢种</span><span class="df-value">${escapeHtml(rec['钢种'] || '-')}</span></div>
                <div class="detail-field"><span class="df-label">类别</span><span class="df-value">${escapeHtml(rec['类别'] || '-')}</span></div>
                <div class="detail-field"><span class="df-label">缺陷分析</span><span class="df-value">${escapeHtml(rec['缺陷分析'] || '-')}</span></div>
            </div>
            <button type="button" class="modal-close-in" onclick="closeRecordDetail()">×</button>
        </div>
        ${buildRecordCardHTML(rec)}
    `;
    detailModalEl.classList.add('active');
}

function closeRecordDetail() {
    if (detailModalEl) detailModalEl.classList.remove('active');
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && detailModalEl && detailModalEl.classList.contains('active')) {
        closeRecordDetail();
    }
});

function closeModal() {
    const modal = document.getElementById('image-modal');
    if (modal) modal.classList.remove('active');
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

// ===== 搜索过滤 =====
// ===== 筛选弹窗 (只显当前列) =====
let currentFilterCol = null;
function openFilterModal(col) {
    console.log('[filter] open col=', col, 'recordsCache.length=', recordsCache.length);
    currentFilterCol = col;
    rebuildFilterDistinct();
    const st = filterState[col];
    const body = document.getElementById('filter-modal-body');
    body.innerHTML = '';
    // 标题
    document.getElementById('filter-modal-title').textContent = `筛选: ${col} (${st.distinct.length})`;
    // 仅一列
    const group = document.createElement('div');
    group.className = 'filter-group';
    if (st.distinct.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'filter-empty';
        empty.textContent = '无值';
        group.appendChild(empty);
    } else {
        for (const val of st.distinct) {
            const checked = !st.excluded.has(val);
            const lbl = document.createElement('label');
            lbl.className = 'filter-item';
            lbl.innerHTML = `<input type="checkbox" data-col="${escapeAttr(col)}" data-val="${escapeAttr(val)}" ${checked ? 'checked' : ''}><span>${escapeHtml(val)}</span>`;
            group.appendChild(lbl);
        }
    }
    body.appendChild(group);
    updateFilterSummary();
    document.getElementById('filter-modal').classList.add('active');
}

function closeFilterModal() {
    document.getElementById('filter-modal').classList.remove('active');
}

function applyFilterModal() {
    console.log('[filter] apply clicked, currentCol=', currentFilterCol);
    document.querySelectorAll('#filter-modal-body input[type=checkbox]').forEach(cb => {
        const col = cb.dataset.col;
        const val = cb.dataset.val;
        if (!filterState[col]) filterState[col] = { excluded: new Set(), distinct: [] };
        if (cb.checked) {
            filterState[col].excluded.delete(val);
        } else {
            filterState[col].excluded.add(val);
        }
    });
    closeFilterModal();
    paginationState.page = 1;   // 筛选后回到第 1 页
    renderRecords();
}

function updateFilterSummary() {
    const total = recordsCache.length;
    const displayed = getDisplayedRecords().length;
    const excludedCols = FILTER_COLS.filter(c => filterState[c] && filterState[c].excluded.size > 0).length;
    const el = document.getElementById('filter-summary');
    if (el) el.textContent = `当前: ${displayed}/${total} 条 (${excludedCols} 列筛选中)`;
}

// 每列筛选按钮
document.querySelectorAll('.th-filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
        e.stopPropagation(); // 不要触发 th 的点击排序
        openFilterModal(btn.dataset.col);
    });
});
document.getElementById('filter-apply-btn')?.addEventListener('click', applyFilterModal);
document.getElementById('filter-clear-col')?.addEventListener('click', () => {
    if (!currentFilterCol) return;
    filterState[currentFilterCol].excluded.clear();
    // 重绘弹窗 checkbox
    document.querySelectorAll('#filter-modal-body input[type=checkbox]').forEach(cb => { cb.checked = true; });
    updateFilterSummary();
});
document.getElementById('filter-select-all')?.addEventListener('click', () => {
    document.querySelectorAll('#filter-modal-body input[type=checkbox]').forEach(cb => { cb.checked = true; });
    updateFilterSummary();
});
document.getElementById('filter-invert')?.addEventListener('click', () => {
    document.querySelectorAll('#filter-modal-body input[type=checkbox]').forEach(cb => { cb.checked = !cb.checked; });
    updateFilterSummary();
});
// 点击弹窗背景关闭
document.getElementById('filter-modal')?.addEventListener('click', (e) => {
    if (e.target.id === 'filter-modal') closeFilterModal();
});
// 任何 checkbox 变化时更新摘要
document.addEventListener('change', (e) => {
    if (e.target.matches('#filter-modal-body input[type=checkbox]')) {
        updateFilterSummary();
    }
});


// 表头点击排序
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

// ===== 编辑缺陷参数弹窗 =====
let currentEditRow = null;
let recordsCache = [];  // 当前任务的记录缓存

function openEditParams(rowIndex) {
    const rec = recordsCache.find(r => r.row_index === rowIndex);
    if (!rec) {
        alert('未找到记录');
        return;
    }
    currentEditRow = rowIndex;
    const params = rec['缺陷数据'] || {};

    let modal = document.getElementById('edit-params-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'edit-params-modal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-content" onclick="event.stopPropagation()">
                <div class="modal-close" onclick="closeEditParams()">×</div>
                <h3>✏️ 编辑缺陷参数</h3>
                <p class="edit-hint">行 ${rowIndex} 钢板号: ${escapeHtml(rec['钢板号'] || '')}</p>
                <form id="edit-params-form">
                    <div class="form-field">
                        <label>材料尺寸</label>
                        <input type="text" name="材料尺寸" placeholder="如 12000×2430×30">
                    </div>
                    <div class="form-field">
                        <label>缺陷中心 X [mm]</label>
                        <input type="text" name="缺陷中心X" placeholder="如 8412">
                    </div>
                    <div class="form-field">
                        <label>缺陷中心 Y [mm]</label>
                        <input type="text" name="缺陷中心Y" placeholder="如 1839">
                    </div>
                    <div class="form-field">
                        <label>缺陷长度 [mm]</label>
                        <input type="text" name="缺陷长度" placeholder="如 1669.4">
                    </div>
                    <div class="form-field">
                        <label>缺陷宽度 [mm]</label>
                        <input type="text" name="缺陷宽度" placeholder="如 162.6">
                    </div>
                    <div class="form-field">
                        <label>缺陷深度 [mm]</label>
                        <input type="text" name="缺陷深度" placeholder="如 14.3">
                    </div>
                    <div class="form-actions">
                        <button type="button" class="btn-secondary" onclick="closeEditParams()">取消</button>
                        <button type="submit" class="btn-primary">💾 保存</button>
                    </div>
                </form>
            </div>
        `;
        document.body.appendChild(modal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeEditParams();
        });
        // 绑定提交
        document.getElementById('edit-params-form').addEventListener('submit', saveEditParams);
    }

    // 填充当前值
    const form = document.getElementById('edit-params-form');
    form.reset();
    ['材料尺寸', '缺陷中心X', '缺陷中心Y', '缺陷长度', '缺陷宽度', '缺陷深度'].forEach(k => {
        const input = form.elements[k];
        if (input) input.value = params[k] || '';
    });
    // 更新提示文字
    modal.querySelector('.edit-hint').textContent =
        `行 ${rowIndex} 钢板号: ${rec['钢板号'] || ''} 类别: ${rec['类别'] || ''}`;

    modal.classList.add('active');
    setTimeout(() => {
        const firstInput = form.querySelector('input');
        if (firstInput) firstInput.focus();
    }, 100);
}

function closeEditParams() {
    const modal = document.getElementById('edit-params-modal');
    if (modal) modal.classList.remove('active');
    currentEditRow = null;
}

async function saveEditParams(e) {
    e.preventDefault();
    if (currentEditRow === null || !currentTaskId) return;

    const form = e.target;
    const newParams = {};
    ['材料尺寸', '缺陷中心X', '缺陷中心Y', '缺陷长度', '缺陷宽度', '缺陷深度'].forEach(k => {
        const v = form.elements[k].value.trim();
        if (v) newParams[k] = v;
    });

    // 乐观更新 UI
    const rec = recordsCache.find(r => r.row_index === currentEditRow);
    if (rec) rec['缺陷数据'] = newParams;

    // 发送到后端
    try {
        const res = await fetch(`/api/records/${currentTaskId}/${currentEditRow}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 缺陷数据: newParams })
        });
        const data = await res.json();
        if (data.error) throw new Error(data.error);
        // 重新渲染
        renderRecords();
        closeEditParams();
    } catch (err) {
        alert('保存失败: ' + err.message);
    }
}

// ===== 任务列表 =====
async function refreshTaskList() {
    try {
        const res = await fetch('/api/list');
        const data = await res.json();
        const list = document.getElementById('task-list') || document.getElementById('app-bar-tasks');
        if (!data.tasks.length) {
            list.innerHTML = '<p class="empty">暂无任务</p>';
            return;
        }
        list.innerHTML = data.tasks.map(t => {
            const stage = t.stage ? ' · ' + t.stage : '';
            const prog = t.status === 'processing' ? ' ' + Math.round((t.progress||0)*100) + '%' : '';
            const count = t.count != null ? ' · ' + t.count + ' 条' : '';
            return `
            <div class="task-item ${t.task_id === currentTaskId ? 'active' : ''}"
                 onclick="selectTask('${t.task_id}')">
                <div class="task-name">${escapeHtml(t.file)}</div>
                <div class="task-status ${t.status}">
                    ${t.status === 'completed' ? '✓ 已完成' :
                      t.status === 'failed' ? '✗ 失败' :
                      t.status === 'processing' ? '⏳' + prog + stage :
                      '⏸ 等待中'}
                    ${count}
                </div>
            </div>
        `;}).join('');

        // 默认选中第一个已完成任务, 自动加载其记录
        if (!currentTaskId && data.tasks.length > 0) {
            const first = data.tasks.find(t => t.status === 'completed') || data.tasks[0];
            selectTask(first.task_id);
        }
    } catch (e) {
        console.error('Refresh tasks error:', e);
    }
}

async function selectTask(taskId) {
    currentTaskId = taskId;
    document.querySelectorAll('.task-item').forEach(el => el.classList.remove('active'));
    const items = document.querySelectorAll('.task-item');
    items.forEach(el => {
        if (el.textContent.includes(taskId)) el.classList.add('active');
    });

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

// ===== 下载 =====
// ===== 下载 (按当前 filter+sort) =====
// 8 张图: 2 张原图 + 2 套三视图(俯视图 / 长边 / 短边); 还多 1 张视图标注预览-1/-2
const EXPORT_IMG_KEYS = [
    '视图标注预览-1', '图-1', '俯视图-1', '长边方向侧视图-1', '短边方向侧视图-1',
    '视图标注预览-2', '图-2', '俯视图-2', '长边方向侧视图-2', '短边方向侧视图-2',
];

const EXPORT_COLS = [
    { key: '序号', label: '序号' },
    { key: '生产厂', label: '生产厂' },
    { key: '钢板号', label: '钢板号' },
    { key: '钢种', label: '钢种' },
    { key: '类别', label: '类别' },
    { key: '缺陷分析', label: '缺陷分析' },
    { key: '视图标注预览-1', label: '标注预览-1', kind: 'image' },
    { key: '图-1', label: '原图-1', kind: 'image' },
    { key: '俯视图-1', label: '俯视图-1', kind: 'image' },
    { key: '长边方向侧视图-1', label: '长边-1', kind: 'image' },
    { key: '短边方向侧视图-1', label: '短边-1', kind: 'image' },
    { key: '视图标注预览-2', label: '标注预览-2', kind: 'image' },
    { key: '图-2', label: '原图-2', kind: 'image' },
    { key: '俯视图-2', label: '俯视图-2', kind: 'image' },
    { key: '长边方向侧视图-2', label: '长边-2', kind: 'image' },
    { key: '短边方向侧视图-2', label: '短边-2', kind: 'image' },
    { key: '_材料尺寸', label: '材料尺寸', param: '材料尺寸' },
    { key: '_缺陷中心X', label: '中心X', param: '缺陷中心X' },
    { key: '_缺陷中心Y', label: '中心Y', param: '缺陷中心Y' },
    { key: '_缺陷长度', label: '长度', param: '缺陷长度' },
    { key: '_缺陷宽度', label: '宽度', param: '缺陷宽度' },
    { key: '_缺陷深度', label: '深度', param: '缺陷深度' },
    { key: '_缺陷面积', label: '面积', param: '缺陷面积' },
    { key: '_C扫描值', label: 'C扫描值', param: 'C扫描值' },
    { key: 'warnings', label: '警告', list: true },
];

function buildExportRows() {
    const displayed = getDisplayedRecords();
    return displayed.map((rec, i) => {
        const row = { '序号': i + 1 };
        const params = rec['缺陷数据'] || {};
        for (const c of EXPORT_COLS) {
            if (c.key === '序号') continue;
            if (c.kind === 'image') {
                row[c.key] = rec[c.key] || null;
            } else if (c.param) {
                const v = params[c.param];
                // 用 param 自己的名字(去掉下划线前缀)作为 row key, 让 JSON 也好看
                const rowKey = c.key.startsWith('_') ? c.key.slice(1) : c.key;
                row[rowKey] = v != null && v !== '' ? v : '';
            } else if (c.list) {
                const arr = rec[c.key];
                row[c.key] = Array.isArray(arr) && arr.length ? arr.join('; ') : '';
            } else {
                row[c.key] = rec[c.key] != null ? rec[c.key] : '';
            }
        }
        return row;
    });
}

// 把 image 路径转成可访问的 URL (与详情弹窗同一套规则)
function imageUrl(absPath) {
    if (!absPath) return null;
    return `/api/image/${currentTaskId}/${relPath(absPath)}`;
}

// 抓一张图的二进制, 返回 { bytes: Uint8Array, ext: 'png'|'jpeg' } 或 null
async function fetchImageBytes(absPath) {
    const url = imageUrl(absPath);
    if (!url) return null;
    try {
        const resp = await fetch(url);
        if (!resp.ok) return null;
        const buf = await resp.arrayBuffer();
        const bytes = new Uint8Array(buf);
        const lower = url.toLowerCase();
        const ext = lower.endsWith('.png') ? 'png'
                  : lower.endsWith('.jpg') || lower.endsWith('.jpeg') ? 'jpeg'
                  : lower.endsWith('.gif') ? 'gif'
                  : 'png';
        return { bytes, ext };
    } catch (e) {
        console.error('fetchImageBytes failed:', url, e);
        return null;
    }
}

function downloadBlob(content, filename, mime) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function escapeXml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

document.getElementById('download-json').addEventListener('click', () => {
    if (!currentTaskId) return;
    const rows = buildExportRows();
    const payload = { task_id: currentTaskId, count: rows.length, records: rows };
    downloadBlob(JSON.stringify(payload, null, 2), 'defect_records_' + currentTaskId + '.json', 'application/json');
});

// ========== OOXML (.xlsx) 构造 ==========
// 用 JSZip 拼出真实的 .xlsx zip, 内嵌图-1/图-2 原图。

// 把 colIdx (0-based) 转成 Excel 字母列名 (0->A, 1->B, ..., 26->AA)
function colLetter(colIdx) {
    let s = '';
    let n = colIdx;
    while (true) {
        s = String.fromCharCode(65 + (n % 26)) + s;
        n = Math.floor(n / 26) - 1;
        if (n < 0) break;
    }
    return s;
}

// XML 字符转义
function xEsc(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

// Excel 内置列宽单位很怪: 1 char ≈ 7 px, 但我们用 8 像素/字符单位 (Excel 内部用字符宽度)
// 这里我们直接用 pixel 估算, 乘以 ~256/8 让 Excel 接受
function pixelsToXlsxWidth(px) {
    return Math.max(1, Math.round(px * 256 / 8));
}

// 高度用磅 (1 pt = 1/72 inch); 110px ≈ 82pt
function pixelsToRowHeightPt(px) {
    return Math.round(px * 72 / 96);  // 假设 96 dpi
}

async function buildXlsxFile(rows) {
    if (typeof JSZip === 'undefined') {
        throw new Error('JSZip 未加载 (检查网络)');
    }

    // 1) 抓所有图片, 收集进 mediaImages 数组
    const imgJobs = [];
    const imgKeys = [];   // 与 imgJobs 平行: 记录每张图对应的 (rowIdx, colKey)
    for (let i = 0; i < rows.length; i++) {
        for (const k of EXPORT_IMG_KEYS) {
            const p = rows[i][k];
            if (p) {
                imgJobs.push(fetchImageBytes(p));
                imgKeys.push({ rowIdx: i, colKey: k });
            }
        }
    }
    const imgResults = await Promise.all(imgJobs);
    // 收集成功的图片: { idx, ext, bytes, rowIdx, colKey }
    const mediaImages = [];
    for (let i = 0; i < imgResults.length; i++) {
        const r = imgResults[i];
        if (r) {
            mediaImages.push({
                idx: mediaImages.length,
                ext: r.ext,
                bytes: r.bytes,
                rowIdx: imgKeys[i].rowIdx,
                colKey: imgKeys[i].colKey,
            });
        }
    }

    // 2) 列宽配置 (像素)
    const colPxWidths = EXPORT_COLS.map(c => {
        if (c.kind === 'image') return 180;
        if (c.key === '钢板号' || c.key === '钢种') return 140;
        if (c.key === '缺陷分析') return 160;
        return 80;
    });
    const headerRowPxHeight = 24;
    const dataRowPxHeight = 110;   // 行高足够展示图

    // 3) 构建 sheet1.xml
    //   - 表头行 (索引 1)
    //   - 数据行 (索引 2..N+1)
    //   - <drawing r:id="rId1"/> 引用 drawing
    const sheetRows = [];
    // 表头
    let headerCells = '';
    EXPORT_COLS.forEach((c, ci) => {
        headerCells += `<c r="${colLetter(ci)}1" s="1" t="inlineStr"><is><t>${xEsc(c.label)}</t></is></c>`;
    });
    sheetRows.push(`<row r="1" ht="${pixelsToRowHeightPt(headerRowPxHeight)}" customHeight="1">${headerCells}</row>`);

    // 数据行
    for (let i = 0; i < rows.length; i++) {
        const r = rows[i];
        const excelRow = i + 2;
        let cells = '';
        EXPORT_COLS.forEach((c, ci) => {
            const v = r[c.key];
            const col = colLetter(ci);
            if (c.kind === 'image') {
                // 留空 (图片在 drawing 里通过 anchor 覆盖在 cell 上)
                cells += `<c r="${col}${excelRow}"/>`;
            } else if (v == null || v === '') {
                cells += `<c r="${col}${excelRow}"/>`;
            } else if (typeof v === 'number') {
                cells += `<c r="${col}${excelRow}"><v>${v}</v></c>`;
            } else {
                cells += `<c r="${col}${excelRow}" t="inlineStr"><is><t xml:space="preserve">${xEsc(v)}</t></is></c>`;
            }
        });
        sheetRows.push(`<row r="${excelRow}" ht="${pixelsToRowHeightPt(dataRowPxHeight)}" customHeight="1">${cells}</row>`);
    }

    // cols (列宽)
    let colsXml = '<cols>';
    EXPORT_COLS.forEach((c, ci) => {
        const w = pixelsToXlsxWidth(colPxWidths[ci]);
        colsXml += `<col min="${ci + 1}" max="${ci + 1}" width="${w}" customWidth="1"/>`;
    });
    colsXml += '</cols>';

    // sheetView: 冻结表头
    const sheetView = `<sheetView tabSelected="1" workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView>`;

    // drawing 引用 (如果有任何图片)
    const drawingRef = mediaImages.length > 0
        ? '<drawing r:id="rId1"/>'
        : '';

    const sheet1Xml =
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
        sheetView +
        '<sheetFormatPr defaultRowHeight="15"/>' +
        colsXml +
        '<sheetData>' + sheetRows.join('') + '</sheetData>' +
        drawingRef +
        '</worksheet>';

    // 4) drawing1.xml
    //    每个图片用 <xdr:twoCellAnchor> 定位到 (rowIdx+2, colIdx) 到 (rowIdx+3, colIdx+1)
    //    图片的 rId 通过 drawing1.xml.rels 解析
    function drawingForImage(img) {
        const ci = EXPORT_COLS.findIndex(c => c.key === img.colKey);
        const excelRow = img.rowIdx + 2;     // 1-based, +1 表头
        const fromCol = ci, toCol = ci + 1;
        const fromRow = excelRow - 1, toRow = excelRow;   // 0-based; 图片"覆盖"在数据行上
        return (
            `<xdr:twoCellAnchor>` +
                `<xdr:from><xdr:col>${fromCol}</xdr:col><xdr:colOff>0</xdr:colOff>` +
                `<xdr:row>${fromRow}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>` +
                `<xdr:to><xdr:col>${toCol}</xdr:col><xdr:colOff>0</xdr:colOff>` +
                `<xdr:row>${toRow}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>` +
                `<xdr:pic>` +
                    `<xdr:nvPicPr>` +
                        `<xdr:cNvPr id="${img.idx + 1}" name="img${img.idx + 1}"/>` +
                        `<xdr:cNvPicPr/>` +
                    `</xdr:nvPicPr>` +
                    `<xdr:blipFill>` +
                        `<a:blip xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:embed="rId${img.idx + 1}"/>` +
                        `<a:stretch xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:fillRect/></a:stretch>` +
                    `</xdr:blipFill>` +
                    `<xdr:spPr>` +
                        `<a:xfrm xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">` +
                            `<a:off x="0" y="0"/><a:ext cx="1500000" cy="1100000"/>` +
                        `</a:xfrm>` +
                        `<a:prstGeom xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" prst="rect"><a:avLst/></a:prstGeom>` +
                    `</xdr:spPr>` +
                `</xdr:pic>` +
                `<xdr:clientData/>` +
            `</xdr:twoCellAnchor>`
        );
    }
    const drawing1Xml = mediaImages.length === 0
        ? ''
        : '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
          '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" ' +
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' +
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
          mediaImages.map(drawingForImage).join('') +
          '</xdr:wsDr>';

    // 5) 各种 .rels
    const relsRoot =
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
        '</Relationships>';

    const workbookRels =
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' +
        '</Relationships>';

    const sheetRels = mediaImages.length === 0
        ? ''
        : '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
              '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>' +
          '</Relationships>';

    const drawingRels =
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
            mediaImages.map(img =>
                `<Relationship Id="rId${img.idx + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image${img.idx + 1}.${img.ext}"/>`
            ).join('') +
        '</Relationships>';

    // 6) workbook.xml
    const workbookXml =
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
            '<sheets>' +
                '<sheet name="缺陷记录" sheetId="1" r:id="rId1"/>' +
            '</sheets>' +
        '</workbook>';

    // 7) styles.xml — 至少 2 个样式:
    //    0: 默认
    //    1: 表头 (粗体 + 灰底)
    const stylesXml =
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
            '<fonts count="2">' +
                '<font><sz val="11"/><name val="Calibri"/></font>' +
                '<font><b/><sz val="11"/><name val="Calibri"/></font>' +
            '</fonts>' +
            '<fills count="3">' +
                '<fill><patternFill patternType="none"/></fill>' +
                '<fill><patternFill patternType="gray125"/></fill>' +
                '<fill><patternFill patternType="solid"><fgColor rgb="FFDDDDDD"/><bgColor indexed="64"/></patternFill></fill>' +
            '</fills>' +
            '<borders count="1"><border/></borders>' +
            '<cellStyleXfs count="1"><xf/></cellStyleXfs>' +
            '<cellXfs count="2">' +
                '<xf fontId="0" fillId="0" borderId="0" xfId="0"/>' +
                '<xf fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>' +
            '</cellXfs>' +
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>' +
        '</styleSheet>';

    // 8) [Content_Types].xml
    //    至少包含: workbook, styles, sheet1; 有图片则加 png/jpeg/gif 默认
    const defaultTypes = [];
    // 对每个图片 ext 加一个 Default 声明
    const exts = new Set(mediaImages.map(m => m.ext));
    for (const e of exts) {
        const mime = e === 'png' ? 'image/png' : e === 'jpeg' ? 'image/jpeg' : 'image/gif';
        defaultTypes.push(`<Default Extension="${e}" ContentType="${mime}"/>`);
    }
    const overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ];
    if (drawing1Xml) {
        overrides.push('<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>');
    }
    const contentTypesXml =
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
            '<Default Extension="xml" ContentType="application/xml"/>' +
            defaultTypes.join('') +
            overrides.join('') +
        '</Types>';

    // 9) 用 JSZip 打包
    const zip = new JSZip();
    zip.file('[Content_Types].xml', contentTypesXml);
    zip.file('_rels/.rels', relsRoot);
    zip.folder('xl').file('workbook.xml', workbookXml);
    zip.folder('xl').folder('_rels').file('workbook.xml.rels', workbookRels);
    zip.folder('xl').file('styles.xml', stylesXml);
    zip.folder('xl/worksheets').file('sheet1.xml', sheet1Xml);
    if (sheetRels) {
        zip.folder('xl/worksheets/_rels').file('sheet1.xml.rels', sheetRels);
    }
    if (drawing1Xml) {
        zip.folder('xl/drawings').file('drawing1.xml', drawing1Xml);
        zip.folder('xl/drawings/_rels').file('drawing1.xml.rels', drawingRels);
    }
    for (const img of mediaImages) {
        zip.folder('xl/media').file(`image${img.idx + 1}.${img.ext}`, img.bytes);
    }
    return await zip.generateAsync({ type: 'blob', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
}

document.getElementById('download-excel').addEventListener('click', async () => {
    if (!currentTaskId) return;
    const btn = document.getElementById('download-excel');
    const origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ 抓图中...';
    try {
        const rows = buildExportRows();
        const blob = await buildXlsxFile(rows);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'defect_records_' + currentTaskId + '.xlsx';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
        console.error('Excel download failed:', err);
        alert('导出失败: ' + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = origText;
    }
});


// 初始化
refreshTaskList();
setInterval(refreshTaskList, 5000);

// ===== 上传弹窗控制 =====
const uploadModal = document.getElementById('upload-modal');
const openUploadBtn = document.getElementById('open-upload-btn');
const cancelUploadBtn = document.getElementById('cancel-upload-btn');

function openUploadModal() {
    if (!uploadModal) return;
    uploadModal.classList.add('active');
}

function closeUploadModal() {
    if (!uploadModal) return;
    uploadModal.classList.remove('active');
}

if (openUploadBtn) openUploadBtn.addEventListener('click', openUploadModal);
if (cancelUploadBtn) cancelUploadBtn.addEventListener('click', closeUploadModal);
if (uploadModal) {
    uploadModal.addEventListener('click', (e) => {
        if (e.target === uploadModal) closeUploadModal();
    });
}
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && uploadModal && uploadModal.classList.contains('active')) {
        closeUploadModal();
    }
});
