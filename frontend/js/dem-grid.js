/* Shared ESRI ASCII DEM renderer and UTM 48N cell picker. */
(() => {
    'use strict';

    const colorStops = [
        [0.00, [24, 55, 68]],
        [0.24, [40, 105, 99]],
        [0.50, [110, 151, 112]],
        [0.73, [202, 186, 121]],
        [1.00, [238, 226, 191]],
    ];

    function parse(text) {
        const source = String(text || '').replace(/^\uFEFF/, '');
        const lines = [];
        let cursor = 0;
        for (let i = 0; i < 6; i += 1) {
            const end = source.indexOf('\n', cursor);
            if (end < 0) throw new Error('File DEM thiếu dữ liệu.');
            lines.push(source.slice(cursor, end).trim());
            cursor = end + 1;
        }
        const header = {};
        for (const line of lines.slice(0, 6)) {
            const [key, value] = line.trim().split(/\s+/);
            if (!key || value == null) throw new Error('Tiêu đề DEM không đúng định dạng ESRI ASCII Grid.');
            header[key.toLowerCase()] = Number(value);
        }
        const ncols = header.ncols;
        const nrows = header.nrows;
        const cellsize = header.cellsize;
        const nodata = header.nodata_value;
        const xKey = Object.prototype.hasOwnProperty.call(header, 'xllcorner') ? 'xllcorner' : 'xllcenter';
        const yKey = Object.prototype.hasOwnProperty.call(header, 'yllcorner') ? 'yllcorner' : 'yllcenter';
        if (!Number.isInteger(ncols) || !Number.isInteger(nrows) || ncols < 1 || nrows < 1 || ncols * nrows > 10000000
            || !Number.isFinite(cellsize) || cellsize <= 0 || !Number.isFinite(nodata)
            || !Number.isFinite(header[xKey]) || !Number.isFinite(header[yKey])) {
            throw new Error('Thông số lưới hoặc tọa độ DEM không hợp lệ.');
        }
        const xllcorner = header[xKey] - (xKey === 'xllcenter' ? cellsize / 2 : 0);
        const yllcorner = header[yKey] - (yKey === 'yllcenter' ? cellsize / 2 : 0);
        const expected = ncols * nrows;
        const values = new Float32Array(expected);
        let min = Infinity;
        let max = -Infinity;
        const tokens = /\S+/g;
        tokens.lastIndex = cursor;
        let i = 0;
        let match;
        while ((match = tokens.exec(source))) {
            if (i >= expected) throw new Error('Số ô dữ liệu không khớp kích thước DEM.');
            const value = Number(match[0]);
            if (!Number.isFinite(value)) throw new Error('DEM chứa giá trị không hợp lệ.');
            values[i] = value;
            if (value !== nodata) { min = Math.min(min, value); max = Math.max(max, value); }
            i += 1;
        }
        if (i !== expected) throw new Error('Số ô dữ liệu không khớp kích thước DEM.');
        if (!Number.isFinite(min)) throw new Error('DEM không có độ cao hợp lệ.');
        return { ncols, nrows, cellsize, nodata, xllcorner, yllcorner, values, min, max, crs: 'EPSG:32648' };
    }

    function utm48ToWgs84(easting, northing) {
        const a = 6378137;
        const eccentricity = 0.00669437999014;
        const secondEccentricity = eccentricity / (1 - eccentricity);
        const k0 = 0.9996;
        const x = easting - 500000;
        const meridian = northing / k0;
        const mu = meridian / (a * (1 - eccentricity / 4 - 3 * eccentricity ** 2 / 64 - 5 * eccentricity ** 3 / 256));
        const e1 = (1 - Math.sqrt(1 - eccentricity)) / (1 + Math.sqrt(1 - eccentricity));
        const phi1 = mu
            + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * Math.sin(6 * mu)
            + (1097 * e1 ** 4 / 512) * Math.sin(8 * mu);
        const sin = Math.sin(phi1);
        const cos = Math.cos(phi1);
        const tan = Math.tan(phi1);
        const n1 = a / Math.sqrt(1 - eccentricity * sin ** 2);
        const t1 = tan ** 2;
        const c1 = secondEccentricity * cos ** 2;
        const r1 = a * (1 - eccentricity) / (1 - eccentricity * sin ** 2) ** 1.5;
        const d = x / (n1 * k0);
        const latitude = phi1 - (n1 * tan / r1) * (d ** 2 / 2
            - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * secondEccentricity) * d ** 4 / 24
            + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * secondEccentricity - 3 * c1 ** 2) * d ** 6 / 720);
        const longitude = 105 * Math.PI / 180 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
            + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * secondEccentricity + 24 * t1 ** 2) * d ** 5 / 120) / cos;
        return { lat: latitude * 180 / Math.PI, lon: longitude * 180 / Math.PI };
    }

    function mixColor(t) {
        const index = colorStops.findIndex(stop => stop[0] >= t);
        if (index <= 0) return colorStops[0][1];
        const [leftT, left] = colorStops[index - 1];
        const [rightT, right] = colorStops[index];
        const f = (t - leftT) / (rightT - leftT);
        return left.map((value, i) => Math.round(value + (right[i] - value) * f));
    }

    function rasterize(grid) {
        const canvas = document.createElement('canvas');
        canvas.width = grid.ncols;
        canvas.height = grid.nrows;
        const context = canvas.getContext('2d', { alpha: false });
        const image = context.createImageData(grid.ncols, grid.nrows);
        const range = Math.max(0.001, grid.max - grid.min);
        for (let row = 0; row < grid.nrows; row += 1) {
            for (let column = 0; column < grid.ncols; column += 1) {
                const index = row * grid.ncols + column;
                const value = grid.values[index];
                const pixel = index * 4;
                if (value === grid.nodata) {
                    image.data[pixel + 3] = 0;
                    continue;
                }
                const color = mixColor((value - grid.min) / range);
                const left = grid.values[row * grid.ncols + Math.max(0, column - 1)];
                const right = grid.values[row * grid.ncols + Math.min(grid.ncols - 1, column + 1)];
                const up = grid.values[Math.max(0, row - 1) * grid.ncols + column];
                const down = grid.values[Math.min(grid.nrows - 1, row + 1) * grid.ncols + column];
                const slope = (left === grid.nodata || right === grid.nodata || up === grid.nodata || down === grid.nodata)
                    ? 0 : ((left - right) + (up - down)) / Math.max(grid.cellsize * 10, 1);
                const shade = Math.max(0.68, Math.min(1.25, 0.92 + slope * 0.07));
                image.data[pixel] = Math.min(255, color[0] * shade);
                image.data[pixel + 1] = Math.min(255, color[1] * shade);
                image.data[pixel + 2] = Math.min(255, color[2] * shade);
                image.data[pixel + 3] = 255;
            }
        }
        context.putImageData(image, 0, 0);
        return canvas;
    }

    function mount(canvas, grid, { onSelect = null, selectable = false } = {}) {
        const context = canvas.getContext('2d');
        const raster = rasterize(grid);
        const listeners = new AbortController();
        const state = { zoom: 1, panX: 0, panY: 0, pointer: null, down: null, selected: null, destroyed: false };
        let width = 0;
        let height = 0;
        let dpr = 1;

        function geometry() {
            const fit = Math.min(width / grid.ncols, height / grid.nrows) * 0.92;
            const drawWidth = grid.ncols * fit * state.zoom;
            const drawHeight = grid.nrows * fit * state.zoom;
            return { drawWidth, drawHeight, x: (width - drawWidth) / 2 + state.panX, y: (height - drawHeight) / 2 + state.panY };
        }

        function render() {
            if (state.destroyed) return;
            const box = canvas.getBoundingClientRect();
            if (!box.width || !box.height) return;
            dpr = Math.min(window.devicePixelRatio || 1, 2);
            width = box.width;
            height = box.height;
            canvas.width = Math.round(width * dpr);
            canvas.height = Math.round(height * dpr);
            context.setTransform(dpr, 0, 0, dpr, 0, 0);
            context.clearRect(0, 0, width, height);
            const { x, y, drawWidth, drawHeight } = geometry();
            context.imageSmoothingEnabled = state.zoom < 8;
            context.drawImage(raster, x, y, drawWidth, drawHeight);
            if (state.zoom >= 8) {
                context.beginPath();
                context.strokeStyle = 'rgba(233, 247, 240, .14)';
                context.lineWidth = 1;
                const cell = drawWidth / grid.ncols;
                for (let column = 0; column <= grid.ncols; column += 1) {
                    const lineX = x + column * cell;
                    context.moveTo(lineX, y);
                    context.lineTo(lineX, y + drawHeight);
                }
                for (let row = 0; row <= grid.nrows; row += 1) {
                    const lineY = y + row * cell;
                    context.moveTo(x, lineY);
                    context.lineTo(x + drawWidth, lineY);
                }
                context.stroke();
            }
            if (state.selected) {
                const cellWidth = drawWidth / grid.ncols;
                const cellHeight = drawHeight / grid.nrows;
                context.fillStyle = 'rgba(246, 191, 83, .23)';
                context.strokeStyle = '#fff1b0';
                context.lineWidth = 2;
                context.fillRect(x + state.selected.column * cellWidth, y + state.selected.row * cellHeight, cellWidth, cellHeight);
                context.strokeRect(x + state.selected.column * cellWidth, y + state.selected.row * cellHeight, cellWidth, cellHeight);
            }
        }

        function selectAt(clientX, clientY) {
            if (!selectable || !onSelect) return;
            const box = canvas.getBoundingClientRect();
            const { x, y, drawWidth, drawHeight } = geometry();
            const localX = clientX - box.left;
            const localY = clientY - box.top;
            if (localX < x || localY < y || localX >= x + drawWidth || localY >= y + drawHeight) return;
            const column = Math.min(grid.ncols - 1, Math.floor((localX - x) / drawWidth * grid.ncols));
            const row = Math.min(grid.nrows - 1, Math.floor((localY - y) / drawHeight * grid.nrows));
            const elevation = grid.values[row * grid.ncols + column];
            if (elevation === grid.nodata) return;
            const easting = grid.xllcorner + (column + 0.5) * grid.cellsize;
            const northing = grid.yllcorner + (grid.nrows - row - 0.5) * grid.cellsize;
            const point = { row, column, easting, northing, elevation, ...utm48ToWgs84(easting, northing) };
            state.selected = point;
            render();
            onSelect(point, { commit: true, source: 'pointer' });
        }

        function pointAt(row, column) {
            const boundedRow = Math.max(0, Math.min(grid.nrows - 1, row));
            const boundedColumn = Math.max(0, Math.min(grid.ncols - 1, column));
            const elevation = grid.values[boundedRow * grid.ncols + boundedColumn];
            if (elevation === grid.nodata) return null;
            const easting = grid.xllcorner + (boundedColumn + 0.5) * grid.cellsize;
            const northing = grid.yllcorner + (grid.nrows - boundedRow - 0.5) * grid.cellsize;
            return { row: boundedRow, column: boundedColumn, easting, northing, elevation, ...utm48ToWgs84(easting, northing) };
        }

        canvas.addEventListener('pointerdown', event => {
            state.pointer = event.pointerId;
            state.down = { x: event.clientX, y: event.clientY, panX: state.panX, panY: state.panY, moved: false };
            canvas.setPointerCapture?.(event.pointerId);
        }, { signal: listeners.signal });
        canvas.addEventListener('pointermove', event => {
            if (state.pointer !== event.pointerId || !state.down) return;
            const dx = event.clientX - state.down.x;
            const dy = event.clientY - state.down.y;
            if (Math.abs(dx) + Math.abs(dy) > 5) state.down.moved = true;
            if (state.down.moved) {
                state.panX = state.down.panX + dx;
                state.panY = state.down.panY + dy;
                render();
            }
        }, { signal: listeners.signal });
        const endPointer = event => {
            if (state.pointer !== event.pointerId) return;
            if (!state.down?.moved) selectAt(event.clientX, event.clientY);
            state.pointer = null;
            state.down = null;
        };
        canvas.addEventListener('pointerup', endPointer, { signal: listeners.signal });
        canvas.addEventListener('pointercancel', endPointer, { signal: listeners.signal });
        canvas.addEventListener('wheel', event => {
            event.preventDefault();
            const before = geometry();
            const box = canvas.getBoundingClientRect();
            const localX = event.clientX - box.left;
            const localY = event.clientY - box.top;
            const factor = event.deltaY < 0 ? 1.25 : 0.8;
            const nextZoom = Math.max(1, Math.min(40, state.zoom * factor));
            const ratio = nextZoom / state.zoom;
            state.panX = localX - (localX - before.x) * ratio - (width - before.drawWidth * ratio) / 2;
            state.panY = localY - (localY - before.y) * ratio - (height - before.drawHeight * ratio) / 2;
            state.zoom = nextZoom;
            if (state.zoom === 1) { state.panX = 0; state.panY = 0; }
            render();
        }, { passive: false, signal: listeners.signal });
        canvas.addEventListener('keydown', event => {
            if (!selectable || !onSelect) return;
            const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
            if (moves[event.key]) {
                event.preventDefault();
                const current = state.selected || pointAt(Math.floor(grid.nrows / 2), Math.floor(grid.ncols / 2));
                if (!current) return;
                if (state.zoom < 8) state.zoom = 8;
                state.selected = pointAt(current.row + moves[event.key][0], current.column + moves[event.key][1]);
                if (state.selected) {
                    render();
                    onSelect(state.selected, { commit: false, source: 'keyboard' });
                }
            } else if (event.key === 'Enter' && state.selected) {
                event.preventDefault();
                onSelect(state.selected, { commit: true, source: 'keyboard' });
            }
        }, { signal: listeners.signal });

        const resizeObserver = new ResizeObserver(render);
        resizeObserver.observe(canvas);
        render();
        return {
            zoomIn() { state.zoom = Math.min(40, state.zoom * 1.5); render(); },
            zoomOut() { state.zoom = Math.max(1, state.zoom / 1.5); if (state.zoom === 1) { state.panX = 0; state.panY = 0; } render(); },
            fit() { state.zoom = 1; state.panX = 0; state.panY = 0; render(); },
            destroy() { state.destroyed = true; resizeObserver.disconnect(); listeners.abort(); },
        };
    }

    window.DemGrid = { parse, mount, utm48ToWgs84 };
})();
