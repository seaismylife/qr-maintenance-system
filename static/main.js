document.addEventListener('DOMContentLoaded', () => {
    resetMobileScroll();

    const themeCheckbox = document.getElementById('theme-toggle');
    const htmlElement = document.documentElement;
    
    
    const savedTheme = localStorage.getItem('theme');
    const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    let currentTheme = savedTheme || (systemPrefersDark ? 'dark' : 'light');
    
    
    htmlElement.setAttribute('data-theme', currentTheme);
    // Theme checkbox toggle event
    if (themeCheckbox) {
        themeCheckbox.checked = currentTheme === 'dark';
        themeCheckbox.addEventListener('change', (e) => {
            currentTheme = e.target.checked ? 'dark' : 'light';
            htmlElement.setAttribute('data-theme', currentTheme);
            localStorage.setItem('theme', currentTheme);
        });
    }
});

function resetMobileScroll() {
    if (!window.matchMedia('(max-width: 768px)').matches) return;
    window.scrollTo(0, 0);
    document.documentElement.scrollLeft = 0;
    document.body.scrollLeft = 0;
}

window.addEventListener('pageshow', resetMobileScroll);

// Notifications Logic & Real-Time Polling
function toggleNotifDropdown() {
    const dropdown = document.getElementById('notifDropdown');
    const backdrop = document.getElementById('notifBackdrop');
    if (!dropdown) return;
    const isShown = dropdown.classList.toggle('show');
    if (backdrop) {
        if (isShown) backdrop.classList.add('show');
        else backdrop.classList.remove('show');
    }
}

// Close notification dropdown when clicking outside
document.addEventListener('click', (e) => {
    const wrapper = document.querySelector('.notif-wrapper');
    const dropdown = document.getElementById('notifDropdown');
    const backdrop = document.getElementById('notifBackdrop');
    if (wrapper && dropdown && dropdown.classList.contains('show') && !wrapper.contains(e.target) && !e.target.closest('#notifBtn')) {
        dropdown.classList.remove('show');
        if (backdrop) backdrop.classList.remove('show');
    }
});

async function fetchNotifications() {
    try {
        const res = await fetch('/notifications/api/unread');
        if (!res.ok) return;
        const data = await res.json();
        
        const badge = document.getElementById('notifBadge');
        const list = document.getElementById('notifList');
        
        if (badge) {
            if (data.count > 0) {
                badge.innerText = data.count > 99 ? '99+' : data.count;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }
        
        if (list) {
            if (data.notifications && data.notifications.length > 0) {
                list.innerHTML = data.notifications.map(n => `
                    <a href="${n.link || '#'}" class="notif-item ${!n.is_read ? 'unread' : ''}" onclick="markNotifRead(event, ${n.id}, '${n.link || '#'}')">
                        <div>${n.message}</div>
                        <span class="notif-time">${n.created_at}</span>
                    </a>
                `).join('');
            } else {
                list.innerHTML = '<div class="notif-empty">No notifications</div>';
            }
        }
    } catch (err) {
        console.error('Error fetching notifications:', err);
    }
}

async function markNotifRead(e, id, link) {
    e.preventDefault();
    const dropdown = document.getElementById('notifDropdown');
    const backdrop = document.getElementById('notifBackdrop');
    if (dropdown) dropdown.classList.remove('show');
    if (backdrop) backdrop.classList.remove('show');
    try {
        await fetch(`/notifications/api/read/${id}`, { method: 'POST' });
    } catch (err) {}
    if (link && link !== '#') {
        window.location.href = link;
    } else {
        fetchNotifications();
    }
}

async function markAllNotificationsRead() {
    try {
        await fetch('/notifications/api/read-all', { method: 'POST' });
        fetchNotifications();
    } catch (err) {}
}

document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('notifBtn')) {
        fetchNotifications();
        setInterval(fetchNotifications, 10000);
    }
});

function toggleSidebar() {
    const sidebar = document.getElementById('appSidebar');
    const backdrop = document.getElementById('sidebarBackdrop');
    if (!sidebar) return;
    const isOpen = sidebar.classList.toggle('open');
    if (backdrop) {
        if (isOpen) backdrop.classList.add('show');
        else backdrop.classList.remove('show');
    }
}

// ─── Real-Time Live Clock & Dynamic Time Displays ───
function updateLiveClock() {
    const now = new Date();
    
    // Format date: "Mon, Oct 12, 2026"
    const dateOptions = { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' };
    const dateStr = now.toLocaleDateString('en-US', dateOptions);
    
    // Format time: "09:58:32 PM"
    const timeOptions = { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true };
    const timeStr = now.toLocaleTimeString('en-US', timeOptions);

    const dateEl = document.getElementById('liveClockDate');
    const timeEl = document.getElementById('liveClockTime');
    if (dateEl) dateEl.textContent = dateStr;
    if (timeEl) timeEl.textContent = timeStr;

    // Elements across pages requesting real-time clock
    const clocks = document.querySelectorAll('.live-realtime-clock');
    clocks.forEach(el => {
        el.textContent = `${dateStr} • ${timeStr}`;
    });

    const reportTimeEl = document.getElementById('reportGeneratedLive');
    if (reportTimeEl && !reportTimeEl.dataset.frozen) {
        reportTimeEl.textContent = `${dateStr} ${timeStr}`;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    updateLiveClock();
    setInterval(updateLiveClock, 1000);
});


