const questionSets = {
  全体面接: [
    'あなたが学生時代に力を入れたことを教えてください。',
    'あなたの強みと、それが仕事で活かせる場面を教えてください。',
    '当社で挑戦したいことを教えてください。'
  ],
  質問別面接: [
    '自己紹介を1分程度でお願いします。',
    '苦手なことに向き合った経験を教えてください。',
    '最後に、面接官へ質問はありますか？'
  ]
};
const historyStorageKey = 'career-loom-interview-history';
const state = { company: '三日月デザイン', mode: '全体面接', questionIndex: 0, stream: null, recordingStream: null, recorder: null, recordingMimeType: '', recordingExtension: 'webm', chunks: [], startedAt: null, timer: null, recognition: null, recognitionSession: 0, transcript: '', recognizing: false, shouldRecognize: false, speakingQuestion: false, expressionReady: false, expressionInterval: null, expressionBusy: false, expressionTotal: 0, expressionSamples: 0, history: loadHistory() };
const $ = (selector) => document.querySelector(selector);

function updateProgress(step, copy) {
  $('#step-label').textContent = `${String(step).padStart(2, '0')} / 04`;
  $('#progress-fill').style.width = `${step * 25}%`;
  $('#step-copy').textContent = copy;
}

function setDeviceStatus(ready, type) {
  const dot = $(`#${type}-dot`);
  const label = $(`#${type}-status`);
  dot.classList.toggle('ready', ready);
  label.textContent = ready ? '接続中' : '未接続';
}

async function loadExpressionModels() {
  if (!window.faceapi) return;
  try {
    const modelUrl = 'https://justadudewhohacks.github.io/face-api.js/models';
    await Promise.all([
      faceapi.nets.tinyFaceDetector.loadFromUri(modelUrl),
      faceapi.nets.faceLandmark68Net.loadFromUri(modelUrl),
      faceapi.nets.faceExpressionNet.loadFromUri(modelUrl)
    ]);
    state.expressionReady = true;
    $('#expression-status').textContent = '顔を確認中';
  } catch (error) {
    $('#expression-status').textContent = '表情解析を利用できません';
  }
}

function clampScore(value) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function loadHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(historyStorageKey) || '[]');
    return Array.isArray(saved) ? saved : [];
  } catch (error) {
    return [];
  }
}

function saveHistory() {
  localStorage.setItem(historyStorageKey, JSON.stringify(state.history.slice(0, 30)));
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
}

async function analyzeExpression() {
  const preview = $('#preview');
  if (!state.expressionReady || state.expressionBusy || preview.readyState < 2) return;
  state.expressionBusy = true;
  try {
    const result = await faceapi.detectSingleFace(preview, new faceapi.TinyFaceDetectorOptions()).withFaceLandmarks().withFaceExpressions();
    if (!result) {
      $('#expression-status').textContent = '顔が検出されていません';
      return;
    }
    const expressions = result.expressions;
    const positive = expressions.happy * 100 + expressions.neutral * 62 + expressions.surprised * 45;
    const negative = (expressions.sad + expressions.angry + expressions.fear + expressions.disgust) * 100;
    const score = clampScore(positive - negative * 0.35);
    state.expressionTotal += score;
    state.expressionSamples += 1;
    $('#expression-score').textContent = score;
    $('#expression-status').textContent = expressions.happy > 0.45 ? '自然な笑顔' : '表情を確認中';
  } finally {
    state.expressionBusy = false;
  }
}

function startExpressionAnalysis() {
  clearInterval(state.expressionInterval);
  state.expressionInterval = window.setInterval(analyzeExpression, 700);
  analyzeExpression();
}

function stopExpressionAnalysis() {
  clearInterval(state.expressionInterval);
  state.expressionInterval = null;
  state.expressionBusy = false;
}

function calculateAnswerScore(answer) {
  const text = answer.trim();
  if (!text) return 0;
  const detailWords = ['経験', '課題', '工夫', '役割', '結果', '学び', '改善', '具体', '強み', '理由'];
  const detailCount = detailWords.filter((word) => text.includes(word)).length;
  const sentenceCount = (text.match(/[。！？!?]/g) || []).length;
  return clampScore(Math.min(38, text.length * 0.32) + Math.min(42, detailCount * 7) + Math.min(20, sentenceCount * 5));
}

