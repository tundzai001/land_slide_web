import { renderLandingTemplate } from './templates/landing-template.js';
import { setupHeader, setupMetrics } from './landing-common.js';

const root = document.getElementById('landing-root');
const logo = document.querySelector('link[rel="icon"]')?.getAttribute('href');
root.innerHTML = renderLandingTemplate(logo);
setupHeader();
setupMetrics();
