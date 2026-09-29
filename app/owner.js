const $ = (id) => document.getElementById(id);
const state = {products: [], settings: {}, billLines: [], forecast: null, closePreview: null, pendingBillId: null};
let forecastPollTimer = null;

function localDay() {
  if (state.settings.demo_day) return state.settings.demo_day;
  const day = new Date();
  return [day.getFullYear(), String(day.getMonth() + 1).padStart(2, '0'), String(day.getDate()).padStart(2, '0')].join('-');
}

function amount(value) {
  return Number(value).toLocaleString(undefined, {maximumFractionDigits: 2});
}

function money(cents) {
  const currency = state.settings.currency || '';
  return `${currency ? currency + ' ' : ''}${(Number(cents) / 100).toFixed(2)}`;
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request could not be completed.');
  return result;
}

function post(path, body) {
  return request(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
}

function message(text, error = false) {
  $('global-message').textContent = text;
  $('global-message').classList.toggle('error', error);
}

function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined && text !== null) item.textContent = String(text);
  if (className) item.className = className;
  return item;
}

function button(label, onClick, className = 'tiny secondary') {
  const item = node('button', label, className);
  item.type = 'button';
  item.addEventListener('click', onClick);
  return item;
}

function rowInto(body, values, action) {
  const tr = document.createElement('tr');
  for (const value of values) tr.append(node('td', value));
  if (action) {
    const td = document.createElement('td');
    td.append(action);
    tr.append(td);
  }
  body.append(tr);
  return tr;
}

function emptyRow(body, columns, text) {
  const tr = document.createElement('tr');
  const td = node('td', text, 'empty');
  td.colSpan = columns;
  tr.append(td);
  body.append(tr);
}

function showTab(tab) {
  for (const panel of document.querySelectorAll('.tab-panel')) {
    panel.hidden = panel.id !== `panel-${tab}`;
  }
  for (const item of document.querySelectorAll('.main-nav button')) {
    item.classList.toggle('active', item.dataset.tab === tab);
  }
  if (tab === 'forecast') loadForecast();
  if (tab === 'billing') loadHistory();
  if (tab === 'store') loadOpportunities();
  if (tab === 'to-buy') loadToBuy();
}

function showSub(group, chosen) {
  for (const item of document.querySelectorAll(`[data-${group}-view]`)) {
    item.classList.toggle('active', item.dataset[`${group}View`] === chosen);
  }
  for (const item of document.querySelectorAll(`#panel-${group} .sub-panel`)) {
    item.hidden = item.id !== `${group}-${chosen}`;
  }
  if (group === 'store' && chosen === 'opportunities') loadOpportunities();
  if (group === 'billing' && chosen === 'history') loadHistory();
}

function selectOptions(selectId, products) {
  const select = $(selectId);
  const previous = select.value;
  select.replaceChildren();
  for (const product of products) {
    const option = node('option', `${product.name} · ${product.sku}`);
    option.value = product.id;
    select.append(option);
  }
  if (products.some((product) => String(product.id) === previous)) select.value = previous;
}

async function loadSettings() {
  state.settings = await request('/api/shop/settings');
  if (state.settings.demo_disclosure) {
    $('demo-banner').textContent = state.settings.demo_disclosure;
    $('demo-banner').hidden = false;
  }
  $('shop-label').textContent = state.settings.shop_name || 'Your shop workspace';
  $('shop-name').value = state.settings.shop_name;
  $('shop-currency').value = state.settings.currency;
}

async function loadProducts() {
  state.products = await request('/api/shop/products');
  $('product-count').textContent = `${state.products.length} products`;
  for (const id of ['bill-product', 'stock-product', 'buy-product', 'offer-product', 'web-product']) {
    selectOptions(id, state.products);
  }
  const body = $('product-rows');
  body.replaceChildren();
  if (!state.products.length) emptyRow(body, 6, 'No products yet. Add your first catalogue product below.');
  for (const product of state.products) {
    rowInto(body, [
      product.name, product.sku, `${amount(product.stock)} ${product.unit}`,
      money(product.unit_price_cents), `${product.lead_days} days`,
    ], button('Edit', () => editProduct(product)));
  }
  updateBillPrice();
}

