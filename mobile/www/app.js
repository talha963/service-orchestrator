// ==================== CONFIG ====================
let API_URL = localStorage.getItem('API_URL') || (window.location.protocol.startsWith('http') ? window.location.origin : 'http://localhost:8000');
let USER_ID = localStorage.getItem('USER_ID') || 'mobile_user_1';
let USER_LAT = parseFloat(localStorage.getItem('USER_LAT')) || 33.6310;
let USER_LNG = parseFloat(localStorage.getItem('USER_LNG')) || 73.0120;
let currentBooking = null;
let pendingProvider = null; // Tracks provider awaiting WhatsApp confirmation
let pendingProvidersList = [];
let currentProviderIndex = 0;

// ==================== INIT ====================
document.addEventListener('DOMContentLoaded', () => {
  if (sessionStorage.getItem('splashShown')) {
    document.getElementById('splash-screen').classList.remove('active');
    document.getElementById('splash-screen').style.display = 'none';
    document.getElementById('home-screen').classList.add('active');
    document.getElementById('bottom-nav').classList.remove('hidden');
  } else {
    setTimeout(() => {
      document.getElementById('splash-screen').classList.remove('active');
      document.getElementById('home-screen').classList.add('active');
      document.getElementById('bottom-nav').classList.remove('hidden');
      sessionStorage.setItem('splashShown', 'true');
    }, 3800);
  }

  // Nav buttons
  document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const screen = btn.dataset.screen;
      showScreen(screen);
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      if (screen === 'bookings') loadBookings();
      if (screen === 'traces') loadTraces();
      if (screen === 'dashboard') loadDashboard();
    });
  });

  // Back buttons
  document.querySelectorAll('.back-btn').forEach(btn => {
    btn.addEventListener('click', () => showScreen(btn.dataset.back));
  });

  // Chat
  document.getElementById('send-btn').addEventListener('click', sendMessage);
  document.getElementById('chat-input').addEventListener('keypress', e => {
    if (e.key === 'Enter') sendMessage();
  });

  // Quick actions
  document.querySelectorAll('.quick-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('chat-input').value = btn.dataset.msg;
      sendMessage();
    });
  });

  // Settings
  document.getElementById('settings-btn').addEventListener('click', () => {
    document.getElementById('api-url-input').value = API_URL;
    document.getElementById('user-id-input').value = USER_ID;
    document.getElementById('lat-input').value = USER_LAT;
    document.getElementById('lng-input').value = USER_LNG;
    document.getElementById('settings-modal').classList.remove('hidden');
  });
  document.getElementById('close-settings').addEventListener('click', () => document.getElementById('settings-modal').classList.add('hidden'));
  document.querySelector('.modal-overlay')?.addEventListener('click', () => document.getElementById('settings-modal').classList.add('hidden'));
  document.getElementById('save-settings').addEventListener('click', saveSettings);
  document.getElementById('refresh-traces-btn')?.addEventListener('click', loadTraces);

  // Geolocation setup
  document.getElementById('gps-btn')?.addEventListener('click', detectLocation);
  document.getElementById('map-gps-btn')?.addEventListener('click', detectLocation);
  document.getElementById('detect-location-btn')?.addEventListener('click', detectLocation);
  document.getElementById('allow-location-btn')?.addEventListener('click', () => {
    document.getElementById('location-overlay').classList.add('hidden');
    detectLocation();
  });
  document.getElementById('skip-location-btn')?.addEventListener('click', () => {
    document.getElementById('location-overlay').classList.add('hidden');
    updateLocationUI("📍 Default Location");
  });

  // Initial location detection
  setTimeout(detectLocation, 2500); // Try detecting shortly after splash
});

function updateLocationUI(text) {
  const statusEl = document.getElementById('location-status');
  if (statusEl) statusEl.innerHTML = text;
  const displayEl = document.getElementById('current-location-display');
  if (displayEl) displayEl.innerHTML = `<span class="material-icons-round">my_location</span><span>${text}</span>`;
}

async function detectLocation() {
  updateLocationUI("📍 Detecting location...");
  if (!navigator.geolocation) {
    updateLocationUI("📍 Location unsupported");
    return;
  }
  
  navigator.geolocation.getCurrentPosition(
    async (position) => {
      USER_LAT = position.coords.latitude;
      USER_LNG = position.coords.longitude;
      document.getElementById('lat-input').value = USER_LAT;
      document.getElementById('lng-input').value = USER_LNG;
      
      try {
        const res = await fetch(`${API_URL}/api/geocode?lat=${USER_LAT}&lng=${USER_LNG}`);
        const data = await res.json();
        if (data && data.address) {
          // Use a shortened version of the address
          const shortAddress = data.address.split(',').slice(0, 2).join(',');
          updateLocationUI(`📍 ${shortAddress}`);
        } else {
          updateLocationUI("📍 Location Active");
        }
      } catch (e) {
        updateLocationUI("📍 Location Active");
      }
    },
    (error) => {
      console.error("Geolocation error:", error);
      // Use default Islamabad coordinates
      USER_LAT = 33.6310;
      USER_LNG = 73.0120;
      updateLocationUI("📍 Islamabad (Default)");
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
  );
}

function showScreen(name) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const el = document.getElementById(name + '-screen');
  if (el) el.classList.add('active');
}

function saveSettings() {
  API_URL = document.getElementById('api-url-input').value.replace(/\/$/, '');
  USER_ID = document.getElementById('user-id-input').value;
  USER_LAT = parseFloat(document.getElementById('lat-input').value);
  USER_LNG = parseFloat(document.getElementById('lng-input').value);
  
  localStorage.setItem('API_URL', API_URL);
  localStorage.setItem('USER_ID', USER_ID);
  localStorage.setItem('USER_LAT', USER_LAT);
  localStorage.setItem('USER_LNG', USER_LNG);
  
  document.getElementById('settings-modal').classList.add('hidden');
}

// ==================== CHAT ====================
function addMessage(text, isUser = false) {
  const container = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = `message ${isUser ? 'user-message' : 'bot-message'}`;
  div.innerHTML = isUser
    ? `<div class="message-bubble"><p>${text}</p></div>`
    : `<div class="message-avatar">🤖</div><div class="message-bubble">${text}</div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function addTyping() {
  const container = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'message bot-message';
  div.id = 'typing-msg';
  div.innerHTML = `<div class="message-avatar">🤖</div><div class="message-bubble"><div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById('typing-msg');
  if (el) el.remove();
}

async function sendMessage() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  addMessage(msg, true);

  // Check if user is responding to contact confirmation
  const lower = msg.toLowerCase();
  if (pendingProvider && (lower.includes('sms'))) {
    await sendSMSToProvider(pendingProvider);
    return;
  }
  if (pendingProvider && (lower === 'yes' || lower === 'haan' || lower === 'ha' || lower === 'y' || lower.includes('contact') || lower.includes('whatsapp'))) {
    await sendWhatsAppToProvider(pendingProvider);
    return;
  }
  if (pendingProvider && (lower === 'no' || lower === 'nahi' || lower === 'n' || lower === 'skip' || lower === 'cancel')) {
    skipWhatsApp();
    return;
  }

  addTyping();

  try {
    // Step 1: NLU — extract intent via webhook
    const res = await fetch(`${API_URL}/webhook/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: USER_ID, message: msg, latitude: USER_LAT, longitude: USER_LNG })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    removeTyping();

    // Show NLU + booking result
    handleResponse(data);

    // Step 2: Also find nearest REAL provider on Google Maps (if not already returned via scheduling fallback)
    const serviceType = data.intent?.service_type;
    if (serviceType && data.status !== 'clarification_needed' && data.status !== 'no_available_slot') {
      addTyping();
      addMessage(`<p>🔍 Searching Google Maps for the nearest <strong>${serviceType}</strong> near your location...</p>`);

      try {
        const provRes = await fetch(`${API_URL}/api/find-provider`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ lat: USER_LAT, lng: USER_LNG, service_type: serviceType, radius: 5000 })
        });
        const provData = await provRes.json();
        removeTyping();

        if (provData.status === 'provider_found' && provData.provider) {
          const p = provData.provider;
          pendingProvidersList = [p, ...(provData.all_providers?.slice(1) || [])];
          currentProviderIndex = 0;
          pendingProvider = p;

          renderProviderCard(p);

          // Show other providers if available
          if (provData.all_providers && provData.all_providers.length > 1) {
            const others = provData.all_providers.slice(1, 4).map(op =>
              `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.05)">` +
              `<div><div style="font-weight:600;font-size:13px">${op.name}</div><div style="font-size:11px;color:var(--text-muted)">${op.distance_km}km away</div></div>` +
              `<div style="font-size:13px">${op.rating || 'N/A'} ⭐</div></div>`
            ).join('');
            addMessage(`<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px">Other nearby providers:</p>${others}`);
          }

        } else {
          addMessage(`<p>😔 No real providers found on Google Maps for <strong>${serviceType}</strong> within 5km of your location.</p>`);
        }
      } catch (e) {
        removeTyping();
        console.error('Find provider error:', e);
      }
    }
  } catch (err) {
    removeTyping();
    addMessage(`<p>❌ Connection error. Make sure the backend is running at <strong>${API_URL}</strong></p><p class="message-hint">Run: py orchestrator.py</p>`);
  }
}