function renderAdvicePanel(advice) {
  const panel = $('#advice-panel');
  if (!panel) return;
  panel.hidden = false;
  const summary = advice?.summary || '回答と表情を確認しました。';
  $('#advice-summary').textContent = summary;
  $('#advice-strengths').innerHTML = (advice?.strengths || []).map((item) => `<li>${item}</li>`).join('') || '<li>まだ十分な強みが見えません。</li>';
  $('#advice-improvements').innerHTML = (advice?.improvements || []).map((item) => `<li>${item}</li>`).join('') || '<li>継続して練習すると改善できます。</li>';
  $('#advice-tips').innerHTML = (advice?.tips || []).map((item) => `<li>${item}</li>`).join('') || '<li>話すスピードを落として、声のトーンを整えましょう。</li>';
}

function renderSummaryPanel(summary) {
  const panel = $('#summary-panel');
  if (!panel) return;
  const totalScore = summary?.total_score ?? 0;
  panel.hidden = false;
  $('#summary-score').textContent = `${totalScore}点`;
  $('#summary-score-fill').style.width = `${totalScore}%`;
  $('#summary-score-label').textContent = totalScore >= 80 ? 'とても良い' : totalScore >= 60 ? 'あと一歩' : '伸びしろあり';
  $('#summary-verdict').textContent = summary?.verdict || 'まだまだ伸びます。';
}

function renderHistoryList() {
  const historyList = $('#history-list');
  if (!historyList) return;
  if (!state.history.length) {
    historyList.innerHTML = '<p class="empty-history">まだ練習履歴はありません</p>';
    return;
  }
  const groups = state.history.reduce((result, entry) => {
    const date = entry.date || '日付不明';
    (result[date] ||= []).push(entry);
    return result;
  }, {});
  historyList.innerHTML = Object.entries(groups).slice(0, 7).map(([date, entries]) => `
    <section class="history-day">
      <h4>${escapeHtml(date)}</h4>
      ${entries.slice(0, 5).map((entry) => {
        const label = entry.mode || '面接';
        const score = entry.score || 0;
        return `<div class="history-item"><span><strong>${escapeHtml(entry.company || '企業')}</strong><small>${escapeHtml(label)} ・ ${escapeHtml(entry.time || 'たった今')}</small></span><b class="history-score">${score}<small> SCORE</small></b></div>`;
      }).join('')}
    </section>`).join('');
}

async function generateInterviewAdvice(answer, question, expressionScore) {
  const payload = {
    answer,
    question,
    expression_score: expressionScore || 0,
    company: state.company,
    mode: state.mode
  };
  try {
    const response = await fetch('/api/interview-advice', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!response.ok) throw new Error('アドバイス生成に失敗しました');
    const advice = await response.json();
    renderAdvicePanel(advice);
  } catch (error) {
    renderAdvicePanel({
      summary: '回答の質と表情の状態を確認しました。具体例を一つ増やして、行動と結果をセットで話すとさらに伝わります。',
      strengths: ['自分の言葉で説明しようとしています。', '落ち着いて話せている印象があります。'],
      improvements: ['「何をしたか」と「結果」をセットで伝えると説得力が上がります。', '表情が少し硬く見える場合は、少し笑顔を作って話しましょう。'],
      tips: ['一文ごとに結論を先に伝えましょう。', '最後に学びと次への意欲を加えると印象が強くなります。']
    });
  }
}

async function checkDevices() {
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    if (!state.stream.getAudioTracks().length) throw new Error('マイクの音声トラックがありません');
    $('#preview').srcObject = state.stream;
    $('#interview-preview').srcObject = state.stream;
    $('#preview').classList.add('active');
    $('#video-placeholder').style.display = 'none';
    $('#live-pill').textContent = '● LIVE';
    $('#live-pill').classList.add('live');
    setDeviceStatus(true, 'camera');
    setDeviceStatus(true, 'mic');
    $('#start-button').disabled = false;
    $('#device-button').textContent = '接続済み';
    loadExpressionModels();
    updateProgress(3, '準備ができました。面接を始められます');
  } catch (error) {
    setDeviceStatus(false, 'camera');
    setDeviceStatus(false, 'mic');
    $('#device-button').textContent = 'もう一度確認';
    alert('カメラとマイクへのアクセスが必要です。ブラウザの権限を確認してください。');
  }
}

function startRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    $('#listening-state').textContent = '手入力のみ';
    $('#recognition-button').disabled = true;
    return;
  }
  state.shouldRecognize = true;
  if (state.recognizing) return;
  state.recognitionSession += 1;
  const recognitionSession = state.recognitionSession;
  state.recognition = new Recognition();
  state.recognition.lang = 'ja-JP';
  state.recognition.continuous = true;
  state.recognition.interimResults = true;
  state.recognition.onstart = () => {
    state.recognizing = true;
    $('#listening-state').textContent = '● 聞き取り中';
    $('#recognition-button').textContent = '聞き取り中';
  };
  state.recognition.onresult = (event) => {
    if (recognitionSession !== state.recognitionSession) return;
    let interim = '';
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const phrase = event.results[index][0].transcript;
      if (event.results[index].isFinal) state.transcript += phrase;
      else interim += phrase;
    }
    $('#transcript').value = state.transcript + interim;
    $('#transcript-count').textContent = `${$('#transcript').value.length}文字`;
  };
  state.recognition.onerror = (event) => {
    state.recognizing = false;
    const messages = { 'not-allowed': 'マイクの権限が必要です', 'audio-capture': 'マイクを確認してください', network: '音声認識サービスに接続できません' };
    state.shouldRecognize = false;
    $('#listening-state').textContent = messages[event.error] || '聞き取りを再開してください';
    $('#recognition-button').textContent = 'マイクで聞き取りを再開';
  };
  state.recognition.onend = () => {
    state.recognizing = false;
    if (recognitionSession === state.recognitionSession && state.shouldRecognize && !state.speakingQuestion) {
      window.setTimeout(() => {
        if (!state.shouldRecognize || state.recognizing) return;
        try { state.recognition.start(); } catch (error) { /* recognition is already restarting */ }
      }, 250);
    }
  };
  try {
    state.recognition.start();
  } catch (error) {
    $('#listening-state').textContent = 'マイクで聞き取りを再開してください';
  }
}

function updateTimer() {
  const seconds = Math.floor((Date.now() - state.startedAt) / 1000);
  const value = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  $('#room-timer').textContent = value;
  $('#record-time').textContent = value;
}

function speakQuestion(onComplete) {
  if (!('speechSynthesis' in window)) {
    if (onComplete) onComplete();
    return;
  }
  state.speakingQuestion = false;
  window.speechSynthesis.cancel();
  const speech = new SpeechSynthesisUtterance($('#question-text').textContent);
  speech.lang = 'ja-JP';
  speech.rate = 0.95;
  state.speakingQuestion = true;
  speech.onend = () => {
    state.speakingQuestion = false;
    if (onComplete) onComplete();
  };
  window.speechSynthesis.speak(speech);
}

function showQuestion(questionText = null) {
  const questions = questionSets[state.mode];
  $('#question-number').textContent = String(state.questionIndex + 1).padStart(2, '0');
  $('#question-text').textContent = questionText || questions[state.questionIndex % questions.length];
  $('#question-mode').textContent = state.mode;
  $('#next-question-button').textContent = state.questionIndex === questions.length - 1 ? '最初の質問に戻る →' : '次の質問 →';
  speakQuestion(() => {
    if (state.shouldRecognize) startRecognition();
  });
}

function getRecordingMimeType() {
  const types = [
    { type: 'video/webm;codecs=vp8,opus', extension: 'webm' },
    { type: 'video/webm;codecs=vp9,opus', extension: 'webm' },
    { type: 'video/mp4;codecs=avc1.42E01E,mp4a.40.2', extension: 'mp4' },
    { type: 'video/mp4', extension: 'mp4' },
    { type: 'video/webm', extension: 'webm' }
  ];
  const supported = types.find(({ type }) => MediaRecorder.isTypeSupported(type));
  state.recordingExtension = supported ? supported.extension : 'webm';
  return supported ? supported.type : '';
}