function editProduct(product) {
  showTab('store');
  showSub('store', 'catalogue');
  $('product-details').open = true;
  $('product-id').value = product.id;
  $('product-sku').value = product.sku;
  $('product-name').value = product.name;
  $('product-unit').value = product.unit;
  $('product-price').value = (product.unit_price_cents / 100).toFixed(2);
  $('product-opening').value = product.opening_stock;
  $('product-first-day').value = product.first_stocked_on;
  $('product-lead').value = product.lead_days;
  $('product-increment').value = product.order_increment;
  $('product-cover').value = product.extra_cover_days;
  $('product-incoming').value = product.incoming_units;
  $('product-incoming-day').value = product.incoming_day ?? '';
  $('product-shelf').value = product.shelf_life_days ?? '';
  for (const label of document.querySelectorAll('.new-only')) label.hidden = true;
  $('product-sku').focus();
}

function clearProduct() {
  $('product-form').reset();
  $('product-id').value = '';
  $('product-first-day').value = localDay();
  for (const label of document.querySelectorAll('.new-only')) label.hidden = false;
}

async function saveProduct(event) {
  event.preventDefault();
  const existingId = $('product-id').value;
  const payload = {
    sku: $('product-sku').value, name: $('product-name').value, unit: $('product-unit').value,
    unit_price: $('product-price').value,
    lead_days: Number($('product-lead').value),
    order_increment: Number($('product-increment').value),
    extra_cover_days: Number($('product-cover').value),
    incoming_units: Number($('product-incoming').value || 0),
    incoming_day: $('product-incoming-day').value || null,
    shelf_life_days: $('product-shelf').value || null,
  };
  if (existingId) payload.id = Number(existingId);
  else {
    payload.opening_stock = Number($('product-opening').value);
    payload.first_stocked_on = $('product-first-day').value;
  }
  try {
    await post('/api/shop/products', payload);
    clearProduct();
    $('product-details').open = false;
    await loadProducts();
    message('Product saved.');
  } catch (error) { message(error.message, true); }
}

async function saveSettings(event) {
  event.preventDefault();
  try {
    await post('/api/shop/settings', {
      shop_name: $('shop-name').value, currency: $('shop-currency').value,
    });
    await loadSettings();
    await loadProducts();
    message('Shop details saved.');
  } catch (error) { message(error.message, true); }
}

async function saveStockChange(event) {
  event.preventDefault();
  try {
    await post('/api/shop/stock', {
      product_id: Number($('stock-product').value), day: $('stock-day').value,
      reason: $('stock-reason').value, quantity_change: $('stock-change').value,
      note: $('stock-note').value,
    });
    $('stock-change').value = '';
    $('stock-note').value = '';
    await loadProducts();
    message('Stock change recorded.');
  } catch (error) { message(error.message, true); }
}

function updateBillPrice() {
  const product = state.products.find((row) => String(row.id) === $('bill-product').value);
  if (product) $('bill-price').value = (product.unit_price_cents / 100).toFixed(2);
}

function renderBillLines() {
  const body = $('bill-lines');
  body.replaceChildren();
  let total = 0;
  if (!state.billLines.length) emptyRow(body, 5, 'Choose a product and add it to this bill.');
  state.billLines.forEach((line, index) => {
    const product = state.products.find((row) => row.id === line.product_id);
    const lineCents = Math.round(line.quantity * line.unit_price * 100);
    total += lineCents;
    rowInto(body, [
      product?.name || 'Product', amount(line.quantity),
      money(line.unit_price * 100), money(lineCents),
    ], button('Remove', () => {
      state.billLines.splice(index, 1);
      renderBillLines();
    }));
  });
  $('bill-total').textContent = `Total ${money(total)}`;
}

function addBillLine(event) {
  event.preventDefault();
  const productId = Number($('bill-product').value);
  const quantity = Number($('bill-quantity').value);
  const price = Number($('bill-price').value);
  if (!productId || !(quantity > 0) || !(price >= 0)) return;
  state.billLines.push({product_id: productId, quantity, unit_price: price});
  renderBillLines();
}

