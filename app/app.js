const $ = (id) => document.getElementById(id);
const number = (value, digits = 2) => Number(value).toFixed(digits);
const whole = (value) => Number(value).toLocaleString();
let experiments = [];
let allProducts = [];
let futureForecasts = [];

async function getJson(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Could not load results.');
  return data;
}

const quantity = (value) => Number(value).toLocaleString(undefined, {maximumFractionDigits: 6});
const optionalNumber = (id) => $(id).value.trim() === '' ? null : Number($(id).value);

function showFutureForecast() {
  const forecast = futureForecasts.find((entry) => entry.id === $('future-forecast').value);
  const body = $('future-table');
  body.replaceChildren();
  $('restock-results').hidden = true;
  $('restock-status').textContent = '';
  if (!forecast) return;
  for (const row of forecast.rows) {
    const tr = document.createElement('tr');
    for (const value of [row.date, number(row.forecast), number(row.median)]) {
      const td = document.createElement('td');
      td.textContent = value;
      tr.append(td);
    }
    body.append(tr);
  }
  $('future-status').textContent = `Store ${forecast.store} · product ${forecast.item} · ${forecast.start} to ${forecast.end}. These dates follow the local dataset cutoff; actual sales for them are not in this file.`;
}

function syncIncomingDay() {
  const hasIncoming = Number($('incoming-units').value) > 0;
  $('incoming-day').disabled = !hasIncoming;
  $('incoming-day').required = hasIncoming;
  if (!hasIncoming) $('incoming-day').value = '';
}

function showRestock(result) {
  const plan = result.plan;
  const unit = plan.unit;
  $('demand-result').textContent = `${quantity(plan.expected_demand_7d)} ${unit}`;
  $('cover-result').textContent = plan.coverage_reaches_forecast_end
    ? 'At least 7 days' : `${plan.days_covered_by_current_stock} full days`;
  $('reorder-result').textContent = plan.reorder_point_units === null
    ? 'Beyond 7 days' : `${quantity(plan.reorder_point_units)} ${unit}`;
  $('quantity-result').textContent = plan.suggested_order_units === null
    ? 'Needs review' : `${quantity(plan.suggested_order_units)} ${unit}`;
  $('buffer-result').textContent = `Planning cushion: ${quantity(plan.buffer_units)} ${unit}, based on the extra days of cover you entered.`;

  const orderMessage = $('order-message');
  orderMessage.className = 'result-message';
  if (!plan.horizon_sufficient) {
    orderMessage.textContent = 'The supplier would arrive after this seven-day forecast. A full order quantity needs a longer forecast.';
    orderMessage.classList.add('warning');
  } else if (plan.order_constraint_status === 'shelf_life_conflict') {
    orderMessage.textContent = `An order is indicated, but the required quantity (${quantity(plan.unconstrained_order_units)} ${unit} before supplier rules) exceeds the forecast sell-through limit (${quantity(plan.shelf_life_sell_through_cap_units)} ${unit}) before expiry. Review the supplier or stock plan.`;
    orderMessage.classList.add('conflict');
  } else if (plan.order_now) {
    orderMessage.textContent = `Order now: ${quantity(plan.suggested_order_units)} ${unit}. This includes any known supplier minimum and full-pack rule.`;
  } else {
    orderMessage.textContent = 'No order indicated today. Recheck when stock or sales information changes.';
  }

  const shortage = $('shortage-message');
  shortage.className = 'result-message';
  if (plan.shortage_before_new_delivery) {
    shortage.textContent = `Before-delivery warning: forecast demand first exceeds available stock on ${result.first_short_date}. About ${quantity(plan.bridging_units_needed)} ${unit} would be needed sooner; a new order with the entered delivery time cannot fix that earlier gap. Recalculate if you obtain stock sooner.`;
    shortage.classList.add('warning');
  } else if (plan.pre_delivery_check_limited_to_forecast) {
    shortage.textContent = 'No shortage appears in the seven forecast days, but the supplier arrives later. Days after this forecast have not been checked.';
    shortage.classList.add('warning');
  } else {
    shortage.textContent = 'No before-delivery shortage appears in this seven-day forecast.';
  }

  const shelf = $('shelf-message');
  shelf.hidden = !plan.shelf_life_check_limited;
  if (plan.shelf_life_check_limited) {
    shelf.textContent = 'Shelf-life check incomplete: the entered shelf life extends beyond the seven forecast days.';
    shelf.className = 'result-message warning';
  }
  $('restock-results').hidden = false;
}

