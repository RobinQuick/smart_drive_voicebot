// ===== Smart Drive Voice Bot - main.js (clean UTF-8) =====
console.log("[boot] main.js v1.3 loaded");

// ---------- State ----------
// Default to Netlify proxied path "/api". You can override in UI.
let BACKEND = localStorage.getItem('backendUrl') || '/api';
let token = null;
let pc = null;
let localStream = null;
let audioCtx = null;
let processedTrack = null;
let dc = null; // data channel for realtime events

let currentOrder = { lines: [], notes: [] };
let vadSilenceTimer = null;
let currentTranscript = '';
let muteWhileTalking = true;

// ---------- Helpers UI ----------
function $(id){ return document.getElementById(id); }

function appendLog(kind, msg){
  const box = $('log');
  if (!box) return;
  const line = document.createElement('div');
  line.textContent = `[${kind}] ${msg}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function nameFromSKU(sku){
  return String(sku || '')
    .replace(/_/g,' ')
    .toLowerCase()
    .replace(/\b\w/g, c=>c.toUpperCase());
}

function renderMods(mods = {}){
  const keys = Object.keys(mods||{});
  if (!keys.length) return '';
  const parts = keys.map(k => `${k}: ${String(mods[k])}`);
  return `<div style="color:#666; font-size:0.9em;">${parts.join(' · ')}</div>`;
}

function renderOrder(){
  const tbody = document.querySelector('#orderTable tbody');
  const notes = $('orderNotes');
  if (!tbody) return;

  tbody.innerHTML = '';
  let totalQty = 0;
  (currentOrder.lines || []).forEach(l=>{
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td style="padding:6px 4px; border-bottom:1px solid #f2f2f2;">
        <div class="line-name"><strong>${nameFromSKU(l.sku)}</strong></div>
        ${renderMods(l.mods)}
      </td>
      <td style="padding:6px 4px; text-align:right; border-bottom:1px solid #f2f2f2;"><span class="qty-pill">${l.qty || 1}</span></td>
    `;
    tbody.appendChild(tr);
    totalQty += (l.qty || 1);
  });

  // Summary banner
  const panel = document.querySelector('#orderPanel');
  if (panel){
    let summaryEl = document.querySelector('#orderSummary');
    if (!summaryEl){
      summaryEl = document.createElement('div');
      summaryEl.id = 'orderSummary';
      summaryEl.style.cssText = 'margin:8px 0; font-weight:600;';
      panel.insertBefore(summaryEl, panel.querySelector('#orderNotes'));
    }
    summaryEl.textContent = `Total articles: ${totalQty} • Total: —`;
  }

  const tips = (currentOrder.notes || []).map(n=>`• ${n}`).join('<br>');
  notes.innerHTML = tips ? `<div><em>Conseils/upsell :</em><br>${tips}</div>` : '';

  // no CTA: this screen is display-only for the customer
}

// ---------- Backend ----------
function setBackend(url){
  BACKEND = url;
  localStorage.setItem('backendUrl', url);
}

async function fetchToken(){
  const r = await fetch(`${BACKEND}/token`);
  const txt = await r.text();
  appendLog('debug', `GET /token -> ${r.status} ${txt.slice(0,140)}`);
  if (!r.ok) throw new Error(`/token ${r.status}: ${txt}`);
  return JSON.parse(txt);
}

async function analyzeTextWithNLU(text){
  const clean = (text || '').trim();
  if (!clean) return;
  const r = await fetch(`${BACKEND}/nlu`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ utterance: clean })
  });
  const txt = await r.text();
  appendLog('debug', `/nlu -> ${r.status} ${txt.slice(0,140)}`);
  if (!r.ok) throw new Error(`/nlu ${r.status}: ${txt}`);
  const data = JSON.parse(txt);

  currentOrder = data.order ? data.order : data;
  renderOrder();
  if (document.getElementById('orderRecap')) updateRecap();

  const hasErrors = Array.isArray(data.errors) && data.errors.length > 0;
  const sendBtn = $('sendToKitchen');
  if (sendBtn) sendBtn.disabled = !!hasErrors;
  if (hasErrors) appendLog('warn', `Validation: ${data.errors.join(' | ')}`);
}

