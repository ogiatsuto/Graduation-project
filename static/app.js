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
const state = { company: '三日月デザイン', mode: '全体面接', questionIndex: 0, stream: null, recorder: null, chunks: [], startedAt: null, timer: null, recognition: null, transcript: '' };
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

async function checkDevices() {
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    $('#preview').srcObject = state.stream;
    $('#preview').classList.add('active');
    $('#video-placeholder').style.display = 'none';
    $('#live-pill').textContent = '● LIVE';
    $('#live-pill').classList.add('live');
    setDeviceStatus(true, 'camera');
    setDeviceStatus(true, 'mic');
    $('#start-button').disabled = false;
    $('#device-button').textContent = '接続済み';
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
    $('#listening-state').textContent = '手入力にも対応';
    return;
  }
  state.recognition = new Recognition();
  state.recognition.lang = 'ja-JP';
  state.recognition.continuous = true;
  state.recognition.interimResults = true;
  state.recognition.onstart = () => { $('#listening-state').textContent = '● 聞き取り中'; };
  state.recognition.onresult = (event) => {
    let interim = '';
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const phrase = event.results[index][0].transcript;
      if (event.results[index].isFinal) state.transcript += phrase;
      else interim += phrase;
    }
    $('#transcript').textContent = state.transcript + interim;
  };
  state.recognition.onerror = () => { $('#listening-state').textContent = '文字起こしを確認中'; };
  state.recognition.start();
}

function updateTimer() {
  const seconds = Math.floor((Date.now() - state.startedAt) / 1000);
  const value = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  $('#room-timer').textContent = value;
  $('#record-time').textContent = value;
}

function speakQuestion() {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const speech = new SpeechSynthesisUtterance($('#question-text').textContent);
  speech.lang = 'ja-JP';
  speech.rate = 0.95;
  window.speechSynthesis.speak(speech);
}

function showQuestion() {
  const questions = questionSets[state.mode];
  $('#question-number').textContent = String(state.questionIndex + 1).padStart(2, '0');
  $('#question-text').textContent = questions[state.questionIndex];
  $('#question-mode').textContent = state.mode;
  $('#next-question-button').textContent = state.questionIndex === questions.length - 1 ? '最初の質問に戻る →' : '次の質問 →';
  speakQuestion();
}

function startInterview() {
  $('#interview-room').hidden = false;
  $('#room-title').textContent = `${state.company}との面接`;
  state.questionIndex = 0;
  showQuestion();
  $('#interview-room').scrollIntoView({ behavior: 'smooth', block: 'start' });
  $('#recording-indicator').classList.add('active');
  state.startedAt = Date.now();
  state.timer = setInterval(updateTimer, 1000);
  state.chunks = [];
  state.recorder = new MediaRecorder(state.stream);
  state.recorder.ondataavailable = (event) => { if (event.data.size) state.chunks.push(event.data); };
  state.recorder.start();
  startRecognition();
  $('#start-button').disabled = true;
  updateProgress(4, '面接中です。落ち着いて話しましょう');
}

function stopInterview() {
  if (state.recorder && state.recorder.state !== 'inactive') state.recorder.stop();
  if (state.recognition) state.recognition.stop();
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  clearInterval(state.timer);
  $('#recording-indicator').classList.remove('active');
  $('#listening-state').textContent = '保存しました';
  const score = Math.floor(72 + Math.random() * 19);
  $('#history-list').innerHTML = `<div class="history-item"><span><strong>${state.company}</strong><small>${state.mode} ・ たった今</small></span><b class="history-score">${score}<small> SCORE</small></b></div>`;
  if (state.chunks.length) {
    const recording = new Blob(state.chunks, { type: 'video/webm' });
    const url = URL.createObjectURL(recording);
    const link = document.createElement('a');
    link.href = url;
    link.download = `interview-${Date.now()}.webm`;
    link.textContent = '録画をダウンロード';
    link.className = 'download-link';
    $('#history-list').appendChild(link);
  }
  $('#start-button').disabled = false;
  updateProgress(3, '保存しました。もう一度練習できます');
}

document.querySelectorAll('.company-option').forEach((button) => button.addEventListener('click', () => { document.querySelectorAll('.company-option').forEach((item) => item.classList.remove('selected')); button.classList.add('selected'); state.company = button.dataset.company; }));
document.querySelectorAll('.mode-option').forEach((button) => button.addEventListener('click', () => { document.querySelectorAll('.mode-option').forEach((item) => item.classList.remove('selected')); button.classList.add('selected'); state.mode = button.dataset.mode; }));
$('#device-button').addEventListener('click', checkDevices);
$('#start-button').addEventListener('click', startInterview);
$('#stop-button').addEventListener('click', stopInterview);
$('#speak-button').addEventListener('click', speakQuestion);
$('#next-question-button').addEventListener('click', () => {
  const questions = questionSets[state.mode];
  state.questionIndex = (state.questionIndex + 1) % questions.length;
  showQuestion();
});