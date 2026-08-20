(() => {
const { useEffect, useRef, useState } = React;

const ICONS = {
  arrow: <path d="m7 4 6 6-6 6" />,
  check: <path d="M5 13l4 4L19 7" />,
  clock: <><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></>,
  pulse: <path d="M4 12h3l2-5 4 10 2-5h5" />,
  alert: <><circle cx="12" cy="12" r="8" /><path d="M12 8v5M12 16v.1" /></>,
  close: <path d="M7 7l10 10M17 7 7 17" />,
  eye: <><path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="2.5"/></>,
  layers: <><path d="m12 3 9 5-9 5-9-5Z"/><path d="m3 12 9 5 9-5M3 16l9 5 9-5"/></>,
  shield: <><path d="M12 3 4 7v5c0 5 3.4 8 8 9 4.6-1 8-4 8-9V7Z" /><path d="m9 12 2 2 4-4" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 15.2A8 8 0 0 1 8.8 4 8.4 8.4 0 1 0 20 15.2Z" />,
};

function Icon({ name }) {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">{ICONS[name]}</svg>;
}

function Brand({ footer = false }) {
  return <a className={`brand${footer ? ' footer-brand' : ''}`} href="/" aria-label="Landslide Monitor — Trang chủ">
    <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 40 40" fill="none"><path d="M7 28.5 16.2 13l5.2 8.2 4.2-6.1L33 28.5"/><path d="M7 32h26"/><circle cx="27" cy="10" r="2.5"/></svg></span>
    <span className="brand-copy"><strong>Landslide</strong><small>Monitor</small></span>
  </a>;
}

function Header({ authLink }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'light');
  const [scrolled, setScrolled] = useState(() => scrollY > 12);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('theme', theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#07121d' : '#f7faf9');
  }, [theme]);
  useEffect(() => {
    const onScroll = () => setScrolled(scrollY > 12);
    addEventListener('scroll', onScroll, { passive: true });
    return () => removeEventListener('scroll', onScroll);
  }, []);
  useEffect(() => {
    document.body.style.overflow = menuOpen ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [menuOpen]);

  return <>
    <header className={`site-header${scrolled ? ' scrolled' : ''}`}>
      <div className="header-inner">
        <Brand />
        <nav className="desktop-nav" aria-label="Điều hướng chính"><a href="#story">Câu chuyện</a><a href="#network">Mạng trực tiếp</a><a href="#response">Hành động</a></nav>
        <div className="header-actions">
          <button className="icon-button" type="button" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')} aria-label={theme === 'dark' ? 'Chuyển giao diện sáng' : 'Chuyển giao diện tối'}><Icon name={theme === 'dark' ? 'sun' : 'moon'} /></button>
          <a className="button button-ghost login-link" href={authLink.href}>{authLink.label}</a>
          <a className="button button-primary header-cta" href="/map">Mở bản đồ</a>
          <button className="menu-button" type="button" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen} aria-controls="mobile-menu"><span></span><span></span><span></span><span className="sr-only">Mở trình đơn</span></button>
        </div>
      </div>
    </header>
    <div className="mobile-menu" id="mobile-menu" hidden={!menuOpen}><nav aria-label="Điều hướng di động" onClick={() => setMenuOpen(false)}><a href="#story">Câu chuyện</a><a href="#network">Mạng trực tiếp</a><a href="#response">Hành động</a><a href="/map">Mở bản đồ realtime</a><a href={authLink.href}>{authLink.label}</a></nav></div>
  </>;
}

function LivePreview({ compact = false }) {
  return <div className={`live-preview${compact ? ' compact' : ''}`} aria-label="Mô phỏng khu vực quan trắc đang hoạt động">
    <div className="preview-bar"><span><i></i><i></i><i></i></span><b>VÙNG QUAN TRẮC · SIN QUYỀN</b><em><i></i> ĐANG THEO DÕI</em></div>
    <div className="preview-map" aria-hidden="true">
      <div className="contour contour-one"></div><div className="contour contour-two"></div><div className="contour contour-three"></div>
      <svg className="network-lines" viewBox="0 0 640 420" preserveAspectRatio="none"><path d="M72 330 188 116 344 246 496 80 568 316"/><path d="M188 116 496 80M72 330 344 246 568 316"/></svg>
      <span className="map-node node-one"></span><span className="map-node node-two"></span><span className="map-node node-three alert-node"></span><span className="map-node node-four"></span><span className="map-node node-five"></span>
      <div className="signal-card"><small>DỊCH CHUYỂN GHI NHẬN</small><strong>0.1259 <span>mm/s</span></strong><p><i></i> Trong ngưỡng ổn định</p></div>
      <div className="preview-caption"><span>59 điểm quan trắc</span><strong>Toàn khu vực trong một góc nhìn</strong></div>
    </div>
  </div>;
}

