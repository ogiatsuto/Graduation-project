let companies = [];
let state = {
  company: null, mode: 'all', selectedQuestions: [],
  stream: null, mediaRecorder: null, chunks: [],
  qIndex: 0, followupCount: 0, dialogueHistory: [], recognition: null,
  deviceMonitor: null, // カメラ/マイクの生存状態を1秒ごとに監視するタイマーID
};
const MAX_FOLLOWUPS = 2;
const SILENCE_MS = 1800; // pause length that counts as "done speaking"

function showScreen(name) {
  document.querySelectorAll('main > section').forEach(s => s.classList.add('hidden'));
  document.getElementById('screen-' + name).classList.remove('hidden');
  document.getElementById('crumb').textContent = 'HOME > ' + ({ home: '面接練習', mode: '練習方法の選択', camera: 'カメラ確認', history: '練習履歴', playback: 'ログ確認' }[name] || '');
  if (name === 'home') renderHome();
  if (name === 'history') loadHistory();
}

async function loadCompanies() {
  const res = await fetch('/api/companies');
  companies = await res.json();
  renderHome();
}

function renderHome() {
  const list = document.getElementById('companyList');
  list.innerHTML = '';
  document.getElementById('homeEmpty').style.display = companies.length ? 'none' : 'block';
  companies.forEach(c => {
    const div = document.createElement('div');
    div.className = 'card row';
    div.innerHTML = `<div><h3>${c.name}</h3><p>過去の質問 ${c.questions.length}件</p></div>
      <button class="btn" onclick="selectCompany(${c.id})">面接練習を始める</button>`;
    list.appendChild(div);
  });
}

function selectCompany(id) {
  state.company = companies.find(c => c.id === id);
  state.mode = 'all';
  state.selectedQuestions = [...state.company.questions];
  document.getElementById('modeCompanyName').textContent = state.company.name;
  document.querySelector('input[name=mode][value=all]').checked = true;
  document.getElementById('questionPickBox').classList.add('hidden');
  renderQuestionPicker();
  showScreen('mode');
}

function renderQuestionPicker() {
  const box = document.getElementById('qList');
  box.innerHTML = '';
  state.company.questions.forEach((q, i) => {
    const row = document.createElement('label');
    row.className = 'qitem';
    row.innerHTML = `<input type="checkbox" value="${i}" checked onchange="onQCheck()"> ${q}`;
    box.appendChild(row);
  });
}
function onQCheck() {
  const checked = [...document.querySelectorAll('#qList input:checked')].map(i => +i.value);
  state.selectedQuestions = checked.map(i => state.company.questions[i]);
}
function onModeChange() {
  state.mode = document.querySelector('input[name=mode]:checked').value;
  document.getElementById('questionPickBox').classList.toggle('hidden', state.mode !== 'pick');
  state.selectedQuestions = state.mode === 'all'
    ? [...state.company.questions]
    : [...document.querySelectorAll('#qList input:checked')].map(i => state.company.questions[+i.value]);
}

// ---------- camera / mic check ----------

// トラックが「存在するだけ」でなく実際に使える状態かどうかを判定する。
// readyState === 'ended' はデバイス切断・停止、muted === true はOS側での
// 一時的な無効化（ハードウェアスイッチ等）を意味するため、どちらも false 扱いにする。
function isTrackLive(track) {
  return !!track && track.readyState === 'live' && !track.muted;
}

function updateDeviceStatus() {
  if (!state.stream) return;
  const camOk = isTrackLive(state.stream.getVideoTracks()[0]);
  const micOk = isTrackLive(state.stream.getAudioTracks()[0]);
  document.getElementById('camDot').className = 'dot ' + (camOk ? 'ok' : 'bad');
  document.getElementById('micDot').className = 'dot ' + (micOk ? 'ok' : 'bad');
  document.getElementById('startBtn').disabled = !(camOk && micOk);
}

function stopDeviceMonitor() {
  if (state.deviceMonitor) {
    clearInterval(state.deviceMonitor);
    state.deviceMonitor = null;
  }
}

