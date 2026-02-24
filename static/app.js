// Check authentication status and update nav
document.addEventListener('DOMContentLoaded', function() {
    updateNav();
});

async function updateNav() {
    const token = localStorage.getItem('token');
    const loginLink = document.getElementById('loginLink');
    const registerLink = document.getElementById('registerLink');
    const logoutLink = document.getElementById('logoutLink');
    const dashboardLink = document.getElementById('dashboardLink');
    const adminLink = document.getElementById('adminLink');

    if (token) {
        if (loginLink) loginLink.style.display = 'none';
        if (registerLink) registerLink.style.display = 'none';
        if (logoutLink) logoutLink.style.display = 'inline';

        // Determine link based on role
        try {
            const res = await fetch('/auth/me', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const user = await res.json();
                if (user.role === 'admin') {
                    if (adminLink) adminLink.style.display = 'inline';
                    if (dashboardLink) dashboardLink.style.display = 'none';
                } else {
                    if (dashboardLink) dashboardLink.style.display = 'inline';
                    if (adminLink) adminLink.style.display = 'none';
                }
            } else {
                // Token invalid
                localStorage.removeItem('token');
                updateNavLoggedOut();
            }
        } catch (_) {
            if (dashboardLink) dashboardLink.style.display = 'inline';
        }
    } else {
        updateNavLoggedOut();
    }
}

function updateNavLoggedOut() {
    const loginLink = document.getElementById('loginLink');
    const registerLink = document.getElementById('registerLink');
    const logoutLink = document.getElementById('logoutLink');
    const dashboardLink = document.getElementById('dashboardLink');
    const adminLink = document.getElementById('adminLink');

    if (loginLink) loginLink.style.display = 'inline';
    if (registerLink) registerLink.style.display = 'inline';
    if (logoutLink) logoutLink.style.display = 'none';
    if (dashboardLink) dashboardLink.style.display = 'none';
    if (adminLink) adminLink.style.display = 'none';
}

function logout() {
    localStorage.removeItem('token');
    window.location.href = '/';
}

// API helper
async function apiRequest(endpoint, options = {}) {
    const token = localStorage.getItem('token');
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(endpoint, {
        ...options,
        headers
    });

    if (response.status === 401) {
        localStorage.removeItem('token');
        window.location.href = '/login';
        return;
    }

    return response;
}
