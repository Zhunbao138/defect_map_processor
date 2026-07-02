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

// ===== 任务下拉 =====
async function refreshTaskList() {
    try {
        const res = await fetch('/api/list');
        const data = await res.json();
        const select = document.getElementById('task-list');
        if (!select) return;

        if (!data.tasks.length) {
            select.innerHTML = '<option value="">暂无任务</option>';
            return;
        }

        // 渲染 <option> 列表, label 里塞状态 + 进度
        select.innerHTML = data.tasks.map(t => {
            const prog = t.status === 'processing' ? ' · ' + Math.round((t.progress||0)*100) + '%' : '';
            const count = t.count != null ? ' · ' + t.count + ' 条' : '';
            const statusLabel = t.status === 'completed' ? '✓ 已完成'
                              : t.status === 'failed' ? '✗ 失败'
                              : t.status === 'processing' ? '⏳ 处理中' + prog
                              : '⏸ 等待中';
            const file = (t.file || '').split('/').pop();   // 只显示文件名, 不显示完整路径
            return `<option value="${t.task_id}">${escapeHtml(statusLabel + count + ' — ' + file)}</option>`;
        }).join('');

        // 保持当前选中状态
        if (currentTaskId && data.tasks.some(t => t.task_id === currentTaskId)) {
            select.value = currentTaskId;
        }

        // 默认选中第一个已完成任务, 自动加载其记录
        if (!currentTaskId && data.tasks.length > 0) {
            const first = data.tasks.find(t => t.status === 'completed') || data.tasks[0];
            select.value = first.task_id;
            selectTask(first.task_id);
        }
    } catch (e) {
        console.error('Refresh tasks error:', e);
    }
}

async function selectTask(taskId) {
    if (!taskId) return;
    currentTaskId = taskId;
    // 同步下拉的选中状态 (如果调用方还没设)
    const select = document.getElementById('task-list');
    if (select && select.value !== taskId) select.value = taskId;

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

// 任务下拉的 change 事件 (用户直接换 task 时)
document.getElementById('task-list')?.addEventListener('change', (e) => {
    selectTask(e.target.value);
});

// ===== 下载 (按当前 filter+sort) =====
// JSON 导出 (前端生成): 文本 + OCR 参数 + warnings
// xlsx 导出 (后端 openpyxl 生成): 通过 GET /api/image/<task>/defect_records.xlsx
const EXPORT_COLS = [
    { key: '序号', label: '序号' },
    { key: '生产厂', label: '生产厂' },
    { key: '钢板号', label: '钢板号' },
    { key: '钢种', label: '钢种' },
    { key: '类别', label: '类别' },
    { key: '缺陷分析', label: '缺陷分析' },
    { key: '图-1', label: '图-1' },
    { key: '图-2', label: '图-2' },
    { key: '俯视图-1', label: '俯视图-1' },
    { key: '长边方向侧视图-1', label: '长边方向侧视图-1' },
    { key: '短边方向侧视图-1', label: '短边方向侧视图-1' },
    { key: '俯视图-2', label: '俯视图-2' },
    { key: '长边方向侧视图-2', label: '长边方向侧视图-2' },
    { key: '短边方向侧视图-2', label: '短边方向侧视图-2' },
    { key: '材料尺寸', label: '材料尺寸', param: '材料尺寸' },
    { key: '缺陷中心X', label: '缺陷中心X', param: '缺陷中心X' },
    { key: '缺陷中心Y', label: '缺陷中心Y', param: '缺陷中心Y' },
    { key: '缺陷长度', label: '缺陷长度', param: '缺陷长度' },
    { key: '缺陷宽度', label: '缺陷宽度', param: '缺陷宽度' },
    { key: '缺陷深度', label: '缺陷深度', param: '缺陷深度' },
    { key: '缺陷面积', label: '缺陷面积', param: '缺陷面积' },
    { key: 'C扫描值', label: 'C扫描值', param: 'C扫描值' },
    { key: 'warnings', label: '警告', list: true },
];

function buildExportRows() {
    const displayed = getDisplayedRecords();
    return displayed.map((rec, i) => {
        const row = { '序号': i + 1 };
        const params = rec['缺陷数据'] || {};
        for (const c of EXPORT_COLS) {
            if (c.key === '序号') continue;
            if (c.param) {
                const v = params[c.param];
                row[c.key] = v != null && v !== '' ? v : '';
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

// (Excel 导出改成后端 openpyxl 生成, 见 app.py 里的 /api/export/xlsx/<task_id> 端点)
// 客户端只需要触发下载即可, 不再手工拼 OOXML.

document.getElementById('download-excel').addEventListener('click', () => {
    if (!currentTaskId) return;
    // 后端 openpyxl 生成的 xlsx, 通过 /api/image/<task>/defect_records.xlsx 提供下载
    window.location.href = `/api/image/${currentTaskId}/defect_records.xlsx`;
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