async function submitRestock(event) {
  event.preventDefault();
  $('restock-status').textContent = '';
  $('restock-results').hidden = true;
  const payload = {
    forecast_id: $('future-forecast').value,
    stock_on_hand: Number($('stock-on-hand').value),
    unit: $('stock-unit').value.trim(),
    order_increment: Number($('order-increment').value),
    lead_days: Number($('lead-days').value),
    incoming_units: Number($('incoming-units').value),
    incoming_day: optionalNumber('incoming-day'),
    extra_cover_days: Number($('extra-cover').value),
    minimum_order_units: optionalNumber('minimum-order'),
    pack_multiple_units: optionalNumber('pack-multiple'),
    shelf_life_days: optionalNumber('shelf-life'),
  };
  try {
    const result = await getJson('/api/restock', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    showRestock(result);
  } catch (error) {
    $('restock-status').textContent = error.message;
  }
}

async function startFutureForecast() {
  try {
    futureForecasts = await getJson('/api/forecasts');
    const select = $('future-forecast');
    if (!futureForecasts.length) {
      $('future-status').textContent = 'No saved seven-day forecast is available yet.';
      select.disabled = true;
      $('restock-form').querySelector('button').disabled = true;
      return;
    }
    for (const forecast of futureForecasts) {
      const option = document.createElement('option');
      option.value = forecast.id;
      option.textContent = `Store ${forecast.store} · product ${forecast.item} · ${forecast.start}`;
      select.append(option);
    }
    showFutureForecast();
    select.addEventListener('change', showFutureForecast);
    $('incoming-units').addEventListener('input', syncIncomingDay);
    $('restock-form').addEventListener('submit', submitRestock);
  } catch (error) {
    $('future-status').textContent = error.message;
  }
}

async function startModelMetrics() {
  try {
    const summary = await getJson('/api/model-metrics');
    if (!summary) {
      $('model-metrics-intro').textContent = 'Saved validation metrics are not available yet.';
      return;
    }
    const count = summary.methods[0].predictions;
    $('model-metrics-intro').textContent = `${summary.store_weeks} store-weeks · ${whole(count)} matching product-days per method. The provisional model and simple reference were checked on the same targets.`;
    const body = $('model-metrics-table');
    body.replaceChildren();
    for (const method of summary.methods) {
      const tr = document.createElement('tr');
      const cells = [
        method.label, `${number(method.mae)} units`,
        method.wape === null ? 'Undefined' : `${number(method.wape * 100, 1)}%`,
        `${number(method.rmse)} units`,
        whole(method.misses_over_20_units),
      ];
      for (const value of cells) {
        const td = document.createElement('td');
        td.textContent = value;
        tr.append(td);
      }
      body.append(tr);
    }
  } catch (error) {
    $('model-metrics-intro').textContent = error.message;
  }
}

function svgNode(name, attributes) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function drawChart(rows) {
  const chart = $('chart');
  chart.replaceChildren();
  const width = 780, height = 290, left = 50, right = 20, top = 18, bottom = 46;
  const maxValue = Math.max(1, ...rows.flatMap((row) => [row.actual, row.average, row.linear]));
  const ceiling = Math.ceil(maxValue * 1.12);
  const x = (index) => left + index * (width - left - right) / (rows.length - 1);
  const y = (value) => height - bottom - value / ceiling * (height - top - bottom);
  for (let step = 0; step <= 4; step++) {
    const value = ceiling * step / 4;
    const line = svgNode('line', {x1: left, x2: width - right, y1: y(value), y2: y(value), stroke: '#e7eeee'});
    chart.append(line);
    const label = svgNode('text', {x: left - 10, y: y(value) + 4, 'text-anchor': 'end', fill: '#748890', 'font-size': 11});
    label.textContent = number(value, value < 10 ? 1 : 0);
    chart.append(label);
  }
  rows.forEach((row, index) => {
    const label = svgNode('text', {x: x(index), y: height - 17, 'text-anchor': 'middle', fill: '#687e86', 'font-size': 11});
    label.textContent = row.date.slice(5);
    chart.append(label);
  });
  const series = [
    ['average', '#e4a647'], ['linear', '#6869b0'], ['actual', '#238779'],
  ];
  for (const [key, color] of series) {
    const path = svgNode('polyline', {
      points: rows.map((row, index) => `${x(index)},${y(row[key])}`).join(' '),
      fill: 'none', stroke: color, 'stroke-width': key === 'actual' ? 3 : 2.5,
      'stroke-linecap': 'round', 'stroke-linejoin': 'round',
    });
    chart.append(path);
    rows.forEach((row, index) => {
      const dot = svgNode('circle', {
        cx: x(index), cy: y(row[key]), r: 4.5,
        fill: key === 'actual' && row.assumed_zero ? '#ffffff' : color,
        stroke: color, 'stroke-width': 2,
      });
      chart.append(dot);
    });
  }
}

function showExperiment(experiment) {
  $('product-count').textContent = whole(experiment.product_count);
  $('average-error').textContent = number(experiment.average_error);
  $('linear-error').textContent = number(experiment.linear_error);
  $('zero-error').textContent = number(experiment.zero_error);
}

function showProduct(product, experiment) {
  $('detail-title').textContent = `Product ${product.item}`;
  $('detail-subtitle').textContent = `Store ${experiment.store} · ${experiment.start} to ${experiment.end}`;
  $('detail-score').innerHTML = `Four-week average miss<br><strong>${number(product.average_error)} units</strong><br>Linear model miss: ${number(product.linear_error)} units`;
  drawChart(product.rows);
  const body = $('detail-table');
  body.replaceChildren();
  for (const row of product.rows) {
    const tr = document.createElement('tr');
    const cells = [row.date, number(row.actual), number(row.average), number(row.linear)];
    for (const value of cells) {
      const td = document.createElement('td');
      td.textContent = value;
      tr.append(td);
    }
    const source = document.createElement('td');
    const tag = document.createElement('span');
    tag.className = row.assumed_zero ? 'tag assumed' : 'tag';
    tag.textContent = row.assumed_zero ? 'Assumed zero' : 'Recorded';
    source.append(tag);
    tr.append(source);
    body.append(tr);
  }
}

async function loadProduct() {
  const experimentId = $('experiment').value;
  const item = $('product').value;
  if (!experimentId || !item) return;
  try {
    $('status').textContent = '';
    const product = await getJson(`/api/product?experiment=${encodeURIComponent(experimentId)}&item=${encodeURIComponent(item)}`);
    showProduct(product, experiments.find((entry) => entry.id === experimentId));
  } catch (error) {
    $('status').textContent = error.message;
  }
}

function renderProducts() {
  const query = $('product-search').value.trim();
  const select = $('product');
  const previous = select.value;
  select.replaceChildren();
  const matches = allProducts.filter((item) => String(item).includes(query));
  for (const item of matches) {
    const option = document.createElement('option');
    option.value = item;
    option.textContent = `Product ${item}`;
    select.append(option);
  }
  if (matches.includes(Number(previous))) select.value = previous;
  $('status').textContent = matches.length ? '' : 'No product number matches that search.';
  if (matches.length) loadProduct();
}

async function loadExperiment() {
  const experimentId = $('experiment').value;
  const experiment = experiments.find((entry) => entry.id === experimentId);
  if (!experiment) return;
  try {
    $('status').textContent = '';
    showExperiment(experiment);
    allProducts = await getJson(`/api/products?experiment=${encodeURIComponent(experimentId)}`);
    $('product-search').value = '';
    renderProducts();
  } catch (error) {
    $('status').textContent = error.message;
  }
}

async function start() {
  try {
    experiments = await getJson('/api/experiments');
    if (!experiments.length) {
      $('status').textContent = 'Saved research files are not available on this computer yet.';
      return;
    }
    const select = $('experiment');
    for (const experiment of experiments) {
      const option = document.createElement('option');
      option.value = experiment.id;
      option.textContent = experiment.label;
      select.append(option);
    }
    await loadExperiment();
    $('experiment').addEventListener('change', loadExperiment);
    $('product').addEventListener('change', loadProduct);
    $('product-search').addEventListener('input', renderProducts);
  } catch (error) {
    $('status').textContent = error.message;
  }
}

start();
startFutureForecast();
startModelMetrics();