async function completeBill() {
  if (!state.billLines.length) {
    $('bill-message').textContent = 'Add at least one product to the bill.';
    return;
  }
  const control = $('complete-bill');
  control.disabled = true;
  state.pendingBillId ||= (crypto.randomUUID?.() || `bill-${Date.now()}`);
  try {
    const result = await post('/api/shop/bills', {
      receipt_id: state.pendingBillId, day: localDay(),
      lines: state.billLines,
    });
    state.billLines = [];
    state.pendingBillId = null;
    renderBillLines();
    $('history-day').value = localDay();
    await loadProducts();
    await loadHistory();
    $('bill-message').textContent = `Bill ${result.id} completed: ${money(result.total_cents)}.`;
    message('Bill completed and stock updated.');
  } catch (error) {
    $('bill-message').textContent = error.message;
    message(error.message, true);
  } finally { control.disabled = false; }
}

async function loadHistory() {
  const day = $('history-day').value || localDay();
  try {
    const [summary, bills] = await Promise.all([
      request(`/api/shop/day?day=${encodeURIComponent(day)}`),
      request(`/api/shop/bills?day=${encodeURIComponent(day)}`),
    ]);
    const strip = $('day-summary');
    strip.replaceChildren();
    for (const label of [
      `${summary.bill_count} completed bills`,
      `Sales ${money(summary.sales_cents)}`,
      summary.close?.status === 'closed' ? 'Day closed' : 'Day open',
    ]) strip.append(node('span', label));
    const body = $('history-rows');
    body.replaceChildren();
    if (!bills.length) emptyRow(body, 5, 'No customer bills on this day.');
    for (const bill of bills) {
      const items = bill.lines.map((line) => `${amount(line.quantity)} × ${line.name}`).join(', ');
      const action = bill.status === 'completed' && summary.close?.status !== 'closed'
        ? button('Void', () => voidBill(bill.id)) : null;
      rowInto(body, [bill.id, items, money(bill.total_cents), bill.status], action);
    }
    $('done-day').disabled = summary.close?.status === 'closed';
    $('reopen-day').hidden = summary.close?.status !== 'closed';
    state.closePreview = summary;
  } catch (error) { message(error.message, true); }
}

async function voidBill(receiptId) {
  if (!window.confirm('Void this bill and restore its stock? The bill remains in History.')) return;
  try {
    await post('/api/shop/bills/void', {receipt_id: receiptId});
    await loadProducts();
    await loadHistory();
    message('Bill voided and stock restored.');
  } catch (error) { message(error.message, true); }
}

async function reviewClose() {
  if (state.billLines.length) {
    message('Finish or clear the bill still open on this screen before closing the day.', true);
    return;
  }
  await loadHistory();
  const summary = state.closePreview;
  if (!summary || summary.close?.status === 'closed') return;
  const preview = $('close-preview');
  preview.replaceChildren();
  preview.append(node('p', `Day: ${summary.day}`));
  preview.append(node('p', `Completed bills: ${summary.bill_count}`));
  preview.append(node('p', `Sales total: ${money(summary.sales_cents)}`));
  preview.append(node('p', 'Current stock:'));
  const list = document.createElement('ul');
  for (const product of summary.stock) list.append(node('li', `${product.name}: ${amount(product.stock)} ${product.unit}`));
  preview.append(list);
  $('close-dialog').showModal();
}

async function confirmClose() {
  const control = $('confirm-close');
  control.disabled = true;
  try {
    const summary = state.closePreview;
    const result = await post('/api/shop/day-close', {
      day: summary.day, review_token: summary.review_token,
    });
    $('close-dialog').close();
    await loadHistory();
    await loadForecast();
    message(`Day closed. Forecast task ${result.job_status}; you can continue using the application.`);
    showTab('forecast');
  } catch (error) { message(error.message, true); }
  finally { control.disabled = false; }
}