async function sendToKitchen(){
  const btn = $('sendToKitchen');
  if (btn) btn.disabled = true;
  const r = await fetch(`${BACKEND}/pos/order`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ order: currentOrder })
  });
  const txt = await r.text();
  if (!r.ok){
    appendLog('error', `POS refused ${r.status}: ${txt}`);
    alert("Impossible d'envoyer : précisions requises ou limites dépassées.");
    if (btn) btn.disabled = false;
    return;
  }
  const data = JSON.parse(txt);
  appendLog('pos', `OK. Ticket envoyé: ${data.ticket_id || JSON.stringify(data)}`);
}

// ---------- Audio processing (VAD + ducking + watchdog) ----------
let modelAudio = (document.getElementById('remote') || new Audio());
modelAudio.autoplay = true;
let userTalking = false;
let lastSpeechTs = 0;    // last moment user was speaking
let duckTimer = null;    // watchdog to restore volume

function smoothRMS(prev, next, alpha = 0.2) {
  return (1 - alpha) * prev + alpha * next;
}

function attachVAD(ctx, sourceNode, outNode, {
  startThreshold = 0.06,
  stopThreshold  = 0.03,
  minActiveMs    = 300,
  holdMs         = 500
} = {}) {
  const proc = ctx.createScriptProcessor(1024, 1, 1);
  let opened = false;
  let lastAbove = 0;
  let lastChange = 0;
  let ema = 0;

  proc.onaudioprocess = (e) => {
    const inp = e.inputBuffer.getChannelData(0);
    const out = e.outputBuffer.getChannelData(0);

    // RMS
    let sum = 0;
    for (let i = 0; i < inp.length; i++) sum += inp[i] * inp[i];
    const rms = Math.sqrt(sum / inp.length);
    ema = smoothRMS(ema, rms, 0.15);

    const now = performance.now();

    if (!opened) {
      if (ema >= startThreshold) {
        if (lastAbove === 0) lastAbove = now;
        if (now - lastAbove >= minActiveMs) {
          opened = true;
          lastChange = now;
          lastSpeechTs = Date.now();
          onVadChange(true);
        }
      } else { lastAbove = 0; }
    } else {
      if (ema < stopThreshold && (now - lastChange) > holdMs) {
        opened = false;
        lastAbove = 0;
        lastChange = now;
        onVadChange(false);
      } else {
        lastSpeechTs = Date.now();
      }
    }

    out.set(inp); // always forward mic to model
  };

  sourceNode.connect(proc).connect(outNode);
  return proc;
}

function maybeFlushTranscript(reason){
  const text = (currentTranscript || '').trim();
  if (text.length >= 2){
    appendLog('user', text + (reason ? ` (${reason})` : ''));
    analyzeTextWithNLU(text).catch(e=>appendLog('error', e.message||String(e)));
  }
  currentTranscript = '';
  const tEl = document.getElementById('transcript');
  if (tEl) tEl.textContent = '';
}

function onVadChange(isTalking) {
  userTalking = isTalking;
  try {
    if (isTalking) {
      lastSpeechTs = Date.now();
      modelAudio.volume = 0.5; // softer ducking while user talks
      modelAudio.muted = !!muteWhileTalking;
      if (duckTimer) clearInterval(duckTimer);
      duckTimer = setInterval(() => {
        if (Date.now() - lastSpeechTs > 1400) { // 1.4s silence => restore
          modelAudio.volume = 1.0;
          modelAudio.muted = false;
          clearInterval(duckTimer);
          duckTimer = null;
          userTalking = false;
        }
      }, 300);
    } else {
      modelAudio.volume = 1.0; // end of talk => restore
      modelAudio.muted = false;
      if (duckTimer) { clearInterval(duckTimer); duckTimer = null; }

      // Give a small grace period, then flush transcript if any
      if (vadSilenceTimer) clearTimeout(vadSilenceTimer);
      vadSilenceTimer = setTimeout(()=> maybeFlushTranscript('VAD'), 600);
    }
  } catch (e) {}
}