// Send SMS message to the pending provider (Hits backend API)
async function sendSMSToProvider(provider) {
  if (!provider) return;
  addMessage(`<p>📤 Sending SMS message to <strong>${provider.name}</strong>...</p>`);
  addTyping();

  try {
    const res = await fetch(`${API_URL}/api/send-sms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        phone: provider.phone || '',
        place_id: provider.place_id || '',
        provider_name: provider.name,
        service_type: provider.service || 'service',
        target_language: 'urdu', // Assuming user preference
        channel: 'sms'
      })
    });
    const data = await res.json();
    removeTyping();

    if (data.status === 'no_phone_number') {
      addMessage(`<p>Phone number is not publicly listed for ${provider.name} on Google Maps.</p>`);
      return;
    }

    if (data.status === 'message_sent' || data.sms_delivered) {
      addMessage(
        `<div style="border:1px solid rgba(0,206,201,0.3);border-radius:16px;padding:16px;background:rgba(0,206,201,0.08)">` +
        `<p>✅ <strong>SMS message sent to ${provider.name}!</strong></p>` +
        `<p style="font-size:13px;margin-top:8px">📞 To: <strong>${data.phone || provider.phone}</strong></p>` +
        `<p style="font-size:13px">👤 Provider: <strong>${provider.name}</strong></p>` +
        `<p style="font-size:12px;color:var(--text-muted);margin-top:8px;font-style:italic">"${data.message_body || 'Assalam o Alaikum! I need a service urgently.'}"</p>` +
        `</div>`
      );
    } else {
      addMessage(`<p>❌ Failed to send SMS message.</p>${data.error ? `<p style="font-size:12px;color:var(--danger)">Reason: ${data.error}</p>` : ''}`);
    }
  } catch (e) {
    removeTyping();
    addMessage(`<p>❌ Error sending SMS message. Check server logs.</p>`);
  }
}

// Send WhatsApp message (Simulated UI but hits backend for translation details)
async function sendWhatsAppToProvider(provider) {
  if (!provider) return;
  addMessage(`<p>📤 Sending WhatsApp message to <strong>${provider.name}</strong>...</p>`);
  addTyping();

  try {
    const res = await fetch(`${API_URL}/api/send-sms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        phone: provider.phone || '',
        place_id: provider.place_id || '',
        provider_name: provider.name,
        service_type: provider.service || 'service',
        target_language: 'urdu', // Assuming user preference
        channel: 'whatsapp'
      })
    });
    const data = await res.json();
    removeTyping();

    if (data.status === 'no_phone_number') {
      addMessage(`<p>Phone number is not publicly listed for ${provider.name} on Google Maps.</p>`);
      return;
    }

    if (data.status === 'message_sent' || data.sms_delivered) {
      addMessage(
        `<div style="border:1px solid rgba(37,211,102,0.3);border-radius:16px;padding:16px;background:rgba(37,211,102,0.08)">` +
        `<p>✅ <strong>WhatsApp message sent to ${provider.name}!</strong></p>` +
        `<p style="font-size:13px;margin-top:8px">📞 To: <strong>${data.phone || provider.phone}</strong></p>` +
        `<p style="font-size:13px">👤 Provider: <strong>${provider.name}</strong></p>` +
        `<p style="font-size:12px;color:var(--text-muted);margin-top:8px;font-style:italic">"${data.message_body || 'Assalam o Alaikum! I need a service urgently.'}"</p>` +
        `</div>`
      );
    } else {
      addMessage(`<p>❌ Failed to send WhatsApp message.</p>${data.error ? `<p style="font-size:12px;color:var(--danger)">Reason: ${data.error}</p>` : ''}`);
    }
  } catch (e) {
    removeTyping();
    addMessage(`<p>❌ Error sending WhatsApp message. Check server logs.</p>`);
  }
}

// Book provider on user's request
async function bookProvider(provider) {
  if (!provider) return;
  addMessage(`<p>📅 Booking <strong>${provider.name}</strong> on the platform...</p>`);
  addTyping();

  try {
    const res = await fetch(`${API_URL}/api/book-provider`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: USER_ID,
        provider: provider,
        service_type: provider.service || 'service',
        user_lat: USER_LAT,
        user_lng: USER_LNG
      })
    });
    const data = await res.json();
    removeTyping();

    if (data.status === 'booking_confirmed') {
      handleResponse(data);
      pendingProvider = null; // Clear now that they are booked
    } else {
      addMessage(`<p>❌ Failed to book provider.</p>`);
    }
  } catch (e) {
    removeTyping();
    console.error('Book provider error:', e);
    addMessage(`<p>❌ Error booking provider.</p>`);
  }
}

function skipWhatsApp() {
  if (pendingProvidersList && pendingProvidersList.length > currentProviderIndex + 1) {
    currentProviderIndex++;
    const nextProvider = pendingProvidersList[currentProviderIndex];
    pendingProvider = nextProvider;
    addMessage(`<p>👍 Searching for the next nearest provider...</p>`);
    renderProviderCard(nextProvider);
  } else {
    pendingProvider = null;
    addMessage(`<p>👍 No more providers found. You can ask for a different service or time.</p>`);
  }
}

function renderProviderCard(p) {
  const displayPhone = p.phone || "Not publicly listed";
  const phoneInfo = `<p>📞 Phone: <strong>${displayPhone}</strong></p>`;
  const openInfo = p.is_open === true ? '<span style="color:#4caf50;font-weight:700">● Open Now</span>' : p.is_open === false ? '<span style="color:#f44336;font-weight:700">● Closed</span>' : '';
  const label = p.address === 'Platform Certified Provider' ? '✨ Platform Certified Provider' : '📍 Nearby Provider on Google Maps';

  addMessage(
    `<div style="border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:16px;background:rgba(255,255,255,0.05);margin-top:4px">` +
    `<p style="font-size:11px;color:var(--accent-light);font-weight:600;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">${label}</p>` +
    `<p style="font-size:17px;font-weight:700;margin-bottom:4px">${p.name}</p>` +
    `<p style="font-size:12px;color:var(--text-muted);margin-bottom:12px">${p.address || ''}</p>` +
    `<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">` +
      `<div style="background:rgba(255,255,255,0.05);padding:8px;border-radius:8px;text-align:center"><div style="font-size:18px;font-weight:700">${p.rating || 'N/A'} ⭐</div><div style="font-size:10px;color:var(--text-muted)">${p.review_count || 0} reviews</div></div>` +
      `<div style="background:rgba(255,255,255,0.05);padding:8px;border-radius:8px;text-align:center"><div style="font-size:18px;font-weight:700">${p.distance_km} km</div><div style="font-size:10px;color:var(--text-muted)">away ${openInfo}</div></div>` +
    `</div>` +
    phoneInfo +
    `</div>`
  );

  // Ask for SMS, WhatsApp or Book confirmation
  const contactDisabled = (!p.phone && !p.place_id) ? 'disabled title="No public phone number listed"' : '';
  const contactOpacity = (!p.phone && !p.place_id) ? 'opacity:0.45;cursor:not-allowed;' : 'cursor:pointer;';
  addMessage(
    `<p>📱 How would you like me to <strong>contact/book ${p.name}</strong>?</p>` +
    `<div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">` +
      `<button onclick="sendSMSToProvider(pendingProvider)" style="flex:1;min-width:70px;padding:8px;border:none;border-radius:12px;background:linear-gradient(135deg,#00cec9,#00b894);color:white;font-weight:700;font-size:12px;cursor:pointer">💬 SMS</button>` +
      `<button onclick="sendWhatsAppToProvider(pendingProvider)" style="flex:1;min-width:70px;padding:8px;border:none;border-radius:12px;background:linear-gradient(135deg,#25D366,#128C7E);color:white;font-weight:700;font-size:12px;cursor:pointer">✅ WhatsApp</button>` +
      `<button onclick="bookProvider(pendingProvider)" style="flex:1;min-width:70px;padding:8px;border:none;border-radius:12px;background:linear-gradient(135deg,#ff7675,#d63031);color:white;font-weight:700;font-size:12px;cursor:pointer">📅 Book</button>` +
      `<button onclick="skipWhatsApp()" style="flex:1;min-width:70px;padding:8px;border:none;border-radius:12px;background:rgba(255,255,255,0.1);color:white;font-weight:600;font-size:12px;cursor:pointer">❌ Skip</button>` +
    `</div>`
  );
}