function Hero() {
  return <section className="hero" aria-labelledby="hero-title">
    <div className="hero-copy reveal"><div className="eyebrow"><span className="live-dot"></span> An toàn bắt đầu từ việc thấy sớm</div><h1 id="hero-title">Nhìn thấy chuyển động.<br/><em>Trước khi thành rủi ro.</em></h1><p className="hero-lead">Mỗi thay đổi rất nhỏ ngoài hiện trường được biến thành một tín hiệu dễ hiểu, để đội vận hành có thêm thời gian đưa ra quyết định đúng.</p><div className="hero-actions"><a className="button button-primary button-large" href="/map">Xem khu vực đang quan trắc <Icon name="arrow" /></a><a className="button button-ghost button-large" href="#story">Theo dõi hành trình tín hiệu</a></div><div className="outcome-strip"><span>Phát hiện sớm</span><i></i><span>Đánh giá rõ</span><i></i><span>Phản ứng kịp thời</span></div></div>
    <div className="hero-visual reveal"><div className="visual-glow"></div><LivePreview/><div className="floating-status"><span className="status-icon"><Icon name="check" /></span><span><small>Trạng thái hiện tại</small><strong>Khu vực ổn định</strong></span></div></div>
  </section>;
}

const STORY_STEPS = [
  ['01','eye','Một thay đổi rất nhỏ xuất hiện','Một điểm dịch chuyển chỉ vài milimét có thể là khởi đầu của một diễn biến lớn. Hệ thống ghi nhận nó ngay khi vừa xuất hiện.'],
  ['02','layers','Tín hiệu được đặt vào đúng bối cảnh','Chuyển động, mưa, mực nước và độ nghiêng được nhìn trên cùng một dòng thời gian — không còn những mảnh dữ liệu rời rạc.'],
  ['03','pulse','Bất thường trở nên rõ ràng','Những thay đổi đáng chú ý được làm nổi bật khỏi nhiễu nền, giúp đội vận hành tập trung đúng nơi cần kiểm tra.'],
  ['04','shield','Một quyết định được đưa ra sớm hơn','Bản đồ, cảnh báo và thông tin hiện trường gặp nhau trong một luồng hành động rõ ràng — trước khi rủi ro lan rộng.'],
];

function StoryScene() {
  return <div className="story-scene" aria-hidden="true">
    <div className="scene-grid"></div><div className="scene-ridge ridge-back"></div><div className="scene-ridge ridge-front"></div>
    <svg className="scene-path" viewBox="0 0 720 520"><path d="M76 390C190 330 225 170 358 188s142 184 282 108"/></svg>
    <span className="scene-node scene-node-a"></span><span className="scene-node scene-node-b"></span><span className="scene-node scene-node-c"></span>
    <div className="scene-reading reading-motion"><small>CHUYỂN ĐỘNG</small><strong>+2.4 mm</strong></div>
    <div className="scene-reading reading-context"><small>BỐI CẢNH HIỆN TRƯỜNG</small><span>Mưa tăng · Mực nước ổn định</span></div>
    <div className="scene-alert"><span><Icon name="alert" /></span><div><small>TÍN HIỆU CẦN CHÚ Ý</small><strong>Đang xác minh tại hiện trường</strong></div></div>
    <div className="scene-response"><span><Icon name="check" /></span><div><small>ĐỘI VẬN HÀNH</small><strong>Đã tiếp nhận · 10:42</strong></div></div>
    <div className="scene-status"><span>LIVE STORY</span><b><i></i> Dòng dữ liệu đang chạy</b></div>
  </div>;
}

function Story() {
  const sectionRef = useRef(null);
  useEffect(() => {
    const section = sectionRef.current;
    if (!section || matchMedia('(prefers-reduced-motion: reduce)').matches) return undefined;
    let frame = 0;
    const update = () => {
      frame = 0;
      const rect = section.getBoundingClientRect();
      const range = Math.max(1, section.offsetHeight - innerHeight);
      const progress = Math.max(0, Math.min(1, -rect.top / range));
      section.style.setProperty('--story-progress', progress.toFixed(4));
      section.dataset.step = String(Math.min(3, Math.floor(progress * 4)));
    };
    const queue = () => { if (!frame) frame = requestAnimationFrame(update); };
    addEventListener('scroll', queue, { passive: true });
    addEventListener('resize', queue);
    update();
    return () => { removeEventListener('scroll', queue); removeEventListener('resize', queue); if (frame) cancelAnimationFrame(frame); };
  }, []);

  return <section className="story" id="story" ref={sectionRef} data-step="0" aria-labelledby="story-title">
    <div className="story-shell">
      <div className="story-copy"><div className="story-heading"><span className="overline">MỘT TÍN HIỆU. MỘT HÀNH TRÌNH.</span><h2 id="story-title">Từ dịch chuyển nhỏ<br/>đến hành động rõ ràng.</h2></div>{STORY_STEPS.map(([number,icon,title,copy]) => <article key={number}><span>{number}</span><div className="story-icon"><Icon name={icon}/></div><div><h3>{title}</h3><p>{copy}</p></div></article>)}</div>
      <div className="story-stage"><StoryScene/><div className="story-progress"><span></span></div></div>
    </div>
  </section>;
}

