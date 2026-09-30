const adviceHistoryKey = 'puti-interview-advice-history';
let companies = [];
let state = {
  company: null, mode: 'all', selectedQuestions: [],
  stream: null, mediaRecorder: null, chunks: [],
  qIndex: 0, followupCount: 0, dialogueHistory: [], recognition: null,
  interviewActive: false, interviewController: null,
  deviceMonitor: null, // カメラ/マイクの生存状態を1秒ごとに監視するタイマーID
  adviceHistory: loadAdviceHistory(),
};
const MAX_FOLLOWUPS = 2;

function showScreen(name) {
  document.querySelectorAll('main > section').forEach(s => s.classList.add('hidden'));
  document.getElementById('screen-' + name).classList.remove('hidden');
  document.getElementById('crumb').textContent = 'HOME > ' + ({ home: '面接練習', mode: '質問選択', camera: 'カメラ確認', history: '練習履歴', advice: 'アドバイス履歴', playback: 'ログ確認' }[name] || '');
  if (name === 'home') renderHome();
  if (name === 'history') loadHistory();
  if (name === 'advice') renderAdviceHistory();
}

function loadAdviceHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(adviceHistoryKey) || '[]');
    return Array.isArray(saved) ? saved : [];
  } catch (e) {
    return [];
  }
}

function saveAdviceHistory() {
  localStorage.setItem(adviceHistoryKey, JSON.stringify(state.adviceHistory.slice(0, 100)));
}

function escapeAdviceText(value) {
  return String(value || '').replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
}