function handleResponse(data) {
  if (data.status === 'clarification_needed') {
    const qs = (data.clarification_questions || []).map(q => `• ${q}`).join('<br>');
    addMessage(`<p>🤔 I'm not fully sure I understood. Confidence: <strong>${data.intent?.confidence_score}%</strong></p><p>${qs}</p><p class="message-hint">Please provide more details.</p>`);
    return;
  }
  if (data.status === 'proposal_pending') {
    const p = data.provider;
    addMessage(`<p>🔍 <strong>Matching provider found on the platform!</strong></p>`);

    pendingProvidersList = [p];
    currentProviderIndex = 0;
    pendingProvider = p;

    renderProviderCard(p);
    
    // Render the matches/providers list in the background tab
    renderProvidersScreen(data);
    return;
  }
  if (data.status === 'no_provider_available') {
    addMessage(`<p>😔 No providers found for <strong>${data.intent?.service_type}</strong> in your area.</p><p class="message-hint">${(data.suggestions||[]).join(' | ')}</p>`);
    return;
  }
  if (data.status === 'no_available_slot') {
    if (data.google_providers && data.google_providers.length > 0) {
      addMessage(`<p>⏰ <strong>No platform slots are available at the requested time.</strong><br>However, we found alternative providers on Google Maps (scraped data) near your location:</p>`);
      
      const p = data.google_providers[0];
      pendingProvidersList = data.google_providers;
      currentProviderIndex = 0;
      pendingProvider = p;

      renderProviderCard(p);

      if (data.google_providers.length > 1) {
        const others = data.google_providers.slice(1, 5).map(op =>
          `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.05)">` +
          `<div><div style="font-weight:600;font-size:13px">${op.name}</div><div style="font-size:11px;color:var(--text-muted)">${op.distance_km}km away</div></div>` +
          `<div style="font-size:13px">${op.rating || 'N/A'} ⭐</div></div>`
        ).join('');
        addMessage(`<p style="font-size:12px;color:var(--text-muted);margin-bottom:8px">Other alternative providers found:</p>${others}`);
      }
    } else {
      const slots = (data.alternate_slots || []).map(s => `${s.date} at ${s.time}`).join(', ');
      addMessage(`<p>⏰ No available slot at the requested time on the platform, and no nearby Google Maps providers were found.</p><p>Platform alternate slots: <strong>${slots || 'None'}</strong></p>`);
    }
    return;
  }
  if (data.status === 'booking_confirmed') {
    currentBooking = data;
    const i = data.intent, m = data.match, p = data.pricing;
    addMessage(
      `<p>✅ <strong>Booking Confirmed!</strong></p>` +
      `<p>📋 Service: ${i.service_type} (${i.complexity})</p>` +
      `<p>👤 Provider: <strong>${m.provider_name}</strong> (${m.rating}⭐, ${m.on_time_pct}% reliable)</p>` +
      `<p>📅 ${data.scheduling.date} at ${data.scheduling.time}</p>` +
      `<p>💰 Total: <strong>Rs. ${p.total}</strong></p>` +
      `<p>🆔 Booking: ${data.booking_id}</p>` +
      `<p class="message-hint" style="cursor:pointer;color:var(--accent-light);font-weight:600;margin-top:8px" onclick="showScreen('booking')">Tap to see full details ↓</p>`
    );
    renderBookingScreen(data);
    renderProvidersScreen(data);
  }
}

// ==================== PROVIDERS SCREEN ====================
function renderProvidersScreen(data) {
  const el = document.getElementById('providers-content');
  const matches = data.all_matches || [];
  el.innerHTML = `<p class="section-title">Ranked by 8-Factor AI Scoring</p>` +
    matches.map((m, i) => `
      <div class="glass-card provider-card ${i === 0 ? 'best' : ''}">
        <div class="card-header">
          <div><div class="card-title">${m.provider_name}</div>
          <div style="font-size:12px;color:var(--text-muted)">${m.skill_level} • ${m.distance_km}km away</div></div>
          <div class="provider-score">${m.match_score}</div>
        </div>
        <div class="provider-meta">
          <div class="meta-item"><span class="meta-label">Rating</span><span class="meta-value">${m.rating}⭐</span></div>
          <div class="meta-item"><span class="meta-label">Reliability</span><span class="meta-value">${m.on_time_pct}%</span></div>
          <div class="meta-item"><span class="meta-label">Travel Time</span><span class="meta-value">${m.travel_time_mins} min</span></div>
          <div class="meta-item"><span class="meta-label">Cancel Rate</span><span class="meta-value">${m.cancellation_rate}%</span></div>
        </div>
        <p style="font-size:12px;color:var(--text-secondary);margin-top:12px">${m.reasoning}</p>
      </div>
    `).join('');
}