function saveRecording() {
  if (!state.chunks.length) {
    $('#listening-state').textContent = '録画データを作成できませんでした';
    return;
  }
  const recording = new Blob(state.chunks, { type: state.recordingMimeType || state.chunks[0].type || 'video/webm' });
  const extension = recording.type.includes('mp4') ? 'mp4' : 'webm';
  const url = URL.createObjectURL(recording);
  const link = document.createElement('a');
  link.href = url;
  link.download = `interview-${Date.now()}.${extension}`;
  link.textContent = `録画をダウンロード（${extension.toUpperCase()}・音声付き）`;
  link.className = 'download-link';
  $('#history-list').appendChild(link);
}

function startInterview() {
  $('#interview-room').hidden = false;
  $('#room-title').textContent = `${state.company}との面接`;
  state.questionIndex = 0;
  state.shouldRecognize = true;
  showQuestion();
  $('#interview-room').scrollIntoView({ behavior: 'smooth', block: 'start' });
  $('#recording-indicator').classList.add('active');
  state.startedAt = Date.now();
  state.timer = setInterval(updateTimer, 1000);
  state.chunks = [];
  state.transcript = '';
  $('#transcript').value = '';
  $('#transcript-count').textContent = '0文字';
  state.expressionTotal = 0;
  state.expressionSamples = 0;
  $('#expression-score').textContent = '--';
  $('#expression-status').textContent = state.expressionReady ? '顔を確認中' : '解析準備中';
  $('#answer-score').textContent = '--';
  startExpressionAnalysis();
  state.recordingMimeType = getRecordingMimeType();
  state.recordingStream = new MediaStream([...state.stream.getVideoTracks(), ...state.stream.getAudioTracks()]);
  state.recorder = new MediaRecorder(state.recordingStream, state.recordingMimeType ? { mimeType: state.recordingMimeType } : undefined);
  state.recorder.ondataavailable = (event) => { if (event.data.size) state.chunks.push(event.data); };
  state.recorder.onerror = () => { $('#listening-state').textContent = '録画に失敗しました'; };
  state.recorder.onstop = saveRecording;
  state.recorder.start(1000);
  $('#start-button').disabled = true;
  updateProgress(4, '面接中です。落ち着いて話しましょう');
}

async function generateInterviewSummary(answer, expressionScore) {
  try {
    const response = await fetch('/api/interview-summary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer, expression_score: expressionScore, company: state.company, mode: state.mode })
    });
    if (!response.ok) throw new Error('総評生成に失敗しました');
    const summary = await response.json();
    renderSummaryPanel(summary);
    return summary;
  } catch (error) {
    const fallbackSummary = {
      total_score: clampScore((calculateAnswerScore(answer) * 0.7) + (expressionScore || 0) * 0.3),
      verdict: '回答の軸は良いです。具体例と学びを一つ増やすと、さらに印象を強くできます。'
    };
    renderSummaryPanel(fallbackSummary);
    return fallbackSummary;
  }
}

async function askAIConsult() {
  const answer = state.transcript.trim();
  if (!answer) {
    alert('回答が空です。まず面接の回答を入力してください。');
    return;
  }
  const question = $('#question-text').textContent || '';
  const expressionScore = state.expressionSamples ? clampScore(state.expressionTotal / state.expressionSamples) : 0;
  try {
    const response = await fetch('/api/ai-consult', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer, question, expression_score: expressionScore, company: state.company, mode: state.mode })
    });
    if (!response.ok) throw new Error('AI相談に失敗しました');
    const data = await response.json();
    renderConsultPanel(data.message || 'まず結論を伝え、次に具体的な行動と結果を添えると、話の軸が伝わりやすくなります。');
  } catch (error) {
    renderConsultPanel('まず結論を伝え、そのあとに具体例と結果を添えましょう。面接官が話の要点を追いやすくなります。');
  }
}

function renderConsultPanel(message) {
  const panel = $('#consult-panel');
  if (!panel) return;
  panel.hidden = false;
  $('#consult-message').textContent = message;
}