async function confirmReopen() {
  try {
    await post('/api/shop/day-reopen', {
      day: $('history-day').value, reason: $('reopen-reason').value,
    });
    $('reopen-dialog').close();
    $('reopen-reason').value = '';
    await loadHistory();
    await loadForecast();
    message('Day reopened. Correct its records, then close it again for a new forecast.');
  } catch (error) { message(error.message, true); }
}

function chooseToBuy(product, suggested) {
  showTab('to-buy');
  $('buy-product').value = product.id;
  $('buy-quantity').value = suggested && suggested > 0 ? suggested : '';
  $('buy-quantity').focus();
  message('Enter the quantity you decide to consider, then add it to To-buy.');
}

async function loadForecast() {
  try {
    const data = await request('/api/shop/forecast');
    state.forecast = data;
    if (forecastPollTimer) clearTimeout(forecastPollTimer);
    forecastPollTimer = null;
    const body = $('forecast-rows');
    body.replaceChildren();
    $('forecast-count').textContent = `${state.products.length} products`;
    const first = data.products.find((row) => row.daily?.length);
    const forecastDay = first?.daily[0].target_day
      || (data.origin_day ? new Date(data.origin_day + 'T00:00:00').toLocaleDateString() : null);
    const job = data.job;
    $('forecast-date-note').textContent = !data.origin_day
      ? 'Close a day in Billing to prepare the next dated forecast.'
      : job?.status === 'queued' ? `Forecasts for ${data.origin_day} are queued.`
      : job?.status === 'running' ? `Forecasts for ${data.origin_day} are being prepared.`
      : job?.status === 'failed' ? `Forecast calculation failed: ${job.error || 'unknown error'}. You can retry.`
      : first ? `Forecast for ${forecastDay}, prepared after ${data.origin_day} closed.`
      : job?.status === 'complete' ? `Calculation completed for ${data.origin_day}. Products still need enough history or a passing model check.`
      : `Latest closed day: ${data.origin_day}. Product forecasts are not available yet.`;
    $('retry-forecast').hidden = job?.status !== 'failed';
    const byId = new Map(data.products.map((row) => [row.product_id, row]));
    if (!state.products.length) emptyRow(body, 5, 'Start by adding products under Store → Catalogue.');
    for (const product of state.products) {
      const forecast = byId.get(product.id);
      const available = forecast?.status === 'available' && forecast.daily?.length;
      const value = available ? `${amount(forecast.daily[0].units)} ${product.unit}` : '—';
      const restock = job?.status === 'queued' || job?.status === 'running'
        ? 'Preparing forecast'
        : job?.status === 'failed' ? 'Calculation failed'
        : available
        ? (forecast.restock_error || (forecast.restock?.order_now
          ? (forecast.restock.suggested_order_units === null
            ? 'Needs review' : `Review ${amount(forecast.restock.suggested_order_units)} ${product.unit}`)
          : 'No order indicated'))
        : (forecast?.status === 'validation_failed' ? 'Model check did not pass' : 'History needed');
      const action = available ? button('Consider buying', () =>
        chooseToBuy(product, forecast.restock?.suggested_order_units)) : null;
      const tr = rowInto(body, [
        product.name, `${amount(product.stock)} ${product.unit}`, value, restock,
      ], action);
      if (forecast?.reason) tr.cells[3].title = forecast.reason;
    }
    if (job?.status === 'queued' || job?.status === 'running') {
      forecastPollTimer = setTimeout(() => {
        if (!$('panel-forecast').hidden) loadForecast();
      }, 2000);
    }
  } catch (error) { message(error.message, true); }
}

async function retryForecast() {
  if (!state.forecast?.origin_day) return;
  try {
    const result = await post('/api/shop/forecast/retry', {day: state.forecast.origin_day});
    await loadForecast();
    message(`Forecast task ${result.status}. The page will update when it finishes.`);
  } catch (error) { message(error.message, true); }
}