// ==================== BOOKING SCREEN ====================
function renderBookingScreen(data) {
  const el = document.getElementById('booking-content');
  const b = data.booking, p = data.pricing || data.booking?.price_breakdown || {}, i = data.intent || {};
  const notifs = (b.notifications || []).map(n =>
    `<div class="notification-card"><div class="notif-icon">${n.type === 'sms' ? '📱' : '💬'}</div><div><div class="notif-text">${n.message}</div><div class="notif-time">${n.status}</div></div></div>`
  ).join('');

  const checklist = (b.completion_checklist || []).map(c =>
    `<div class="checklist-item"><div class="checklist-dot ${c.completed ? 'done' : ''}"></div>${c.item}</div>`
  ).join('');

  // Progress Timeline
  const statusOrder = ['confirmed', 'provider_en_route', 'in_progress', 'completed', 'rated'];
  const statusLabels = ['Confirmed', 'En Route', 'In Progress', 'Completed', 'Rated'];
  const statusIcons = ['✓', '🚗', '🔧', '✅', '⭐'];
  const currentIdx = statusOrder.indexOf(b.status);
  const timeline = statusOrder.map((s, idx) => {
    let dotClass = 'pending';
    let labelClass = '';
    if (idx < currentIdx) { dotClass = 'done'; labelClass = 'done'; }
    else if (idx === currentIdx) { dotClass = 'active'; labelClass = 'active'; }
    return `<div class="timeline-step">
      <div class="timeline-dot ${dotClass}">${statusIcons[idx]}</div>
      <div class="timeline-label ${labelClass}">${statusLabels[idx]}</div>
    </div>`;
  }).join('');

  const priceRows = [
    { label: 'Base Rate', val: p.base_rate },
    p.distance_surcharge ? { label: 'Distance', val: p.distance_surcharge } : null,
    p.urgency_premium ? { label: 'Urgency', val: p.urgency_premium } : null,
    p.complexity_addon ? { label: 'Complexity', val: p.complexity_addon } : null,
    p.demand_surge ? { label: 'Demand Surge', val: p.demand_surge } : null,
    p.loyalty_discount ? { label: 'Discount', val: -p.loyalty_discount, cls: 'price-discount' } : null,
  ].filter(Boolean).map(r =>
    `<div class="price-row"><span>${r.label}</span><span class="${r.cls || ''}">Rs. ${r.val}</span></div>`
  ).join('');

  let budgetAlt = '';
  if (p.budget_alternative) {
    const ba = p.budget_alternative;
    budgetAlt = `<div class="glass-card" style="border-color:var(--success);margin-top:12px">
      <div class="card-header"><div class="card-title">💡 Budget Alternative</div><span class="card-badge badge-success">Save Rs.${ba.savings}</span></div>
      <p style="font-size:13px">${ba.provider_name} — Rs.${ba.estimated_price} (${ba.rating}⭐)</p>
      <p style="font-size:12px;color:var(--text-muted)">${ba.trade_off}</p></div>`;
  }

  el.innerHTML = `
    <div class="glass-card">
      <div class="card-header"><div class="card-title">Booking ${b.booking_id}</div><span class="card-badge badge-success">${b.status}</span></div>
      <div class="timeline">${timeline}</div>
      <div class="detail-row"><span class="detail-label">Service</span><span class="detail-value">${b.service_type}</span></div>
      <div class="detail-row"><span class="detail-label">Provider</span><span class="detail-value">${b.provider_name}</span></div>
      <div class="detail-row"><span class="detail-label">Date</span><span class="detail-value">${b.scheduled_date}</span></div>
      <div class="detail-row"><span class="detail-label">Time</span><span class="detail-value">${b.scheduled_hour}:00</span></div>
      <div class="detail-row"><span class="detail-label">Location</span><span class="detail-value">${b.location || 'GPS'}</span></div>
    </div>
    <p class="section-title">💰 Price Breakdown</p>
    <div class="glass-card">${priceRows}<div class="price-row total"><span>Total</span><span>Rs. ${p.total || b.price_total}</span></div>
      <p style="font-size:11px;color:var(--text-muted);margin-top:8px">${p.fairness_note || ''}</p></div>
    ${budgetAlt}
    <p class="section-title">📋 Service Checklist</p>
    <div class="glass-card">${checklist}</div>
    <p class="section-title">🔔 Notifications</p>
    <div class="glass-card" style="padding:12px">${notifs}</div>
    <div id="booking-action-feedback" class="inline-status hidden"></div>
    <div class="action-row">
      <button class="secondary-btn" onclick="simulateProgress('${b.booking_id}')">▶ Simulate Progress</button>
      <button class="danger-btn" onclick="cancelBooking('${b.booking_id}')">Cancel</button>
    </div>
    <div class="action-row" style="margin-top:8px">
      <button class="primary-btn" onclick="showFeedbackScreen('${b.booking_id}','${b.provider_id}','${b.provider_name}')">⭐ Rate Service</button>
    </div>
    <div class="action-row" style="margin-top:8px">
      <button class="danger-btn" style="width:48%" onclick="showDisputeScreen('${b.booking_id}')">⚠ Report Issue</button>
      <button class="secondary-btn" style="width:48%" onclick="simulateProviderCancel('${b.booking_id}')">🚫 Simulate Provider Cancel</button>
    </div>`;
}

function bookingViewFromBooking(booking) {
  return {
    booking,
    pricing: booking.price_breakdown || {},
    intent: currentBooking?.intent || { service_type: booking.service_type },
    scheduling: {
      date: booking.scheduled_date,
      time: `${String(booking.scheduled_hour).padStart(2, '0')}:00`
    }
  };
}

function setBookingActionFeedback(message, type = 'info') {
  const el = document.getElementById('booking-action-feedback');
  if (!el) return;
  el.className = `inline-status ${type}`;
  el.innerHTML = message;
}

// Simulate provider cancellation for demo
async function simulateProviderCancel(bookingId) {
  if (!confirm('Simulate provider cancellation? This will trigger auto-reschedule.')) return;
  showScreen('booking');
  setBookingActionFeedback(`Simulating provider cancellation for booking <strong>${bookingId}</strong>...`, 'info');
  addMessage(`<p>🚫 Simulating provider cancellation for booking ${bookingId}...</p>`);
  try {
    const res = await fetch(`${API_URL}/booking/${bookingId}/cancel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cancelled_by: 'provider', reason: 'Provider emergency — auto-reschedule triggered' })
    });
    const data = await res.json();
    if (data.reschedule && data.reschedule.rescheduled) {
      const updatedBooking = data.booking || data.reschedule.booking;
      if (updatedBooking) {
        currentBooking = bookingViewFromBooking(updatedBooking);
        renderBookingScreen(currentBooking);
      }
      setBookingActionFeedback(
        `Auto-rescheduled to <strong>${data.reschedule.new_provider.name}</strong> for ${data.reschedule.date} at ${data.reschedule.time}.`,
        'success'
      );
      addMessage(
        `<div style="border:1px solid var(--success);border-radius:16px;padding:16px;background:rgba(0,206,201,0.08)">` +
        `<p>✅ <strong>Auto-Rescheduled!</strong></p>` +
        `<p style="font-size:13px;margin-top:8px">New Provider: <strong>${data.reschedule.new_provider.name}</strong></p>` +
        `<p style="font-size:13px">Time: <strong>${data.reschedule.date} at ${data.reschedule.time}</strong></p>` +
        `</div>`
      );
    } else {
      addMessage(`<p>⚠️ Provider cancelled. No alternate provider available at the same time. Please try a different slot.</p>`);
    }
    showScreen('booking');
  } catch (e) { addMessage(`<p>❌ Error simulating cancellation</p>`); }
}

// ==================== SIMULATE PROGRESS ====================
async function simulateProgress(bookingId) {
  const statuses = ['provider_en_route', 'in_progress', 'completed'];
  showScreen('booking');
  for (const status of statuses) {
    const label = status.replace(/_/g, ' ');
    setBookingActionFeedback(`Simulating status: <strong>${label}</strong>...`, 'info');
    addMessage(`<p>🔄 Simulating: <strong>${status.replace(/_/g, ' ')}</strong>...</p>`);
    try {
      const res = await fetch(`${API_URL}/booking/${bookingId}/status?status=${status}`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.booking) {
        currentBooking = bookingViewFromBooking(data.booking);
        renderBookingScreen(currentBooking);
        setBookingActionFeedback(`Status updated to <strong>${label}</strong>.`, 'success');
      }
      await new Promise(r => setTimeout(r, 900));
    } catch (e) { addMessage(`<p>❌ Error updating status</p>`); return; }
  }
  addMessage(`<p>✅ Service completed! Please rate your experience.</p>`);
}

// ==================== CANCEL ====================
async function cancelBooking(bookingId) {
  if (!confirm('Cancel this booking?')) return;
  try {
    const res = await fetch(`${API_URL}/booking/${bookingId}/cancel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cancelled_by: 'user', reason: 'User cancelled' })
    });
    const data = await res.json();
    addMessage(`<p>❌ Booking ${bookingId} cancelled.</p>`);
    showScreen('home');
  } catch (e) { alert('Error cancelling booking'); }
}

// ==================== FEEDBACK ====================
let feedbackState = { bookingId: '', providerId: '', rating: 0 };

function showFeedbackScreen(bookingId, providerId, providerName) {
  feedbackState = { bookingId, providerId, rating: 0 };
  const el = document.getElementById('feedback-content');
  el.innerHTML = `
    <div class="glass-card" style="text-align:center">
      <p style="font-size:18px;font-weight:700;margin-bottom:8px">Rate ${providerName}</p>
      <p style="color:var(--text-muted);font-size:13px">How was your experience?</p>
      <div class="star-rating">${[1,2,3,4,5].map(n => `<button class="star-btn" data-star="${n}" onclick="setRating(${n})">⭐</button>`).join('')}</div>
      <textarea class="text-area" id="review-text" placeholder="Write a review (optional)..."></textarea>
      <button class="primary-btn" style="margin-top:16px" onclick="submitFeedback()">Submit Rating</button>
    </div>`;
  showScreen('feedback');
}

