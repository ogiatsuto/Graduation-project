const essay = document.querySelector('#essay');
const targetCharCount = document.querySelector('#target-char-count');
const count = document.querySelector('#char-count');
const reviewButton = document.querySelector('#review-button');
const clearButton = document.querySelector('#clear-button');
const emptyState = document.querySelector('#empty-state');
const report = document.querySelector('#report');
const status = document.querySelector('#status');
const questionType = document.querySelector('#question-type');
const questionOptions = [
  '志望動機', '自己PR', 'ガクチカ', '長所・短所', '趣味・特技', '資格・スキル',
  '学業で力を入れたこと', '自己紹介', '就活の軸', '希望職種', '入社後にしたいこと',
  '将来のキャリア', '企業で実現したいこと', 'チーム経験', '失敗・挫折経験', '課題・改善経験',
  '趣味・興味', 'アルバイト経験', '部活・サークル経験', 'インターン経験', '最近気になるニュース',
  'あなたを一言で表すと', '周囲からどんな人と言われるか', 'これまでで一番頑張ったこと',
  '挫折したときの乗り越え方', '入社後に身につけたいスキル',
];

questionOptions.forEach((option) => {
  questionType?.append(new Option(option, option));
});

document.querySelectorAll('.document-switch, .file-drop, .workflow, .analysis-grid, #save-button, .report-meta').forEach((element) => {
  element.remove();
});
document.querySelectorAll('#purpose, #target-job').forEach((element) => {
  element.closest('.select-wrap, .char-limit-input')?.remove();
});
document.querySelectorAll('label[for="purpose"], label[for="target-job"]').forEach((element) => element.remove());
document.querySelector('#ai-suggestion')?.closest('.suggestion')?.remove();
document.querySelector('.history-section')?.remove();

function characterCount() {
  return essay.value.replace(/\n/g, '').length;
}

function updateCount() {
  count.textContent = `${characterCount()} / ${targetCharCount.value || 0}`;
}

function renderReport(data) {
  document.querySelector('#report-count').textContent = data.character_count;
  document.querySelector('#report-limit').textContent = data.target_char_count;
  document.querySelector('#summary').textContent = data.summary;
  document.querySelector('#corrected-text').value = data.corrected_text || '';
  const goodFindings = data.findings.filter((finding) => finding.type === '良い点');
  const improvementFindings = data.findings.filter((finding) => finding.type !== '良い点');
  const renderFindings = (findings) => findings.map((finding) => `
    <article class="finding">
      <span class="finding-type ${finding.type === '良い点' ? 'good' : finding.type === '警告' ? 'warning' : ''}">${finding.type}</span>
      <h3>${finding.title}</h3><p>${finding.body}</p>
    </article>`).join('');
  document.querySelector('#findings').innerHTML = `
    ${goodFindings.length ? `<section class="finding-group good-group"><h3 class="finding-group-title">良い点</h3>${renderFindings(goodFindings)}</section>` : ''}
    ${improvementFindings.length ? `<section class="finding-group improvement-group"><h3 class="finding-group-title">改善・要確認</h3>${renderFindings(improvementFindings)}</section>` : ''}`;
  emptyState?.remove();
  report.hidden = false;
  status.textContent = data.ai_used ? 'AI REVIEWED' : 'REVIEWED';
}

async function runReview() {
  if (!essay.value.trim()) {
    window.alert('添削する文章を入力してください。');
    essay.focus();
    return;
  }
  if (!targetCharCount.value || Number(targetCharCount.value) < 1) {
    window.alert('指定文字数を入力してください。');
    targetCharCount.focus();
    return;
  }
  reviewButton.disabled = true;
  reviewButton.querySelector('span').textContent = '添削中...';
  status.textContent = 'REVIEWING...';
  try {
    const response = await fetch('/api/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ essay: essay.value, target_char_count: targetCharCount.value, question_type: questionType?.value || '' }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    renderReport(data);
  } catch (error) {
    status.textContent = 'ERROR';
    window.alert(error.message || '添削に失敗しました。');
  } finally {
    reviewButton.disabled = false;
    reviewButton.querySelector('span').textContent = '文章を添削する';
  }
}

essay.addEventListener('input', updateCount);
targetCharCount.addEventListener('input', updateCount);
clearButton.addEventListener('click', () => {
  essay.value = '';
  updateCount();
  essay.focus();
});
reviewButton.addEventListener('click', runReview);
updateCount();