async function getProcessedMicTrack(pc){
  localStream = await navigator.mediaDevices.getUserMedia({
    audio:{
      channelCount:1,
      sampleRate:48000,
      sampleSize:16,
      noiseSuppression:true,
      echoCancellation:true,
      autoGainControl:true,
      suppressLocalAudioPlayback:true
    }
  });

  audioCtx = new AudioContext({ sampleRate:48000 });
  const src = audioCtx.createMediaStreamSource(localStream);

  const hpf = audioCtx.createBiquadFilter();
  hpf.type='highpass'; hpf.frequency.value = 150;

  const comp = audioCtx.createDynamicsCompressor();
  comp.threshold.value=-28; comp.knee.value=20; comp.ratio.value=3;
  comp.attack.value=0.003; comp.release.value=0.12;

  const vadOut = audioCtx.createGain();
  attachVAD(audioCtx, src, vadOut, { startThreshold:0.06, stopThreshold:0.03, minActiveMs:300, holdMs:500 });

  vadOut.connect(hpf).connect(comp);

  const dest = audioCtx.createMediaStreamDestination();
  comp.connect(dest);

  const track = dest.stream.getAudioTracks()[0];
  const sender = pc.addTrack(track, dest.stream);

  try{
    const params = sender.getParameters();
    params.encodings = params.encodings || [{}];
    // Smoother continuous audio to reduce cut-offs
    Object.assign(params.encodings[0], { dtx:false, ptime:20, maxBitrate:32000 });
    await sender.setParameters(params);
  }catch(e){
    console.warn('Opus params set failed:', e);
  }

  processedTrack = track;
  return track;
}

// ---------- Realtime events parsing ----------
function handleRealtimeMessage(data){
  // messages may be JSON or NDJSON
  const chunks = String(data).split(/\n+/).filter(Boolean);
  for (const ch of chunks){
    let obj = null;
    try { obj = JSON.parse(ch); } catch { continue; }
    const type = obj.type || obj.event || '';

    if (/transcript|input/i.test(type)){
      if (typeof obj.delta === 'string'){
        currentTranscript += obj.delta;
      } else if (typeof obj.text === 'string'){
        currentTranscript = obj.text;
      } else if (typeof obj.transcript === 'string'){
        currentTranscript = obj.transcript;
      }
      const tEl = document.getElementById('transcript');
      if (tEl) tEl.textContent = currentTranscript;
      if (/complete|completed|final|done/i.test(type)){
        maybeFlushTranscript('final');
      }
    }

    // Some responses may include user role content
    if (obj.role === 'user'){
      const t = (obj.text || (obj.content && obj.content[0] && obj.content[0].text) || '').trim();
      if (t) { currentTranscript = t; maybeFlushTranscript('user'); }
    }
  }
}

// ---------- WebRTC Realtime ----------
async function connectRealtime(){
  appendLog('info', 'Connexion');

  token = await fetchToken();

  pc = new RTCPeerConnection({ iceServers:[{urls:['stun:stun.l.google.com:19302']}] });

  pc.oniceconnectionstatechange = () => {
    appendLog('webrtc', `ice=${pc.iceConnectionState}`);
    if (pc.iceConnectionState === 'failed' || pc.iceConnectionState === 'disconnected') {
      appendLog('error', 'Connexion audio interrompue. Cliquez Reconnect.');
    }
  };

  pc.ontrack = (ev)=>{ modelAudio.srcObject = ev.streams[0]; appendLog('webrtc','ontrack'); };

  pc.ondatachannel = (ev)=>{
    appendLog('webrtc', `datachannel:${ev.channel.label}`);
    ev.channel.onmessage = (e)=> handleRealtimeMessage(e.data);
  };
  // Create a channel as well (some servers expect the client to open it)
  dc = pc.createDataChannel('oai-events');
  dc.onmessage = (e)=> handleRealtimeMessage(e.data);

  await getProcessedMicTrack(pc);

  const offer = await pc.createOffer({offerToReceiveAudio:true});
  await pc.setLocalDescription(offer);

  const sdpRes = await fetch(`https://api.openai.com/v1/realtime?model=${encodeURIComponent('gpt-4o-realtime-preview')}`, {
    method:'POST',
    body: offer.sdp,
    headers:{
      'Authorization': `Bearer ${token.client_secret}`,
      'Content-Type':'application/sdp',
      'OpenAI-Beta':'realtime=v1'
    }
  });
  const sdpText = await sdpRes.text();
  appendLog('debug', `OpenAI SDP status=${sdpRes.status}`);
  if (!sdpRes.ok) throw new Error(`Realtime SDP failed: ${sdpText}`);

  await pc.setRemoteDescription({ type:'answer', sdp: sdpText });
  appendLog('info', 'Connecte.');
}