function setRating(n) {
  feedbackState.rating = n;
  document.querySelectorAll('.star-btn').forEach(btn => {
    btn.classList.toggle('active', parseInt(btn.dataset.star) <= n);
  });
}

async function submitFeedback() {
  if (!feedbackState.rating) { alert('Please select a rating'); return; }
  try {
    const res = await fetch(`${API_URL}/booking/${feedbackState.bookingId}/rate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating: feedbackState.rating, review_text: document.getElementById('review-text').value })
    });
    const data = await res.json();
    const el = document.getElementById('feedback-content');
    el.innerHTML = `
      <div class="glass-card" style="text-align:center">
        <p style="font-size:48px">✅</p>
        <p style="font-size:18px;font-weight:700;margin:12px 0">Thank You!</p>
        <p style="color:var(--text-muted);font-size:13px">Your feedback helps improve our service</p>
      </div>
      <div class="glass-card">
        <div class="detail-row"><span class="detail-label">Rating</span><span class="detail-value">${feedbackState.rating}/5</span></div>
        <div class="detail-row"><span class="detail-label">Sentiment</span><span class="detail-value">${data.sentiment || 'N/A'}</span></div>
        <div class="detail-row"><span class="detail-label">Old Rating</span><span class="detail-value">${data.old_rating}</span></div>
        <div class="detail-row"><span class="detail-label">New Rating</span><span class="detail-value">${data.new_rating}</span></div>
        <div class="detail-row"><span class="detail-label">Impact</span><span class="detail-value" style="font-size:11px">${data.matching_impact || ''}</span></div>
      </div>`;
  } catch (e) { alert('Error submitting feedback'); }
}

// ==================== DISPUTE ====================
function showDisputeScreen(bookingId) {
  const el = document.getElementById('dispute-content');
  el.innerHTML = `
    <div class="glass-card">
      <p class="card-title" style="margin-bottom:16px">Report an Issue</p>
      <div class="settings-group"><label>Dispute Type</label>
        <select class="select-input" id="dispute-type">
          <option value="no_show">Provider No-Show</option>
          <option value="late_arrival">Late Arrival</option>
          <option value="quality_complaint">Quality Complaint</option>
          <option value="price_disagreement">Price Disagreement</option>
          <option value="service_overrun">Service Overrun</option>
          <option value="cancellation">Provider Cancelled</option>
        </select></div>
      <div class="settings-group"><label>Description</label>
        <textarea class="text-area" id="dispute-desc" placeholder="Describe the issue..."></textarea></div>
      <button class="primary-btn" onclick="submitDispute('${bookingId}')">Submit Dispute</button>
    </div>`;
  showScreen('dispute');
}

async function submitDispute(bookingId) {
  const type = document.getElementById('dispute-type').value;
  const desc = document.getElementById('dispute-desc').value;
  if (!desc) { alert('Please describe the issue'); return; }
  try {
    const res = await fetch(`${API_URL}/booking/${bookingId}/dispute`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dispute_type: type, description: desc })
    });
    const data = await res.json();
    const r = data.resolution || {};
    document.getElementById('dispute-content').innerHTML = `
      <div class="glass-card" style="text-align:center">
        <p style="font-size:48px">${data.status === 'resolved' ? '✅' : '⏳'}</p>
        <p style="font-size:18px;font-weight:700;margin:12px 0">Dispute ${data.status === 'resolved' ? 'Resolved' : 'Under Review'}</p>
      </div>
      <div class="glass-card">
        <div class="detail-row"><span class="detail-label">Status</span><span class="detail-value"><span class="card-badge ${data.status === 'resolved' ? 'badge-success' : 'badge-warning'}">${data.status}</span></span></div>
        <div class="detail-row"><span class="detail-label">Type</span><span class="detail-value">${type}</span></div>
        ${data.refund_amount ? `<div class="detail-row"><span class="detail-label">Refund</span><span class="detail-value" style="color:var(--success)">Rs. ${data.refund_amount}</span></div>` : ''}
        <div class="detail-row"><span class="detail-label">Action</span><span class="detail-value" style="font-size:11px">${r.action || 'Under review'}</span></div>
      </div>`;
  } catch (e) { alert('Error submitting dispute'); }
}

// ==================== BOOKINGS LIST ====================
async function loadBookings() {
  const el = document.getElementById('bookings-list-content');
  el.innerHTML = '<div class="skeleton" style="height:100px;margin-bottom:12px"></div>'.repeat(3);
  try {
    const res = await fetch(`${API_URL}/bookings/user/${USER_ID}`);
    const data = await res.json();
    const bookings = data.bookings || [];
    if (!bookings.length) {
      el.innerHTML = `<div class="empty-state"><span class="material-icons-round">event_busy</span><p>No bookings yet. Start by sending a service request!</p></div>`;
      return;
    }
    el.innerHTML = bookings.reverse().map(b => {
      const badge = { confirmed: 'badge-success', completed: 'badge-success', cancelled: 'badge-danger', disputed: 'badge-warning', rated: 'badge-info' }[b.status] || 'badge-accent';
      return `<div class="glass-card" onclick="viewBookingDetail('${b.booking_id}')">
        <div class="card-header"><div class="card-title">${b.service_type || 'Service'}</div><span class="card-badge ${badge}">${b.status}</span></div>
        <div class="detail-row"><span class="detail-label">Provider</span><span class="detail-value">${b.provider_name}</span></div>
        <div class="detail-row"><span class="detail-label">Date</span><span class="detail-value">${b.scheduled_date} ${b.scheduled_hour}:00</span></div>
        <div class="detail-row"><span class="detail-label">Price</span><span class="detail-value">Rs. ${b.price_total}</span></div>
      </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div class="empty-state"><span class="material-icons-round">cloud_off</span><p>Cannot connect to server</p></div>`;
  }
}

async function viewBookingDetail(bookingId) {
  try {
    const res = await fetch(`${API_URL}/booking/${bookingId}`);
    const data = await res.json();
    if (data.booking) {
      currentBooking = { booking: data.booking, pricing: data.booking.price_breakdown || {}, intent: {} };
      renderBookingScreen(currentBooking);
      showScreen('booking');
    }
  } catch (e) { alert('Error loading booking'); }
}

// ==================== TRACES ====================
async function loadTraces() {
  const el = document.getElementById('traces-content');
  el.innerHTML = '<div class="skeleton" style="height:80px;margin-bottom:12px"></div>'.repeat(4);
  try {
    const res = await fetch(`${API_URL}/traces?limit=30`);
    const data = await res.json();
    const traces = data.traces || [];
    if (!traces.length) {
      el.innerHTML = `<div class="empty-state"><span class="material-icons-round">psychology</span><p>No traces yet. Send a service request to see AI reasoning.</p></div>`;
      return;
    }
    el.innerHTML = traces.reverse().map(t => {
      const confColor = t.confidence > 80 ? 'var(--success)' : t.confidence > 50 ? 'var(--warning)' : 'var(--danger)';
      return `<div class="glass-card trace-card">
        <span class="trace-stage">${t.stage}</span>
        <span class="trace-time">${t.trace_id} • ${new Date(t.timestamp).toLocaleTimeString()}</span>
        <div class="trace-reasoning">${t.reasoning}</div>
        <div class="trace-confidence">
          <span style="font-size:12px;color:var(--text-muted)">Confidence</span>
          <div class="confidence-bar"><div class="confidence-fill" style="width:${t.confidence}%;background:${confColor}"></div></div>
          <span style="font-size:12px;font-weight:700;color:${confColor}">${t.confidence}%</span>
        </div>
      </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<div class="empty-state"><span class="material-icons-round">cloud_off</span><p>Cannot load traces</p></div>`;
  }
}

// ==================== DASHBOARD ====================
let dashboardTab = 'overview';
let dashData = null;

async function loadDashboard() {
  const el = document.getElementById('dashboard-content');
  el.innerHTML = '<div class="skeleton" style="height:200px"></div>';
  try {
    const [dashRes, earnRes] = await Promise.all([
      fetch(`${API_URL}/providers/dashboard`),
      fetch(`${API_URL}/providers/earnings`)
    ]);
    const dash = await dashRes.json();
    const earn = await earnRes.json();

    const providers = dash.providers || [];
    const summary = dash.service_summary || {};
    const recs = dash.recommendations || [];
    const es = earn.summary || {};
    dashData = { providers, summary, recs, es, earn, dash };

    el.innerHTML = `
      <div class="tab-bar">
        <button class="tab-btn ${dashboardTab === 'overview' ? 'active' : ''}" onclick="switchDashTab('overview')">Overview</button>
        <button class="tab-btn ${dashboardTab === 'providers' ? 'active' : ''}" onclick="switchDashTab('providers')">Providers</button>
        <button class="tab-btn ${dashboardTab === 'stress' ? 'active' : ''}" onclick="switchDashTab('stress')">Stress Tests</button>
      </div>
      <div id="dash-tab-content"></div>`;

    renderDashTab(dashboardTab);
  } catch (e) {
    el.innerHTML = `<div class="empty-state"><span class="material-icons-round">cloud_off</span><p>Cannot load dashboard</p></div>`;
  }
}

function switchDashTab(tab) {
  dashboardTab = tab;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach((b, i) => { if ((['overview','providers','stress'])[i] === tab) b.classList.add('active'); });
  renderDashTab(tab);
}

function renderDashTab(tab) {
  const el = document.getElementById('dash-tab-content');
  if (!el || !dashData) return;

  if (tab === 'overview') {
    const { providers, summary, recs, es, dash } = dashData;
    el.innerHTML = `
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-value" style="color:var(--accent-light)">${dash.total_providers}</div><div class="stat-label">Providers</div></div>
        <div class="stat-card"><div class="stat-value" style="color:var(--success)">${Object.keys(summary).length}</div><div class="stat-label">Services</div></div>
        <div class="stat-card"><div class="stat-value" style="color:var(--warning)">${es.fairness_score || 100}%</div><div class="stat-label">Fairness</div></div>
        <div class="stat-card"><div class="stat-value" style="color:var(--info)">${providers.filter(p=>p.status==='available').length}</div><div class="stat-label">Available</div></div>
      </div>
      
      <!-- SVG Service Utilization Chart -->
      ${drawServiceUtilizationChart(summary)}
      
      <p class="section-title">Service Utilization Details</p>
      ${Object.entries(summary).map(([svc, s]) => `
        <div class="glass-card" style="padding:14px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span style="font-weight:600;text-transform:capitalize">${svc}</span>
            <span class="card-badge ${s.utilization_pct > 80 ? 'badge-danger' : s.utilization_pct > 50 ? 'badge-warning' : 'badge-success'}">${s.utilization_pct}%</span>
          </div>
          <div style="margin-top:8px;height:4px;background:var(--bg-input);border-radius:4px;overflow:hidden">
            <div style="width:${Math.min(100, s.utilization_pct)}%;height:100%;background:${s.utilization_pct > 80 ? 'var(--danger)' : 'var(--success)'};border-radius:4px;transition:width 0.5s ease"></div>
          </div>
          <div style="font-size:11px;color:var(--text-muted);margin-top:4px">${s.total_load}/${s.total_capacity} slots filled • ${s.providers} providers</div>
        </div>`).join('')}
      ${recs.length ? `<p class="section-title">Recommendations</p>${recs.map(r => `
        <div class="glass-card" style="padding:14px;margin-bottom:8px;border-left:3px solid ${r.priority === 'high' ? 'var(--danger)' : 'var(--warning)'}">
          <span class="card-badge ${r.priority === 'high' ? 'badge-danger' : 'badge-warning'}" style="margin-bottom:8px">${r.priority}</span>
          <p style="font-size:13px">${r.message}</p>
        </div>`).join('')}` : ''}`;

  } else if (tab === 'providers') {
    const { providers, earn } = dashData;
    const providerEarnings = earn?.provider_earnings || {};
    el.innerHTML = `
      <!-- SVG Provider Earnings Chart -->
      ${drawProviderEarningsChart(providers, providerEarnings)}
      
      <p class="section-title">All Providers</p>
      ${providers.map(p => {
        const pe = providerEarnings[p.id] || {};
        const statusColor = p.status === 'overloaded' ? 'var(--danger)' : p.status === 'busy' ? 'var(--warning)' : 'var(--success)';
        return `<div class="provider-dash-card">
          <div class="provider-dash-avatar">${p.name[0]}</div>
          <div class="provider-dash-info">
            <div class="provider-dash-name">${p.name}</div>
            <div class="provider-dash-service">${p.service} • <span style="color:${statusColor};font-weight:700">${p.status}</span></div>
          </div>
          <div class="provider-dash-stats">
            <div class="mini-stat"><div class="mini-stat-value">${p.rating || 'N/A'}</div><div class="mini-stat-label">Rating</div></div>
            <div class="mini-stat"><div class="mini-stat-value">${p.utilization_pct}%</div><div class="mini-stat-label">Util</div></div>
          </div>
        </div>`;
      }).join('')}`;

  } else if (tab === 'stress') {
    loadStressTests();
  }
}

// ==================== STRESS TESTS ====================
async function loadStressTests() {
  const el = document.getElementById('dash-tab-content');
  if (!el) return;
  el.innerHTML = '<div class="skeleton" style="height:200px"></div>';

  try {
    const res = await fetch(`${API_URL}/simulate/scenarios`);
    const data = await res.json();
    const scenarios = data.scenarios || [];

    el.innerHTML = `
      <button class="run-all-btn" id="run-all-btn" onclick="runAllStressTests()">
        🚀 Run All Stress Tests
      </button>
      <div id="stress-summary"></div>
      <div id="stress-scenarios">
        ${scenarios.map(s => `
          <div class="stress-card" id="stress-${s.id}">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <div>
                <div class="stress-title">${s.name}</div>
                <div class="stress-desc">${s.description}</div>
              </div>
              <button class="run-btn" onclick="runSingleTest('${s.id}')">Run</button>
            </div>
            <div class="stress-steps" id="steps-${s.id}"></div>
          </div>
        `).join('')}
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="empty-state"><span class="material-icons-round">cloud_off</span><p>Cannot load stress tests</p></div>`;
  }
}

async function runSingleTest(name) {
  const card = document.getElementById(`stress-${name}`);
  const stepsEl = document.getElementById(`steps-${name}`);
  if (!card || !stepsEl) return;

  card.classList.add('running');
  stepsEl.innerHTML = '<div class="skeleton" style="height:60px"></div>';

  try {
    const res = await fetch(`${API_URL}/simulate/run/${name}`, { method: 'POST' });
    const result = await res.json();
    card.classList.remove('running');
    renderTestResult(stepsEl, result);
  } catch (e) {
    card.classList.remove('running');
    stepsEl.innerHTML = `<div style="color:var(--danger);font-size:12px">❌ Error: ${e.message}</div>`;
  }
}

function renderTestResult(container, result) {
  const badge = result.status === 'passed' ? 'badge-success'
    : result.status === 'failed' ? 'badge-danger'
    : result.status === 'partial' ? 'badge-warning' : 'badge-info';

  container.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;margin-top:12px">
      <span class="card-badge ${badge}">${result.status}</span>
      <span style="font-size:11px;color:var(--text-muted)">${result.summary || ''}</span>
    </div>
    ${(result.steps || []).map(step => `
      <div class="stress-step">
        <div class="step-icon">${step.passed ? '✅' : '❌'}</div>
        <div class="step-detail">
          <strong>${step.step || step.input || 'Step'}</strong><br>
          ${Object.entries(step).filter(([k]) => !['passed', 'step', 'input'].includes(k)).map(([k, v]) =>
            `<span style="color:var(--text-muted)">${k}:</span> ${typeof v === 'object' ? JSON.stringify(v) : v}`
          ).join(' • ')}
        </div>
      </div>
    `).join('')}`;
}

async function runAllStressTests() {
  const btn = document.getElementById('run-all-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Running All Tests...'; }

  try {
    const res = await fetch(`${API_URL}/simulate/run-all`, { method: 'POST' });
    const data = await res.json();

    // Show summary
    const summaryEl = document.getElementById('stress-summary');
    if (summaryEl) {
      summaryEl.innerHTML = `
        <div class="test-summary">
          <div class="stat-card"><div class="stat-value" style="color:var(--success)">${data.passed}</div><div class="stat-label">Passed</div></div>
          <div class="stat-card"><div class="stat-value" style="color:var(--danger)">${data.failed}</div><div class="stat-label">Failed</div></div>
          <div class="stat-card"><div class="stat-value" style="color:var(--accent-light)">${data.pass_rate}</div><div class="stat-label">Rate</div></div>
        </div>`;
    }

    // Update individual cards
    for (const result of (data.results || [])) {
      const stepsEl = document.getElementById(`steps-${result.scenario}`);
      const card = document.getElementById(`stress-${result.scenario}`);
      if (!stepsEl || !card) continue;
      card.classList.remove('running');
      renderTestResult(stepsEl, result);
    }
  } catch (e) {
    alert('Error running stress tests: ' + e.message);
  }

  if (btn) { btn.disabled = false; btn.textContent = '🚀 Run All Stress Tests'; }
}
// ==================== GOOGLE MAPS INTEGRATION ====================
let map;
let markers = [];
let mapInitialized = false;

async function initMapScript() {
  if (mapInitialized) return;
  try {
    const res = await fetch(`${API_URL}/api/config`);
    const config = await res.json();
    if (!config.has_maps_key || !config.maps_api_key) {
      initializeMockVectorMap();
      return;
    }

    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${config.maps_api_key}&callback=initializeGoogleMap`;
    script.async = true;
    script.defer = true;
    window.initializeGoogleMap = initializeGoogleMap;
    document.head.appendChild(script);
  } catch (e) {
    console.error("Error loading map config:", e);
    initializeMockVectorMap();
  }
}

function initializeGoogleMap() {
  document.getElementById('map-placeholder').style.display = 'none';
  const mapEl = document.getElementById('google-map');
  mapEl.style.display = 'block';

  map = new google.maps.Map(mapEl, {
    center: { lat: USER_LAT, lng: USER_LNG },
    zoom: 13,
    styles: [
      { elementType: "geometry", stylers: [{ color: "#242f3e" }] },
      { elementType: "labels.text.stroke", stylers: [{ color: "#242f3e" }] },
      { elementType: "labels.text.fill", stylers: [{ color: "#746855" }] },
      {
        featureType: "road",
        elementType: "geometry",
        stylers: [{ color: "#38414e" }]
      },
      {
        featureType: "road",
        elementType: "geometry.stroke",
        stylers: [{ color: "#212a37" }]
      },
      {
        featureType: "road.highway",
        elementType: "geometry",
        stylers: [{ color: "#746855" }]
      },
      {
        featureType: "water",
        elementType: "geometry",
        stylers: [{ color: "#17263c" }]
      }
    ],
    disableDefaultUI: true,
  });

  mapInitialized = true;
  loadNearbyProviders('electrician'); // Load default

  // Add marker for user location
  new google.maps.Marker({
    position: { lat: USER_LAT, lng: USER_LNG },
    map,
    icon: {
      path: google.maps.SymbolPath.CIRCLE,
      scale: 10,
      fillColor: "#4285F4",
      fillOpacity: 1,
      strokeWeight: 2,
      strokeColor: "#ffffff",
    },
    title: "You are here"
  });
}

async function loadNearbyProviders(service) {
  if (!mapInitialized) return;
  
  if (!window.google) {
    loadNearbyProvidersMock(service);
    return;
  }
  
  // Clear existing markers
  markers.forEach(m => m.setMap(null));
  markers = [];

  try {
    const res = await fetch(`${API_URL}/api/nearby-providers?lat=${USER_LAT}&lng=${USER_LNG}&service=${service}&radius=5000`);
    const data = await res.json();
    
    const providers = [...(data.google_places || []), ...(data.platform_providers || [])];
    
    providers.forEach(p => {
      if (!p.lat || !p.lng) return;
      const marker = new google.maps.Marker({
        position: { lat: p.lat, lng: p.lng },
        map,
        title: p.name,
        icon: {
          url: p.source === 'google_places' ? 'https://maps.google.com/mapfiles/ms/icons/red-dot.png' : 'https://maps.google.com/mapfiles/ms/icons/blue-dot.png',
        }
      });
      
      marker.addListener('click', () => {
        showProviderPanel(p);
      });
      
      markers.push(marker);
    });
  } catch (e) {
    console.error("Error loading nearby providers", e);
  }
}

function showProviderPanel(p) {
  const panel = document.getElementById('provider-panel');
  const content = document.getElementById('provider-panel-content');
  panel.classList.remove('hidden');
  
  content.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
      <div>
        <h3 style="margin:0 0 4px 0">${p.name}</h3>
        <p style="margin:0; font-size:12px; color:var(--text-muted)">${p.service} • ${p.distance_km}km away</p>
      </div>
      <div style="background:var(--bg-input); padding:4px 8px; border-radius:12px; font-size:12px; font-weight:bold;">
        ${p.rating || 'New'} ⭐
      </div>
    </div>
    <p style="font-size:13px; margin-top:12px;">${p.address || ''}</p>
    <p style="font-size:13px; margin-top:8px;">Phone: <strong>${p.phone || 'Not publicly listed'}</strong></p>
    <button class="primary-btn" style="width:100%; margin-top:16px;" onclick="quickBook('${p.service}')">
      Request Service Here
    </button>
  `;
}

function quickBook(service) {
  document.getElementById('provider-panel').classList.add('hidden');
  showScreen('home');
  document.getElementById('chat-input').value = `I need a ${service} here.`;
  sendMessage();
}

// Attach map specific event listeners
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('nav-map')?.addEventListener('click', () => {
    initMapScript();
  });
  
  document.querySelectorAll('.filter-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      loadNearbyProviders(chip.dataset.service);
    });
  });
});

