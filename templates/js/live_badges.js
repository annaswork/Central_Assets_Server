/**
 * live_badges.js - Real-time notification badge updater
 * Polls /api/notifications/badge-counts and updates unread message and access request badges without reloading the page.
 */

(function () {
  'use strict';

  async function pollNotificationBadges() {
    try {
      const res = await fetch('/api/notifications/badge-counts', {
        headers: { 'Accept': 'application/json' },
        cache: 'no-store'
      });
      if (!res.ok) return;

      const data = await res.json();
      if (!data || data.role === 'guest') return;

      const unreadMessages = data.unread_messages || 0;
      const pendingRequests = data.pending_requests || 0;

      // 1. Update Messages Badges
      const navMsgBadges = document.querySelectorAll('.nav-badge-messages, #navBadgeMessages');
      navMsgBadges.forEach(badge => {
        if (unreadMessages > 0) {
          badge.textContent = unreadMessages;
          badge.classList.remove('badge-hidden');
          badge.style.display = '';
        } else {
          badge.classList.add('badge-hidden');
          badge.style.display = 'none';
        }
      });

      const railMsgBadges = document.querySelectorAll('.rail-badge-messages, #railBadgeMessages');
      railMsgBadges.forEach(dot => {
        if (unreadMessages > 0) {
          dot.style.display = 'block';
        } else {
          dot.style.display = 'none';
        }
      });

      // 2. Update Access Requests Badges (Admin)
      const navReqBadges = document.querySelectorAll('.nav-badge-requests, #navBadgeAccessRequests');
      navReqBadges.forEach(badge => {
        if (pendingRequests > 0) {
          badge.textContent = pendingRequests;
          badge.classList.remove('badge-hidden');
          badge.style.display = '';
        } else {
          badge.classList.add('badge-hidden');
          badge.style.display = 'none';
        }
      });

      const railReqBadges = document.querySelectorAll('.rail-badge-requests, #railBadgeAccessRequests');
      railReqBadges.forEach(dot => {
        if (pendingRequests > 0) {
          dot.style.display = 'block';
        } else {
          dot.style.display = 'none';
        }
      });
    } catch (e) {
      // Ignore background fetch errors silently
    }
  }

  // Poll every 5 seconds, and poll immediately on page load
  document.addEventListener('DOMContentLoaded', () => {
    pollNotificationBadges();
    setInterval(pollNotificationBadges, 5000);
  });
})();
