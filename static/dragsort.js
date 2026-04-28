// dragsort.js — lightweight HTML5 drag-and-drop list sorter for AISBF
// Items must carry data-sort-key attribute.
// Drag handles must have class="drag-handle" (clicking elsewhere won't drag).
(function (global) {
    'use strict';

    var _active = null; // { key, inst }
    var _navTimer = null;

    function _clearNav() {
        if (_navTimer) { clearTimeout(_navTimer); _navTimer = null; }
    }

    function _clearIndicators() {
        document.querySelectorAll('.ds-over-top,.ds-over-bottom').forEach(function (el) {
            el.classList.remove('ds-over-top', 'ds-over-bottom');
        });
    }

    function _nearest(el, selector) {
        while (el && el !== document.body) {
            if (el.matches && el.matches(selector)) return el;
            el = el.parentElement;
        }
        return null;
    }

    function _moveItem(order, srcKey, tgtKey, before) {
        var arr = order.slice();
        var si = arr.indexOf(srcKey);
        if (si === -1) return arr;
        arr.splice(si, 1);
        var ti = arr.indexOf(tgtKey);
        if (ti === -1) return arr;
        arr.splice(before ? ti : ti + 1, 0, srcKey);
        return arr;
    }

    // ──────────────────────────────────────────────────────────────────────────
    // DragSort constructor
    //
    // opts:
    //   containerId   string  — id of the list container element
    //   masterOrder   object  — { value: string[] }  (ref so we can mutate it)
    //   onReorder     fn(newOrder)  — called after every reorder
    //   pagination    object (optional):
    //     getCurrentPage()  → int
    //     getTotalPages()   → int
    //     goToPage(p)
    //     pageSize          int
    //     getFilteredKeys() → string[]  (ordered, filtered, all pages)
    // ──────────────────────────────────────────────────────────────────────────
    function DragSort(opts) {
        this._opts = opts;
        this._containerListeners = false;
        this.attach();
    }

    DragSort.prototype._container = function () {
        return document.getElementById(this._opts.containerId);
    };

    // Attach container-level event delegation (once) and per-item dragstart.
    // Safe to call after every render — container listeners are only added once.
    DragSort.prototype.attach = function () {
        var self = this;
        var container = self._container();
        if (!container) return;

        // Container-level delegation — only wired once
        if (!self._containerListeners) {
            self._containerListeners = true;

            container.addEventListener('dragover', function (e) {
                if (!_active || _active.inst !== self) return;
                var item = _nearest(e.target, '[data-sort-key]');
                if (!item) return;
                if (item.dataset.sortKey === _active.key) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';

                _clearIndicators();
                var r = item.getBoundingClientRect();
                item.classList.add(e.clientY < r.top + r.height * 0.5 ? 'ds-over-top' : 'ds-over-bottom');

                // Auto-navigate near edges when pagination is active
                var p = self._opts.pagination;
                if (p) {
                    var cr = container.getBoundingClientRect();
                    _clearNav();
                    if (e.clientY < cr.top + 48 && p.getCurrentPage() > 0) {
                        _navTimer = setTimeout(function () {
                            _navTimer = null;
                            p.goToPage(p.getCurrentPage() - 1);
                        }, 650);
                    } else if (e.clientY > cr.bottom - 48 && p.getCurrentPage() < p.getTotalPages() - 1) {
                        _navTimer = setTimeout(function () {
                            _navTimer = null;
                            p.goToPage(p.getCurrentPage() + 1);
                        }, 650);
                    }
                }
            });

            container.addEventListener('dragleave', function (e) {
                var item = _nearest(e.target, '[data-sort-key]');
                if (item) { item.classList.remove('ds-over-top', 'ds-over-bottom'); }
                _clearNav();
            });

            container.addEventListener('drop', function (e) {
                if (!_active || _active.inst !== self) return;
                var item = _nearest(e.target, '[data-sort-key]');
                if (!item) return;
                e.preventDefault();
                _clearNav();
                var tgt = item.dataset.sortKey;
                if (tgt === _active.key) { _clearIndicators(); return; }
                var before = item.classList.contains('ds-over-top');
                _clearIndicators();
                var newOrder = _moveItem(self._opts.masterOrder.value, _active.key, tgt, before);
                self._opts.masterOrder.value = newOrder;
                self._opts.onReorder(newOrder);
            });
        }

        // Per-item: dragstart / dragend
        container.querySelectorAll('[data-sort-key]').forEach(function (item) {
            var handle = item.querySelector('.drag-handle');
            if (handle) {
                // Only allow drag when pointer is on the handle
                item.setAttribute('draggable', 'false');
                handle.addEventListener('pointerdown', function () {
                    item.setAttribute('draggable', 'true');
                });
                // Reset after a tick if dragstart didn't fire
                handle.addEventListener('pointerup', function () {
                    setTimeout(function () { item.setAttribute('draggable', 'false'); }, 100);
                });
            } else {
                item.setAttribute('draggable', 'true');
            }

            item.addEventListener('dragstart', function (e) {
                if (item.getAttribute('draggable') !== 'true') { e.preventDefault(); return; }
                _active = { key: item.dataset.sortKey, inst: self };
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', item.dataset.sortKey);
                requestAnimationFrame(function () { item.classList.add('ds-dragging'); });
            });

            item.addEventListener('dragend', function () {
                item.classList.remove('ds-dragging');
                item.setAttribute('draggable', 'false');
                _clearIndicators();
                _clearNav();
                _active = null;
            });
        });

        // Cross-page sentinel zones (optional, only rendered when pagination active)
        self._setupSentinel(self._opts.containerId + '-page-prev', -1);
        self._setupSentinel(self._opts.containerId + '-page-next', +1);
    };

    DragSort.prototype._setupSentinel = function (sentinelId, direction) {
        var self = this;
        var el = document.getElementById(sentinelId);
        if (!el) return;

        el.ondragover = function (e) {
            if (!_active || _active.inst !== self) return;
            e.preventDefault();
            el.classList.add('ds-sentinel-active');
            _clearNav();
            var p = self._opts.pagination;
            if (!p) return;
            _navTimer = setTimeout(function () {
                _navTimer = null;
                var pg = p.getCurrentPage() + direction;
                if (pg >= 0 && pg < p.getTotalPages()) { p.goToPage(pg); }
            }, 600);
        };

        el.ondragleave = function () {
            el.classList.remove('ds-sentinel-active');
            _clearNav();
        };

        el.ondrop = function (e) {
            e.preventDefault();
            el.classList.remove('ds-sentinel-active');
            _clearNav();
            if (!_active || _active.inst !== self) return;
            var p = self._opts.pagination;
            if (!p) return;
            var pg = p.getCurrentPage() + direction;
            if (pg < 0 || pg >= p.getTotalPages()) return;
            var filtered = p.getFilteredKeys();
            var pageStart = pg * p.pageSize;
            var pageEnd = Math.min(pageStart + p.pageSize, filtered.length);
            // direction < 0 → insert before first item of prev page
            // direction > 0 → insert after last item of next page
            var anchor = direction < 0 ? filtered[pageStart] : filtered[pageEnd - 1];
            if (anchor) {
                var newOrder = _moveItem(
                    self._opts.masterOrder.value,
                    _active.key,
                    anchor,
                    direction < 0   // before=true for prev page, before=false (after) for next page
                );
                self._opts.masterOrder.value = newOrder;
                self._opts.onReorder(newOrder);
            }
            p.goToPage(pg);
        };
    };

    // ── CSS injected once ────────────────────────────────────────────────────
    (function () {
        if (document.getElementById('dragsort-css')) return;
        var style = document.createElement('style');
        style.id = 'dragsort-css';
        style.textContent = [
            '.drag-handle{cursor:grab;padding:0 8px;color:var(--color-muted,#888);font-size:18px;line-height:1;user-select:none;touch-action:none;flex-shrink:0;}',
            '.drag-handle:active{cursor:grabbing;}',
            '.ds-dragging{opacity:.35;}',
            '[data-sort-key]{transition:border-top-color .1s,border-bottom-color .1s;}',
            '.ds-over-top{border-top:2px solid #3b82f6!important;}',
            '.ds-over-bottom{border-bottom:2px solid #3b82f6!important;}',
            '.ds-sentinel{display:none;align-items:center;justify-content:center;height:36px;border:2px dashed var(--color-border,#555);border-radius:4px;margin:4px 0;color:var(--color-muted,#888);font-size:12px;gap:6px;transition:background .15s,border-color .15s;}',
            '.ds-sentinel.ds-visible{display:flex;}',
            '.ds-sentinel.ds-sentinel-active{border-color:#3b82f6;background:rgba(59,130,246,.08);color:#3b82f6;}',
        ].join('');
        document.head.appendChild(style);
    })();

    global.DragSort = DragSort;
})(window);