// ==================== NEW ENHANCEMENTS: MOCK MAP & SVG CHARTS & SMS CONSOLE ====================

function initializeMockVectorMap() {
  document.getElementById('map-placeholder').style.display = 'none';
  const mapEl = document.getElementById('google-map');
  mapEl.style.display = 'block';
  
  mapEl.innerHTML = `
    <div id="vector-map-container" style="position:relative; width:100%; height:100%; background:#17172c; overflow:hidden;">
      <svg width="100%" height="100%" style="position:absolute; top:0; left:0; pointer-events:none;">
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(255,255,255,0.03)" stroke-width="1"/>
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />
        
        <!-- Stylized Streets -->
        <line x1="0" y1="100" x2="500" y2="100" stroke="rgba(255,255,255,0.08)" stroke-width="8" />
        <line x1="120" y1="0" x2="120" y2="600" stroke="rgba(255,255,255,0.08)" stroke-width="10" />
        <line x1="0" y1="350" x2="500" y2="350" stroke="rgba(255,255,255,0.08)" stroke-width="6" />
        <line x1="300" y1="0" x2="300" y2="600" stroke="rgba(255,255,255,0.08)" stroke-width="8" />
        
        <!-- Parks / Green zones -->
        <rect x="20" y="140" width="80" height="180" rx="8" fill="rgba(16,185,129,0.05)" stroke="rgba(16,185,129,0.15)" stroke-width="1" />
        <rect x="340" y="50" width="100" height="120" rx="8" fill="rgba(16,185,129,0.05)" stroke="rgba(16,185,129,0.15)" stroke-width="1" />
        
        <!-- Water body -->
        <path d="M 0,500 Q 150,450 300,550 T 600,500" fill="none" stroke="rgba(59,130,246,0.1)" stroke-width="24" stroke-linecap="round" />
        
        <!-- User pulsing ring -->
        <circle cx="200" cy="250" r="12" fill="none" stroke="var(--info)" stroke-width="2" opacity="0.8">
          <animate attributeName="r" values="8;24" dur="2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.8;0" dur="2s" repeatCount="indefinite" />
        </circle>
        <!-- User point -->
        <circle cx="200" cy="250" r="6" fill="#3b82f6" stroke="#ffffff" stroke-width="2" />
      </svg>
      <!-- User Label -->
      <div style="position:absolute; top:215px; left:165px; background:rgba(10,10,26,0.85); padding:2px 8px; border-radius:10px; font-size:9px; font-weight:bold; border:1px solid var(--border); color:#3b82f6; white-space:nowrap;">You are here</div>
      
      <!-- Providers layer -->
      <div id="vector-map-pins" style="position:absolute; top:0; left:0; width:100%; height:100%;"></div>
    </div>
  `;
  
  mapInitialized = true;
  loadNearbyProvidersMock('electrician');
}