function stopInterview() {
  state.shouldRecognize = false;
  state.recognitionSession += 1;
  state.speakingQuestion = false;
  if (state.recorder && state.recorder.state !== 'inactive') {
    state.recorder.requestData();
    state.recorder.stop();
  }
  if (state.recognition && state.recognizing) state.recognition.stop();
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  stopExpressionAnalysis();
  clearInterval(state.timer);
  $('#recording-indicator').classList.remove('active');
  $('#listening-state').textContent = '保存しました';
  const answerScore = calculateAnswerScore(state.transcript);
  const expressionScore = state.expressionSamples ? clampScore(state.expressionTotal / state.expressionSamples) : 0;
  const score = clampScore(answerScore * 0.6 + expressionScore * 0.4);
  $('#answer-score').textContent = answerScore;
  $('#expression-score').textContent = expressionScore || '--';
  const completedAt = new Date();
  state.history.unshift({ company: state.company, mode: state.mode, score, time: completedAt.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' }), date: completedAt.toLocaleDateString('ja-JP', { year: 'numeric', month: 'long', day: 'numeric' }) });
  saveHistory();
  renderHistoryList();
  generateInterviewSummary(state.transcript, expressionScore);
  generateInterviewAdvice(state.transcript, $('#question-text').textContent, expressionScore);
  $('#start-button').disabled = false;
  updateProgress(3, '保存しました。もう一度練習できます');
}

document.querySelectorAll('.company-option').forEach((button) => button.addEventListener('click', () => { document.querySelectorAll('.company-option').forEach((item) => item.classList.remove('selected')); button.classList.add('selected'); state.company = button.dataset.company; }));
document.querySelectorAll('.mode-option').forEach((button) => button.addEventListener('click', () => { document.querySelectorAll('.mode-option').forEach((item) => item.classList.remove('selected')); button.classList.add('selected'); state.mode = button.dataset.mode; }));
renderHistoryList();
$('#device-button').addEventListener('click', checkDevices);
$('#start-button').addEventListener('click', startInterview);
$('#consult-button').addEventListener('click', askAIConsult);
$('#stop-button').addEventListener('click', stopInterview);
$('#speak-button').addEventListener('click', () => {
  state.shouldRecognize = false;
  if (state.recognition && state.recognizing) state.recognition.stop();
  state.shouldRecognize = true;
  speakQuestion(() => startRecognition());
});
$('#recognition-button').addEventListener('click', startRecognition);
$('#transcript').addEventListener('input', (event) => {
  state.transcript = event.target.value;
  $('#transcript-count').textContent = `${state.transcript.length}文字`;
  $('#answer-score').textContent = calculateAnswerScore(state.transcript) || '--';
});
$('#next-question-button').addEventListener('click', () => {
  const button = $('#next-question-button');
  const answer = state.transcript.trim();
  const previousQuestion = $('#question-text').textContent;
  const currentExpressionScore = state.expressionSamples ? clampScore(state.expressionTotal / state.expressionSamples) : 0;
  button.disabled = true;
  button.textContent = '回答を分析中...';
  state.shouldRecognize = false;
  state.recognitionSession += 1;
  if (state.recognition && state.recognizing) state.recognition.stop();
  generateInterviewAdvice(answer, previousQuestion, currentExpressionScore);
  fetch('/api/next-question', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ answer, previous_question: previousQuestion, question_number: state.questionIndex, mode: state.mode })
  })
    .then((response) => response.ok ? response.json() : Promise.reject(new Error('質問生成に失敗しました')))
    .then((result) => {
      state.transcript = '';
      $('#transcript').value = '';
      $('#transcript-count').textContent = '0文字';
      $('#answer-score').textContent = '--';
      state.questionIndex += 1;
      state.shouldRecognize = true;
      showQuestion(result.question);
    })
    .catch(() => {
      state.transcript = '';
      $('#transcript').value = '';
      $('#transcript-count').textContent = '0文字';
      $('#answer-score').textContent = '--';
      state.shouldRecognize = true;
      button.disabled = false;
      showQuestion();
    })
    .finally(() => {
      button.disabled = false;
    });
});