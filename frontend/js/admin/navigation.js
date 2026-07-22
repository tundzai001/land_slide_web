(() => {
class AdminNavigationFeature extends window.AdminManager {
    // =========================================================================
    // NAVIGATION SYSTEM
    // =========================================================================

    resetNavigation() {
        this.currentView = 'projects';
        this.currentProjectId = null;
        this.navigationStack = [];
        this.updateBreadcrumb();
        this.updateBackButton();
    }

    navigateBack() {
        if (this.navigationStack.length === 0) return;

        this.navigationStack.pop();

        this.resetNavigation();
        this.loadProjects();

        this.updateBreadcrumb();
        this.updateBackButton();
    }

    updateBreadcrumb() {
        const breadcrumb = document.getElementById('project-breadcrumb');
        if (!breadcrumb) return;

        let html = '<li class="breadcrumb-item"><a href="#" onclick="window.adminManager.resetNavigation(); window.adminManager.loadProjects();">Dự án</a></li>';

        if (this.currentView === 'stations') {
            const projectName = this.getProjectName(this.currentProjectId);
            html += `<li class="breadcrumb-item active">${projectName}</li>`;
        }

        breadcrumb.innerHTML = html;
    }

    updateBackButton() {
        const backBtn = document.getElementById('btn-back-nav');
        if (backBtn) {
            backBtn.style.display = this.navigationStack.length > 0 ? 'inline-block' : 'none';
        }
    }

    getProjectName(projectId) {
        const project = this.projectsData?.find(p => p.id === projectId);
        return project?.name || 'Dự án';
    }

}
window.applyAdminFeature(AdminNavigationFeature);
})();
