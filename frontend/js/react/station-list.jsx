(() => {
const { memo, useEffect, useMemo, useRef, useState } = React;

const STATION_ROW_HEIGHT = 84;
const STATION_OVERSCAN = 6;

const StationListItem = memo(function StationListItem({ station }) {
    const riskUi = getRiskPresentation(station.risk_level, station.status);
    const badgeClass = getRiskBadgeClass(riskUi.className);

    const select = () => {
        selectStation(station.id);
        if (window.innerWidth < 768) {
            setStationListSidebarOpen(document.getElementById('station-list-sidebar'), false);
        }
    };

    return (
        <button
            type="button"
            className="station-item station-item-react"
            data-station-id={station.id}
            onClick={select}
            aria-label={`${station.name}: ${riskUi.display}`}
        >
            <span className="station-item-copy">
                <strong>{station.name}</strong>
                <small>{station.station_code}</small>
            </span>
            <span id={`list-badge-${station.id}`} className={`badge ${badgeClass}`}>
                {riskUi.display}
            </span>
        </button>
    );
}, (previous, next) => (
    previous.station.id === next.station.id
    && previous.station.name === next.station.name
    && previous.station.station_code === next.station.station_code
    && previous.station.status === next.station.status
    && previous.station.risk_level === next.station.risk_level
));

function StationListView({ stations }) {
    const hostRef = useRef(null);
    const [viewport, setViewport] = useState({ scrollTop: 0, height: 600 });

    useEffect(() => {
        const host = hostRef.current;
        const scroller = host?.parentElement;
        if (!scroller) return undefined;

        let frameId = null;
        let scrollingTimer = null;
        const measure = () => {
            frameId = null;
            setViewport({ scrollTop: scroller.scrollTop, height: scroller.clientHeight || 600 });
        };
        const scheduleMeasure = () => {
            scroller.classList.add('is-scrolling');
            if (frameId === null) frameId = requestAnimationFrame(measure);
            clearTimeout(scrollingTimer);
            scrollingTimer = setTimeout(() => scroller.classList.remove('is-scrolling'), 120);
        };

        measure();
        scroller.addEventListener('scroll', scheduleMeasure, { passive: true });
        const resizeObserver = typeof ResizeObserver === 'function'
            ? new ResizeObserver(scheduleMeasure)
            : null;
        resizeObserver?.observe(scroller);

        return () => {
            scroller.removeEventListener('scroll', scheduleMeasure);
            resizeObserver?.disconnect();
            if (frameId !== null) cancelAnimationFrame(frameId);
            clearTimeout(scrollingTimer);
            scroller.classList.remove('is-scrolling');
        };
    }, []);

    useEffect(() => {
        const scroller = hostRef.current?.parentElement;
        if (scroller && scroller.scrollTop > stations.length * STATION_ROW_HEIGHT) {
            scroller.scrollTop = 0;
        }
    }, [stations.length]);

    const range = useMemo(() => {
        const first = Math.max(0, Math.floor(viewport.scrollTop / STATION_ROW_HEIGHT) - STATION_OVERSCAN);
        const visibleCount = Math.ceil(viewport.height / STATION_ROW_HEIGHT) + STATION_OVERSCAN * 2;
        return {
            first,
            last: Math.min(stations.length, first + visibleCount),
        };
    }, [stations.length, viewport.height, viewport.scrollTop]);

    if (!stations.length) {
        return (
            <div className="text-center text-muted mt-4" role="status">
                <i className="bi bi-inbox fs-1" aria-hidden="true" />
                <p className="mt-2">Chưa có trạm nào</p>
            </div>
        );
    }

    const visibleStations = stations.slice(range.first, range.last);
    return (
        <div
            ref={hostRef}
            className="station-virtual-list"
            style={{ height: `${stations.length * STATION_ROW_HEIGHT}px` }}
        >
            <div
                className="station-virtual-window"
                style={{ transform: `translateY(${range.first * STATION_ROW_HEIGHT}px)` }}
            >
                {visibleStations.map(station => (
                    <StationListItem key={station.id} station={station} />
                ))}
            </div>
        </div>
    );
}

window.renderReactStationList = function renderReactStationList(stations) {
    const container = document.getElementById('station-list-container');
    if (!container) return false;
    if (!window.__stationListReactRoot) {
        window.__stationListReactRoot = ReactDOM.createRoot(container);
    }
    window.__stationListReactRoot.render(<StationListView stations={stations || []} />);
    return true;
};

window.unmountReactStationList = function unmountReactStationList() {
    window.__stationListReactRoot?.unmount();
    window.__stationListReactRoot = null;
};

if (Array.isArray(window.allStations)) {
    window.renderReactStationList(window.allStations);
}
})();