async function loadNearbyProvidersMock(service) {
  const pinsEl = document.getElementById('vector-map-pins');
  if (!pinsEl) return;
  pinsEl.innerHTML = '';
  
  try {
    const res = await fetch(`${API_URL}/api/nearby-providers?lat=${USER_LAT}&lng=${USER_LNG}&service=${service}&radius=5000`);
    const data = await res.json();
    const providers = [...(data.google_places || []), ...(data.platform_providers || [])];
    
    providers.forEach(p => {
      if (!p.lat || !p.lng) return;
      
      const latDiff = p.lat - USER_LAT;
      const lngDiff = p.lng - USER_LNG;
      const px = 200 + (lngDiff * 4000);
      const py = 250 - (latDiff * 4000);
      
      if (px < 10 || px > 390 || py < 10 || py > 490) return;
      
      const pin = document.createElement('div');
      pin.style.position = 'absolute';
      pin.style.left = `${px - 14}px`;
      pin.style.top = `${py - 28}px`;
      pin.style.cursor = 'pointer';
      pin.style.animation = 'fadeInUp 0.4s ease';
      
      const color = p.source === 'google_places' ? 'var(--danger)' : 'var(--accent-light)';
      
      pin.innerHTML = `
        <svg width="28" height="28" viewBox="0 0 24 24" style="filter: drop-shadow(0px 2px 4px rgba(0,0,0,0.5));">
          <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z" fill="${color}" />
        </svg>
      `;
      
      pin.addEventListener('click', () => {
        showProviderPanel(p);
      });
      
      pinsEl.appendChild(pin);
    });
  } catch (e) {
    console.error("Error loading nearby mock providers", e);
  }
}