function adviceItemText(value) {
  if (value && typeof value === 'object') {
    value = value.value || value.text || value.content || '';
  }
  if (typeof value !== 'string') return '';
  const text = value.trim();
  if (text.startsWith('{') || text.startsWith('[')) {
    try {
      const parsed = JSON.parse(text);
      return adviceItemText(parsed);
    } catch (e) {
      return text.replace(/[{}\[\]"]/g, '').replace(/\b(key|value|strengths|improvements|tips)\s*:/g, '').trim();
    }
  }
  return text.replace(/^#+\s*/, '').replace(/^[-*]\s*/, '').trim();
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
  state.selectedQuestions = getDefaultQuestionIndexes().map(index => state.company.questions[index]);
  document.getElementById('modeCompanyName').textContent = state.company.name;
  renderQuestionPicker();
  showScreen('mode');
}

function getDefaultQuestionIndexes() {
  return state.company.questions
    .map((question, index) => ({ question, index }))
    .sort((a, b) => {
      const aIsIntroduction = /自己紹介|自己PR/.test(a.question);
      const bIsIntroduction = /自己紹介|自己PR/.test(b.question);
      return Number(bIsIntroduction) - Number(aIsIntroduction);
    })
    .map(item => item.index);
}

function renderQuestionPicker() {
  const box = document.getElementById('qList');
  const randomCheckbox = document.getElementById('randomQuestion');
  const randomCount = document.getElementById('randomCount');
  randomCheckbox.checked = false;
  randomCount.disabled = true;
  randomCount.innerHTML = state.company.questions.map((question, index) => `<option value="${index + 1}">${index + 1}</option>`).join('');
  box.innerHTML = '';
  getDefaultQuestionIndexes().slice(1).forEach(i => {
    const q = state.company.questions[i];
    const row = document.createElement('label');
    row.className = 'qitem';
    row.innerHTML = `<input type="checkbox" value="${i}" checked onchange="onQCheck()"> ${q}`;
    box.appendChild(row);
  });
}
function onQCheck() {
  document.getElementById('randomQuestion').checked = false;
  document.getElementById('randomCount').disabled = true;
  const defaultIndexes = getDefaultQuestionIndexes();
  const firstQuestionIndex = defaultIndexes[0];
  const inputs = [...document.querySelectorAll('#qList input[type="checkbox"]')];
  const checked = new Set(inputs.filter(input => input.checked).map(input => +input.value));
  state.selectedQuestions = [firstQuestionIndex, ...defaultIndexes.slice(1)
    .filter(index => checked.has(index))
  ].map(index => state.company.questions[index]);
}
function selectRandomQuestion() {
  const randomCheckbox = document.getElementById('randomQuestion');
  const randomCount = document.getElementById('randomCount');
  if (!randomCheckbox.checked) {
    randomCount.disabled = true;
    onQCheck();
    return;
  }
  randomCount.disabled = false;
  const count = Math.min(Number(randomCount.value), state.company.questions.length);
  const defaultIndexes = getDefaultQuestionIndexes();
  const firstQuestionIndex = defaultIndexes[0];
  const randomIndexes = defaultIndexes.slice(1)
    .sort(() => Math.random() - 0.5)
    .slice(0, count - 1);
  document.querySelectorAll('#qList input[type="checkbox"]').forEach(input => {
    input.checked = false;
  });
  state.selectedQuestions = [firstQuestionIndex, ...randomIndexes]
    .map(index => state.company.questions[index]);
}
function selectAllQuestions() {
  document.getElementById('randomQuestion').checked = false;
  document.getElementById('randomCount').disabled = true;
  document.querySelectorAll('#qList input[type="checkbox"]').forEach(input => { input.checked = true; });
  onQCheck();
}
function clearAllQuestions() {
  document.getElementById('randomQuestion').checked = false;
  document.getElementById('randomCount').disabled = true;
  document.querySelectorAll('#qList input[type="checkbox"]').forEach(input => { input.checked = false; });
  onQCheck();
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
  if (state.selectedQuestions.length === 0) { alert('質問を1つ以上選択してください'); return; }
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
  function selectRandomQuestion() {
    const randomCheckbox = document.getElementById('randomQuestion');
    if (!randomCheckbox.checked) {
      onQCheck();
      return;
    }
    const randomIndex = Math.floor(Math.random() * state.company.questions.length);
    document.querySelectorAll('#qList input[type="checkbox"]').forEach((input, index) => {
      input.checked = index === randomIndex;
    });
    state.selectedQuestions = [state.company.questions[randomIndex]];
  }
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

async function requestAdvice(answer, question) {
  const controller = new AbortController();
  state.interviewController = controller;
  try {
    const response = await fetch('/api/interview-advice', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        answer,
        question,
        followup_count: state.followupCount,
        dialogue_history: state.dialogueHistory,
      }),
    });
    if (!response.ok) throw new Error('advice request failed');
    return await response.json();
  } catch (e) {
    return {
      summary: '回答を確認しました。具体的な行動と結果をセットで伝えると、さらに説得力が増します。',
      strengths: ['自分の言葉で経験を説明しようとしています。'],
      improvements: ['「自分が何をしたか」を一つ具体的に説明しましょう。'],
      tips: ['結論・行動・結果・学びの順に整理して話しましょう。'],
      criteria: [],
    };
  } finally {
    if (state.interviewController === controller) state.interviewController = null;
  }
}

function renderAdviceHistory() {
  const list = document.getElementById('adviceHistoryList');
  const empty = document.getElementById('adviceHistoryEmpty');
  if (!list || !empty) return;
  empty.classList.toggle('hidden', state.adviceHistory.length > 0);
  list.innerHTML = state.adviceHistory.slice().reverse().map((entry, index) => {
    const advice = entry.advice || {};
    const items = (values, fallback) => (values && values.length ? values : [fallback]).map(value => `<li>${escapeAdviceText(adviceItemText(value))}</li>`).join('');
    const criteriaStatus = { good: '良好', needs_improvement: '改善が必要', not_applicable: '対象外' };
    const criteria = (advice.criteria || []).map(item => `<article class="criteria-item ${escapeAdviceText(item.status || '')}">
      <div class="criteria-heading"><strong>${escapeAdviceText(item.label)}</strong><span>${escapeAdviceText(criteriaStatus[item.status] || '確認中')}${item.score !== null && item.score !== undefined ? `・${escapeAdviceText(item.score)}点` : ''}</span></div>
      <small>${escapeAdviceText(item.method)}</small>
      <p><b>根拠：</b>${escapeAdviceText(item.evidence)}</p>
      <p><b>改善：</b>${escapeAdviceText(item.feedback)}</p>
    </article>`).join('');
    const summary = adviceItemText(advice.summary || '回答を確認しました。');
    return `<article class="advice-history-card">
      <div class="advice-history-meta"><strong>${escapeAdviceText(entry.company)}</strong><span>${escapeAdviceText(entry.created_at)} ・ ${entry.followup_count ? `深掘り ${entry.followup_count}回目` : 'メイン質問'}</span></div>
      <h3>${escapeAdviceText(entry.question)}</h3>
      <p class="advice-answer">${escapeAdviceText(entry.answer)}</p>
      <p class="advice-history-summary">${escapeAdviceText(summary)}</p>
      ${criteria ? `<div class="criteria-list"><h4>評価項目</h4>${criteria}</div>` : ''}
      <div class="advice-columns"><div><h4>良い点</h4><ul>${items(advice.strengths, '自分の言葉で回答できています。')}</ul></div><div><h4>改善ポイント</h4><ul>${items(advice.improvements, '具体例を一つ加えてみましょう。')}</ul></div><div><h4>次の一手</h4><ul>${items(advice.tips, '結論から話してみましょう。')}</ul></div></div>
    </article>`;
  }).join('');
}

// ---------- interview flow ----------
function startInterview() {
  stopDeviceMonitor(); // カメラ確認画面用の監視はここで停止する
  state.interviewActive = true;
  document.getElementById('answerBox').classList.add('hidden');
  document.getElementById('fallbackBox').classList.add('hidden');
  document.getElementById('recIndicator').classList.add('hidden');
  document.getElementById('liveCaption').value = '';
  document.getElementById('fallbackText').value = '';
  document.getElementById('liveCaption').disabled = false;
  document.getElementById('manualSendBtn').classList.add('hidden');
  document.getElementById('retryAnswerBtn').classList.add('hidden');
  document.getElementById('sendAnswerBtn').classList.add('hidden');
  document.getElementById('interview').style.display = 'block';
  document.getElementById('ivideo').srcObject = state.stream;
  document.getElementById('ivCompany').textContent = state.company.name;
  document.getElementById('ivQtext').textContent = 'まもなく開始します…';
  beginRecording();
  speakOnce('これから面接を始めます', () => {
    if (state.interviewActive) askQuestion(0);
  });
}

function askQuestion(i) {
  if (!state.interviewActive) return;
  if (i >= state.selectedQuestions.length) return endInterview(false);

  state.qIndex = i;
  state.followupCount = 0;
  state.dialogueHistory = [];
  const q = state.selectedQuestions[i];
  document.getElementById('ivProgress').textContent = `質問 ${i + 1} / ${state.selectedQuestions.length}`;
  document.getElementById('ivQtext').textContent = q;
  document.getElementById('answerBox').classList.add('hidden');
  document.getElementById('fallbackBox').classList.add('hidden');

  speakOnce(q, () => {
    if (state.interviewActive) listenForAnswer();
  });
}

function beginRecording() {
  state.chunks = [];
  try {
    state.mediaRecorder = new MediaRecorder(state.stream);
    state.mediaRecorder.ondataavailable = e => { if (e.data.size > 0) state.chunks.push(e.data); };
    state.mediaRecorder.onstop = () => {
      const practiceLabel = `全${state.selectedQuestions.length}問の面接練習`;
      uploadRecording(practiceLabel, new Blob(state.chunks, { type: 'video/webm' }));
    };
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

function listenForAnswer(resume = false) {
  document.getElementById('ivQtext').textContent = state.dialogueHistory.length
    ? state.dialogueHistory[state.dialogueHistory.length - 1].text
    : state.selectedQuestions[state.qIndex];
  document.getElementById('answerBox').classList.remove('hidden');
  document.getElementById('recIndicator').classList.remove('hidden');
  document.getElementById('liveCaption').value = '';
  document.getElementById('liveCaption').disabled = false;
  document.getElementById('sendAnswerBtn').classList.add('hidden');
  document.getElementById('retryAnswerBtn').classList.add('hidden');
  document.getElementById('manualSendBtn').classList.remove('hidden');

  if (!speechRecognitionSupported()) {
    document.getElementById('recIndicator').classList.add('hidden');
    document.getElementById('answerBox').classList.add('hidden');
    document.getElementById('fallbackBox').classList.remove('hidden');
    const fallbackText = document.getElementById('fallbackText');
    fallbackText.value = '';
    fallbackText.onkeydown = (event) => {
      if (event.key === 'Enter' && !event.isComposing && !event.shiftKey) {
        event.preventDefault();
        submitFallbackAnswer();
      }
    };
    fallbackText.focus();
    return;
  }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rec = new SR();
  rec.lang = 'ja-JP';
  rec.interimResults = true;
  rec.continuous = true;
  let finalText = '';
  let finished = false;
  const finishByEnter = (event) => {
    if (event.key === 'Enter' && !event.isComposing) {
      event.preventDefault();
      event.stopPropagation();
      finish();
    }
  };

  const finish = () => {
    if (finished) return;
    finished = true;
    document.removeEventListener('keydown', finishByEnter);
    try { rec.onend = null; rec.stop(); } catch (e) {}
    document.getElementById('recIndicator').classList.add('hidden');
    document.getElementById('manualSendBtn').classList.add('hidden');
    const answerEditor = document.getElementById('liveCaption');
    answerEditor.value = finalText.trim() || answerEditor.value.trim();
    answerEditor.disabled = false;
    document.getElementById('retryAnswerBtn').classList.remove('hidden');
    document.getElementById('sendAnswerBtn').classList.remove('hidden');
    answerEditor.focus();
  };

  rec.onresult = (e) => {
    let interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const t = e.results[i][0].transcript;
      if (e.results[i].isFinal) finalText += t; else interim += t;
    }
    document.getElementById('liveCaption').value = finalText + interim;
  };
  rec.onerror = (e) => {
    console.error('SpeechRecognition error:', e.error);
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed' || e.error === 'audio-capture') {
      // Permanent failure: switch straight to the text fallback instead of retrying.
      finished = true;
      document.removeEventListener('keydown', finishByEnter);
      document.getElementById('recIndicator').classList.add('hidden');
      document.getElementById('manualSendBtn').classList.add('hidden');
      document.getElementById('retryAnswerBtn').classList.add('hidden');
      document.getElementById('sendAnswerBtn').classList.add('hidden');
      document.getElementById('answerBox').classList.add('hidden');
      document.getElementById('fallbackBox').classList.remove('hidden');
      document.getElementById('fallbackText').focus();
      return;
    }
    finish();
  };
  rec.onend = () => {
    if (finished || !state.interviewActive) return;
    try {
      rec.start();
    } catch (e) {
      setTimeout(() => {
        if (!finished && state.interviewActive) {
          try { rec.start(); } catch (retryError) { finish(); }
        }
      }, 150);
    }
  };

  document.getElementById('manualSendBtn').onclick = finish;
  document.getElementById('retryAnswerBtn').onclick = () => listenForAnswer(true);
  document.getElementById('sendAnswerBtn').onclick = () => {
    const answer = document.getElementById('liveCaption').value.trim();
    document.getElementById('retryAnswerBtn').classList.add('hidden');
    document.getElementById('sendAnswerBtn').classList.add('hidden');
    document.getElementById('liveCaption').disabled = true;
    handleAnswer(answer);
  };
  document.addEventListener('keydown', finishByEnter);

  state.recognition = rec;
  try { rec.start(); } catch (e) { finish(); }
}

function submitFallbackAnswer() {
  const text = document.getElementById('fallbackText').value.trim();
  document.getElementById('fallbackText').onkeydown = null;
  document.getElementById('fallbackBox').classList.add('hidden');
  handleAnswer(text);
}

async function handleAnswer(answerText) {
  if (!state.interviewActive) return;
  if (!answerText) answerText = '（発言を聞き取れませんでした）';
  const answeredQuestionIndex = state.qIndex;
  const currentQuestion = document.getElementById('ivQtext').textContent;
  const advice = await requestAdvice(answerText, currentQuestion);
  state.adviceHistory.push({
    company: state.company.name,
    question: currentQuestion,
    answer: answerText,
    followup_count: state.followupCount,
    advice,
    created_at: new Date().toLocaleString('ja-JP', { dateStyle: 'short', timeStyle: 'short' }),
  });
  saveAdviceHistory();
  if (!state.interviewActive) return;
  state.dialogueHistory.push({ role: 'student', text: answerText });
  document.getElementById('ivQtext').textContent = '回答を確認しています…';

  const turn = await fetchInterviewerReply(answeredQuestionIndex);
  if (!state.interviewActive) return;
  state.dialogueHistory.push({ role: 'interviewer', text: turn.reply });
  document.getElementById('ivQtext').textContent = turn.reply;

  speakOnce(turn.reply, () => {
    if (!state.interviewActive) return;
    if (turn.move_on || state.followupCount >= MAX_FOLLOWUPS) {
      askQuestion(answeredQuestionIndex + 1);
    } else {
      state.followupCount++;
      listenForAnswer();
    }
  });
}

async function fetchInterviewerReply(questionIndex = state.qIndex) {
  const controller = new AbortController();
  state.interviewController = controller;
  const timer = setTimeout(() => controller.abort(), 25000);
  try {
    const res = await fetch('/api/interview/reply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        question: state.selectedQuestions[questionIndex],
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
  } finally {
    if (state.interviewController === controller) state.interviewController = null;
  }
}

function endInterview(aborted) {
  state.interviewActive = false;
  if (state.interviewController) {
    state.interviewController.abort();
    state.interviewController = null;
  }
  if (state.recognition) { try { state.recognition.onend = null; state.recognition.stop(); } catch (e) {} }
  state.recognition = null;
  if (state.mediaRecorder && state.mediaRecorder.state === 'recording') state.mediaRecorder.stop();
  state.mediaRecorder = null;
  speechSynthesis.cancel();
  if (state.stream) {
    state.stream.getTracks().forEach(track => track.stop());
    state.stream = null;
  }
  document.getElementById('ivideo').srcObject = null;
  document.getElementById('preview').srcObject = null;
  document.getElementById('interview').style.display = 'none';
  if (!aborted) {
    alert('お疲れ様でした。質問ごとのアドバイスを確認できます。');
    showScreen('advice');
  } else {
    showScreen('history');
  }
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