async function goToCameraCheck() {
  if (state.mode === 'pick' && state.selectedQuestions.length === 0) { alert('質問を1つ以上選択してください'); return; }
  showScreen('camera');
  stopDeviceMonitor();
  document.getElementById('camDot').className = 'dot';
  document.getElementById('micDot').className = 'dot';
  document.getElementById('startBtn').disabled = true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    state.stream = stream;
    document.getElementById('preview').srcObject = stream;
    updateDeviceStatus();
    state.deviceMonitor = setInterval(updateDeviceStatus, 1000);
  } catch (e) {
    document.getElementById('camDot').className = 'dot bad';
    document.getElementById('micDot').className = 'dot bad';
    alert('カメラ・マイクにアクセスできませんでした。ブラウザの権限設定をご確認ください。');
  }
}

function speakOnce(text, onEnd) {
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'ja-JP';
    u.onend = onEnd || null;
    u.onerror = onEnd || null;
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  } catch (e) { if (onEnd) onEnd(); }
}

function speechRecognitionSupported() {
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
}

// ---------- interview flow ----------
function startInterview() {
  stopDeviceMonitor(); // カメラ確認画面用の監視はここで停止する
  document.getElementById('interview').style.display = 'block';
  document.getElementById('ivideo').srcObject = state.stream;
  document.getElementById('ivCompany').textContent = state.company.name;
  document.getElementById('ivQtext').textContent = 'まもなく開始します…';
  speakOnce('これから面接を始めます', () => askQuestion(0));
}

function askQuestion(i) {
  if (i >= state.selectedQuestions.length) return endInterview(false);
  if (state.mediaRecorder && state.mediaRecorder.state === 'recording') state.mediaRecorder.stop();

  state.qIndex = i;
  state.followupCount = 0;
  state.dialogueHistory = [];
  const q = state.selectedQuestions[i];
  document.getElementById('ivProgress').textContent = `質問 ${i + 1} / ${state.selectedQuestions.length}`;
  document.getElementById('ivQtext').textContent = q;
  document.getElementById('answerBox').classList.add('hidden');
  document.getElementById('fallbackBox').classList.add('hidden');

  beginRecording(q);
  speakOnce(q, () => listenForAnswer());
}

function beginRecording(question) {
  state.chunks = [];
  try {
    state.mediaRecorder = new MediaRecorder(state.stream);
    state.mediaRecorder.ondataavailable = e => { if (e.data.size > 0) state.chunks.push(e.data); };
    state.mediaRecorder.onstop = () => uploadRecording(question, new Blob(state.chunks, { type: 'video/webm' }));
    state.mediaRecorder.start();
  } catch (e) { /* recording unsupported; continue without saving video */ }
}

async function uploadRecording(question, blob) {
  const form = new FormData();
  form.append('company', state.company.name);
  form.append('question', question);
  form.append('video', blob, 'answer.webm');
  try { await fetch('/api/logs', { method: 'POST', body: form }); }
  catch (e) { console.error('録画のアップロードに失敗しました', e); }
}

function listenForAnswer() {
  document.getElementById('ivQtext').textContent = state.dialogueHistory.length
    ? state.dialogueHistory[state.dialogueHistory.length - 1].text
    : state.selectedQuestions[state.qIndex];
  document.getElementById('answerBox').classList.remove('hidden');
  document.getElementById('recIndicator').classList.remove('hidden');
  document.getElementById('liveCaption').textContent = '';
  document.getElementById('manualSendBtn').classList.remove('hidden');

  if (!speechRecognitionSupported()) {
    document.getElementById('recIndicator').classList.add('hidden');
    document.getElementById('answerBox').classList.add('hidden');
    document.getElementById('fallbackBox').classList.remove('hidden');
    document.getElementById('fallbackText').value = '';
    document.getElementById('fallbackText').focus();
    return;
  }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rec = new SR();
  rec.lang = 'ja-JP';
  rec.interimResults = true;
  rec.continuous = true;
  let finalText = '';
  let silenceTimer = null;
  let finished = false;

  const finish = () => {
    if (finished) return;
    finished = true;
    clearTimeout(silenceTimer);
    clearTimeout(hardTimer);
    try { rec.onend = null; rec.stop(); } catch (e) {}
    document.getElementById('recIndicator').classList.add('hidden');
    document.getElementById('manualSendBtn').classList.add('hidden');
    handleAnswer(finalText.trim() || document.getElementById('liveCaption').textContent.trim());
  };

  // Start the "user has gone quiet" clock right away, not just after the
  // first recognized word — otherwise silence (mic not picked up, etc.)
  // never times out and the app appears to hang forever.
  silenceTimer = setTimeout(finish, SILENCE_MS + 2500);
  // Absolute safety net in case the recognizer never fires onend at all.
  const hardTimer = setTimeout(finish, 20000);

  rec.onresult = (e) => {
    let interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) finalText += t; else interim += t;
    }
    document.getElementById('liveCaption').textContent = finalText + interim;
    clearTimeout(silenceTimer);
    silenceTimer = setTimeout(finish, SILENCE_MS);
  };
  rec.onerror = (e) => {
    console.error('SpeechRecognition error:', e.error);
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed' || e.error === 'audio-capture') {
      // Permanent failure: switch straight to the text fallback instead of retrying.
      clearTimeout(silenceTimer); clearTimeout(hardTimer);
      finished = true;
      document.getElementById('recIndicator').classList.add('hidden');
      document.getElementById('manualSendBtn').classList.add('hidden');
      document.getElementById('answerBox').classList.add('hidden');
      document.getElementById('fallbackBox').classList.remove('hidden');
      document.getElementById('fallbackText').focus();
      return;
    }
    finish();
  };
  rec.onend = finish;

  document.getElementById('manualSendBtn').onclick = finish;

  state.recognition = rec;
  try { rec.start(); } catch (e) { finish(); }
}