const METRICS = [['total','Toàn mạng','điểm được quản lý'],['online','Đang trực tuyến','đang gửi dữ liệu'],['stale','Cần chú ý','luồng dữ liệu chậm'],['offline','Ngoại tuyến','chưa có tín hiệu']];

function NetworkSummary({ summary, updated, state, onRetry }) {
  return <section className="network-section" id="network" aria-labelledby="network-title"><div className="section-intro reveal"><div><span className="overline">BỨC TRANH ĐANG DIỄN RA</span><h2 id="network-title">Không phải một bản báo cáo.<br/>Là trạng thái ngay lúc này.</h2></div><div className={`updated updated-${state}`} role="status" aria-live="polite"><span></span><span>{updated}</span>{state === 'error' && <button type="button" onClick={onRetry}>Thử lại</button>}</div></div><div className="metric-grid" aria-live="polite" aria-busy={state === 'loading'}>{METRICS.map(([key,label,copy]) => <article className={`metric-card metric-${key} reveal`} key={key}><span>{label}</span><strong id={`stations-${key}`}>{summary[key]}</strong><p>{copy}</p></article>)}</div></section>;
}

function FinalCta({ authLink }) {
  return <section className="final-cta reveal" id="response" aria-labelledby="cta-title"><div className="cta-grid"></div><span className="overline">TỪ NHẬN BIẾT ĐẾN HÀNH ĐỘNG</span><h2 id="cta-title">Thấy toàn cảnh.<br/>Đi đúng bước tiếp theo.</h2><p>Mở bản đồ vận hành để xem từng khu vực, từng điểm quan trắc và trạng thái mới nhất.</p><div className="hero-actions"><a className="button button-primary button-large" href="/map">Mở bản đồ realtime <Icon name="arrow" /></a><a className="button button-ghost button-large" href={authLink.href}>{authLink.label}</a></div></section>;
}

function App() {
  const [summary, setSummary] = useState({ total:'—', online:'—', stale:'—', offline:'—' });
  const [updated, setUpdated] = useState('Đang cập nhật dữ liệu…');
  const [summaryState, setSummaryState] = useState('loading');
  const [summaryRequest, setSummaryRequest] = useState(0);
  const [authLink, setAuthLink] = useState({ href:'/login?return_to=/management', label:'Đăng nhập' });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const response = await fetch('/api/public/dashboard-summary', { signal: AbortSignal.timeout(10000) });
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (!active) return;
        const format = new Intl.NumberFormat('vi-VN');
        setSummary(Object.fromEntries(['total','online','stale','offline'].map(key => [key, format.format(data.stations?.[key] || 0)])));
        setUpdated(`Cập nhật ${new Intl.DateTimeFormat('vi-VN',{dateStyle:'short',timeStyle:'short'}).format(new Date(data.updated_at))}`);
        setSummaryState('ready');
      } catch (_) { if (active) { setUpdated('Mất kết nối dữ liệu trực tiếp'); setSummaryState('error'); } }
    })();
    window.authSession?.inspect?.().then(session => {
      if (!active || session?.status !== 'authenticated') return;
      const canManage = ['admin','operator'].includes(session.user?.role);
      setAuthLink({ href: canManage ? '/management' : '/map', label: canManage ? 'Quản trị hệ thống' : 'Mở bản đồ' });
    });
    return () => { active = false; };
  }, [summaryRequest]);

  useEffect(() => {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) {
      document.querySelectorAll('.reveal').forEach(element => element.classList.add('is-visible'));
      return undefined;
    }
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) { entry.target.classList.add('is-visible'); observer.unobserve(entry.target); }
    }), { threshold: .12, rootMargin: '0px 0px -40px' });
    document.querySelectorAll('.reveal').forEach(element => observer.observe(element));
    return () => observer.disconnect();
  }, []);

  return <><a className="skip-link" href="#main">Bỏ qua đến nội dung chính</a><Header authLink={authLink}/><main id="main"><Hero/><Story/><NetworkSummary summary={summary} updated={updated} state={summaryState} onRetry={() => { setSummaryState('loading'); setUpdated('Đang cập nhật dữ liệu…'); setSummaryRequest(value => value + 1); }}/><FinalCta authLink={authLink}/></main><footer className="site-footer"><Brand footer/><p>Quan trắc liên tục để hành động sớm hơn.</p><span>© 2026 Aitogy</span></footer></>;
}

ReactDOM.createRoot(document.getElementById('landing-root')).render(<App />);
})();