async function loadToBuy() {
  try {
    const entries = await request('/api/shop/to-buy');
    const body = $('buy-rows');
    body.replaceChildren();
    if (!entries.length) emptyRow(body, 4, 'Your list is empty. Choose products yourself before comparing prices.');
    for (const entry of entries) {
      rowInto(body, [
        entry.name, `${amount(entry.quantity)} ${entry.unit}`,
        `${entry.needed_by_days} days`,
      ], button('Remove', async () => {
        try {
          await post('/api/shop/to-buy/remove', {product_id: entry.product_id});
          await loadToBuy();
        } catch (error) { message(error.message, true); }
      }));
    }
  } catch (error) { message(error.message, true); }
}

async function saveToBuy(event) {
  event.preventDefault();
  try {
    await post('/api/shop/to-buy', {
      product_id: Number($('buy-product').value),
      quantity: Number($('buy-quantity').value),
      needed_by_days: Number($('buy-days').value),
    });
    await loadToBuy();
    message('Added to your To-buy list. No comparison has started yet.');
  } catch (error) { message(error.message, true); }
}

async function saveOffer(event) {
  event.preventDefault();
  const field = (id) => $(id).value.trim() || null;
  try {
    await post('/api/shop/offers', {
      product_id: Number($('offer-product').value),
      supplier: $('offer-supplier').value, channel: $('offer-channel').value,
      source_url: field('offer-url'), pack_units: field('offer-pack'),
      pack_price: field('offer-price'), minimum_order_units: field('offer-minimum'),
      available_units: field('offer-available'), delivery_days: field('offer-delivery'),
      delivery_fee: field('offer-fee'),
    });
    $('offer-form').reset();
    message('Supplier quote saved. Compare prices when you are ready.');
  } catch (error) { message(error.message, true); }
}

async function saveWebLink(event) {
  event.preventDefault();
  const field = (id) => $(id).value.trim() || null;
  try {
    await post('/api/shop/web-links', {
      product_id: Number($('web-product').value), site_name: field('web-site'),
      approved_host: field('web-host'), expected_sku: field('web-sku'),
      url: field('web-url'), mode: $('web-mode').value,
      owner_match_confirmed: $('web-match').checked,
      pack_units: field('web-pack'), minimum_order_units: field('web-minimum'),
      available_units: field('web-available'), delivery_days: field('web-delivery'),
      delivery_fee: field('web-fee'),
    });
    $('web-form').reset();
    message('Trusted product link saved. It will be checked only when you compare prices.');
  } catch (error) { message(error.message, true); }
}

function sourceLink(url) {
  if (!url || !url.startsWith('https://')) return node('span', 'Owner quote');
  const link = node('a', 'Open source');
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  return link;
}

async function comparePrices() {
  const control = $('compare-prices');
  control.disabled = true;
  const output = $('comparison-results');
  output.replaceChildren(node('p', 'Checking saved quotes and trusted product pages…'));
  try {
    const data = await post('/api/shop/compare', {});
    output.replaceChildren();
    const comparison = data.comparison;
    if (comparison.status === 'ready') {
      output.append(node('h3', `Lowest complete basket: ${money(comparison.basket_total * 100)}`));
      for (const offer of comparison.chosen_offers) {
        const card = node('div', null, 'item-card');
        card.append(node('strong', `${offer.product_key} · ${offer.supplier}`));
        card.append(node('p', `${amount(offer.order_units)} ${offer.unit} · goods ${money(offer.goods_cost * 100)} · delivery ${money(offer.delivery_fee * 100)}`));
        card.append(sourceLink(offer.source_url));
        output.append(card);
      }
      output.append(node('p', 'These are observed or owner-entered terms. Check them again before buying; no order was placed.'));
    } else {
      output.append(node('h3', 'A complete price comparison is not available yet.'));
      output.append(node('p', `Missing complete eligible offers for: ${comparison.uncovered_products.join(', ')}.`));
    }
    for (const observation of data.observations) {
      const card = node('div', null, 'item-card');
      card.append(node('strong', `${observation.product_name} · ${observation.site_name}`));
      card.append(node('p', observation.status === 'observed'
        ? `Observed ${observation.currency} ${observation.price} at ${observation.checked_at}. Product match and delivery terms still matter.`
        : `Price unavailable: ${observation.error || observation.status}.`));
      card.append(sourceLink(observation.url));
      output.append(card);
    }
  } catch (error) {
    output.replaceChildren(node('p', error.message, 'message error'));
  } finally { control.disabled = false; }
}

