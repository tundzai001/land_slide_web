# Aitogy Landslide Monitor — UI/UX & Backend Evolution V2

## 0. Trạng thái tài liệu

- Tài liệu này là kế hoạch triển khai tiếp theo sau plan/UI_UX_OVERHAUL.md.
- V1 được giữ nguyên làm implementation ledger; V2 là nguồn quyết định cho vòng nâng cấp mới.
- Mọi thay đổi phải đi qua source rồi build; không sửa trực tiếp frontend/dist.
- Worktree hiện có nhiều thay đổi chưa commit. Trước mỗi phase phải đọc lại diff và merge thủ công, không restore hoặc ghi đè thay đổi không thuộc phase.

### 0.1 Implementation log (2026-08-24)

Đã triển khai và kiểm chứng trong source (dist chỉ được tạo lại bằng build):

- [x] GNSS startup gate: không consume GGA trước khi origin/checkpoint persisted được load; trạng thái `INITIALIZING` không rơi xuống vận tốc `0`/SAFE.
- [x] GNSS quarantine durable: refresh timestamp của active alert trong thời gian warm-up; DB summary lỗi trả `UNKNOWN/degraded` và auto-resolve fail-closed.
- [x] GNSS alert restart retention: unresolved warning/critical không bị TTL lọc mất sau restart; API giữ lại `active_alerts` với `stale`, `fresh_alerts` và `stale_alerts`, còn siren chỉ bật lại khi có telemetry online xác nhận.
- [x] WebSocket ticket: thêm boot epoch, JTI one-time consume và scope hash/absolute authz grace metadata.
- [x] Private authz boundary: admin shell có `data-private-content`; hết grace sẽ inert/revoke blob và hiển thị dialog đăng nhập lại.
- [x] Landing stage morph: story stage đổi scale/position/radius theo progress, chỉ bật sticky/crossfade sau khi Three enhancement sẵn sàng; fallback mobile/reduced-motion vẫn là flow dọc.
- [x] Map data truthfulness: rain/water/IMU/GNSS adjustment không ép missing thành số 0; baseline thiếu tọa độ bị bỏ qua; RTK badge container-aware.
- [x] Visual regression contract: cập nhật snapshot responsive theo layout mới và giữ smoke coverage cho landing, Map, Management, auth.
- [x] Incident/Response foundation: additive Data models + Alembic migration cho case, append-only timeline, mutation idempotency và file-cleanup outbox placeholder.
- [x] Incident API: scoped list/detail/events, signed cursor, catch-up stream, acknowledge/priority/assign/transition/note/scope mutations và optimistic version guard.
- [x] Rescue/Alert adapters: tạo Incident cùng transaction với rescue/alert; legacy rescue PATCH và sensor auto-resolve ghi lại timeline; broadcast operations chỉ chứa envelope không PII.
- [x] Operations realtime/UI: `/ws/operations` ticket channel + scope gate, shared in-memory Incident store và inbox progressive enhancement cho Map/Management.
- [x] Map state/lifecycle slice: mode/layer/selected-station dùng state setter chung; operations socket reconnect/stop theo SPA/authz; Management WebSocket có single-flight connect/dispose guard.
- [x] Simulation audit persistence: thêm migration `simulation_runs` khớp ORM/router, giữ seed/engine/schema/input snapshot/result bundle và recovery interrupted runs.
- [x] Ingest failure retention: batch sensor/config bị lỗi DB được trả lại queue thay vì mất im lặng; bcrypt chuyển khỏi event loop.
- [x] Durable ingest spool: append-only JSONL có fsync, bounded size, torn-tail recovery,
  deterministic `SensorData.ingest_id` dedupe, retry sau restart và bounded final flush khi shutdown.
- [x] Health/runtime diagnostics: liveness/readiness probes và admin runtime snapshot hiển thị
  trạng thái MQTT, spool, task và WebSocket backlog mà không lộ secret.
- [x] Durable file cleanup: `FileCleanupJob` có lease/generation/CAS retry, path safety và worker
  nền; rescue delete không còn unlink đồng bộ sau commit.
- [x] WebSocket backpressure: outbox bounded theo client, reliable overflow đóng 1013,
  best-effort sensor/status coalesce/drop và diagnostics backlog.
- [x] Management authz lifecycle: role-first bootstrap, capability-gated tab/loader/socket,
  URL/history state, revoke fallback và simulation audit workspace.
- [x] Long-term analysis guard: giới hạn cửa sổ 1 giờ–365 ngày, cache 30 giây, semaphore tối đa
  2 request và chạy analyzer CPU-bound qua `asyncio.to_thread`.
- [x] Field-device capability boundary: các mutation/list Pi endpoint dùng đúng
  `VIEW_FIELD_DEVICES`, `ASSIGN_FIELD_DEVICES`, `MANAGE_FIELD_DEVICES` thay vì permission users/stations.
- [x] Private field-device RBAC: list/create/delete device có capability và project scope; admin-project/station reads dùng permission dependency rõ ràng.
- [x] Event source ordering: transaction-scoped PostgreSQL advisory lock serialize cùng `(source_kind, source_id)` trước khi append timeline.

Còn lại là các gate cần kiểm chứng ngoài môi trường dev (field-device token issue/audit/rotate trên
client thật, đầy đủ visual/cross-browser/performance smoke, production DB migration và tile
provider license). Rescue admin channel đã tách riêng khỏi operations envelope và có polling
fallback khi mất realtime; event-order advisory lock, durable ingest/spool và simulation audit
workspace đã có implementation. Không đánh dấu tài liệu hoàn tất cho tới khi các gate còn lại có
code, môi trường và test tương ứng.

## 1. Tóm tắt và quyết định đã khóa

### 1.1 Mục tiêu

Nâng Aitogy Landslide Monitor từ một giao diện đã được reskin thành một sản phẩm vận hành hoàn chỉnh:

- Landing có storytelling thực sự biến đổi theo không gian, không còn cảm giác một card lớn đứng im trong khi chỉ vật thể bên trong chuyển động.
- Map trở thành workspace vận hành có một nguồn trạng thái, bố cục ổn định theo breakpoint, dữ liệu thiếu được biểu diễn trung thực và mọi luồng realtime có trạng thái phục hồi rõ ràng.
- Management khởi động theo quyền trước khi gọi API, có điều hướng/history/focus nhất quán và dùng một inbox sự cố chung thay cho các mảnh Alert/Rescue rời rạc.
- Backend fail-safe trước lỗi DB/restart/mất mạng, không biến dữ liệu lỗi thành số đo mới, không làm mất batch khi flush lỗi và có lifecycle shutdown đo được.
- Incident & Response là tính năng ưu tiên số một: tiếp nhận, triage, acknowledge, phân công, ghi chú, timeline, theo dõi và đóng sự cố xuyên Map/Management.

### 1.2 Quyết định sản phẩm

- Aitogy là masterbrand; Landslide Monitor là tên sản phẩm.
- Teal Operations tiếp tục là phong cách chính. Cam Aitogy chỉ dùng cho nhận diện; amber/đỏ chỉ dùng cho cảnh báo và rủi ro.
- Storytelling chọn hướng Sân khấu biến hình:
  - Một scene Three.js và một canvas liên tục.
  - Khung hình đổi vị trí, tỷ lệ, silhouette và mức độ full-bleed theo từng chương.
  - Không GSAP, scroll-jacking, Lenis hoặc animation loop liên tục.
- Backend chọn Mở rộng tương thích:
  - Được thêm migration và API additive.
  - URL, body REST hiện có, protocol sensor WebSocket, role hiện có và export hiện có không bị phá.
- Incident & Response đứng trước phân tích nâng cao và device-maintenance về thứ tự rollout.
- Deployment tiếp tục dùng một Uvicorn worker trong V2. Chưa scale đa worker khi chưa có event bus dùng chung.

### 1.3 Thành công được đo bằng

- Không có fake measurement, fake zero, fake heatmap hoặc pseudo correlation.
- Graceful restart không làm mất quarantine, baseline, incident hay trạng thái xử lý; hard-kill dùng checkpoint cuối + boot anchor fail-safe và không được âm thầm báo SAFE.
- Một thao tác nhận sự cố hiển thị trong Map và Management dưới 1 giây khi WebSocket khỏe; polling fallback không quá 15 giây.
- Không có PII Rescue trên public WebSocket.
- 20 vòng chuyển Map ↔ Management và 20 vòng mở/đóng 3D không tăng listener, timer, socket, chart, renderer hoặc WebGL context.
- INP p75 không quá 200 ms; CLS không quá 0.1; Landing LCP p75 không quá 2.5 s.
- Landing Lighthouse mobile: Performance tối thiểu 90, Accessibility và SEO tối thiểu 95.
- Map và Management bundle không tăng quá 5%; Landing local JS/CSS mỗi loại không quá 30 KB; Three vẫn nằm ngoài critical path.

### 1.4 Ngoài phạm vi

- Không đổi Digital Twin physics, thuật toán bình sai GNSS, schema report hoặc định dạng export hiện có.
- Không tự đổi tile provider. License và attribution của provider là release gate riêng.
- Không thêm framework frontend, state library, animation library, chart library mới hoặc UI component framework mới.
- Không xây durable cross-process event bus trong V2.
- Không hứa RPO bằng 0 khi process bị kill cứng; durable ingest spool/outbox là phase độc lập nếu vận hành yêu cầu.
- Queue RAM/checkpoint coalescing chỉ cam kết drain ở graceful shutdown; hard-kill có thể mất telemetry chưa flush nhưng không được biến trạng thái chưa biết thành an toàn.

## 2. Baseline và các vấn đề đã xác nhận

### 2.1 Landing / storytelling

- Story hiện cao 410vh nhưng toàn bộ story-shell bị sticky.
- story-stage giữ cùng vị trí, kích thước và tỷ lệ; setProgress chỉ đổi camera, opacity, mưa, nước, vector và glow.
- Bốn article chồng tuyệt đối cùng một vị trí rồi crossfade. Vì vậy trải nghiệm giống video chạy trong một card dashboard cố định.
- Scene chưa thể hiện đủ bốn nội dung đã hứa: chưa có baseline/current rõ, shared timeline, cụm amber cần xác minh, network lines và acknowledgment hoàn chỉnh.
- No-JS desktop vẫn giấu ba article bằng CSS.
- Reduced-motion desktop vẫn giữ 410vh và sticky; hiện chỉ tắt transition.
- Test story chỉ kiểm tra data-step và header không xê dịch, chưa kiểm tra hình thái khung.
- Test mock hiện chưa phục vụ logo thật nên snapshot có thể xuất hiện biểu tượng ảnh lỗi.

### 2.2 Map

- mapUiState đã tồn tại nhưng mode, layers, panel và selected station vẫn bị phản chiếu bởi globals, class CSS và inline style; một số init còn reset layer.
- Desktop >=1440 chưa phải workspace ba cột thật; rail trạm vẫn có hành vi offcanvas.
- Mobile sheet còn dùng click vào header như một thao tác ẩn, không có drag threshold/keyboard fallback hoàn chỉnh.
- Dữ liệu thiếu vẫn có đường bị ép thành 0 ở realtime, historical IMU, analysis và Digital Twin input.
- Marker reconciliation chưa xóa station biến mất; tọa độ hợp lệ bằng 0 có thể bị loại bởi truthiness.
- Rescue realtime đang đi sai channel: public Map nghe ws/updates trong khi backend gửi Rescue tới ws/admin.
- Một số overlay thiếu Escape LIFO, focus trap, inert và focus restore.
- Chart vẫn dùng màu risk cho series thường; một số missing value nối thành đường hoặc hiện 0.
- RTK badge cần contract container-aware, không chỉ thu nhỏ font.
- Brand lockup Map đang đặt logo trong ô/plate trắng dù asset CORS gốc có alpha, làm header lệch với dark operations surface.

### 2.3 Management

- AdminManager có thể gọi Projects/Users trước khi fetch role; DatabaseManager khởi tạo và gọi admin filter cho role không có quyền.
- Desktop restriction và mobile nav chưa dùng chung một permission map.
- switchTab chưa quản lý Back/Forward đầy đủ.
- Mobile nav có template legacy rồi bị JavaScript overwrite, tạo hai nguồn và nguy cơ flash.
- Nhiều loader chưa có AbortController/sequence guard; response cũ có thể đè selection/filter mới.
- Một số DB/server field vẫn đi vào innerHTML hoặc attribute interpolation.
- Dispose chưa dọn đầy đủ timers, wizard listeners, export polling và manager phụ.

### 2.4 Backend / realtime

- GNSS processor có thể nhận MQTT trước khi async origin/checkpoint load xong.
- Checkpoint save lỗi chưa retry bền; shutdown chưa await toàn bộ processor checkpoint.
- Water/Rain/IMU có đường trả last value hoặc 0 với timestamp mới, biến stale/fault thành measurement mới.
- Alert summary lỗi DB có thể fallback LOW và dẫn tới auto-stop siren không an toàn.
- Flush hiện lấy batch khỏi RAM trước khi commit; sensor/config/alert batch lỗi có thể mất.
- Paho callback tạo coroutine không có bounded queue theo device.
- WebSocket serialize send nhưng chưa có bounded outbox/coalescing/reliable policy.
- Shutdown chưa đóng đầy đủ dynamic MQTT, NTRIP, processor, simulation, IPC và scheduler task.
- Một số field/Pi/siren endpoint thiếu authentication hoặc project scope.
- Health hiện chưa phản ánh readiness thực tế của DB, MQTT, queue, flush, checkpoint và scheduler.

## 3. Kiến trúc đích

### 3.1 Nguyên tắc frontend

- HTML semantic và nội dung usable là mặc định. JavaScript chỉ enhancement sau khi controller sẵn sàng.
- Một nguồn state cho mỗi surface:
  - Landing: story controller nội bộ.
  - Map: mapUiState duy nhất.
  - Management: session permission map + switchTab duy nhất.
  - Incident: incident store dùng version từ server; UI không tự suy diễn trạng thái.
- Async request luôn có AbortController, sequence/context guard và retry; last-good chỉ giữ cho lỗi network/retryable, còn 401/403/scope revocation phải purge dữ liệu private trước render.
- Mọi feature có init/dispose idempotent; listener gắn bằng AbortSignal khi platform hỗ trợ.
- Motion thường 150–300 ms, chỉ transform/opacity và state layer. Story là ngoại lệ phức tạp duy nhất.
- Status không bao giờ chỉ dựa vào màu; luôn có text và icon/shape.

### 3.2 Nguyên tắc backend

- Processor phải initialize thành công trước khi consume.
- Phân biệt measurement, sensor_status và operational_event; chỉ measurement hợp lệ mới cập nhật latest/history/analyzer.
- Unknown hoặc DB failure là UNKNOWN/degraded, không phải LOW/safe.
- Producer dừng trước, queue drain sau, checkpoint/flush cuối cùng rồi mới dispose kết nối.
- Mọi queue và outbox phải bounded, có policy drop/coalesce/fail-closed rõ ràng và counter quan sát được.
- Role vẫn là guest/viewer/operator/admin; capability nội bộ tách nhỏ nhưng không đổi token/role model.
- API mới trả error an toàn với code, retryable và request_id; raw exception chỉ vào log đã redact.

## 4. Workstream A — Foundation, contract và baseline

### A1. Tài liệu và đo baseline

- [ ] Coi tài liệu này là source of truth V2; cập nhật checklist sau từng commit.
- [ ] Ghi lại bundle source/dist, số route, số WebSocket client, listener/timer/socket baseline và query count của endpoint chính.
- [ ] Chụp visual baseline cho story step 0–3, Map station/incident/detail, Management incident/database ở light/dark.
- [ ] Lưu trace 60 giây cho scroll story, Map pan, station switch, incident acknowledge và long-term analysis.
- [ ] Ghi schema inventory của ba DB; chỉ Data DB hiện có Alembic revision stream, Auth/Config ghi checksum/model inventory.

### A2. Design system V2

- [ ] Bổ sung token semantic:
  - surface-canvas, surface-panel, surface-elevated, surface-scrim.
  - data-primary, data-secondary, status-safe, status-stale, status-offline.
  - incident-untriaged, incident-warning, incident-critical.
  - motion-fast 150 ms, motion-standard 220 ms, motion-panel 280 ms.
  - z-base 0, z-map 10, z-rail 20, z-popover 30, z-sheet 40, z-modal 50, z-toast 60.
- [ ] Giữ spacing 4/8 px, radius 8/12/16/22 px, focus ring 3 px, target tối thiểu 44×44 px.
- [ ] Metadata không dưới 12 px; mobile body/form input tối thiểu 16 px.
- [ ] Loại transition all khi chạm subsystem; chỉ transition thuộc tính cần thiết.
- [ ] Logo Aitogy luôn dùng đúng PNG alpha gốc từ CORS, wrapper transparent ở light/dark; không background trắng, filter, recolor, crop, glow hoặc CSS làm mất alpha. Tên Landslide Monitor nằm cạnh logo bằng text riêng.
- [ ] Build kiểm SHA-256 source → dist → HTTP và URL có build version.