function submitFallbackAnswer() {
  const text = document.getElementById('fallbackText').value.trim();
  document.getElementById('fallbackBox').classList.add('hidden');
  handleAnswer(text);
}

async function handleAnswer(answerText) {
  if (!answerText) answerText = '（発言を聞き取れませんでした）';
  state.dialogueHistory.push({ role: 'student', text: answerText });
  document.getElementById('ivQtext').textContent = '回答を確認しています…';

  const turn = await fetchInterviewerReply();
  state.dialogueHistory.push({ role: 'interviewer', text: turn.reply });
  document.getElementById('ivQtext').textContent = turn.reply;

  speakOnce(turn.reply, () => {
    if (turn.move_on || state.followupCount >= MAX_FOLLOWUPS) {
      askQuestion(state.qIndex + 1);
    } else {
      state.followupCount++;
      listenForAnswer();
    }
  });
}

async function fetchInterviewerReply() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  try {
    const res = await fetch('/api/interview/reply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        question: state.selectedQuestions[state.qIndex],
        company: state.company.name,
        history: state.dialogueHistory,
        followup_count: state.followupCount,
      }),
    });
    clearTimeout(timer);
    if (!res.ok) throw new Error('server returned ' + res.status);
    return await res.json();
  } catch (e) {
    clearTimeout(timer);
    console.error('AI応答の取得に失敗しました（Ollamaが起動しているか確認してください）:', e);
    return { reply: 'ありがとうございます。次の質問に移ります。', move_on: true };
  }
}

function endInterview(aborted) {
  if (state.recognition) { try { state.recognition.onend = null; state.recognition.stop(); } catch (e) {} }
  if (state.mediaRecorder && state.mediaRecorder.state === 'recording') state.mediaRecorder.stop();
  speechSynthesis.cancel();
  document.getElementById('interview').style.display = 'none';
  if (!aborted) alert('お疲れ様でした。面接練習が終了しました。録画は「練習履歴」から確認できます。');
  showScreen('history');
}

// ---------- history ----------
async function loadHistory() {
  const box = document.getElementById('logList');
  const emptyMsg = document.getElementById('historyEmpty');
  box.innerHTML = '';
  try {
    const res = await fetch('/api/logs');
    const logs = await res.json();
    window.__logs = logs;
    emptyMsg.classList.toggle('hidden', logs.length > 0);
    logs.forEach(l => {
      const row = document.createElement('div');
      row.className = 'logrow';
      row.onclick = () => openLog(l.id);
      row.innerHTML = `<div><h3 style="margin:0 0 4px;font-size:15px;">${l.company}</h3><p style="margin:0;font-size:13px;color:#666;">${l.question}</p></div><span style="font-size:12px;color:#888;">${l.created_at}</span>`;
      box.appendChild(row);
    });
  } catch (e) {
    emptyMsg.classList.remove('hidden');
  }
}
function openLog(id) {
  const l = (window.__logs || []).find(x => x.id === id);
  if (!l) return;
  document.getElementById('pbMeta').textContent = `${l.company} ｜ ${l.question} ｜ ${l.created_at}`;
  document.getElementById('pbVideo').src = l.video_url;
  showScreen('playback');
}

loadCompanies();