function drawServiceUtilizationChart(summary) {
  const entries = Object.entries(summary);
  if (!entries.length) return '';
  const height = 140;
  const width = 320;
  const paddingLeft = 35;
  const paddingRight = 10;
  const paddingTop = 10;
  const paddingBottom = 20;
  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;
  const barWidth = chartWidth / entries.length - 10;
  
  let barsSvg = '';
  let labelsSvg = '';
  entries.forEach(([svc, s], i) => {
    const x = paddingLeft + i * (chartWidth / entries.length) + 5;
    const barHeight = (s.utilization_pct / 100) * chartHeight;
    const y = height - paddingBottom - barHeight;
    const color = s.utilization_pct > 80 ? 'url(#grad-red)' : s.utilization_pct > 50 ? 'url(#grad-yellow)' : 'url(#grad-green)';
    barsSvg += `
      <rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="4" fill="${color}" opacity="0.85">
        <animate attributeName="height" from="0" to="${barHeight}" dur="0.8s" fill="freeze" />
        <animate attributeName="y" from="${height - paddingBottom}" to="${y}" dur="0.8s" fill="freeze" />
      </rect>
      <text x="${x + barWidth/2}" y="${y - 4}" text-anchor="middle" fill="#ffffff" style="font-size:9px;font-weight:bold">${s.utilization_pct}%</text>
    `;
    const shortName = svc.length > 8 ? svc.substring(0, 6) + '..' : svc;
    labelsSvg += `
      <text x="${x + barWidth/2}" y="${height - 5}" text-anchor="middle" fill="var(--text-muted)" style="font-size:9px;text-transform:capitalize">${shortName}</text>
    `;
  });

  return `
    <div class="glass-card" style="padding:14px;margin-bottom:12px;text-align:center">
      <p style="font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:10px;text-align:left">📊 Service Demand Distribution</p>
      <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" style="overflow:visible">
        <defs>
          <linearGradient id="grad-green" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#10b981" />
            <stop offset="100%" stop-color="#059669" />
          </linearGradient>
          <linearGradient id="grad-yellow" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#f59e0b" />
            <stop offset="100%" stop-color="#d97706" />
          </linearGradient>
          <linearGradient id="grad-red" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#ef4444" />
            <stop offset="100%" stop-color="#dc2626" />
          </linearGradient>
        </defs>
        <line x1="${paddingLeft}" y1="${paddingTop}" x2="${width - paddingRight}" y2="${paddingTop}" stroke="rgba(255,255,255,0.05)" stroke-dasharray="2" />
        <line x1="${paddingLeft}" y1="${paddingTop + chartHeight/2}" x2="${width - paddingRight}" y2="${paddingTop + chartHeight/2}" stroke="rgba(255,255,255,0.05)" stroke-dasharray="2" />
        <line x1="${paddingLeft}" y1="${height - paddingBottom}" x2="${width - paddingRight}" y2="${height - paddingBottom}" stroke="rgba(255,255,255,0.15)" />
        
        <text x="${paddingLeft - 5}" y="${paddingTop + 4}" text-anchor="end" fill="var(--text-muted)" style="font-size:9px">100%</text>
        <text x="${paddingLeft - 5}" y="${paddingTop + chartHeight/2 + 4}" text-anchor="end" fill="var(--text-muted)" style="font-size:9px">50%</text>
        <text x="${paddingLeft - 5}" y="${height - paddingBottom + 4}" text-anchor="end" fill="var(--text-muted)" style="font-size:9px">0%</text>
        
        ${barsSvg}
        ${labelsSvg}
      </svg>
    </div>
  `;
}

function drawProviderEarningsChart(providers, providerEarnings) {
  const data = providers.map(p => {
    const pe = providerEarnings[p.id] || {};
    return {
      name: p.name,
      earnings: pe.total_earnings || 0
    };
  }).filter(d => d.earnings > 0).sort((a,b) => b.earnings - a.earnings);

  if (!data.length) return '';

  const barHeight = 20;
  const gap = 8;
  const paddingLeft = 90;
  const paddingRight = 40;
  const paddingTop = 10;
  const paddingBottom = 10;
  const width = 320;
  const height = paddingTop + paddingBottom + data.length * (barHeight + gap);
  const maxEarnings = Math.max(...data.map(d => d.earnings));
  const chartWidth = width - paddingLeft - paddingRight;

  let rowsSvg = '';
  data.forEach((d, i) => {
    const y = paddingTop + i * (barHeight + gap);
    const w = maxEarnings > 0 ? (d.earnings / maxEarnings) * chartWidth : 0;
    rowsSvg += `
      <text x="${paddingLeft - 8}" y="${y + barHeight/2 + 4}" text-anchor="end" fill="var(--text-primary)" style="font-size:10px;font-weight:600">${d.name}</text>
      <rect x="${paddingLeft}" y="${y}" width="${chartWidth}" height="${barHeight}" rx="4" fill="var(--bg-input)" opacity="0.3" />
      <rect x="${paddingLeft}" y="${y}" width="${w}" height="${barHeight}" rx="4" fill="url(#grad-earnings)">
        <animate attributeName="width" from="0" to="${w}" dur="0.8s" fill="freeze" />
      </rect>
      <text x="${paddingLeft + w + 5}" y="${y + barHeight/2 + 4}" fill="#ffffff" style="font-size:10px;font-weight:bold">Rs. ${d.earnings}</text>
    `;
  });

  return `
    <div class="glass-card" style="padding:14px;margin-bottom:12px">
      <p style="font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:10px">💰 Provider Earnings Comparison</p>
      <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" style="overflow:visible">
        <defs>
          <linearGradient id="grad-earnings" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stop-color="#3b82f6" />
            <stop offset="100%" stop-color="#8b5cf6" />
          </linearGradient>
        </defs>
        ${rowsSvg}
      </svg>
    </div>
  `;
}