async function startTalking(){
  appendLog('agent','Pret. Parlez quand vous voulez.');
}

async function reconnect(){
  try { if (pc) pc.close(); } catch {}
  await connectRealtime();
}

// ---------- Wire UI ----------
window.addEventListener('DOMContentLoaded', ()=>{
  if ($('backendUrl')) $('backendUrl').value = BACKEND;

  if ($('saveBackend')) $('saveBackend').onclick = ()=>{
    const v = $('backendUrl').value.trim();
    if (!/^https?:\/\//i.test(v)) { alert('URL invalide'); return; }
    setBackend(v);
    appendLog('info', `Backend: ${v}`);
  };

  if ($('connectBtn')) $('connectBtn').onclick = async ()=>{
    try{
      const url = $('backendUrl').value.trim();
      if (url) setBackend(url);
      await connectRealtime();
      $('startBtn').disabled = false;
    }catch(e){
      console.error(e);
      appendLog('error', e.message || String(e));
      alert(`Erreur Connect: ${e.message || e}`);
    }
  };

  if ($('startBtn')) $('startBtn').onclick = async ()=>{
    try{ await startTalking(); }catch(e){ appendLog('error', e.message || String(e)); }
  };

  if ($('nluSend')) $('nluSend').onclick = async ()=>{
    const txt = ($('nluText').value || '').trim();
    if (!txt) return;
    appendLog('user', txt);
    try{ await analyzeTextWithNLU(txt); }catch(e){ appendLog('error', e.message || String(e)); }
  };

  if ($('sendToKitchen')) $('sendToKitchen').onclick = sendToKitchen;
  if ($('clearOrder')) $('clearOrder').onclick = ()=>{
    currentOrder = { lines: [], notes: [] };
    renderOrder();
    if (document.getElementById('orderRecap')) updateRecap();
  };

  // Mute agent while user speaks (toggle)
  if (document.getElementById('muteToggle')){
    const el = document.getElementById('muteToggle');
    muteWhileTalking = !!el.checked;
    el.addEventListener('change', ()=>{ muteWhileTalking = !!el.checked; });
  }

  appendLog('info','UI prete. Configure le Backend, puis Connect -> Start Talking.');
});

// ---------- Recap helpers ----------
function updateRecap(){
  const el = document.getElementById('orderRecap');
  if (!el) return;
  el.textContent = buildRecapSentence(currentOrder);
}

function buildRecapSentence(order){
  const lines = order && order.lines ? order.lines : [];
  if (!lines.length) return '';
  const parts = lines.map(l => {
    const qty = l.qty || 1;
    const name = nameFromSKU(l.sku);
    const mods = l.mods || {};
    const modParts = [];
    if (mods.size) modParts.push(`taille ${mods.size}`);
    if (mods.drink) modParts.push(`${mods.drink}`);
    if (mods.fries) modParts.push(`frites ${mods.fries}`);
    if (mods.onions === false) modParts.push('sans oignons');
    const modText = modParts.length ? ` (${modParts.join(', ')})` : '';
    return `${qty}× ${name}${modText}`;
  });
  return `Vous avez commandé: ${parts.join('; ')}.`;
}
