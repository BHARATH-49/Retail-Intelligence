const feedbackForm = document.getElementById('customer-feedback-form');
const feedbackMessage = document.getElementById('feedback-message');
let demoDay = '';
const settingsReady = fetch('/api/shop/settings')
  .then((response) => response.json())
  .then((settings) => {
    demoDay = settings.demo_day || '';
    if (settings.demo_disclosure) {
      const banner = document.getElementById('demo-banner');
      banner.textContent = settings.demo_disclosure;
      banner.hidden = false;
    }
  });

function localDay() {
  if (demoDay) return demoDay;
  const day = new Date();
  return [day.getFullYear(), String(day.getMonth() + 1).padStart(2, '0'), String(day.getDate()).padStart(2, '0')].join('-');
}

feedbackForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = feedbackForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  feedbackMessage.textContent = '';
  feedbackMessage.classList.remove('error');
  try {
    await settingsReady;
    const response = await fetch('/api/shop/feedback/customer', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        day: localDay(),
        category: document.getElementById('feedback-category').value,
        product_name: document.getElementById('feedback-product').value,
        note: document.getElementById('feedback-note').value,
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Could not save feedback.');
    feedbackForm.reset();
    feedbackMessage.textContent = 'Thank you. Your feedback was sent to the shop owner for review.';
  } catch (error) {
    feedbackMessage.textContent = error.message;
    feedbackMessage.classList.add('error');
  } finally { submit.disabled = false; }
});