### A3. Permission map dùng chung

- [ ] Mở rộng capability nội bộ:
  - VIEW_STATIONS.
  - EDIT_STATIONS.
  - CONTROL_SIREN.
  - RUN_ADJUSTMENT.
  - VIEW_INCIDENTS.
  - MANAGE_INCIDENTS.
  - VIEW_FIELD_DEVICES.
  - ASSIGN_FIELD_DEVICES.
  - MANAGE_FIELD_DEVICES.
  - MANAGE_DATABASE.
  - MANAGE_RESCUE.
  - MANAGE_SIMULATIONS.
  - MANAGE_USERS.
- [ ] Mapping:
  - guest: public station/map read và tạo rescue; không xem Rescue/Incident list hoặc marker.
  - viewer: VIEW_STATIONS và VIEW_FIELD_DEVICES; VIEW_INCIDENTS chỉ trong assigned_projects.
  - operator: viewer + EDIT_STATIONS, CONTROL_SIREN, RUN_ADJUSTMENT, MANAGE_INCIDENTS, ASSIGN_FIELD_DEVICES trong assigned_projects.
  - admin: toàn bộ capability và toàn bộ project; MANAGE_SIMULATIONS giữ admin-only để bảo toàn contract frontend/backend hiện tại cho toàn bộ /api/simulations/*.
- [ ] Backend luôn là authority; frontend dùng cùng map chỉ để ẩn/disable sớm và tránh gọi endpoint bị cấm.
- [ ] Viewer không có assigned_projects tiếp tục đọc public station data toàn cục để giữ compatibility, nhưng Incident và private device data default-deny.
- [ ] /api/auth/me trả assigned_projects đã normalize, authz_scope_hash ổn định từ user id + is_active + role + sorted project ids, private_authz_grace_seconds đã clamp 60–900 và server_time. Response đặt Cache-Control private,no-store; client fetch cache=no-store. Ticket/WS hello mang cùng hash; hash chỉ là change detector, backend vẫn check scope ở từng request.
- [ ] PII Rescue, note/actor private, precise coordinate, image blob/object URL và private Pi secret/state là memory-only; không ghi localStorage, IndexedDB, Cache API hoặc service-worker cache. Response ảnh giữ Cache-Control private,no-store và object URL phải revoke khi đóng detail/purge/dispose.
- [ ] Chỉ non-PII list summary/filter có thể persist, namespace theo user id + authz_scope_hash và TTL; cold start/reload không hydrate/render bất kỳ scoped cache nào trước một lần /api/auth/me thành công. Hash đổi phải purge namespace/project bị mất trước render hoặc catch-up.
- [ ] Session đang chạy có authz_verified_at_wall_ms + authz_verified_at_monotonic_ms và grace lấy từ /api/auth/me, không hard-code client. Ngay mỗi lần auth thành công, tính absolute_authz_deadline từ thời điểm verified + grace và lập local purge timer độc lập request; request /api/auth/me đang pending/treo không gia hạn deadline. Watchdog chạy khi còn bất kỳ private material trong memory, kể cả panel đóng; revalidate bằng AbortController/deadline khi online/focus/visibility/reconnect và tối thiểu mỗi 60 giây. Tới absolute deadline thì đồng bộ inert/khóa private UI, purge memory-only PII/precise markers/images và chặn mutation dù fetch chưa trả; chỉ auth thành công mới lập deadline mới.
- [ ] Page lifecycle chống flash private data: pagehide/visibility hidden/freeze đồng bộ đặt private root inert + authz-resume-guard hidden trước BFCache/sleep. pageshow/visibility/focus và trước mọi private action phải đồng bộ tính age=max(wall-clock age, monotonic age nếu cùng document), purge/lock nếu quá absolute_authz_deadline rồi mới bỏ guard hoặc gọi async verify; timer bị throttle/suspend không gia hạn quyền và không tạo một frame PII cũ khi foreground.
- [ ] Không thể bảo đảm revoke tức thời khi thiết bị hoàn toàn mất mạng; security guarantee là private data không sống qua reload, và session online/offline chỉ giữ tối đa grace hữu hạn nêu trên trước khi purge.
- [ ] applyAuthzSession(me) là transition nguyên tử theo authz_scope_hash: freeze/inert private surface, abort loader đang chạy, recompute capability + nav, dispose manager/socket/timer mất quyền, đóng panel/tab/selection bị cấm, purge lost-scope data, chọn destination an toàn còn quyền rồi render/unfreeze. Không chỉ thay badge/ẩn nút.
- [ ] Pi action:
  - Viewer chỉ list/read thiết bị đã gắn với station thuộc assigned_projects; không nhìn thấy pool chưa gán.
  - Vì PiDevice hiện chỉ có station_id và không có project reservation, initial assignment từ pool và unassign về pool là admin-only trong V2.
  - Operator chỉ được chuyển thiết bị đang gắn trong project của mình sang station khác của chính project đó; không claim thiết bị station_id=null, không chuyển cross-project và không tạo trạng thái unscoped.
  - Activate, lock, reset, rotate token, initial assignment, unassign về pool và delete chỉ admin.
  - Pi Point→Center tuân cùng scope từ station hiện tại; backend kiểm source station và destination station trong một transaction, không tin project_id từ client.

### A4. Carry-forward SEO/build contract từ V1

- [ ] Không mở lại các quyết định đã khóa trong plan/UI_UX_OVERHAUL.md:
  - index.html semantic/indexable cho `/`, map.html metadata/fallback riêng cho `/map`, app.html `noindex,noarchive` cho login/management/admin.
  - PUBLIC_SITE_URL mặc định https://monitoring.aitogy.com là nguồn duy nhất cho canonical, OG URL và sitemap.
  - Sitemap production chỉ có `/` và `/map`; private route có meta + X-Robots-Tag noindex, non-production noindex toàn site.
  - Canonical/OG/Twitter/JSON-LD có ngay trong HTML nguồn; không phụ thuộc JavaScript để crawler thấy.
  - Build manifest/copy pipeline quản lý logo/social image theo build version; không sửa dist thủ công.
- [ ] V2 thêm regression smoke cho source HTML, status/header, robots/sitemap, JSON-LD parse và asset HTTP 200 sau mọi thay đổi Landing/route shell.
- [ ] Login chỉ nhận đúng brand lockup transparent, theme/focus/error accessibility và noindex; không mở rộng thành redesign nghiệp vụ riêng.

## 5. Workstream B — Backend correctness, security và lifecycle P0

### B1. Processor lifecycle

- [ ] Thêm contract nội bộ initialize() và close() cho processor stateful.
- [ ] Topic reconciliation phải await initialize trước khi cho worker consume.
- [ ] GNSS không được thu origin mới khi DB origin/checkpoint chưa load:
  - Trả sensor_status STATE_UNAVAILABLE.
  - Retry load theo exponential backoff có jitter.
  - Readiness degraded nếu quá ngưỡng.
- [ ] Origin chỉ chuyển locked sau khi transaction lưu origin thành công.
- [ ] Checkpoint save coalesce snapshot mới nhất, retry 1/2/4/8/15/30 giây và không giữ song song nhiều task cho cùng device; GNSS_RUNTIME_STATE_SAVE_INTERVAL_S mặc định 15 giây.
- [ ] close() force checkpoint và await save có deadline; timeout được báo readiness/log, không bị nuốt.
- [ ] GNSS reference-guard durability — xử lý trực tiếp lỗi “restart là mất cảnh báo”:
  - Giữ key hiện có gnss_runtime_state:{device_id}, version schema và origin identity; checkpoint phải chứa generation monotonic, saved_at, last trusted ENU/timestamp, displacement/peak, tracking offset, reference event, quarantine started_at/candidates, consecutive rejects và guard state.
  - Mọi transition vào quarantine, reference refused, guard escalation hoặc verified reacquire phải force-save ngoài chu kỳ 15 giây; failure giữ dirty state và readiness degraded tới khi commit.
  - initialize() phải load origin rồi load/validate runtime checkpoint trước khi consume. Nó so saved_at/generation với last trusted timestamp, RPO 15 giây và newest unresolved GNSS guard Alert trong Data DB. Checkpoint đúng schema/origin nhưng cũ hơn guard Alert hoặc vượt RPO trả restore_result=STALE, STATE_UNAVAILABLE/UNKNOWN; không lấy sample đầu sau boot làm baseline/safe.
  - Quarantine fresh hợp lệ được restore thành REFERENCE_QUARANTINED/REACQUIRE_REQUIRED, không reset AWAITING_CANDIDATES. Data DB unavailable lúc reconciliation cũng fail closed và retry startup reconciliation tới khi đọc được Alert state.
  - Khi restore quarantine/refusal, luôn reconcile legacy Alert category=gnss_reference_guard, minimum source severity HIGH/signal ACTIVE khi fresh và normalized episode key cố định; nếu processor xác nhận mức cao hơn thì giữ mức cao hơn. Chỉ tìm/tạo Incident khi Incident schema đã expand và write_mode=shadow|atomic; nếu chưa, Phase 2 backfill bù từ legacy Alert. Log WARNING chỉ là diagnostic, durable Alert/Incident mới là trạng thái UI/operations.
  - Process restart không resolve/hạ severity/tắt siren. Nếu chưa có sample mới sau restart, evidence chuyển UNKNOWN theo freshness TTL nhưng workflow case vẫn open; sample ổn định phù hợp origin cũ mới được clear guard theo policy xác nhận.
  - Reacquire sang cluster dịch chuyển chỉ được phép bởi reference-change event đã xác minh hoặc action có capability + confirmation/audit; restart, checkpoint miss hay thời gian trôi không phải bằng chứng đổi mốc.
  - Checkpoint stale/invalid/mismatched/missing khi đã có locked origin phải fail closed STATE_UNAVAILABLE/UNKNOWN, giữ newest unresolved guard Alert/Incident open và yêu cầu recovery; không âm thầm zero hoặc auto-origin.
  - Graceful restart RPO=0 trong deadline checkpoint; hard kill RPO tối đa bằng GNSS_RUNTIME_STATE_SAVE_INTERVAL_S đã cấu hình. Expose checkpoint_saved_at, checkpoint_age, guard_state và restore_result trong diagnostics/readiness đã redact.

### B2. Measurement integrity

- [ ] Tạo result contract nội bộ:
  - kind=measurement: có timestamp nguồn, quality và numeric finite/null.
  - kind=sensor_status: stale/offline/invalid/unit_unknown/state_unavailable.
  - kind=operational_event: alert transition, checkpoint, adjustment, command.
- [ ] Pipeline chỉ ghi SensorData/LatestSensorCache và analyzer khi kind=measurement.
- [ ] Water/Rain:
  - Missing/invalid không copy last value thành measurement timestamp mới.
  - Last-good chỉ được trả ở read model với timestamp gốc và stale=true.
  - State tích lũy được restore từ LatestSensorCache.
  - Heuristic GWL được giữ để tương thích nhưng trả unit_inferred=true.
- [ ] IMU:
  - Không tạo ax/ay/az/gx/gy/gz bằng 0 khi thiếu.
  - Baseline phải load/persist trước khi xuất delta.
  - Raw 0 hợp lệ vẫn được giữ là 0.
- [ ] GNSS:
  - Giữ checkpoint/quarantine đã triển khai.
  - Không dựng adv fields bằng 0.
  - gnss_adjusted online dựa vào timestamp và threshold thật.
- [ ] Long-term:
  - Không tạo pseudo GNSS từ daily summary.
  - Thiếu dữ liệu trả status=insufficient_data và lý do.
  - Daily summary chỉ dùng cho thống kê có đủ trường nguồn.

### B3. Alert fail-safe

- [ ] DB lỗi khi đọc active alert trả UNKNOWN + last-known risk nếu còn hợp lệ; tuyệt đối không trả LOW do exception.
- [ ] Không auto-stop siren trên UNKNOWN.
- [ ] Alert/audio/command chỉ phát ở episode start hoặc escalation, không lặp theo từng sample nguy hiểm.
- [ ] Safe transition resolve đúng một lần sau điều kiện xác nhận; không resolve chỉ vì một sample thiếu.
- [ ] Thêm sweeper TTL cho alert episode và event signal_returned; không UPDATE/SELECT mỗi sample.

### B4. Durable-in-process persistence

- [ ] Không clear buffer trước khi commit thành công.
- [ ] Khi flush:
  - Snapshot batch dưới lock.
  - Commit sensor/latest/config/alert theo transaction phù hợp.
  - Chỉ remove đúng item đã commit.
  - Lỗi thì requeue cùng ingest_id; không sinh identity mới cho cùng item trong một process lifetime.
- [ ] Delivery contract:
  - Thêm SensorData.ingest_id String(64) nullable và partial unique index cho row mới; dữ liệu lịch sử giữ null.
  - Nếu payload có device sequence hoặc source timestamp đáng tin cậy, ingest_id là SHA-256 của broker identity + topic + device id + sequence/timestamp + normalized payload; MQTT redelivery và retry sau commit-unknown trở thành idempotent.
  - Bulk insert dùng PostgreSQL INSERT ... ON CONFLICT (ingest_id) WHERE ingest_id IS NOT NULL DO NOTHING; row ingest_id=null vẫn insert bình thường. Sau commit, cả row inserted và conflict vì đã tồn tại đều được coi durable để remove đúng item khỏi queue; conflict constraint khác rollback/retry cả batch.
  - Metric tách inserted, deduped, null_identity và commit_unknown_retries; test batch trộn row mới, row ingest_id đã có và row null không được kẹt retry vô hạn.
  - Nếu thiết bị không có sequence/timestamp ổn định, raw SensorData được tuyên bố at-least-once và có metric duplicate_candidate; latest/config upsert vẫn idempotent, còn Alert/Incident dựa normalized episode key + advisory lock nên một raw duplicate không tạo episode/action lặp.
  - Không âm thầm tuyên bố exactly-once hoặc dedupe heuristic cho payload không có natural identity: raw history/export giữ mọi row và format hiện tại; latest chọn row mới nhất, còn phân tích phụ thuộc sample count phải gắn identity_ambiguous hoặc trả insufficient_data thay vì tự xóa/gộp điểm bằng time window võ đoán.
- [ ] Retry bounded exponential; queue depth và oldest age có metric.
- [ ] Critical alert không bị drop; khi buffer đạt hard limit, reject telemetry thường trước và readiness degraded.
- [ ] Shutdown sequence:
  1. Mark draining và từ chối job mới.
  2. Stop scheduler/rollup/failover tạo việc mới.
  3. Stop MQTT receive.
  4. Drain per-device workers.
  5. Force processor checkpoint.
  6. Final DB flush.
  7. Stop MQTT/NTRIP/forward clients.
  8. Close WebSocket với lý do service restart.
  9. Cancel daemon còn lại.
  10. Dispose ba DB pool.
- [ ] Deadline shutdown mặc định 15 giây; log task chưa hoàn tất bằng event code.

### B5. Bounded MQTT pipeline

- [ ] Paho callback chỉ call_soon_threadsafe để enqueue, không tạo coroutine vô hạn.
- [ ] Một FIFO worker trên mỗi device giữ thứ tự GNSS; các device chạy song song.
- [ ] Queue mặc định 256 item/device:
  - Telemetry thường đầy queue: coalesce/replace oldest cùng sensor key, tăng counter.
  - Alert/AGRICA/adjustment terminal: không drop âm thầm; overflow fail-closed phiên liên quan và broadcast lý do.
- [ ] Topic reload tạo/hủy worker và processor đầy đủ; cache không giữ device/topic chết.
- [ ] Dùng reconnect delay 1–30 giây có jitter; lưu connected, last_message, last_error cho từng broker.
- [ ] Mọi siren/device command đi qua publish_command() dùng persistent client:
  - Thêm command_id UUID vào payload; field unit cũ được phép bỏ qua.
  - Kiểm Paho rc và wait_for_publish trong deadline.
  - Endpoint chỉ trả success khi broker đã nhận publish; lỗi trả 503, retryable=true và request_id.
  - Retry command phải giữ cùng command_id để thiết bị mới có thể dedupe.

### B6. Auth và device trust

- [ ] Gate siren endpoints bằng CONTROL_SIREN và station project scope.
- [ ] Gate device, adjustment, simulation, database và rescue mutation bằng capability tương ứng; mọi create/list/get/stop/rerun/export của /api/simulations/* yêu cầu MANAGE_SIMULATIONS admin-only, không đổi API hoặc physics.
- [ ] Operator project A không được đọc hoặc mutate private resource project B.
- [ ] Invalidate auth cache ngay khi đổi role/project/is_active; đóng operations/admin WebSocket khi quyền bị thu hồi.
- [ ] Bcrypt chạy bằng asyncio.to_thread.
- [ ] Login rate-limit theo IP + username, dùng dummy hash cho username không tồn tại và trả Retry-After.
- [ ] Rescue, login và field-device endpoint có rate limit riêng; request body/image có hard limit và lỗi 413 rõ ràng.
- [ ] Bỏ GeoIP thread khỏi request hot path:
  - Threat-map enrichment tắt mặc định.
  - Nếu bật, dùng bounded executor/queue và HTTPS provider được phê duyệt.
  - Không coi middleware limit 10.000 req/s hiện tại là lớp bảo vệ production.
- [ ] Field device:
  - Khi activate, sinh random token 256-bit.
  - Chỉ lưu SHA-256 token trong PiDevice.extra_config.
  - Trả token đúng một lần cho Pi.
  - Register/heartbeat/confirm/config/status bắt buộc X-Device-Token khi enforce.
  - Verify bằng hash + hmac.compare_digest; bearer token yêu cầu TLS.
  - Hỗ trợ revoke/rotate; previous token có grace tối đa 24 giờ rồi bị xóa.
- [ ] Thêm FIELD_DEVICE_AUTH_MODE=audit|enforce:
  - Staging dùng enforce.
  - Production cũ bắt đầu audit, chuyển enforce sau khi telemetry token coverage đạt 100% trong 7 ngày.
- [ ] Bỏ bypass provisioned=true sau compatibility window.
- [ ] Không log token, license, password, phone, Rescue message hoặc WebSocket ticket.
- [ ] Production fail-fast nếu secret mặc định, DB/MQTT bắt buộc trống hoặc production CORS sai.

## 6. Workstream C — Incident & Response

### C1. Data model additive trong Data DB

Thêm migration Alembic cho ba bảng Incident, file cleanup outbox, migration marker cùng các cột idempotency/ingest/upload additive nêu trong plan; không xóa hoặc đổi nghĩa cột Alert, RescueRequest hay SensorData hiện có.

#### incident_cases

| Cột | Kiểu | Quy tắc |
|---|---|---|
| id | BigInteger PK | autoincrement |
| reference | String(40) | unique, dạng INC-YYYYMMDD-A{id} hoặc INC-YYYYMMDD-R{id} |
| source_kind | String(24) | SENSOR_ALERT hoặc RESCUE_REQUEST |
| source_id | BigInteger | id nguồn, unique cùng source_kind |
| project_id | Integer nullable | soft reference Config DB |
| station_id | Integer nullable | soft reference Config DB |
| scope_state | String(20) | SCOPED, UNSCOPED hoặc LOOKUP_PENDING |
| project_name_snapshot | String(255) nullable | snapshot non-PII để search/audit không join chéo DB |
| project_code_snapshot | String(100) nullable | code canonical tại lúc scope |
| station_name_snapshot | String(255) nullable | snapshot non-PII để search/audit không join chéo DB |
| station_code_snapshot | String(100) nullable | code canonical tại lúc scope |
| title | String(255) | text kỹ thuật/non-PII đã normalize |
| summary | Text | non-PII, không HTML |
| source_severity | String(16) | UNKNOWN, INFO, LOW, MEDIUM, WARNING, HIGH, CRITICAL, EXTREME; system-owned và tương thích đầy đủ legacy |
| signal_state | String(16) | ACTIVE, RETURNED, UNKNOWN, NOT_APPLICABLE; system-owned |
| priority | String(16) | UNTRIAGED, LOW, NORMAL, HIGH, URGENT; workflow-owned |
| status | String(24) | new, acknowledged, in_progress, monitoring, resolved, dismissed |
| assigned_to_user_id | Integer nullable | soft reference Auth DB |
| assigned_to_username | String(150) nullable | snapshot audit |
| opened_at | BigInteger | epoch seconds UTC |
| last_signal_at | BigInteger | epoch seconds UTC; Rescue dùng created_at |
| acknowledged_at | BigInteger nullable | epoch seconds UTC |
| resolved_at | BigInteger nullable | epoch seconds UTC |
| updated_at | BigInteger | epoch seconds UTC |
| version | Integer | workflow version, bắt đầu 1; tăng khi bất kỳ actor nào đổi field workflow-owned |
| revision | BigInteger | case revision, bắt đầu 1; tăng một lần cho mọi transaction làm đổi case |
| last_event_sequence | Integer | bắt đầu 1 sau opened event |

Reference được tạo deterministic từ UTC date của opened_at, source prefix A/R và source_id; unique source_kind + source_id loại race/collision.

CHECK/default:

- Enum chỉ nhận đúng giá trị liệt kê.
- version >=1, revision >=1, last_event_sequence >=1.
- opened_at, last_signal_at và updated_at >0.
- Rescue mặc định source_severity=UNKNOWN, signal_state=NOT_APPLICABLE, scope_state=UNSCOPED, priority=UNTRIAGED.
- Sensor mặc định signal_state=ACTIVE; scope lookup thành công dùng SCOPED, lỗi dependency dùng LOOKUP_PENDING.
- Priority sensor ban đầu map UNKNOWN→UNTRIAGED; INFO/LOW→NORMAL; MEDIUM/WARNING→HIGH; HIGH/CRITICAL/EXTREME→URGENT rồi tách độc lập khỏi source_severity.
- Dùng một SOURCE_SEVERITY_ORDER duy nhất `UNKNOWN < INFO < LOW < MEDIUM < WARNING < HIGH < CRITICAL < EXTREME` cho writer, backfill, escalation, filter và test; không truyền raw enum chưa normalize vào CHECK.

Indexes:

- Unique source_kind + source_id.
- status + priority + updated_at + id.
- source_severity + signal_state + updated_at + id.
- project_id + status + updated_at + id.
- station_id + status + updated_at + id.
- assigned_to_user_id + status + updated_at + id.
- Partial index updated_at + id WHERE scope_state='LOOKUP_PENDING' để reconciler bounded scan, không full table.

#### incident_events

| Cột | Kiểu | Quy tắc |
|---|---|---|
| id | BigInteger PK | event cursor toàn cục; chỉ allocate sau khi giữ event-order lock |
| incident_id | BigInteger FK | cascade delete chỉ khi purge có chủ đích |
| sequence | Integer | unique trong case |
| event_type | String(32) | opened, signal_updated, source_severity_changed, signal_returned, signal_unknown, source_image_state_changed, acknowledged, assigned, priority_changed, scope_changed, status_changed, note_added, source_deleted |
| actor_kind | String(16) | system, user hoặc backfill |
| actor_user_id | Integer nullable | soft reference Auth DB |
| actor_username | String(150) nullable | snapshot audit |
| project_id_at_event | Integer nullable | scope mới/current tại lúc event, không phụ thuộc current case khi catch-up |
| previous_project_id | Integer nullable | chỉ scope_changed; audience cũ nhận tombstone non-PII |
| created_at | BigInteger | epoch seconds UTC |
| note | Text nullable | plain text, tối đa 4000 ký tự |
| payload | JSON | mặc định object rỗng, metadata đã redact |
| mutation_request_id | BigInteger nullable | FK tới incident_mutation_requests; nhiều event được phép cùng mutation |

Indexes:

- Unique incident_id + sequence.
- incident_id + created_at + id.
- created_at + id.
- project_id_at_event + id và previous_project_id + id để catch-up/tombstone không join theo scope hiện tại.
- Alembic tạo/ALTER sequence cấp incident_events.id với CACHE 1. Readiness query pg_sequences và fail 503 nếu cache_size khác 1; không cho pooled connection giữ block ID riêng làm vỡ commit-order cursor.

#### incident_mutation_requests

| Cột | Kiểu | Quy tắc |
|---|---|---|
| id | BigInteger PK | correlation durable của một mutation |
| incident_id | BigInteger FK | case được mutate |
| actor_user_id | Integer | actor đã authenticate |
| idempotency_key | String(64) | giá trị Idempotency-Key, không log |
| action | String(48) | endpoint/action canonical |
| request_fingerprint | String(64) | SHA-256 của method + canonical route/action + canonical JSON; không lưu raw body/PII |
| sequence_from/sequence_to | Integer nullable | dải event do mutation tạo; null khi changed=false |
| result_revision/result_version | BigInteger/Integer | kết quả sau commit |
| changed | Boolean | response replay metadata |
| created_at | BigInteger | epoch seconds UTC |

- Unique incident_id + actor_user_id + idempotency_key.
- Sau auth/scope check, service chạy INSERT ... ON CONFLICT (incident_id, actor_user_id, idempotency_key) DO NOTHING RETURNING id trong transaction. Nếu không nhận id, load/lock ledger hiện hữu sau khi transaction thắng commit, so action/fingerprint rồi replay hoặc trả 409; không để plain IntegrityError làm transaction thứ hai aborted.
- Request thắng hoàn tất ledger trong cùng Data transaction với case/events; concurrent request cùng key bị unique/row lock chặn đến commit hoặc rollback và chỉ một request được mutate case.
- Retry cùng actor + incident + key + action/fingerprint trả current authorized case, event range gốc và idempotent_replay=true, không chạy mutation lại.
- Cùng key nhưng khác endpoint/action hoặc canonical body trả 409 code=IDEMPOTENCY_KEY_REUSED; không trả response của action cũ.
- Tất cả event của một mutation, kể cả assigned + scope_changed, trỏ cùng mutation_request_id nên không có unique conflict.

#### file_cleanup_jobs — durable upload cleanup outbox

| Cột | Kiểu | Quy tắc |
|---|---|---|
| id | BigInteger PK | cleanup job durable |
| upload_id | String(36) | correlation internal, không public |
| image_storage_key | String(255) nullable | opaque relative key đã validate, không raw user path |
| job_generation | Integer | chống promoter/delete race |
| status | String(16) | PENDING, RUNNING, DONE, SKIPPED, FAILED |
| attempts/run_after | Integer/BigInteger | bounded retry schedule |
| lease_owner/lease_until | String(64)/BigInteger nullable | crash-reclaim lease, không chứa hostname secret |
| lease_generation | Integer | monotonic fencing token, bắt đầu 0 |
| created_at/updated_at | BigInteger | epoch seconds UTC |
| last_error_code | String(64) nullable | code redact, không exception/path |

- Unique upload_id + job_generation; một job dọn cả staging/final nên nullable storage key không nằm trong conflict key. Enqueue dùng ON CONFLICT (upload_id,job_generation) DO UPDATE metadata an toàn; worker claim bằng FOR UPDATE SKIP LOCKED, retry bounded và idempotent.
- Claim/reclaim transaction set RUNNING, random lease_owner, lease_until=now+60s và increment lease_generation rồi commit trước filesystem I/O. Startup/periodic sweeper reclaim lease hết hạn bằng owner/generation mới; delete file idempotent, transaction sau mark terminal.
- Mọi renew/defer/DONE/SKIPPED/FAILED UPDATE bắt buộc WHERE id + status=RUNNING + lease_owner + lease_generation và assert rowcount=1. Worker stale sau lease expiry bỏ kết quả nếu CAS=0, không ghi đè owner mới; crash sau delete/trước DONE được reclaim và coi file-absent là success.
- Tối đa 10 attempt trước FAILED + page; admin retry tạo lease mới. Metric cleanup oldest age, expired lease, retry/FAILED; không để RUNNING vĩnh viễn.
- Job chỉ xóa file trong validated RESCUE_UPLOAD_ROOT sau khi query xác nhận không còn RescueRequest nào reference upload_id/storage key; legacy shared file chỉ xóa khi reference count=0.
- Với storage key prefix legacy/, worker bắt buộc đọc marker rescue_image_metadata_v1 ở REFERENCES_COMPLETE hoặc CLEANUP_COMPLETE và query partial index xác nhận không còn row image_writer_schema_version<1/image_metadata_migrated_at NULL. Trước gate hoặc khi thấy inconsistency, atomically đưa marker về RUNNING, alert/reconcile và defer job; tuyệt đối không xóa physical legacy file.
- Adoption migration và legacy cleanup cùng lấy advisory lock theo canonical physical storage key trước commit READY/refcount/delete. Sau marker REFERENCES_COMPLETE, additive storage key là source reference chính xác; trước marker không cleanup dù refcount additive tạm bằng 0.

#### data_migration_markers

- Bảng marker nhỏ trong Data DB: key String(64) PK, status RUNNING|REFERENCES_COMPLETE|CLEANUP_COMPLETE|FAILED, high_watermark BigInteger, required_writer_version Integer, manifest_sha256 String(64), updated_at/completed_at.
- Marker khởi tạo RUNNING + required_writer_version=0. Transaction promote chạy SELECT marker FOR UPDATE, nhờ đó đợi toàn bộ trigger-held FOR SHARE của writer v0 đang in-flight; sau khi có exclusive lock phải scan partial index toàn bảng, không chỉ <=HWM, và recheck declared-image/READY file parity.
- Chỉ khi global scan sạch mới cùng transaction set required_writer_version=1 + REFERENCES_COMPLETE. Writer mới bị block trong lúc promote rồi thức dậy dưới fence version 1; required version không bao giờ giảm và trạng thái này mở cleanup legacy.
- Sau đó cleanup/reconciler mới đưa marker tới CLEANUP_COMPLETE khi pending/running/failed cleanup job liên quan=0 và unreferenced staging/final=0. Release gate dùng CLEANUP_COMPLETE; không tạo vòng chờ orphan=0 trước khi cho cleanup chạy và không dùng env/manual flag thay marker durable.

Transaction invariant:

- Mọi mutation SELECT incident row FOR UPDATE.
- Mọi transaction có thể insert incident_events — live/shadow/atomic writer, user mutation, legacy adapter, scope/image reconciler và backfill — phải lấy cùng PostgreSQL pg_advisory_xact_lock(INCIDENT_EVENT_ORDER_LOCK_KEY) ngay trước event insert đầu tiên và giữ tới commit/rollback.
- INCIDENT_EVENT_ORDER_LOCK_KEY là constant code/schema duy nhất dùng chung mọi process, không cho cấu hình lệch theo instance; helper append_incident_events() là đường insert duy nhất và test cấm direct ORM add/SQL ngoài helper.
- Lock order bắt buộc: validate external Config/Auth trước; lock source/case/mutation ledger; sau đó lấy global event-order lock; sau khi giữ global lock không acquire entity lock mới, không gọi external I/O và chỉ insert event/update case/commit. Vi phạm lock order fail test để tránh deadlock.
- Event sequence/PK chỉ được allocate sau global lock. Vì producer thứ hai không thể insert trước khi producer thứ nhất commit/rollback, max committed event id là safe cursor watermark; rollback được phép tạo numeric gap nhưng không có lower id commit muộn.
- Invariant trên yêu cầu sequence CACHE 1; global advisory lock một mình không đủ nếu physical connection cache block nextval. Migration/readiness/CI cùng assert điều này trên ít nhất hai pooled connections.
- next sequence = last_event_sequence + 1 cho từng event.
- Một transaction có thể append nhiều event nhưng chỉ tăng revision một lần.
- Mọi thay đổi status, priority, assignee, project/station scope hoặc field workflow-owned tăng version đúng một lần/transaction, bất kể actor là user, legacy adapter hay reconciler; source_severity/signal_state/last_signal_at-only chỉ tăng revision và không làm expected_version churn.
- Case update và event insert commit atomically trong Data DB.
- Chỉ broadcast sau commit; broadcast lỗi không rollback durable data.

### C2. Đồng bộ nguồn

#### Sensor Alert

- Định nghĩa một hàm dùng chung normalize_alert_episode_category() trong backend; writer, PostgreSQL advisory lock, lookup unresolved episode, backfill và test đều gọi đúng hàm này. Mapping tối thiểu khóa `tilt_warning`/`tilt_critical`→`tilt`; các suffix severity allowlist khác được normalize bằng bảng explicit, category lạ giữ nguyên sau canonical casing, không strip tự do.
- Alert writer dùng PostgreSQL advisory transaction lock theo station_id + normalized category trước select/create episode để không sinh hai unresolved Alert do concurrent worker.
- Khi tạo episode mới, tạo IncidentCase và opened event trong cùng Data DB transaction ở cutover mode.
- source_severity theo level backend xác nhận; operator không được sửa source_severity.
- last_signal_at được coalesce persist tối đa một lần/60 giây; heartbeat không tăng version.
- Severity hoặc signal_state đổi phải persist ngay, append event và tăng revision.
- Signal trở lại bình thường chỉ đổi signal_state=RETURNED và append signal_returned; không tự đổi human workflow status.
- Lỗi đọc/đánh giá sensor evidence hoặc Data DB đổi signal_state=UNKNOWN; lỗi Config chỉ lookup scope không đổi ACTIVE/source_severity. Không trường hợp lỗi nào được hạ priority, resolve hoặc phát safe.
- Alert episode mới sau khi Alert row cũ resolved tạo case mới.

#### Rescue

- Public Rescue và Incident được tạo cùng Data DB transaction ở cutover mode.
- Case chỉ lưu title generic theo rescue_type allowlist và summary Yêu cầu cứu hộ mới; không copy name, phone, message, image hoặc tọa độ chính xác.
- source_severity=UNKNOWN, signal_state=NOT_APPLICABLE, scope_state=UNSCOPED, priority=UNTRIAGED, status=new.
- project_id null là admin-only.
- Admin scope Rescue bằng API scope; sau đó role đúng project mới nhìn thấy representation được phép.

#### Legacy Rescue mapping

| Legacy status | Incident workflow |
|---|---|
| pending | Giữ open state hiện tại; nếu đang resolved/dismissed thì reopen thành in_progress, clear resolved_at và append status_changed với note/reason tự động `legacy_reopen` |
| resolved | Chuyển resolved |
| rejected | Chuyển dismissed |

- Legacy pending reopen và resolved/rejected được phép đi qua UNTRIAGED để không phá client cũ, nhưng append payload legacy_untriaged_override=true và không bịa priority; đây là adapter exception duy nhất của state table.
- admin_note mới/đổi được append note_added và vẫn cập nhật field legacy.
- Incident open state sync ngược Rescue pending; resolved sync resolved; dismissed sync rejected.
- Legacy PATCH giữ nguyên request/response và transaction Rescue + Incident + event.
- Legacy DELETE chỉ cho source resolved/rejected như policy hiện tại; transaction lock source/case, capture snapshot audit non-PII và upsert durable upload cleanup job, rồi DELETE source trước để trigger/fence lấy marker lock trước global lock. Sau DELETE mới lấy event-order lock và append source_deleted từ snapshot đã capture; tất cả vẫn cùng một Data DB transaction nên source/event/outbox cùng commit hoặc cùng rollback. Giữ Incident audit, không broadcast PII và không để promoter hồi sinh file.
- Alert is_resolved chỉ phản ánh sensor episode; Incident status chỉ là human workflow.

### C3. Workflow state machine

- System processor không được mutate status.
- new → acknowledged hoặc dismissed.
- acknowledged → in_progress, monitoring, resolved hoặc dismissed.
- in_progress → monitoring, resolved hoặc dismissed.
- monitoring → in_progress, resolved hoặc dismissed.
- resolved/dismissed → in_progress với note bắt buộc.
- Priority UNTRIAGED phải được triage trước in_progress/resolved, ngoại trừ legacy adapter có audit nêu trên.
- Dùng một requiresPriorityNote(current,next) shared contract ở server và frontend adapter:
  - UNTRIAGED là sentinel, không nằm trong comparator; lần triage đầu UNTRIAGED→LOW|NORMAL|HIGH|URGENT không cần note.
  - API user không cho chuyển priority đã triage trở lại UNTRIAGED; system/source sync cũng không tự reset workflow priority.
  - Với priority đã triage, rank LOW=0 < NORMAL=1 < HIGH=2 < URGENT=3; chỉ next rank thấp hơn current mới bắt note, bằng/tăng không bắt note.
- Resolve, dismiss, reopen và priority downgrade theo helper trên luôn yêu cầu note.
- Acknowledge:
  - Lần đầu set acknowledged_at và status=acknowledged.
  - assign_to_self mặc định true.
  - Nếu đã acknowledged/open, trả current case với changed=false và không tạo event.
- Operator chỉ tự nhận/bỏ mình; admin được gán active operator/admin.
- Admin chỉ gán operator có incident project trong assigned_projects; admin assignee được phép toàn cục.
- Mọi POST mutation mới yêu cầu Idempotency-Key 1–64 ký tự.
- Idempotency bind actor + incident + action + canonical body qua incident_mutation_requests; retry giống hệt trả current case cùng original sequence range, còn reuse key khác action/body trả 409 IDEMPOTENCY_KEY_REUSED.
- Sau auth/scope check, service kiểm mutation request trước expected_version: replay thành công với expected_version cũ vẫn trả idempotent result, không bị biến thành conflict 409.
- expected_version áp dụng acknowledge/priority/assign/scope/transition; mismatch trả 409 với current case.
- Note không cần expected_version nhưng vẫn cần Idempotency-Key và row lock.

### C4. API mới

#### Đọc và cursor

- GET /api/incidents
  - Auth: viewer/operator/admin; non-admin không assigned project nhận danh sách rỗng.
  - Query: status, priority, source_severity, signal_state, source_kind, project_id, station_id, assigned_to, q, cursor, limit, sort.
  - q chỉ tìm reference, project/station name/code snapshot và case title/summary non-PII; không join Config DB trong request, không tìm phone/message. Snapshot được refresh khi scope/reconciler thành công và giữ last-known khi Config entity bị xóa.
  - limit mặc định 50, min 1, max 100.
  - Keyset cursor là base64url payload + HMAC chứa schema version, sort, last tuple, id, filter hash và current authz_scope_hash; signature/filter/sort sai trả 422 INVALID_CURSOR, authz hash cũ trả 422 CURSOR_AUTHZ_CHANGED.
  - Sort allowlist: attention, -updated_at, updated_at, opened_at.
  - attention_score = max(signal_score, priority_score). signal_score: signal_state UNKNOWN=750; ACTIVE EXTREME=900, CRITICAL=850, HIGH=800, WARNING=700, MEDIUM=650, LOW=550, INFO=500, source UNKNOWN=600; RETURNED/NOT_APPLICABLE=0. priority_score: URGENT=780, UNTRIAGED=680, HIGH=620, NORMAL=400, LOW=200. Tie-break updated_at desc rồi id desc.
  - API chạy trong một Data DB REPEATABLE READ snapshot: câu query đầu tiên đọc global MAX(incident_events.id) thành snapshot_event_id, sau đó mới query list/count/facets trong cùng transaction. Không được query list trước rồi mới lấy watermark.
  - Response: items, total, next_cursor, snapshot_event_id, authz_scope_hash và server_time.
  - Counts áp dụng project/source/q scope và các filter không phải facet; bỏ status/priority/source_severity/signal_state để facet không tự triệt tiêu.
- GET /api/incidents/{id}
  - Ngoài scope trả 404, không dùng 403 để dò id.
  - Trả case, source representation theo role và 50 event mới nhất.
- GET /api/incidents/{id}/events
  - Query before_sequence hoặc after_sequence, không dùng đồng thời.
  - limit mặc định 50, max 100; order sequence rồi id.
- GET /api/incident-events?after_event_id=N&limit=500 cho page đầu; page sau dùng opaque signed cursor và không gửi đồng thời after_event_id
  - Cursor toàn cục, filter theo project_id_at_event hoặc previous_project_id của event thay vì chỉ current case scope.
  - Page đầu chụp catchup_upper_event_id=global MAX(event.id) đúng một lần. Signed cursor chain bind scan_after + catchup_upper_event_id + authz_scope_hash; mọi page sau giữ nguyên upper bound dù producer tiếp tục append.
  - MAX(event.id) chỉ là safe committed watermark vì mọi event producer tuân global event-order transaction lock ở C1; không được thêm producer bỏ qua invariant này.
  - Mỗi page scan tối đa limit raw event liên tiếp có id > scan_after và <= catchup_upper_event_id; limit áp vào raw rows trước audience filter, không phải số visible item.
  - scan_end là id raw cuối đã scan, hoặc catchup_upper_event_id nếu window không còn row. Response trả next_event_id=scan_end, next_cursor khi còn page và has_more=(scan_end < catchup_upper_event_id); tuyệt đối không advance qua row chưa scan.
  - Cursor signature/authz hash mismatch trả 422; client bỏ toàn bộ cursor/watermark cũ và bootstrap list mới, không cố tiếp tục chain của scope cũ.
  - Scope cũ của scope_changed nhận action=incident_removed tombstone chỉ có incident_id, event_id, old_project_id và reason; scope mới nhận current non-PII list summary. Unassigned/null chỉ admin nhận.
  - Trả event header đã redact + current incident list summary hoặc tombstone theo audience.
  - Dùng để phát hiện case mới/đóng trong thời gian mất WebSocket.

#### Mutation

- POST /api/incidents/{id}/acknowledge
  - Body: expected_version, assign_to_self mặc định true.
- POST /api/incidents/{id}/priority
  - Body: priority, note tùy chọn, expected_version.
- POST /api/incidents/{id}/assign
  - Body: assignee_user_id nullable, expected_version.
- POST /api/incidents/{id}/scope
  - Admin-only và chỉ source RESCUE_REQUEST.
  - Body: project_id nullable, station_id nullable, expected_version.
  - project_id null bắt buộc station_id null và đưa case về admin-only.
  - station_id phải thuộc project_id; validation Config DB fail trả 503 retryable trước Data mutation.
  - Đổi scope tự bỏ assignee không còn hợp lệ và append assigned + scope_changed trong cùng transaction; scope_changed persist previous_project_id, project_id_at_event/new_project_id để scope cũ catch-up tombstone kể cả đã mất WS.
- POST /api/incidents/{id}/transition
  - Body: to_status, note tùy/required theo state, expected_version.
- POST /api/incidents/{id}/notes
  - Body: message 1–4000 ký tự.
- GET /api/incidents/{id}/source-image
  - Chỉ operator đúng current project hoặc admin; kiểm capability và scope lại ở mỗi request, ngoài scope trả 404.
  - Chỉ READY trả stream; NONE/PENDING/FAILED không xuất URL và route trả 404 an toàn, UI dùng trạng thái xử lý/không có ảnh thay vì broken image.
  - Stream file qua opaque id, Content-Disposition inline an toàn, Cache-Control private,no-store và X-Content-Type-Options nosniff.
  - Không mở rộng route ảnh filename legacy thành quyền global cho operator.

#### Public Rescue idempotency additive

- POST /api/public/rescue-requests giữ nguyên body/response cho client cũ và nhận optional Idempotency-Key 1–64 ký tự; UI V2 luôn sinh UUID ngẫu nhiên, giữ cùng key qua timeout/retry và chỉ reset sau response success.
- Thêm RescueRequest.client_submission_id/request_fingerprint nullable với partial unique client_submission_id, cùng image_writer_schema_version SmallInteger NOT NULL default 0, upload_id String(36) unique internal, image_job_generation Integer NOT NULL default 0, image_state NONE|PENDING|READY|FAILED, image_storage_key String(255), image_content_sha256 String(64), image_size_bytes BigInteger và image_metadata_migrated_at BigInteger nullable. Writer V2 luôn explicit image_writer_schema_version=1; default 0 nhận diện binary/row legacy. Fingerprint gồm canonical form fields + SHA-256 nội dung ảnh nếu có; cùng client key + payload trả representation đã tạo cùng Incident case, cùng key khác payload/ảnh trả 409 IDEMPOTENCY_KEY_REUSED.
- Partial index RescueRequest(id) WHERE image_writer_schema_version<1 OR image_metadata_migrated_at IS NULL phục vụ fence/reconciler không full-scan.
- Data DB BEFORE INSERT/UPDATE/DELETE trigger luôn SELECT marker rescue_image_metadata_v1 FOR SHARE và giữ row lock tới transaction end. INSERT/UPDATE khi marker.required_writer_version>=1 phải có NEW image_writer_schema_version>=required và migrated_at non-null; required version chỉ tăng.
- DELETE sau fence yêu cầu transaction-local `aitogy.rescue_image_writer_version>=required` do V1 service SET LOCAL, và nếu source có upload/storage thì matching file_cleanup_jobs generation đã được insert trong cùng transaction. Binary cũ không có claim/outbox bị trigger reject tại commit, nên code hiện tại không đi tiếp tới bước unlink file sau commit.
- New readiness assert trigger enabled + binary writer version>=marker; code cũ fail write rõ ràng thay vì tạo/xóa packed-only evidence ngoài lifecycle.
- image_state NOT NULL default NONE; CHECK khóa NONE không cần storage key, PENDING và READY đều cần upload_id+generation>0+image_storage_key+content hash+size>0, FAILED giữ upload/key/hash để audit/retry/cleanup. Partial index image_state=PENDING + updated_at cho sweeper bounded.
- Ảnh được stream vào bounded durable staging path theo upload_id với MIME/size validation; transaction đầu commit Rescue + Incident với image_state=PENDING và không expose URL.
- Trước transaction PENDING, derive final image_storage_key deterministic `uploads/{upload_id}-g{generation}.{safe_ext}`; safe_ext chỉ từ MIME allowlist, không từ filename user. Persist planned key + SHA-256 + size cùng PENDING trước bất kỳ rename/move nào.
- Promoter capture image_job_generation rồi SELECT RescueRequest FOR UPDATE ngay trước move/state commit; row đã mất, state không còn PENDING hoặc generation lệch thì abort và enqueue cleanup, không hồi sinh upload đã delete/retry.
- Post-commit promoter atomic-move sang opaque final key, rồi transaction Data ngắn luôn commit RescueRequest READY/FAILED độc lập với Incident write mode. Nếu case tồn tại thì cùng transaction append source_image_state_changed non-PII và tăng Incident revision nhưng không workflow version; nếu write_mode=off hoặc shadow case fail/chưa có, source state vẫn hội tụ và backfill/reconciler tạo case từ state hiện tại sau đó.
- Serializer/image route/WS/normal success chỉ expose `has_image=true` và URL qua scoped route sau READY. PENDING retry cùng client key reattach cùng row/job, không tạo source mới.
- Rollback xóa staging; startup/periodic sweeper dùng upload_id, không phụ thuộc optional client key, để resume PENDING hoặc mark FAILED và xóa orphan. Crash trước/sau source commit, file promote và READY commit không được tạo URL-missing hoặc hơn một final file.
- Recovery của PENDING chỉ thao tác planned key đã persist: nếu final tồn tại và hash/size khớp thì mark READY; nếu chưa thì move staging; mismatch chuyển FAILED + cleanup. Sweeper không coi final key còn được PENDING row cùng generation reference là orphan.
- Legacy DELETE V1 transaction SET LOCAL aitogy.rescue_image_writer_version=1, SELECT RescueRequest/case FOR UPDATE, capture audit snapshot non-PII cùng upload/storage/generation, upsert file_cleanup_jobs với generation+1, rồi DELETE source trước global event-order lock để BEFORE DELETE trigger lấy marker FOR SHARE theo đúng lock order. Sau DELETE mới lấy global event-order lock và append source_deleted từ snapshot đã capture; DB trigger verify claim+outbox, còn source/event/outbox commit hoặc rollback nguyên tử. After commit mới cancel promoter và để cleanup worker xóa staging/final idempotently sau reference-count check.
- Nếu DELETE gặp legacy row image_metadata_migrated_at=NULL, nó dùng đúng parser/canonical path validator của migration để derive deterministic upload_id + legacy storage key dưới row/key lock trước enqueue; không đưa raw packed path vào job. Cleanup key legacy vẫn defer tới marker REFERENCES_COMPLETE, nên không xóa file còn được row chưa migrate dùng chung.
- Race được khóa: promoter thắng row lock thì DELETE đợi và sau đó cleanup READY file; DELETE thắng thì promoter thấy row missing/generation mismatch và chỉ cleanup. Sweeper xử lý stale PENDING, cleanup job retry và unreferenced final key có tuổi vượt safety TTL; không recursive-delete/glob ngoài root đã resolve.
- Detail đang mở hội tụ PENDING→READY/FAILED bằng revision event; nếu operations WS mất, poll scoped case mỗi 2 giây tối đa 30 giây bằng AbortController rồi chuyển sang nút Retry, không poll vô hạn.

Mọi mutation trả case, events vừa tạo, changed, request_id, version và revision.

#### Privacy/serializer matrix

| Field | Guest | Viewer đúng project | Operator đúng project | Admin |
|---|---|---|---|---|
| Incident API/WS | Không | Có | Có | Có |
| Case non-PII/status/signal | Không | Có | Có | Có |
| Station/project | Không | Có | Có | Có |
| Rescue precise coordinate | Không | Không | Có | Có |
| requester_name/phone/message/image | Không | Không | Có | Có |
| Notes/actor username/assignee username | Không | Redact nội dung và username | Có | Có |
| Unassigned Rescue | Không | Không | Không | Có |

- Guest chỉ submit Rescue; không gọi Rescue list/marker/heat/Incident REST và không nhận operations WS.
- Viewer map chỉ pan tới station, không precise Rescue point.
- Operator/admin source detail load PII theo capability/scope; ảnh đi qua scoped Incident image route, list và WebSocket không bao giờ chứa PII.
- Mọi response có Rescue/source PII hoặc precise coordinate đặt Cache-Control private,no-store, Pragma no-cache; frontend fetch cache=no-store và service worker denylist private API. Browser HTTP cache không được trở thành persistent PII cache ngoài ý muốn.
- Event payload durable không lưu phone/image/full message.
- Chỉ network outage trong authz grace được giữ last-good memory state. Khi REST trả 401/403, socket close unauthorized, role/project đổi, nhận tombstone hoặc grace hết hạn, client phải purge trước render mọi case/source detail không còn scope, phone/message, image/object URL, precise coordinate, Rescue marker/heat point, Pi private state và non-PII persisted namespace cũ.
- Role downgrade operator→viewer xóa PII/precise location nhưng có thể giữ non-PII case nếu viewer vẫn đúng project; scope A→B/null xóa toàn case khỏi client A. Purge là state transition bắt buộc, không chỉ ẩn DOM.
- Incident scope tombstone xử lý case bị chuyển project; user-permission revocation là luồng khác và được phát hiện bằng authz_scope_hash + assigned_projects mới, kể cả reconnect vẫn trả HTTP 200 vì user còn project khác.
- Cold start offline chỉ render public shell/station fallback; không hydrate Incident/Rescue/Pi scoped data. Session mất mạng hiển thị countdown/Đang chờ xác minh quyền theo private_authz_grace_seconds của auth session; hết đúng grace server trả thì chuyển private panels sang locked state và yêu cầu reconnect/login.

### C5. Operations WebSocket và catch-up

- Mở rộng POST /api/auth/ws-ticket bằng optional body channel=legacy_admin|admin|operations:
  - Không body mặc định legacy_admin trong đúng compatibility window để Management cũ của viewer/operator không gãy; frontend mới luôn gửi channel explicit.
  - Mỗi process boot sinh random boot_epoch 128-bit không persist; ticket có sub, role, assigned_projects, authz_scope_hash, purpose, channel, boot_epoch, jti và TTL 60 giây.
  - jti consume atomically một lần bằng locked TTL registry keyed boot_epoch+jti trong single worker.
- Khi WS accept, server constant-time reject boot_epoch khác current process rồi mới consume jti và đọc current auth; ticket đã cấp trước restart không replay được dù signing secret và TTL còn hiệu lực. Ticket authz_scope_hash/role/scope lệch current state thì close 4403 trước subscribe; ticket còn TTL không được giữ quyền đã bị thu hồi.
- Frontend mới gửi hai subprotocol aitogy.v2 và ticket.<credential>; server chỉ echo aitogy.v2.
- Query ticket giữ compatibility một release và access log phải redact ticket query.
- Cutover /ws/admin theo frontend-first:
  1. Deploy Map/Management dùng /ws/operations cho Incident và chỉ explicit channel=admin cho chức năng thật sự admin.
  2. Trong một release, /ws/admin còn nhận legacy_admin của viewer/operator theo đúng project/serializer policy hiện tại; ghi metric role + client version nhưng không log ticket/PII.
  3. Chỉ sau 7 ngày telemetry không còn non-admin legacy client mới enforce /ws/admin = explicit admin ticket + role admin và bỏ legacy_admin.
- Trong compatibility window, mọi legacy private event thiếu project_id/station_id hoặc scope lookup lỗi là admin-only/default-deny; registry không được fallback broadcast viewer/operator.
- /ws/operations chỉ viewer/operator/admin có assigned project, hoặc admin; filter theo project và serializer matrix.
- Public /ws/updates không có Incident/Rescue PII/note.
- Mỗi post-commit envelope:
  - protocol=2, type=incident_changed.
  - event_id là id event cuối transaction.
  - sequence_from, sequence_to.
  - incident_id, incident_revision, workflow_version.
  - action=created|updated|incident_removed; incident_removed là tombstone non-PII cho previous_project_id.
  - project_id/station_id.
  - non-PII list summary.
- Client dedupe theo event_id + action/audience; revision chỉ dùng xác định summary mới hơn.
- Global event_id gap là bình thường vì event project khác bị filter, không được tự coi là packet loss. Chỉ per-incident sequence gap mới fetch case events after_sequence; global catch-up chạy khi reconnect/close, poll định kỳ hoặc bootstrap.
- Initial sync khóa thứ tự:
  1. Trước bootstrap và trước mọi reconnect/catch-up, gọi /api/auth/me; so authz_scope_hash + assigned_projects với session cũ và purge toàn bộ project/PII bị mất trước render. Việc reconnect trả 200 không được dùng để suy ra quyền không đổi.
  2. GET list trả snapshot_event_id đã đọc trước list trong cùng REPEATABLE READ snapshot; response echo authz_scope_hash để client từ chối snapshot thuộc scope cũ.
  3. Mở operations WS, verify hello authz_scope_hash, nhưng buffer mọi envelope và chưa mutate UI.
  4. Gọi global cursor page đầu after snapshot_event_id; server khóa một catchup_upper_event_id. Theo signed cursor chain tới đúng upper bound, mỗi page echo authz_scope_hash, apply visible event/tombstone theo event_id tăng dần và advance scanned watermark.
  5. Sort/dedupe buffer, bỏ item event_id <= catchup_upper_event_id đã có từ cursor, rồi drain phần >upper tăng dần; sau đó chuyển live. Event tới sau upper không kéo dài chain đang chạy; poll sau mở catch-up batch mới.
- Global cursor response trả next_event_id=scan_end của raw window thực sự đã đọc, kể cả page không có visible item; client advance theo next_event_id, không theo id visible cuối và lặp đến has_more=false với cùng catchup_upper_event_id.
- Bootstrap WS buffer bounded 256 envelope. incident_changed cùng incident có thể coalesce list summary tới revision mới nhất nhưng tombstone không drop; per-incident sequence gap vẫn fetch timeline. Nếu vượt cap/distinct-case budget, abort bootstrap, close socket, clear private render state và refetch một snapshot mới thay vì tăng RAM vô hạn.
- Khi authz_scope_hash đổi hoặc server trả CURSOR_AUTHZ_CHANGED, atomically clear next_cursor/list pages/selected item/global scanned watermark/WS buffer rồi bootstrap list + catch-up từ snapshot mới; không reuse cursor A+B dưới scope B.
- Client poll global cursor mỗi 15 giây khi operations WS disconnected; mutation vẫn dùng REST nếu api connectivity ready.
- Reliable event không drop; slow client vượt outbox bị close 1013 rồi reconnect/catch-up.
- Incident scope change đang connected phát tombstone cho old audience trước khi bỏ subscription; khi disconnected, global cursor vẫn đọc previous_project_id để trả tombstone. User bị thu hồi project không cần/không thể có incident tombstone cho mọi case: authz_scope_hash re-bootstrap chịu trách nhiệm purge toàn namespace project bị mất.
- Existing /ws/admin Rescue giữ một release sau khi Map/Management chuyển operations channel, theo usage gate ở trên chứ không hard-cut theo ngày deploy.

### C6. Incident UX trên Map

- Desktop >=1440:
  - Rail trái có hai top-level tabs Trạm và Sự cố.
  - Badge chỉ hiện số new + unacknowledged trong scope.
  - Chọn incident mở context panel; viewer chỉ pan tới station, operator/admin đúng scope mới pan precise Rescue marker.
  - Context panel có Summary, Source data, Timeline và Actions.
- 901–1439:
  - Incident list là overlay drawer.
  - Incident detail dùng context drawer; mở detail đóng station drawer theo invariant một overlay chính.
- <=900:
  - Auth nav: Trạm, Sự cố, Lớp, Thêm.
  - Guest nav: Trạm, Lớp, Cứu hộ, Thêm.
  - Incident list/detail dùng một bottom sheet với ba snap collapsed, khoảng 55dvh, full.
- Action hierarchy:
  - Primary cho new: Tiếp nhận.
  - Primary sau acknowledge: Bắt đầu xử lý hoặc Chuyển sang theo dõi.
  - Secondary: Tự nhận/bỏ nhận, thêm ghi chú.
  - Resolve/dismiss nằm trong overflow; Resolve, dismiss, reopen và priority downgrade theo requiresPriorityNote đều mở shared Incident action dialog và bắt buộc note giống backend. First triage từ UNTRIAGED, priority bằng hoặc tăng không bắt note.
- Shared action dialog Map/Management dùng cùng validator/state adapter cho transition và priority downgrade: focus ô note hoặc field invalid đầu tiên, inline error + aria-describedby, Escape/restore focus, giữ nguyên draft khi 409 và chỉ clear sau success.
- Timeline dùng local time, actor, event label và plain-text note.
- Update realtime không cướp focus/scroll; item thay đổi chỉ dùng finite highlight 600 ms.
- Operations WS disconnected do network giữ last-good chỉ trong authz grace, poll global cursor 15 giây và hiển thị thời điểm cập nhật; mutation chỉ dùng REST khi API ready và authz vừa verify. Grace hết hoặc close unauthorized/401/403 không giữ private last-good mà chạy lock/purge/re-bootstrap theo privacy contract.
- 409 conflict:
  - Giữ nguyên draft note/filter/focus.
  - Refresh case hiện tại và announce Có cập nhật mới bằng aria-live polite.
  - Hiển thị diff workflow nhỏ; user xác nhận lại action với version mới.
- Deep-link /map?incident={id}:
  - Auth đủ scope mở incident và pan theo privacy matrix.
  - Guest giữ public map và thấy login prompt có return_to đầy đủ.
  - Ngoài scope hiển thị Không tìm thấy hoặc không còn quyền, không lộ id tồn tại.
  - Back/Forward khôi phục incident/list/sheet/scroll.

### C7. Incident UX trên Management

- Giữ data-tab và DOM contract của tab Rescue để không phá workflow; đổi nhãn hiển thị thành Sự cố.
- Mobile order: Projects, Pi, Sự cố, Data, More.
- Tab Sự cố mặc định là unified inbox; filters:
  - Tất cả, Cứu hộ, Cảm biến.
  - Status, priority, source severity, signal state, project, station, assignee.
  - Search reference/station/case non-PII text.
- Desktop:
  - Inbox table/list ở giữa.
  - Inspector drawer phải có summary, source, timeline, assignee và actions.
- Mobile:
  - List card ưu tiên source severity, priority, workflow status và time.
  - Detail là full-height bottom sheet.
- Rescue legacy vẫn truy cập bằng source filter Cứu hộ và dùng cùng API compatibility.
- switchTab là nguồn active state; URL dùng query tab=tab-rescue và incident=id, không đổi route /management.
- Back/Forward đóng/mở inspector và khôi phục filter/scroll.
- Cursor pages reconcile keyed theo incident id; event làm item đổi filter/order thì debounce refresh 250 ms, không append duplicate.
- Timeline tải mới bằng after_sequence và tải lịch sử cũ bằng before_sequence.
- Resolve/dismiss/reopen và priority downgrade dùng shared Incident action dialog, bắt buộc note ở client lẫn server, validation/focus/restore như Map; first triage/bằng/tăng priority không bắt note.
- 409 recovery giống Map và không xóa draft note.

## 7. Workstream D — Landing storytelling V2

### D1. Markup và progressive enhancement

- [ ] Bốn article luôn ở normal flow và visible trong HTML mặc định.
- [ ] No-JS desktop/mobile hiển thị heading, bốn chapter, poster, metrics và CTA đầy đủ.
- [ ] JS chỉ thêm class story-enhanced sau khi:
  - media query >=1024 khớp.
  - reduced-motion=false.
  - navigator.connection.saveData không bật; trình duyệt không hỗ trợ API này được coi là false.
  - observer/scroll controller đã init thành công.
- [ ] Khi giảm motion, bật Save-Data hoặc đổi breakpoint giữa phiên, teardown enhancement và trở về normal flow ngay; nghe connection.change khi trình duyệt hỗ trợ.
- [ ] Không dùng aria-live cho chapter scroll; article semantic là nguồn ý nghĩa.

### D2. Cấu trúc sân khấu

- DOM được khóa theo skeleton:
  - section.story chứa story header rồi story-track.
  - story-track đặt story-viewport và story-chapters vào cùng grid-area.
  - story-viewport ở z-layer visual, sticky, pointer-events none và toàn bộ visual aria-hidden.
  - story-chapters ở z-layer content, normal flow; mỗi semantic article là một story-chapter.
  - Mỗi chapter min-height 105dvh và dùng flex/grid alignment theo copy anchor trong bảng pose.
  - HTML/CSS mặc định không sticky/overlay; chỉ story-enhanced mới kích hoạt grid layering.
- DOM order luôn là heading → chapter 0 → 1 → 2 → 3; visual không chen vào reading/focus order.
- story giữ bốn chapter, mỗi chapter khoảng 105dvh trên desktop.
- story-viewport sticky dưới header và có chiều cao calc(100dvh - header).
- story-stage-base được reserve full viewport để CLS bằng 0.
- story-stage-motion là layer duy nhất nhận translate3d + scale; không animate width/height/grid.
- story-stage-motion có transform-origin center center, isolate stacking context và overflow clip; semantic cards ở trên visual và vẫn pointer-events auto.
- Các chapter content card đổi anchor để không đứng yên một chỗ.

Pose desktop >=1280:

| Chapter | Frame pose | Silhouette | Copy anchor |
|---|---|---|---|
| 0 Phát hiện | translate3d(23%, -2%, 0) scale(0.58) | radius 24 px, border/shadow rõ | trái dưới |
| 1 Bối cảnh | translate3d(0, 0, 0) scale(1) | full-bleed, radius 8 px, shadow giảm | trái trên trên surface scrim |
| 2 Làm rõ | translate3d(-7%, 3%, 0) scale(0.82) | inset 20 px, amber focus aperture | phải giữa |
| 3 Phản ứng | translate3d(0, 8%, 0) scale(0.94) | panorama 12 px, visual hướng xuống metrics | trái trên |

- 1024–1279 dùng cùng keyframe nhưng translation nhân 0.55, scale chapter 0 tối thiểu 0.72, chapter 1 radius 12 px và không full-bleed sát mép.
- <1024 không sticky, không transform và không tải Three.
- Border radius đổi chính xác theo pose bằng transition 220 ms ease-out khi active step đổi; không scrub radius theo từng pixel.
- Shadow dùng pseudo-element và transition opacity 220 ms, không animate box-shadow trong scroll RAF.
- Transform nội suy liên tục.
- Progress bar dùng transform scaleX, không đổi width.

### D3. Scroll controller

- Cache anchor khi init, ResizeObserver, document.fonts.ready và breakpoint change:
  - anchor[i] = document scrollY tại tâm chapter i trừ một nửa visualViewport.height.
  - Trước anchor 0 clamp step/progress về 0; sau anchor 3 clamp về 3/1.
  - Trong segment i: t = clamp((scrollY - anchor[i]) / (anchor[i+1] - anchor[i]), 0, 1).
  - eased = t × t × (3 - 2 × t).
  - global progress = (i + eased) / 3.
  - Active step là anchor gần nhất; đổi step tại midpoint giữa hai anchor.
- Trong RAF chỉ đọc scrollY/visual viewport và dùng cache; không đọc bounding box mỗi frame.
- Một progress duy nhất điều khiển:
  - frame pose.
  - active chapter/data-step.
  - copy emphasis.
  - HUD.
  - Three controller setProgress.
- Scroll listener chỉ queue RAF khi story near/in viewport.
- Scroll xuôi, ngược, nhảy nhanh hoặc restore browser history phải cho cùng kết quả deterministic.
- Intersection enter, pageshow/bfcache, initial restore và re-entry phải gọi update ngay trước render.
- StoryEnhancer sở hữu media/connection/scroll/observer lifecycle; Three controller chỉ sở hữu WebGL resources.
- StoryEnhancer contract:
  - init().
  - update().
  - destroy().
- Three controller contract:
  - setProgress(progress).
  - resize().
  - setTheme(theme).
  - destroy().

### D4. Bốn state hình ảnh

#### 0 — Phát hiện

- Terrain close-up.
- Baseline và current point rõ bằng hai shape khác nhau.
- Vector displacement có label cấp mm nhưng không có số giả.
- Sensor chính sáng; các sensor khác giảm emphasis.

#### 1 — Bối cảnh

- Camera kéo ra toàn sườn.
- Rain/water xuất hiện.
- HUD chip GNSS, Rain, Water, IMU và một shared timeline.
- Frame mở full-bleed để thay đổi không gian rõ rệt.

#### 2 — Làm rõ

- Rain/noise opacity giảm.
- Camera hướng vào corroborated cluster.
- Cluster chuyển amber, có text Cần xác minh.
- Không dùng đỏ và không tự gắn nhãn cảnh báo.

#### 3 — Phản ứng

- Camera mở toàn mạng.
- Network lines chạy từ sensor tới operations node.
- Acknowledgment Đã tiếp nhận xuất hiện.
- Hướng nhìn/frame hạ xuống để nối liền với live metrics và CTA.

HUD là HTML/CSS aria-hidden; nội dung tương đương đã có trong article.

- Mưa, drawRange của network line, signal dot, camera và acknowledgment đều là hàm thuần của segment progress.
- Không dùng elapsed time hoặc RAF tự chạy; offscreen chỉ giữ progress và render đúng một lần khi re-enter.
- Copy chapter trong viewport không bị giảm opacity; emphasis dùng border, marker và elevation.
- Chapter full-bleed dùng surface scrim bảo đảm contrast chữ tối thiểu 4.5:1 ở light/dark.

### D5. Three.js performance và fallback

- Dynamic import Three 0.170 khi story cách viewport 750 px.
- Không request Three khi:
  - viewport <1024.
  - reduced-motion.
  - save-data.
  - WebGL probe fail.
- Dùng seeded PRNG cho hạt mưa để snapshot deterministic.
- Dynamic import dùng generation token:
  - Mỗi init/teardown tăng generation.
  - Kết quả import chỉ được tạo controller nếu generation và eligibility còn khớp.
  - Kết quả stale phải dispose ngay và không thêm is-ready.
- Không GLTF, texture, OrbitControls, shadow, postprocessing hoặc continuous loop.
- Render chỉ khi progress/theme/size/data đổi.
- Dừng hoàn toàn khi offscreen hoặc document hidden.
- DPR hiệu dụng = min(devicePixelRatio, 1.5, sqrt(5.000.000 / (cssWidth × cssHeight))) để buffer không vượt 5 megapixel kể cả màn 4K.
- Không gán material mới mỗi frame; dùng shared material và mutate property.
- Context lost hoặc CDN fail:
  - Dispose phần đã tạo.
  - Hide canvas.
  - Poster/HUD CSS tiếp tục phản ánh chapter.
- destroy disconnect observer/listener/RAF, dispose geometry/material/renderer một lần và forceContextLoss.

### D6. Landing polish

- Header không thay width/position khi scrollbar hoặc story chuyển pose.
- Logo test route phải phục vụ asset thật.
- Metrics có loading, ready, empty, stale, error và retry; last-updated dùng server time.
- Theme/reduced-motion media query phản ứng khi thay đổi trong phiên.
- CTA và anchor vẫn dùng được khi CDN/API/WebGL/JavaScript lỗi.

## 8. Workstream E — Map Operations V2

### E1. Một nguồn state

Map state chuẩn:

- workspace: map hoặc digital_twin.
- mode: station hoặc rescue; giữ nguyên key/meaning hiện tại để không phá consumer.
- layers: stations, cors, rescue, heatmap; cors là CORS base layer hiện tại, không rename thành cors_base.
- activePanel: null, stations, incident_list, station_detail, incident_detail, layers, rescue_submit, analysis, gnss.
- selectedStation: id hoặc null.
- selectedIncident: id hoặc null.
- sheetSnap: collapsed, half, full.
- connectivity:
  - api: ready, stale, error, offline.
  - sensorWs: connected, reconnecting, disconnected.
  - operationsWs: connected, reconnecting, disconnected, unauthorized.
  - adminWs: not_applicable, connected, reconnecting, disconnected, unauthorized; chỉ init cho capability/channel admin còn cần trong compatibility window.
  - tiles: ready, degraded, error.
  - cdn: ready, degraded, error.

Chỉ setMapUiState(patch, reason) được mutate state.

- Handlers chỉ dispatch.
- Renderer duy nhất đồng bộ DOM class, aria-expanded/current/controls, Leaflet layer và panel.
- Không init nào tự reset user-selected layer.
- Migration state không big-bang:
  1. Hydrate mapUiState từ globals hiện tại.
  2. Chuyển controls sang dispatch.
  3. Chuyển renderers sang đọc state.
  4. Thay toàn bộ consumer reads.
  5. Giữ compatibility getter cho globals một release rồi xóa.
- Invariant:
  - >=1440 có rail + context panel đồng thời.
  - 901–1439 chỉ một overlay drawer chính.
  - <=900 chỉ một sheet/workspace chính.

### E2. Layout

- >=1440:
  - Rail 336 px, collapsible về 64 px.
  - Map minmax(0, 1fr).
  - Context 416 px, range cho phép 380–440 px.
  - GNSS advanced là workspace/tab trong context, không chồng panel ngẫu nhiên.
- 901–1439:
  - Map full viewport.
  - Rail/detail là drawers có scrim và LIFO.
- <=900:
  - Top bar gọn.
  - Bottom nav bốn item theo role.
  - Sheet snap collapsed 88 px, half 55dvh, full calc(100dvh - topbar - safe area).
  - Có handle nhìn thấy, button toggle, pointer threshold 12 px và keyboard ArrowUp/ArrowDown.
  - Leaflet invalidateSize theo computed transition: reduced-motion hoặc total duration=0 gọi ở next requestAnimationFrame; duration>0 dùng once transitionend với target/property guard, cleanup listener và fallback timer suy ra từ computed duration+delay. Transition bị interrupt vẫn invalidate đúng một lần, không hard-code 220 ms.
- 200% zoom và landscape không sinh horizontal scroll hoặc che primary action.

### E3. Data correctness

- Tạo helper finiteOrNull/normalizeEpochMs duy nhất.
- Null/NaN/undefined/empty:
  - UI text là —.
  - Chart point là null.
  - spanGaps=false.
  - Không đưa vào simulation.
- Real numeric 0 vẫn hiển thị 0.
- Digital Twin input thiếu yêu cầu user chọn:
  - Dùng dữ liệu trạm đủ điều kiện.
  - Hoặc chuyển manual và nhập giá trị.
  - Không tự điền số 0 ngầm.
- Station reconciliation keyed atomic:
  - add/update/remove marker, cache, cluster và line.
  - chấp nhận lat/lon finite kể cả 0.
  - API lỗi giữ last-good, đánh dấu stale và cung cấp retry.
- Không dùng innerHTML cho Nominatim, station/user/project/source text.

### E4. Cards, status và chart

- Sensor card dùng grid minmax(0,1fr) auto; badge flex none.
- Container query:
  - Panel đủ rộng: label và badge cùng hàng.
  - Panel hẹp/200%: grid chuyển một cột, badge xuống hàng và justify-self:start; không ép badge trong cột max-content hẹp, không cắt ký tự cuối như RTK FIXED hiện tại.
  - Card/cell đặt min-width:0; badge max-width:100%, white-space:normal chỉ wrap ở khoảng trắng, line-height đủ và font không giảm dưới 12 px. Không dùng overflow:hidden để che lỗi layout.
- Status tách hai trục:
  - riskState: SAFE, WARNING, CRITICAL, UNKNOWN.
  - dataState: LIVE, STALE, OFFLINE, DEGRADED.
  - Adapter legacy: INFO/LOW→SAFE; MEDIUM/WARNING→WARNING; HIGH/CRITICAL/EXTREME→CRITICAL; null/unknown/malformed/DB error→UNKNOWN. HIGH không được hạ xuống visual warning vì backend coi đây là dangerous.
  - UNKNOWN không bao giờ render SAFE hoặc kích auto-stop.
  - Mỗi risk/data state có text, icon và marker shape/pattern, không chỉ màu.
- Connectivity derived behavior:
  - sensorWs down nhưng API ready: realtime reconnecting, REST polling fallback, mutation vẫn dùng được.
  - operationsWs down: Incident stale/poll fallback; sensor vẫn live.
  - tiles error: panel/list vẫn dùng được, map có retry/fallback message.
  - cdn error: chỉ feature phụ bị disable, không đổi station risk/data state.
- Chart:
  - Teal cho GNSS/data chính.
  - Blue/violet cho series phụ.
  - Amber/red chỉ threshold/risk.
  - Axis có unit và locale time.
  - Có text/table summary thay thế.
- Loading, empty, no-result, stale, disconnected, API error, tile error và CDN error là state riêng có recovery.

### E5. Overlay và accessibility

- Overlay coordinator stack:
  - lưu trigger.
  - set aria-expanded.
  - focus heading/first control.
  - trap focus cho modal/sheet.
  - Escape đóng topmost.
  - restore focus.
  - inert vùng bị che.
- Không dùng click trên header ẩn làm gesture duy nhất.
- Outside click chỉ đóng popover nhẹ, không đóng flow có unsaved input.
- Rescue upload/geolocation/reverse-geocode có progress, fallback và retry.
- Infinite pulse/blink bị bỏ; severity increase chỉ finite attention rồi static.

### E6. Lifecycle

- Map bootstrap/dispose idempotent bằng feature AbortController.
- Tách sensorSocket, operationsSocket và adminSocket thành controller độc lập; mỗi controller sở hữu WebSocket, reconnect timer/backoff, AbortController, auth close-code và dispose riêng.
- Admin có thể nhận GNSS sensor stream + Incident operations stream + admin compatibility event đồng thời; disconnect/dispose một socket không close hoặc schedule reconnect cho socket khác.
- Dọn online/offline/visibility/resize/SPA listeners, polling, cả ba WS controller, chart, observer và timers.
- Chart.js chỉ load khi mở chart.
- Heat plugin chỉ load khi bật heatmap.
- Three analysis/IMU:
  - Lazy khi mở.
  - Render-on-demand; RAF chỉ chạy trong interpolation ngắn.
  - Stop hidden/offscreen/reduced-motion.
  - DPR <=1.5, context lost fallback, dispose + forceContextLoss.

## 9. Workstream F — Management Console V2

### F1. Role-first bootstrap

- Bootstrap gọi /api/auth/me trước mọi private loader.
- Derive permission/nav/manager model một lần cho mỗi authz_scope_hash, không phải một lần suốt SPA lifetime.
- Hash đổi gọi applyAuthzSession atomically: abort forbidden request, dispose forbidden Database/Users/Pi/Incident manager và admin/operations socket, đóng tab/inspector bị cấm, switch sang destination còn quyền rồi mới render nav mới.
- Chỉ init tab/manager được phép.
- Viewer/operator không gọi Users/Database/Pi destructive endpoint nếu không có capability.
- Backend 403 vẫn được xử lý rõ; frontend không coi hidden UI là security.

### F2. Navigation và history

- Một semantic nav renderer cho desktop/mobile; xóa nguồn legacy duplicate sau khi contract test xanh.
- Breakpoint:
  - >=1280: rail 240 px có icon + label.
  - 768–1279: compact rail 72 px, tooltip/focus label.
  - <=767: bottom navigation Projects, Pi, Sự cố, Data, More và safe-area inset.
- Destination không có capability vẫn giữ vị trí ổn định nhưng ở disabled/locked state có giải thích; không init manager hoặc gọi endpoint bị cấm.
- switchTab là nguồn duy nhất cho:
  - active class.
  - aria-current.
  - focus.
  - init/lazy load.
  - URL/history.
- User navigation dùng pushState; initial/fallback dùng replaceState.
- popstate khôi phục tab, subview, incident id, filter và scroll.
- URL chính vẫn /management; state nằm trong query, không tạo route mới.

### F3. Workflow hiện có

- Projects/Stations:
  - Card không dùng article tabindex onclick chứa nested button.
  - Primary link/button thật.
  - Search/filter/status rõ, validation cạnh field.
  - Wizard giữ schema/API, có autosave draft cục bộ và confirm khi dismiss có thay đổi.
  - Draft dùng allowlist field non-secret được review theo từng step; tuyệt đối không persist MQTT username/password, Wi-Fi/network password, token/API/license key, AICaster/NTRIP credential, certificate/private key hoặc secret Pi/device. UI ghi rõ secret không được lưu và restore luôn yêu cầu nhập lại chúng.
  - Namespace draft theo user id + authz_scope_hash + project id, TTL tối đa 24 giờ; clear khi submit thành công, logout, user/role/project scope đổi hoặc project bị xóa. Không ghi draft vào IndexedDB/Cache API/service worker và không migrate namespace cũ thiếu scope binding.
- Database:
  - Query pagination/count ở DB, không load toàn bảng rồi slice.
  - Dataset rail, sticky header, inspector, distinct loading/empty/no-result/error/stale.
  - Stats lỗi trả 503/error, không giả tất cả bằng 0.
  - Export task giữ resume và không duplicate download.
- Pi:
  - Status pending/activating/activated/assigned/locked/offline rõ.
  - Token rollout state audit/enforce hiển thị cho admin.
  - Bulk action có progress và result per device.
  - Viewer chỉ load/list detail.
  - Operator chỉ move thiết bị đã assigned giữa hai station cùng assigned project; không initial-claim hoặc unassign về pool.
  - Activate/lock/reset/token rotation/initial assignment/unassign pool/delete chỉ admin.
- Users:
  - Pagination server-side.
  - Role/project assignment scan-friendly.
  - Cache invalidation và permission refresh sau save.
- Incident:
  - Thực hiện theo Workstream C7.

### F4. Async và XSS

- Mỗi feature loader có AbortController + sequence/context.
- Silent refresh chỉ commit khi tab/filter/selection còn khớp.
- Refresh không cướp focus/scroll.
- Server/DB/WS text dùng textContent/DOM hoặc escapeHtml + escapeAttr đúng context.
- Hostile payload không được tạo node, handler hoặc attribute executable.
- sensorSocket/operationsSocket/adminSocket đều safe JSON parse, exponential backoff+jitter, online/visibility gate và close-code policy riêng; không dùng chung this.ws hoặc _wsReconnectTimer.
- Event burst coalesce refresh tối đa một lần mỗi 250 ms.

### F5. Dispose

- Admin dispose dọn:
  - sensorSocket, operationsSocket, adminSocket cùng reconnect timer/AbortController tương ứng.
  - Project/User/Pi/Rescue timers.
  - DB stats/export polling.
  - Wizard/listener AbortControllers.
  - Bootstrap modal/drawer listeners do feature tạo.
- 20 SPA cycles không tăng resource counters.

## 10. Workstream G — Backend realtime, performance và observability

### G1. WebSocket outbox

- Mỗi client có bounded outbox 64 event.
- Sensor/status coalesce latest theo station + sensor/type.
- Alert, incident, rescue, adjustment terminal là reliable.
- Client slow làm reliable queue đầy bị close 1013; không giữ client khỏe.
- Hoàn thiện channel registry cho adjustment debug/baseline/result và incident.
- Registry bắt buộc khai báo visibility + project resolver cho từng reliable/private event; resolver null/error chỉ gửi explicit admin channel, không broadcast legacy viewer/operator.
- Existing sensor payload giữ nguyên; additive project_id và sequence chỉ thêm khi có.

### G2. API performance

- Long-term analysis:
  - Bound khoảng từ 1 giờ đến 365 ngày.
  - Semaphore tối đa 2 job/process.
  - Query thành plain dict rồi compute bằng asyncio.to_thread.
  - Cache 30 giây theo station/options/latest timestamp.
- Station detail:
  - Bulk latest/history, query count không tăng theo số sensor.
  - include_history=false không query history.
- Station list:
  - SQL paginate sớm khi không có runtime filter.
  - Full map list contract vẫn giữ.
- Database admin:
  - stations/devices count/page trong DB.
  - Chỉ fetch relation cho page hiện tại.
- Rescue legacy list:
  - Trả status counts trong response/header additive; UI fallback request cũ trong rolling deploy.

### G3. Health và runtime diagnostics

- GET /api/health/live:
  - Chỉ xác nhận process/event loop sống.
- GET /api/health/ready:
  - Kiểm ba DB.
  - MQTT connected/topic load age.
  - ingest worker/queue.
  - last flush/error.
  - checkpoint/quarantine persistence health.
  - Incident event sequence cache_size=1 và event-order lock helper/schema revision.
  - scheduler/rollup/failover.
  - draining flag.
  - Trả 503 khi dependency critical degraded.
- GET /api/admin/system/runtime:
  - Admin-only.
  - Queue depth/drop/oldest age.
  - MQTT last message/reconnect/error theo broker.
  - Flush last success/error/retry.
  - Checkpoint last success/error.
  - WS client/backlog/close 1013.
  - Scheduler/rollup/failover state.
  - Không trả credentials, topic secret hoặc PII.

### G4. Logging và error contract

- Middleware cấp request_id và Server-Timing/duration cho endpoint chậm.
- Error mới có:
  - detail an toàn để giữ compatibility.
  - code.
  - retryable.
  - request_id.
- Log rotate bằng stdlib; hỗ trợ text/JSON qua config.
- Event code cố định cho processor init, checkpoint, queue overflow, flush retry, WS slow client, incident transition và auth audit.
- Đo incident_event_order_lock wait/hold p95/p99 và transaction rollback; alert nếu hold vượt 250 ms để phát hiện external I/O hoặc lock-order violation trong critical section.
- Không trả detail=str(exception) ra production.

## 11. Public interface và compatibility

### 11.1 Additive interfaces

- Ba bảng Incident incident_cases/incident_events/incident_mutation_requests, outbox file_cleanup_jobs và data_migration_markers trong Data DB.
- Cột/index nullable SensorData.ingest_id và RescueRequest.client_submission_id/request_fingerprint/upload_id/image_storage_key/image_content_sha256/image_size_bytes/image_metadata_migrated_at; Rescue image_writer_schema_version NOT NULL DEFAULT 0, image_state NOT NULL DEFAULT NONE và image_job_generation NOT NULL DEFAULT 0 cùng DB writer-fence trigger.
- REST Incident theo Workstream C4.
- Scoped Incident source-image route và optional public Rescue Idempotency-Key.
- Additive authz_scope_hash/assigned_projects trên /api/auth/me, Incident list/cursor và WS ticket/hello; PRIVATE_AUTHZ_GRACE_SECONDS.
- /ws/operations và operations ticket.
- /api/health/live, /api/health/ready.
- /api/admin/system/runtime.
- X-Device-Token cho field device.
- FIELD_DEVICE_AUTH_MODE.
- INCIDENT_WRITE_MODE=off|shadow|atomic, mặc định off ở expand.
- INCIDENT_READ_ENABLED=false.
- INCIDENT_MUTATIONS_ENABLED=false.
- INGEST_QUEUE_PER_DEVICE=256.
- WS_OUTBOX_SIZE=64.
- GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS=15.
- GNSS_RUNTIME_STATE_SAVE_INTERVAL_S=15.
- PRIVATE_AUTHZ_GRACE_SECONDS=300, production hard max 900.
- LONG_TERM_MAX_CONCURRENCY=2.
- LONG_TERM_CACHE_TTL_SECONDS=30.
- THREAT_MAP_ENRICHMENT_ENABLED=false.
- Additive quality, stale, unit_inferred, code, retryable, request_id, project_id và sequence nơi phù hợp.

### 11.2 Contract giữ nguyên

- /, /map, /login, /management, /admin và alias hiện có.
- Existing station/rescue/alert/adjustment/database REST body.
- Public /ws/updates sensor/status/alert behavior.
- Roles guest/viewer/operator/admin.
- Existing export files và Digital Twin input/output.

### 11.3 Compatibility window

- Rescue legacy API sync Incident trong ít nhất một release.
- /ws/admin legacy_admin giữ ít nhất một release và chỉ enforce admin-only sau frontend-first cutover + usage gate 7 ngày sạch; không hard-cut khi client non-admin còn dùng.
- Field device auth chạy audit trước enforce; log coverage nhưng không lộ token.
- Client cũ bỏ qua additive field vẫn hoạt động.
- Migration deploy duy nhất theo expand/off → shadow writer → chụp high-watermark → resumable backfill + semantic parity → atomic writer → reader → mutations; không contract/drop trong V2.

## 12. Migration và backfill

### 12.1 Expand

- [ ] Tạo incident/cleanup/migration-marker tables/indexes, incident_events sequence CACHE 1, SensorData.ingest_id partial unique index và toàn bộ RescueRequest idempotency/upload columns; cột nullable hoặc NOT NULL safe default đúng contract cho dữ liệu cũ.
- [ ] Deploy với write_mode=off, read=false, mutations=false.
- [ ] Readiness chỉ kiểm Alembic revision của Data DB; Auth/Config chưa có revision stream.

### 12.2 Shadow writer và high-watermark

- [ ] Chuyển write_mode=shadow trước khi chụp watermark.
- [ ] Shadow mode:
  - Source Alert/Rescue là write ưu tiên.
  - Incident insert chạy trong savepoint cùng Data session.
  - Incident lỗi không rollback source; ghi metric/event và anti-join reconciler bù.
  - Không phát Incident WS khi case chưa commit.
- [ ] Trước watermark, deploy Rescue image dual-writer schema version 1 độc lập INCIDENT_WRITE_MODE: mọi request mới có ảnh populate writer_version/upload_id/state/storage/hash/size+migrated_at, request không ảnh ghi version=1+NONE+migrated_at; legacy packed message vẫn giữ để client cũ hoạt động.
- [ ] Khi telemetry xác nhận row mới có declared image nhưng image_state=NONE bằng 0, chụp max Alert.id, RescueRequest.id và rescue_image_high_watermark=max RescueRequest.id; truyền ba số vào backfill command/manifest.
- [ ] Source id lớn hơn watermark đã do shadow writer xử lý, không nằm trong batch backfill.

### 12.3 Backfill resumable

- [ ] CLI có --dry-run, --alert-high-watermark, --rescue-high-watermark, --rescue-image-high-watermark và batch-size mặc định 500.
- [ ] Anti-join chỉ chọn candidate source ids theo order/watermark. Mỗi source được xử lý trong transaction ngắn: SELECT source FOR UPDATE, đọc lại state mới nhất, map case/events, rồi INSERT case/event ... ON CONFLICT (source_kind,source_id) DO NOTHING; không dùng state stale từ query candidate.
- [ ] Nếu conflict vì shadow/live writer thắng, load case hiện hữu và reconcile state thay vì coi batch lỗi. Rerun tự resume/idempotent; không giữ row lock cho cả batch 500.
- [ ] Alert:
  - Chỉ backfill nếu Alert vẫn unresolved tại lần đọc FOR UPDATE; Alert vừa resolve trước lock được skip và ghi manifest reason=source_no_longer_eligible.
  - Mỗi Alert legacy map 1:1 sang một IncidentCase qua unique source_kind + source_id; historical duplicate vẫn thành case riêng để không thay đổi nghĩa/API/risk legacy.
  - Dùng cùng normalize_alert_episode_category() và SOURCE_SEVERITY_ORDER của writer cho title, priority mapping, dry-run duplicate metric và backfill; không group bằng raw category.
  - Backfill tuyệt đối không UPDATE/resolve/delete Alert và không nhét deduplicated_source_ids thay cho quan hệ bền. Cleanup/merge historical duplicate, nếu cần, là migration riêng sau V2 có product approval và source-link design.
  - opened_at dùng Alert.timestamp hiện có và payload origin_time_unknown=true vì lịch sử episode cũ không còn.
- [ ] Legacy Rescue image metadata chạy trước Rescue→Incident backfill bằng command riêng:
  - Candidate id<=rescue_image_high_watermark có image_writer_schema_version<1 hoặc image_metadata_migrated_at NULL; image-bearing row còn yêu cầu state=NONE. Mỗi row SELECT FOR UPDATE, re-read và skip nếu dual/live writer đã migrate; row >HWM do version-1 dual-writer chịu trách nhiệm.
  - Chỉ parse packed legacy message bằng parser hiện có và update allowlist writer_version=1/upload_id/image_job_generation/image_state/image_storage_key/hash/size/image_metadata_migrated_at; kể cả no-image NONE cũng set version+migrated_at để rerun không scan lại. Không sửa message/status/time/name/phone hoặc copy path vào Incident event.
  - Không có metadata ảnh giữ NONE. Có metadata thì canonical-resolve dưới RESCUE_UPLOAD_ROOT, reject path traversal/absolute outside root/symlink escape; mở regular file đã resolve, kiểm MIME/size và SHA-256 ngay trước commit.
  - Chọn reuse file vật lý đã có, không move/copy: deterministic UUIDv5 upload_id theo Rescue id, image_storage_key=`legacy/<validated-basename>` internal và scoped route map key này về đúng file gốc trong root. Lấy advisory lock theo canonical storage key, recheck target rồi mới commit READY; file thiếu/invalid→FAILED. Legacy filename route/physical file giữ nguyên trong compatibility window.
  - Command resumable/idempotent, không log packed message/path/PII. Manifest/reconciler yêu cầu writer_version<1 hoặc migrated_at NULL=0 trong HWM, declared legacy image + NONE=0 và READY missing/hash mismatch=0; sau đó atomically set marker REFERENCES_COMPLETE. Cleanup chạy sau marker+refcount; pending/orphan=0 mới set CLEANUP_COMPLETE.
- [ ] Rescue:
  - Backfill tất cả pending/resolved/rejected.
  - Re-read status/handled_at/admin-note metadata dưới row lock ngay trước insert; pending → new, resolved → resolved, rejected → dismissed theo state mới nhất.
  - opened event tại created_at; resolved/dismissed event tại handled_at nếu có, nếu không dùng created_at và payload timestamp_inferred=true.
- [ ] Backfill actor_kind=backfill, không phát WebSocket/audio/siren, không đổi station status.
- [ ] Không copy PII vào case/event; source detail luôn load qua scoped serializer.
- [ ] Incident backfill repository không expose UPDATE/DELETE cho Alert/Rescue; SQL guard fail mọi legacy UPDATE/DELETE. Ngoại lệ duy nhất là image metadata command tách riêng, chỉ được update allowlist cột ảnh additive. Không dùng global checksum bất biến vì live writer được phép đổi source hợp lệ trong lúc chạy.
- [ ] Ghi resumable manifest theo source id gồm state_hash_at_locked_read, action inserted/conflict/skipped, incident id/revision và processed_at; manifest cho phép audit backfill mà không nhầm live mutation là side effect.
- [ ] Reconciliation sau backfill cho cả source <= và > watermark so semantic parity, không chỉ anti-join existence: Alert eligibility/is_resolved, normalized severity, signal/timestamp và Rescue status/handled_at phải khớp case/events mới nhất. Lặp đến gap/state mismatch=0.

### 12.4 Atomic cutover và reader

- [ ] Giữ shadow writer và so source/case semantic parity 24 giờ.
- [ ] Chuyển write_mode=atomic:
  - Alert/Rescue + Incident commit trong cùng Data DB transaction.
  - Case failure rollback source; alert record được persistence queue retry, public Rescue trả 503 retryable.
- [ ] Bật read UI sau atomic parity gate.
- [ ] Bật mutations/legacy back-sync sau read smoke.
- [ ] Không drop cột/bảng legacy trong V2.

### 12.5 Ranh giới ba DB

- Data DB transaction là durable source cho SensorData/Alert/Rescue/Incident.
- Station/Device heartbeat trong Config DB là transaction độc lập, retry/coalesce; lỗi Config không rollback hoặc làm mất critical Data record.
- Scope mutation validate Station/Project ở Config DB và assignee ở Auth DB trước Data row lock; dependency lỗi trả 503 retryable, không mutate.
- User/station bị disable/delete sau commit được giữ bằng snapshot audit; reconciler unassign và chuyển sensor scope_state=LOOKUP_PENDING hoặc Rescue scope_state=UNSCOPED theo source policy, không xóa event.
- Sensor incident có project lookup unavailable vẫn được tạo với station_id, project_id=null và scope_state=LOOKUP_PENDING, admin-only; giữ nguyên source_severity và signal_state=ACTIVE vì lỗi scope không phải lỗi evidence. Scope reconciler điền project/snapshots, đổi scope_state=SCOPED, tăng workflow version/revision và phát audience update sau khi Config DB hồi.

### 12.6 Rollback

- Tắt mutations rồi read UI trước.
- Giữ write_mode=shadow trong rollback để không tạo khoảng trống; nếu bắt buộc off phải ghi watermark mới và chạy reconciliation trước lần bật lại.
- Legacy Alert/Rescue REST/body vẫn là đường vận hành cũ, nhưng Rescue writer schema version 1 là forward-only compatibility floor sau khi image marker đạt REFERENCES_COMPLETE.
- Sau REFERENCES_COMPLETE, rollback chỉ bằng feature flags hoặc bundle vẫn chứa image dual-writer v1; deployment preflight/readiness cấm binary khai báo writer version thấp hơn marker.required_writer_version. DB trigger reject stale packed-only insert kể cả instance cũ không có readiness check.
- Cleanup legacy fail-closed trước mỗi delete: nếu partial index phát hiện writer_version<1/migrated_at NULL thì atomically đưa marker về RUNNING, page và reconcile; không tin marker cũ rồi xóa file.
- Bảng/event V2 giữ nguyên để không mất audit.
- Rollback code không downgrade schema/trigger/marker/dual-writer; schema contraction chỉ là release riêng sau khi không còn compatibility client và cleanup complete.

## 13. Test plan

### 13.1 Landing

- [ ] Step 0–3 ở anchor: frame bounding box/transform khác nhau tối thiểu 12 px về position hoặc effective size.
- [ ] Chapter 1 thực sự full-bleed ở >=1280.
- [ ] Scroll xuôi/ngược/jump/restore đúng step, HUD, caption và pose.
- [ ] No-JS: bốn article visible, normal flow và CTA dùng được.
- [ ] Reduced-motion/mobile/save-data: không story-enhanced, không request Three, không sticky, đủ poster/content.
- [ ] Toggle reduced-motion, Save-Data hoặc breakpoint khi import đang pending không tạo controller stale/leak.
- [ ] CDN 503, WebGL fail, context lost: poster còn, không pageerror.
- [ ] Three chỉ request near-story; offscreen không RAF/render liên tục.
- [ ] Visual step 0–3 light/dark Chromium; Firefox/WebKit geometry/state.
- [ ] 390×844, 844×390, 1024×768, 1440×900, 1920×1080, 2560×1440, 3840×2160 và 200% zoom.
- [ ] Full-bleed overlay đạt contrast 4.5:1 ở light/dark; inactive chapter không bị opacity làm giảm readability.
- [ ] 20 vòng eligibility teardown/re-init không tăng observer/listener/renderer/context.
- [ ] Logo asset mock thật, không broken image.

### 13.2 Map

- [ ] Pure state transition/invariant tests.
- [ ] State migration preserves mode=station|rescue and layers.cors consumers until shim removal.
- [ ] Missing/NaN → — và chart null; real zero giữ 0.
- [ ] Unknown/malformed/DB error → risk UNKNOWN, tuyệt đối không SAFE hoặc auto-stop.
- [ ] Marker add/update/delete và coordinate 0.
- [ ] Network/API error giữ public data và private last-good chỉ trong authz grace + stale/retry; 401/403/unauthorized/grace expiry không giữ private cache mà lock/re-bootstrap/purge trước render.
- [ ] API, sensor WS, operations WS, admin WS, tiles và CDN fail độc lập; derived banner/action đúng từng channel, close/reconnect một socket không tác động socket khác.
- [ ] RTK FIXED và synthetic badge dài ở mọi card width/200% zoom không clip ký tự, overflow hoặc giảm font dưới 12 px; narrow card tự đưa badge xuống hàng.
- [ ] Header light/dark dùng pixel-alpha logo gốc trên wrapper transparent, không xuất hiện plate chữ nhật trắng.
- [ ] Geometry đúng tại biên 900/901 và 1439/1440, thêm 912, 960, 1024, 1280, 1366, 1920, 2560 ở normal/200% zoom và landscape: đúng một rail/drawer/sheet/workspace active, không dual overlay hoặc horizontal overflow, primary action luôn nhìn thấy và mỗi layout transition gọi Leaflet invalidateSize đúng một lần.
- [ ] Mobile three-snap, pointer threshold, keyboard và safe-area; invalidateSize đúng ở reduced-motion/duration=0, transitionend đúng property và transition bị interrupt.
- [ ] Overlay Escape LIFO, focus trap/restore/inert.
- [ ] Guest/viewer/operator/admin feature matrix.
- [ ] /map?incident deep-link, Back/Forward, guest login prompt và out-of-scope 404.
- [ ] 20 lần 3D open/close, hidden/reduced motion và context loss không leak.

### 13.3 Incident

- [ ] Alert episode create/update/escalate/signal_returned/signal_unknown/new episode; system không đổi workflow status.
- [ ] 100 signal heartbeat không tăng workflow version hoặc gây user mutation conflict.
- [ ] Toàn bộ source_severity UNKNOWN/INFO/LOW/MEDIUM/WARNING/HIGH/CRITICAL/EXTREME qua writer + CHECK + priority mapping + backfill + attention sort đúng thứ tự.
- [ ] Rescue create/priority/ack/assign/scope/transition/legacy sync; legacy reopen luôn tới in_progress, clear resolved_at và có note/reason legacy_reopen.
- [ ] Unassigned Rescue → scope project A/station A → operator A thấy, operator B không thấy.
- [ ] Legacy pending/resolved/rejected/reopen giữ nguyên request/response và tạo audit đúng, kể cả UNTRIAGED override.
- [ ] State machine reject transition sai.
- [ ] expected_version conflict 409 trả current case.
- [ ] Idempotency-Key replay tuần tự và concurrent cho acknowledge/note không event trùng; same key khác endpoint/body trả 409 IDEMPOTENCY_KEY_REUSED.
- [ ] Scope mutation tạo assigned + scope_changed cùng mutation_request_id, sequence_from/to đầy đủ và replay không unique conflict.
- [ ] Public Rescue concurrent/lost-response replay cùng key tạo đúng một Rescue + Incident + upload_id/final image; PENDING đã persist planned key/hash/size. Kill sau rename trước READY và DELETE PENDING recovery dùng đúng key, không expose URL-missing/orphan/duplicate; khác payload/ảnh trả 409.
- [ ] Image promoter ở write_mode off, shadow case success, shadow case savepoint fail và atomic: Rescue READY/FAILED luôn commit; Incident event/revision chỉ khi case tồn tại, backfill/reconciler đọc source state đúng khi case được bù sau.
- [ ] Legacy DELETE với unmigrated packed image và image NONE/PENDING/READY/FAILED, shared file và delete↔promoter race: validator derive key an toàn, generation/row lock ngăn resurrection, cleanup outbox sống qua crash, concurrent enqueue storage_key NULL chỉ còn một job theo upload_id+generation, final chỉ xóa khi marker REFERENCES_COMPLETE + reference count=0 và sweeper không ra ngoài root.
- [ ] Cleanup lease crash/fence: kill A sau claim RUNNING và sau delete/trước DONE; lease 60 giây được B reclaim với generation mới, file-absent coi success. A resume CAS owner/generation=0 không được đổi DONE/FAILED/defer của B; job không kẹt hoặc xóa reference sống.
- [ ] Note concurrency cấp sequence duy nhất; multi-event transaction có sequence_from/to đầy đủ.
- [ ] Operator scope project A/B; unassigned Rescue admin-only.
- [ ] REST/WS/Map DOM/marker tuân field-level PII matrix; guest/viewer không lộ precise Rescue/phone/message/image/note; mọi PII detail/image trả private,no-store, service worker không cache và filename route cũ không mở rộng.
- [ ] Scope A→B và A→null khi connected/disconnected phát tombstone cho A; operator→viewer và admin/operator project revocation purge PII, image object URL, coordinate, marker và memory/persisted cache trước render.
- [ ] Offline operator có scope A+B bị thu hồi riêng A rồi reconnect vẫn HTTP 200: authz_scope_hash đổi, cache/PII/marker/Pi/image A bị purge trước render trong khi non-PII B hợp lệ được giữ.
- [ ] Cold-start/reload hoàn toàn offline sau revoke không hydrate private cache; background/sleep/BFCache vượt grace không flash private DOM khi pageshow. Test server config 60/120/900, no-store auth response, watchdog cả khi panel đóng, purge/object-URL revoke/mutation lock đúng response grace; treo /api/auth/me xuyên deadline, throttle timer rồi foreground vẫn inert/purge trước private frame và request pending không gia hạn quyền. Ghi nhận không thể revoke tức thời trước grace khi không network.
- [ ] Snapshot race injection ở trước watermark, giữa watermark/list và giữa list/WS không miss case; WS event 102 đến trước cursor 101 vẫn apply 101→102 đúng thứ tự, không duplicate.
- [ ] Global event commit-order trên ít nhất hai physical pooled connections: readiness assert sequence CACHE 1; T1 giữ transaction trước event insert, T2 concurrent live/mutation/backfill phải đợi advisory lock. T1 commit/rollback tạo ID gap và backfill-vs-live đều không có lower event id commit sau cursor advance; CACHE>1 fixture phải fail readiness/test.
- [ ] Global event_id gap do project khác không trigger false packet-loss; disconnect → tạo unseen case → reconnect/global cursor/poll <=15 giây phát hiện đúng.
- [ ] Cursor page có >500 visible event xen hàng nghìn raw event project khác: mỗi page scan tối đa 500 raw row, next_event_id không nhảy qua row chưa scan và cuối cùng nhận đủ visible event.
- [ ] Producer append liên tục trong multi-page catch-up: catchup_upper_event_id giữ cố định, chain hội tụ rồi drain buffer >upper/chuyển live; client buffer không vượt 256. Overflow path re-bootstrap bounded, không render stale private state.
- [ ] List page 1 dưới scope A+B rồi revoke A: cursor signed cũ trả CURSOR_AUTHZ_CHANGED; client reset list/snapshot/catch-up và paginate B đầy đủ, không skip/duplicate.
- [ ] Cursor list stable tie-break, realtime reorder không skip/duplicate; timeline before/after sequence.
- [ ] Search station/project chỉ dùng snapshot local; Config unavailable không silently trả partial live lookup và LOOKUP_PENDING vẫn tìm được bằng reference/title.
- [ ] DB failure không để source có mà case thiếu sau retry/reconciliation.
- [ ] normalize_alert_episode_category cho tilt_warning/tilt_critical và allowlist khác giống hệt writer/lock/backfill.
- [ ] Shadow writer, watermark, Alert resolve/escalate và Rescue status đổi đúng giữa candidate SELECT/source lock, backfill dry-run/resume hai lần và semantic reconciliation không duplicate/gap; SQL guard chứng minh backfill không UPDATE/DELETE legacy, manifest phân biệt đúng live change.
- [ ] Legacy Rescue image dual-writer/HWM migration: live writer race khiến command skip non-NONE/migrated; valid shared in-root file→READY legacy/key/hash, no image→NONE+migrated, missing/traversal/absolute outside/symlink escape→FAILED; crash/rerun giữ migrated_at NULL/declared+NONE/READY-missing/orphan=0 và PENDING detail hội tụ qua event/poll.
- [ ] Hai legacy row cùng physical file: migrate A rồi DELETE A khi B còn NONE phải defer cleanup và giữ file; migrate B + marker REFERENCES_COMPLETE vẫn giữ do refcount, chỉ DELETE B cuối mới xóa rồi marker mới tới CLEANUP_COMPLETE. Advisory key lock/marker survive concurrent worker/crash.
- [ ] Mixed-version linearization: T1 writer v0 INSERT dừng sau trigger/shared marker lock trước commit; T2 promote marker FOR UPDATE phải đợi. Sau T1 commit, global partial scan thấy row và không mở cleanup; migrate xong mới REFERENCES_COMPLETE. Writer v0 mới bị reject.
- [ ] DELETE lock-order isolation: giữ promoter ở marker FOR UPDATE, chạy V1 DELETE và một Incident writer không liên quan đồng thời. DELETE phải chờ marker trước khi lấy global event-order lock, writer không liên quan vẫn commit; sau khi nhả promoter không deadlock và source/event/cleanup outbox của DELETE cùng commit hoặc cùng rollback.
- [ ] Stale v0 DELETE sau fence thiếu SET LOCAL/outbox bị DB trigger reject nên endpoint cũ không tới unlink sau commit. Nếu fixture bypass tạo row version0/migrated NULL, cleanup atomically revert marker RUNNING, defer file delete/reconcile rồi chỉ mở lại khi references complete.

### 13.4 Management

- [ ] Boot từng role và assert không gọi forbidden endpoint.
- [ ] Map/Management đang mở khi operator→viewer hoặc mất project: applyAuthzSession abort loader, dispose forbidden manager/socket/timer, đóng panel/tab cấm, purge data rồi chuyển destination an toàn trước render; không request/reconnect endpoint cấm.
- [ ] Desktop/mobile nav parity.
- [ ] Rail/bottom-nav geometry ở 767, 768, 912, 1024, 1279, 1280 và 200% zoom.
- [ ] switchTab + Back/Forward + filter/scroll/inspector restore.
- [ ] Hostile payload render literal, không injected node/handler.
- [ ] Wizard draft secret-leak test: nhập sentinel vào mọi MQTT/network/AICaster/NTRIP/token/license/private-key field rồi autosave/reload, role downgrade, scope revoke và logout; localStorage, sessionStorage, IndexedDB, Cache API/service-worker cache không chứa sentinel, non-secret draft chỉ restore đúng namespace/TTL và secret luôn phải nhập lại.
- [ ] Latest request wins khi đổi tab/filter/station nhanh.
- [ ] Incident drawer/sheet Escape/focus/restore.
- [ ] 409 refresh giữ draft/focus và cho retry với version mới.
- [ ] Pi viewer/operator/admin load/action/project-scope đúng: operator A không xem/claim pool null hoặc thiết bị project B, chỉ move giữa station project A; initial assignment/unassign pool/Pi Point→Center cross-project bị chặn đúng contract.
- [ ] Full priority matrix: UNTRIAGED first triage và bằng/tăng LOW<NORMAL<HIGH<URGENT không bắt note; chỉ rank giảm bắt note, chuyển ngược UNTRIAGED bị reject. Resolve/dismiss/reopen vẫn bắt note; inline error focus đúng, 409 giữ draft và retry được.
- [ ] 20 Map↔Management cycles không tăng sensor/operations/admin socket, reconnect timer, listener hoặc AbortController.
- [ ] Light/dark/reduced/keyboard/200% zoom.

### 13.5 Backend

- [ ] MQTT đến trước processor init.
- [ ] Origin/checkpoint load/save fail rồi recovery; save failure thực sự retry đến commit, không clear dirty state sau lần lỗi đầu.
- [ ] Tạo persistent shifted cluster quarantine giống production log, restart graceful và hard-kill: locked origin/last trusted displacement/guard restore đúng, Alert+Incident vẫn open, không auto-baseline/auto-safe; hard-kill chỉ mất tối đa checkpoint RPO công bố.
- [ ] Checkpoint đúng schema/origin nhưng saved_at cũ hơn newest unresolved GNSS guard Alert hoặc quá 15 giây trả STALE/STATE_UNAVAILABLE, giữ case open; shutdown force-save timeout cũng không restore thành safe.
- [ ] Checkpoint origin identity mismatch/corrupt/missing trả STATE_UNAVAILABLE/UNKNOWN, không nhận fix đầu làm origin; reference-change verified/action audited mới cho reacquire.
- [ ] Missing Water/Rain/IMU không tạo fresh row hoặc zero.
- [ ] DB mất 30 giây rồi hồi: critical alert không mất, batch drain đủ.
- [ ] Batch SensorData trộn ingest_id mới/đã tồn tại/null sau commit-unknown: ON CONFLICT chỉ dedupe identity row, null vẫn insert at-least-once, queue drain và metric inserted/deduped/null_identity đúng; không tạo Alert/Incident lặp.
- [ ] Alert summary DB lỗi không phát LOW/tắt còi.
- [ ] Concurrent worker cùng station/category chỉ tạo một unresolved Alert episode/Incident.
- [ ] Per-device ordering và 100 device ×1 Hz soak.
- [ ] Queue overflow normal có metric; reliable overflow fail-closed.
- [ ] Slow WS client không giữ client khỏe.
- [ ] RBAC matrix cho siren/device/adjustment/simulation/database/rescue/incident; simulation create/list/get/stop/rerun/export và button/workspace visibility đều admin-only qua MANAGE_SIMULATIONS, không đổi physics/payload.
- [ ] Config/Auth dependency lỗi trước scope/assign trả 503 và không mutate Data DB; Config heartbeat lỗi không mất Data critical record.
- [ ] Field token issue/audit/enforce/spoof/revoke/rotate/grace; bearer token không được tuyên bố chống replay.
- [ ] WebSocket ticket jti replay bị từ chối trong cùng boot; issue+consume rồi recreate process/registry với boot_epoch mới thì ticket cũ vẫn close 4403 dù TTL/signing secret còn hiệu lực, còn ticket mới hoạt động. Ticket chưa consume trước restart cũng bị reject fail-closed.
- [ ] /ws/admin frontend-first compatibility: legacy non-admin còn hoạt động trong window, metric usage đúng; private event thiếu/lookup lỗi scope chỉ tới admin; enforce admin-only chỉ sau gate 7 ngày và explicit channel client đã cutover.
- [ ] Long-term bound, concurrency, cache và fixed query count.
- [ ] 20 start/stop không leak task/thread/client/connection.
- [ ] Graceful shutdown hoàn tất trong 15 giây ở tải chuẩn.

### 13.6 Release quality

- [ ] git diff --check sạch.
- [ ] Build manifest chứa đúng shells/assets.
- [ ] Không sửa dist thủ công.
- [ ] Source HTML canonical/OG/Twitter/JSON-LD parse đúng; robots/sitemap chỉ index `/` và `/map`; private/non-production trả noindex ở HTML/header.
- [ ] Chromium, Firefox, WebKit: console.error/pageerror bằng 0 trong production smoke.
- [ ] Accessibility scan + keyboard-only + 200% zoom.
- [ ] Lighthouse/CWV và bundle gates.
- [ ] Security: secret/PII trong log bằng 0.
- [ ] Critical queue drop bằng 0.

## 14. Thứ tự commit và rollout

### Phase 0 — Baseline và contract

1. Cập nhật design system V2.
2. Thêm resource counters/test harness.
3. Khóa API/DB Incident bằng tests trước implementation.

Gate: baseline reproducible và test hiện tại xanh.

### Phase 1 — Safety P0

1. Processor initialize/close.
2. Measurement/status split.
3. Alert fail-safe.
4. GNSS guard restore luôn reconcile legacy Alert; Incident chỉ conditional khi schema/write mode sẵn sàng.
5. Buffer retry/drain.
6. Auth/project scope lỗ hổng nghiêm trọng.

Gate: không fake fresh measurement, không lost batch trong fault test.

### Phase 2 — Incident backend

1. Expand migration.
2. Shadow Incident writer + Rescue image dual-writer, telemetry gate rồi chụp Alert/Rescue/image high-watermarks.
3. Chạy legacy Rescue image metadata allowlist migration với row lock/manifest/file parity.
4. Dry-run/backfill/reconciliation đến semantic parity, với row-lock reread, manifest và SQL no-legacy-mutation guard.
5. Chuyển atomic writer.
6. Incident service/workflow, REST + operations WS.
7. Bật reader rồi mutations sau RBAC/privacy tests.

Gate: source/case semantic parity 24 giờ ở staging, rescue image marker CLEANUP_COMPLETE/backlog-orphan=0, public WS không PII, snapshot/cursor race và scope tombstone/authz purge test xanh.

### Phase 3 — Storytelling V2

1. Semantic normal-flow chapters.
2. Morphing stage + CSS poster/HUD.
3. Piecewise Three scene.
4. Lifecycle/fallback/test snapshots.

Gate: frame thực sự đổi pose; no-JS/reduced/mobile đầy đủ.

### Phase 4 — Map correctness và state

1. finite/null + marker reconciliation.
2. mapUiState reducer/renderer.
3. 3-column/drawer/sheet layout.
4. Incident inbox/detail.
5. Overlay/lifecycle/chart polish.

Gate: role/data/state/layout matrix xanh; ba socket controller và unauthorized purge độc lập, không leak.

### Phase 5 — Management

1. Role-first bootstrap.
2. One nav + history.
3. Unified Incident tab.
4. Request guards/XSS/dispose.
5. Existing workflow regression.

Gate: toàn bộ workflow cũ + Incident xanh.

### Phase 6 — Throughput và observability

1. Per-device queues.
2. WS outbox.
3. API query/compute optimization.
4. readiness/runtime diagnostics/logging.
5. Device token audit.

Gate: soak test, queue/backlog/latency within thresholds.

### Phase 7 — Enforce và release

1. Field token coverage 100% trong 7 ngày.
2. Enforce device auth.
3. Production smoke/visual/Lighthouse.
4. Search Console/SEO smoke giữ nguyên.
5. Tile license gate được chủ dự án xác nhận.
6. /ws/admin admin-only chỉ enforce sau telemetry legacy non-admin bằng 0 liên tục 7 ngày.

## 15. Monitoring sau deploy

Theo dõi dashboard/log trong ít nhất 7 ngày:

- Processor init failures và checkpoint age/error.
- Queue depth, oldest age, coalesced/drop count.
- Flush retry và critical record parity.
- MQTT reconnect/last-message theo broker.
- WS clients, backlog, close 1013 và reconnect.
- Incident source/case existence + state parity, time-to-ack, priority UNTRIAGED age, unresolved age.
- Incident cursor lag, tombstone/purge count, idempotent replay/conflict và scope LOOKUP_PENDING age.
- 401/403/429 theo route, không ghi username/PII.
- Authz revalidation age/grace lock/purge và CURSOR_AUTHZ_CHANGED count; không log project list/user PII.
- /ws/admin legacy_admin connection theo role/client version và Rescue upload PENDING age/FAILED/staging orphan, cleanup lease expiry/oldest/FAILED và recovery count.
- Event-loop lag, DB pool wait, endpoint p95/p99.
- Frontend reconnect, mutation conflict 409, pageerror và failed asset.

Alert vận hành đề xuất:

- Critical record drop >0: page ngay.
- Incident source/case existence hoặc semantic state parity lệch >0 sau 60 giây: page.
- Checkpoint bắt buộc chưa persist >60 giây: readiness fail + page.
- Flush oldest age >30 giây: warning; >120 giây: page.
- MQTT last message quá threshold theo station: incident sensor status, không giả zero.
- WS close 1013 tăng bất thường: warning.
- Rescue priority UNTRIAGED >5 phút: operational warning.

## 16. Definition of Done

V2 chỉ được coi là hoàn tất khi:

- Story stage biến hình rõ ràng qua bốn chương; card lớn không còn đứng yên xuyên toàn hành trình.
- No-JS, mobile, reduced-motion, save-data, CDN/WebGL failure vẫn có đủ nội dung và CTA.
- Map có một nguồn state và đúng layout desktop/tablet/mobile.
- Incident từ Alert/Rescue tách source severity/signal/priority/workflow, có timeline, acknowledge, scope, assignment và audit đầy đủ.
- Idempotency, snapshot/catch-up và scope tombstone không tạo trùng, không mất event và không giữ PII sau thu hồi quyền.
- Management không gọi endpoint sai quyền và mọi nav/history/focus đồng bộ.
- Backend không biến missing/fault thành measurement mới, không trả LOW do DB exception và không mất batch trong fault window đã test.
- Queue/outbox/lifecycle đều bounded và quan sát được.
- Contract cũ, export và Digital Twin physics vẫn tương thích.
- Backfill không phát UPDATE/DELETE Alert/Rescue legacy; live writer vẫn được đổi source hợp lệ và manifest/reconciler chứng minh semantic parity.
- Toàn bộ gate test, performance, accessibility, privacy và rollout phía trên đều xanh.
