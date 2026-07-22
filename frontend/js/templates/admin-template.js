window.LegacyTemplates ||= {};
window.LegacyTemplates.admin = ['shell', 'gnss-project-modals', 'station-wizard-shell', 'station-basic',
    'station-connectivity', 'station-alerts', 'station-storage', 'data-modals-nav']
    .map((key) => window.LegacyTemplateParts[key])
    .join('');
