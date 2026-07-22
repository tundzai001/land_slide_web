window.LegacyTemplates ||= {};
window.LegacyTemplates.map = ['shell', 'station-panels', 'analysis', 'rescue']
    .map((key) => window.LegacyTemplateParts[key])
    .join('');