async function loadOpportunities() {
  try {
    const data = await request(`/api/shop/opportunities?day=${encodeURIComponent(localDay())}`);
    const ideas = $('opportunity-ideas'), actions = $('opportunity-actions');
    ideas.replaceChildren(); actions.replaceChildren();
    if (!data.ideas.length) ideas.append(node('p', data.message || 'No new-product ideas to review yet.'));
    for (const idea of data.ideas) {
      const card = node('div', null, 'item-card');
      card.append(node('strong', idea.product_name));
      card.append(node('p', idea.reason));
      ideas.append(card);
    }
    if (!data.store_actions.length) actions.append(node('p', data.message || 'No store-improvement notes yet.'));
    for (const action of data.store_actions) {
      const card = node('div', null, 'item-card');
      card.append(node('strong', action.product_name || action.category));
      card.append(node('p', action.recommendation));
      card.append(node('small', action.reasons));
      actions.append(card);
    }
  } catch (error) { message(error.message, true); }
}

async function saveOwnerNote(event) {
  event.preventDefault();
  try {
    await post('/api/shop/feedback/owner', {
      day: $('owner-note-day').value, category: $('owner-note-category').value,
      product_name: $('owner-note-product').value, note: $('owner-note-text').value,
    });
    $('owner-note-text').value = '';
    $('owner-note-product').value = '';
    await loadOpportunities();
    message('Owner note saved for review.');
  } catch (error) { message(error.message, true); }
}

async function start() {
  for (const id of ['history-day', 'stock-day', 'owner-note-day', 'product-first-day']) $(id).value = localDay();
  for (const item of document.querySelectorAll('.main-nav button')) item.addEventListener('click', () => showTab(item.dataset.tab));
  for (const item of document.querySelectorAll('[data-billing-view]')) item.addEventListener('click', () => showSub('billing', item.dataset.billingView));
  for (const item of document.querySelectorAll('[data-store-view]')) item.addEventListener('click', () => showSub('store', item.dataset.storeView));
  $('settings-form').addEventListener('submit', saveSettings);
  $('product-form').addEventListener('submit', saveProduct);
  $('product-reset').addEventListener('click', clearProduct);
  $('stock-form').addEventListener('submit', saveStockChange);
  $('bill-product').addEventListener('change', updateBillPrice);
  $('bill-line-form').addEventListener('submit', addBillLine);
  $('complete-bill').addEventListener('click', completeBill);
  $('history-day').addEventListener('change', loadHistory);
  $('done-day').addEventListener('click', reviewClose);
  $('cancel-close').addEventListener('click', () => $('close-dialog').close());
  $('confirm-close').addEventListener('click', confirmClose);
  $('reopen-day').addEventListener('click', () => $('reopen-dialog').showModal());
  $('cancel-reopen').addEventListener('click', () => $('reopen-dialog').close());
  $('confirm-reopen').addEventListener('click', confirmReopen);
  $('to-buy-form').addEventListener('submit', saveToBuy);
  $('offer-form').addEventListener('submit', saveOffer);
  $('web-form').addEventListener('submit', saveWebLink);
  $('compare-prices').addEventListener('click', comparePrices);
  $('owner-note-form').addEventListener('submit', saveOwnerNote);
  $('refresh-forecast-view').addEventListener('click', loadForecast);
  $('retry-forecast').addEventListener('click', retryForecast);
  try {
    await loadSettings();
    for (const id of ['history-day', 'stock-day', 'owner-note-day', 'product-first-day']) $(id).value = localDay();
    await loadProducts();
    renderBillLines();
    await Promise.all([loadHistory(), loadForecast(), loadToBuy(), loadOpportunities()]);
  } catch (error) { message(error.message, true); }
}

start();
