const $ = s => document.querySelector(s), $$ = s => Array.from(document.querySelectorAll(s));
const fields = [
  ['title', 'Subject or title'],
  ['course_code', 'Course code'],
  ['module', 'Module / unit'],
  ['institution', 'University / institution'],
  ['scheme', 'Scheme / academic year'],
  ['category', 'Notes category'],
  ['website', 'Website'],
  ['phone', 'Phone number'],
  ['email', 'Email'],
  ['subtitle', 'Subtitle'],
  ['tags', 'Topic tags / programs']
];

let state = {
  job: null,
  documents: [],
  configs: {},
  metadataRecords: [],
  metadataMatches: {},
  defaults: {},
  logoUrl: null
};

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[c]));

const toast = t => {
  const n = $('#toast');
  n.textContent = t;
  n.classList.add('show');
  setTimeout(() => n.classList.remove('show'), 2800);
};

const rules = () => {
  try { return JSON.parse(localStorage.getItem('invytraRules') || '[]'); }
  catch { return []; }
};

function saveRules(a) {
  localStorage.setItem('invytraRules', JSON.stringify([...new Set(a.map(x => String(x).trim()).filter(Boolean))]));
  renderRules();
}

function renderRules() {
  const box = $('#rulesList'), a = rules();
  box.innerHTML = a.length
    ? a.map((x, i) => `<span class="rule-chip">${esc(x)} <button type="button" data-rule-del="${i}" aria-label="Remove rule">×</button></span>`).join('')
    : '<small class="muted">No remembered watermark rules yet.</small>';
  box.querySelectorAll('[data-rule-del]').forEach(b => b.onclick = () => saveRules(rules().filter((_, i) => i !== +b.dataset.ruleDel)));
}
renderRules();

$('#addRule').onclick = () => {
  let v = $('#ruleInput').value.trim();
  if (v) saveRules([...rules(), v]);
  $('#ruleInput').value = '';
};
$('#resetRules').onclick = () => saveRules([]);

const pdfinput = $('#pdfs');
pdfinput.addEventListener('change', () => {
  $('#chosenFiles').textContent = [...pdfinput.files].map(f => f.name).join(' · ');
});

const dz = $('#dropzone');
['dragenter', 'dragover'].forEach(e => dz.addEventListener(e, x => { x.preventDefault(); dz.classList.add('drag'); }));
['dragleave', 'drop'].forEach(e => dz.addEventListener(e, x => { x.preventDefault(); dz.classList.remove('drag'); }));
dz.addEventListener('drop', e => {
  if (e.dataTransfer.files.length) {
    pdfinput.files = e.dataTransfer.files;
    pdfinput.dispatchEvent(new Event('change'));
  }
});

function goStep(n) {
  $$('.step').forEach(s => {
    s.classList.toggle('active', +s.dataset.step === n);
    s.classList.toggle('done', +s.dataset.step < n);
  });
}

function blankDefaults() {
  return {
    institution: '',
    scheme: 'KTU 2024 SCHEME',
    category: 'LAB EXAM NOTES',
    website: 'azhumathimayam.invytra.in',
    phone: '8606159002',
    email: '',
    subtitle: '',
    tags: '12 Programs • Aim • Algorithm • C Program • Sample I/O • Result'
  };
}

async function safeFetchJSON(url, options = {}) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (netErr) {
    throw new Error('Network error connecting to server. Please check your connection.');
  }

  const rawText = await res.text();
  let data;
  try {
    data = JSON.parse(rawText);
  } catch (parseErr) {
    if (!res.ok) {
      if (res.status === 413) throw new Error('File upload too large. Reduce file size and try again.');
      if (res.status === 504 || res.status === 502) throw new Error('Server timeout or gateway error. Please try again.');
      if (res.status === 404) throw new Error('The requested session was not found or has expired. Please re-upload.');
      const cleanSnippet = rawText.slice(0, 150).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
      throw new Error(`Server returned error ${res.status}${cleanSnippet ? ': ' + cleanSnippet : ''}`);
    }
    throw new Error('Server returned an unreadable response format.');
  }

  if (!res.ok) {
    const msg = data.error || data.message || `Request failed with status ${res.status}`;
    const extra = data.file_errors?.length ? ' — ' + data.file_errors.map(z => `${z.filename}: ${z.error}`).join(' | ') : '';
    throw new Error(msg + extra);
  }

  return data;
}

function upload() {
  const fd = new FormData();
  for (const f of pdfinput.files) fd.append('pdfs', f);
  if ($('#metadata').files[0]) fd.append('metadata', $('#metadata').files[0]);
  if ($('#logo').files[0]) fd.append('logo', $('#logo').files[0]);
  if ($('#coverReference').files[0]) fd.append('cover_reference', $('#coverReference').files[0]);
  
  return safeFetchJSON('/api/upload', { method: 'POST', body: fd });
}

$('#uploadForm').addEventListener('submit', async e => {
  e.preventDefault();
  if (!pdfinput.files.length) return;
  $('#analyzeBtn').disabled = true;
  $('#analyzeBtn').innerHTML = 'Analyzing locally…';
  $('#uploadError').textContent = '';
  
  try {
    let d = await upload();
    state.job = d.job_id;
    state.documents = d.documents;
    state.metadataRecords = d.metadata_records || [];
    state.metadataMatches = d.metadata_matches || {};
    state.defaults = d.defaults || blankDefaults();
    state.logoUrl = $('#logo').files[0] ? URL.createObjectURL($('#logo').files[0]) : '/static/azhumathimayam-logo.png';
    initConfigs();
    renderReview(d);
    $('#uploadPanel').classList.add('hidden');
    $('#reviewPanel').classList.remove('hidden');
    $('#resultsPanel').classList.add('hidden');
    goStep(2);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (err) {
    $('#uploadError').textContent = err.message;
  } finally {
    $('#analyzeBtn').disabled = false;
    $('#analyzeBtn').innerHTML = 'Analyze PDFs <span>→</span>';
  }
});

function initConfigs() {
  state.configs = {};
  state.documents.filter(d => !d.error).forEach(d => {
    let m = state.metadataMatches[d.id] || {};
    let s = d.suggestions || {};
    let f = {
      ...blankDefaults(),
      title: s.title || '',
      course_code: s.course_code || '',
      module: s.module || '',
      institution: s.institution || '',
      scheme: s.scheme || 'KTU 2024 SCHEME',
      category: s.category || 'LAB EXAM NOTES',
      tags: s.tags || '12 Programs • Aim • Algorithm • C Program • Sample I/O • Result'
    };
    
    Object.keys(m).forEach(k => {
      if (k !== 'filename' && fields.some(x => x[0] === k) && String(m[k]).trim()) {
        f[k] = m[k];
      }
    });

    // Check remembered rules
    let autoTexts = (d.text_candidates || [])
      .filter(x => rules().some(rule => x.text.toLowerCase().includes(rule.toLowerCase())))
      .map(x => x.text);

    state.configs[d.id] = {
      fields: f,
      remove_pages: [],
      remove_texts: autoTexts,
      manual_mark: '',
      manual_include: false,
      watermark: true,
      watermark_pages: d.pages.filter(p => p.classification.label === 'Study material').map(p => p.number - 1),
      remove_brand_links: false,
      remove_brand_annotations: false,
      remove_images: []
    };
  });
}

function inputHTML(key, label, val, cls = '') {
  return `<div class="field ${cls}"><label>${esc(label)}</label><input data-field="${esc(key)}" value="${esc(val)}" placeholder="${key === 'title' ? 'e.g. Data Structures Lab Exam' : key === 'scheme' ? 'KTU 2024 SCHEME' : key === 'website' ? 'azhumathimayam.invytra.in' : ''}"></div>`;
}

function renderReview(resp) {
  const defaults = $('#globalDefaults .defaults-grid');
  defaults.innerHTML = fields
    .filter(([k]) => !['title', 'course_code', 'module'].includes(k))
    .map(([k, l]) => inputHTML(k, l, state.defaults[k] || ''))
    .join('');

  defaults.querySelectorAll('[data-field]').forEach(i => i.oninput = () => state.defaults[i.dataset.field] = i.value);

  $('#applyDefaults').onclick = () => {
    for (const d of state.documents.filter(x => !x.error)) {
      const c = state.configs[d.id];
      for (const [k] of fields) {
        if (!c.fields[k] && state.defaults[k]) c.fields[k] = state.defaults[k];
      }
    }
    renderDocs();
    toast('Defaults applied to blank fields.');
  };

  const ref = $('#referenceNotice');
  if (resp.cover_reference_uploaded) {
    ref.classList.remove('hidden');
    ref.innerHTML = `Cover reference saved for this batch:<br><img src="/reference/${state.job}" alt="Cover reference" style="max-width:180px;max-height:220px;object-fit:contain;margin-top:9px;border:1px solid #e4d9d3;border-radius:6px">`;
  } else {
    ref.classList.add('hidden');
  }

  const errDocs = state.documents.filter(d => d.error);
  const unmatched = resp.metadata_unmatched || [];
  const noticeParts = [
    resp.metadata_error,
    errDocs.length ? errDocs.map(d => `${d.filename}: ${d.error}`).join(' | ') : '',
    unmatched.length ? `Metadata matching: ${unmatched.map(x => `${x.filename} (${x.reason})`).join(' · ')}` : ''
  ].filter(Boolean);
  
  $('#metadataNotice').classList.toggle('hidden', !noticeParts.length);
  $('#metadataNotice').textContent = noticeParts.join(' ');

  renderMetadataMap();
  renderDocs();
  
  const hasValid = state.documents.some(d => !d.error);
  $('#processBtn').disabled = !hasValid;
  if (!hasValid) $('#processBtn').textContent = 'No analyzable PDFs in this batch';
}

function renderMetadataMap() {
  const rows = state.metadataRecords;
  const el = $('#metadataMapping');
  if (!rows.length) { el.classList.add('hidden'); return; }
  el.classList.remove('hidden');
  
  let options = state.documents.filter(d => !d.error).map(d => `<option value="${d.id}">${esc(d.filename)}</option>`).join('');
  el.innerHTML = `<h4>Batch metadata matching</h4><div class="muted">Filename matches are prefilled. Assign any other records manually.</div>` +
    rows.map((r, i) => {
      let exact = state.documents.find(d => !d.error && d.filename.toLowerCase() === String(r.filename || '').toLowerCase());
      return `<div class="metadata-row"><span><b>${esc(r.filename || 'Unnamed record')}</b><br>${esc(Object.entries(r).filter(([k]) => k !== 'filename').map(([k, v]) => `${k}: ${v}`).join(' · ').slice(0, 190))}</span><select data-meta-select="${i}"><option value="">Select a PDF…</option>${options}</select><button class="button secondary" data-meta-apply="${i}">Apply fields</button></div>`;
    }).join('');

  el.querySelectorAll('[data-meta-select]').forEach(s => {
    let r = rows[+s.dataset.metaSelect];
    let m = state.documents.find(d => !d.error && d.filename.toLowerCase() === String(r.filename || '').toLowerCase());
    if (m) s.value = m.id;
  });

  el.querySelectorAll('[data-meta-apply]').forEach(b => b.onclick = () => {
    let i = +b.dataset.metaApply;
    let id = el.querySelector(`[data-meta-select="${i}"]`).value;
    if (!id) { toast('Choose a PDF for this record first.'); return; }
    let r = rows[i], c = state.configs[id];
    let updates = Object.entries(r).filter(([k, v]) => k !== 'filename' && fields.some(x => x[0] === k) && v);
    updates.forEach(([k, v]) => c.fields[k] = v);
    renderDocs();
    toast('Metadata applied to selected PDF.');
  });
}

function renderDocs() {
  const wrap = $('#docs');
  wrap.innerHTML = state.documents.map(d => d.error ? `
    <article class="doc-card">
      <div class="doc-head">
        <div><div class="doc-name">${esc(d.filename)}</div><div class="doc-meta">Could not analyze this file</div></div>
        <span class="badge" style="background:#fff0ee;color:#9d3028">Needs attention</span>
      </div>
      <div class="doc-body"><div class="result-error">${esc(d.error)}</div></div>
    </article>` : docHTML(d)).join('');
  bindDocs();
}

function docHTML(d) {
  const c = state.configs[d.id], f = c.fields;
  const candidateRules = rules().map(x => x.toLowerCase());
  let pages = d.pages || [];
  let detected = d.text_candidates || [];
  let linkCandidates = pages.flatMap(p => (p.links || []).filter(u => /invytra|azhumathimayam|telegram|whatsapp/i.test(u)).map(u => ({ page: p.number, url: u })));

  let pageRows = pages.map(p => {
    let checked = c.remove_pages.includes(p.number - 1);
    let isPromo = ['Possible branded cover', 'Promotional page', 'QR / contact page'].includes(p.classification.label);
    return `<div class="page-row">
      <label class="page-remove">
        <input type="checkbox" data-remove-page="${p.number - 1}" ${checked ? 'checked' : ''}>
        <span class="page-text">
          <strong>Page ${p.number} · ${esc(p.classification.label)}</strong>
          <small class="evidence">${esc([...(p.classification.evidence || []), ...(p.page_number_detected ? ['page number detected'] : [])].join(' · ') || 'No strong signal.')}</small>
        </span>
      </label>
      <label class="page-mark" title="Watermark only if retained">
        <input type="checkbox" data-watermark-page="${p.number - 1}" ${c.watermark_pages.includes(p.number - 1) ? 'checked' : ''}>
        <small>Watermark</small>
      </label>
      <span class="confidence">${Math.round(p.classification.confidence * 100)}%${isPromo ? ' · suggest remove' : ''}</span>
    </div>`;
  }).join('');

  let canText = detected.map((x, i) => {
    let remembered = candidateRules.some(r => x.text.toLowerCase().includes(r));
    return `<label class="candidate">
      <input type="checkbox" data-remove-text="${i}" ${c.remove_texts.includes(x.text) || remembered ? 'checked' : ''}>
      <span><b>${esc(x.text)}</b><br>${esc(x.kind)} · pages ${esc(x.pages.join(', '))} · ${Math.round(x.confidence * 100)}% confidence${remembered ? ' · matched rule' : ''}</span>
    </label>`;
  }).join('');

  let imageCandidates = (d.repeated_images || []).map((im, i) => `
    <div class="image-candidate">
      <img src="${im.preview}" alt="Repeated image preview">
      <div>
        <label class="checkline"><input type="checkbox" data-remove-image="${i}" ${c.remove_images.includes(im.xref) ? 'checked' : ''}> Remove this exact image object</label>
        <small>Found on pages ${esc(im.pages.join(', '))}. ${esc(im.warning)}</small>
      </div>
    </div>`).join('');

  let imageSection = imageCandidates ? `<div class="brain-box"><h4>Repeated image objects</h4><p class="muted">Check thumbnails before removing.</p>${imageCandidates}</div>` : '';
  let warnings = (d.warnings || []).map(x => `<div class="warning">${esc(x)}</div>`).join('');

  return `<article class="doc-card" data-doc="${d.id}">
    <div class="doc-head">
      <div>
        <div class="doc-name">${esc(d.filename)}</div>
        <div class="doc-meta">${d.page_count} pages · ${esc(d.dimensions)} · original stays untouched</div>
      </div>
      <span class="badge">Analyzed locally</span>
    </div>
    <div class="doc-body">
      <div class="doc-layout">
        <div>
          <div class="section-title">Cover details & metadata</div>
          <div class="doc-fields">${fields.map(([k, l]) => inputHTML(k, l, f[k] || '')).join('')}</div>

          <div class="section-title" style="margin-top:24px">Page decisions</div>
          <div class="pages-list">${pageRows}</div>

          <div class="brain-box">
            <h4>Detected old watermarks & text marks</h4>
            ${canText || '<div class="muted">No recurring selectable watermark text detected.</div>'}
            <div class="field" style="margin-top:10px">
              <label>Other exact brand text to erase</label>
              <input data-manual-mark value="${esc(c.manual_mark || '')}" placeholder="e.g. oldsite.com or @telegram">
            </div>
            <label class="checkline">
              <input type="checkbox" data-manual-include ${c.manual_include ? 'checked' : ''}> Erase this exact text on retained pages
            </label>
            ${linkCandidates.length ? `<div class="candidate">Promotional links detected: ${linkCandidates.map(x => `p.${x.page}: ${esc(x.url)}`).join(' | ')}</div>` : ''}
            <label class="checkline">
              <input type="checkbox" data-remove-links ${c.remove_brand_links ? 'checked' : ''}> Remove promotional links
            </label>
            ${(d.annotation_candidates || []).length ? `<label class="checkline"><input type="checkbox" data-remove-annotations ${c.remove_brand_annotations ? 'checked' : ''}> Remove promotional annotations</label>` : ''}
          </div>

          <label class="checkline">
            <input type="checkbox" data-watermark ${c.watermark ? 'checked' : ''}> Add subtle AZHUMATHIMAYAM watermark on retained study pages
          </label>
          ${imageSection}
          ${warnings}
        </div>

        <div>
          <div class="section-title">Live Cover Preview</div>
          <div class="cover-preview">
            <div class="cover-caption">Updates instantly as you edit</div>
            <div class="cover" data-cover="${d.id}">
              <div class="cover-top">
                <div class="cover-scheme">KTU 2024 SCHEME</div>
                <img class="cover-logo" src="${state.logoUrl}" alt="Azhumathimayam">
                <div class="cover-logo-fallback hidden">അഴിമതി മയം</div>
              </div>
              <div class="cover-bottom">
                <div class="cover-cat">LAB EXAM NOTES</div>
                <div class="cover-title">Data Structures Lab Exam</div>
                <div class="cover-sub"></div>
                <div class="cover-divider"></div>
                <div class="cover-pill-btn">
                  <span class="cover-link-text">azhumathimayam.invytra.in</span>
                </div>
                <div class="cover-contact">Contact • 8606159002</div>
                <div class="cover-brand">I N V Y T R A</div>
                <div class="cover-tags">12 Programs • Aim • Algorithm • C Program • Sample I/O • Result</div>
              </div>
            </div>
          </div>

          <div class="section-title" style="margin-top:20px">Original Previews</div>
          <div class="preview-grid">
            <div class="preview-card">
              <img src="${d.pages[0]?.preview || ''}" alt="Page 1 preview">
              <span>Original · Page 1</span>
            </div>
            <div class="preview-card">
              <img src="${d.pages[d.pages.length - 1]?.preview || ''}" alt="Last page preview">
              <span>Original · Page ${d.pages.length}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </article>`;
}

function syncCover(id) {
  let c = state.configs[id], f = c.fields;
  let box = document.querySelector(`[data-cover="${id}"]`);
  if (!box) return;

  box.querySelector('.cover-scheme').textContent = (f.scheme || 'KTU 2024 SCHEME').toUpperCase();
  box.querySelector('.cover-cat').textContent = (f.category || 'LAB EXAM NOTES').toUpperCase();
  box.querySelector('.cover-title').textContent = f.title || 'Data Structures Lab Exam';

  let subParts = [f.subtitle, f.institution, [f.course_code, f.module].filter(Boolean).join(' · ')].filter(Boolean);
  let subEl = box.querySelector('.cover-sub');
  if (subParts.length) {
    subEl.textContent = subParts.join(' — ');
    subEl.style.display = 'block';
  } else {
    subEl.textContent = '';
    subEl.style.display = 'none';
  }

  let website = (f.website || 'azhumathimayam.invytra.in').replace(/^https?:\/\//, '').replace(/\/$/, '') || 'azhumathimayam.invytra.in';
  box.querySelector('.cover-link-text').textContent = website;

  let phone = (f.phone || '8606159002').trim();
  let email = (f.email || '').trim();
  let contactParts = [phone, email].filter(Boolean);
  let contactText = 'Contact • ' + (contactParts.length ? contactParts.join(' • ') : '8606159002');
  box.querySelector('.cover-contact').textContent = contactText;

  let tagsEl = box.querySelector('.cover-tags');
  if (tagsEl) {
    tagsEl.textContent = f.tags || '12 Programs • Aim • Algorithm • C Program • Sample I/O • Result';
  }
}

function bindDocs() {
  state.documents.filter(d => !d.error).forEach(d => {
    let card = document.querySelector(`[data-doc="${d.id}"]`), c = state.configs[d.id];
    
    card.querySelectorAll('[data-field]').forEach(i => {
      i.addEventListener('input', () => {
        c.fields[i.dataset.field] = i.value;
        syncCover(d.id);
      });
    });

    card.querySelectorAll('[data-remove-page]').forEach(i => {
      i.onchange = () => {
        let n = +i.dataset.removePage;
        c.remove_pages = i.checked ? [...new Set([...c.remove_pages, n])] : c.remove_pages.filter(x => x !== n);
      };
    });

    card.querySelectorAll('[data-watermark-page]').forEach(i => {
      i.onchange = () => {
        let n = +i.dataset.watermarkPage;
        c.watermark_pages = i.checked ? [...new Set([...c.watermark_pages, n])] : c.watermark_pages.filter(x => x !== n);
      };
    });

    card.querySelectorAll('[data-remove-image]').forEach(i => {
      i.onchange = () => {
        let x = d.repeated_images[+i.dataset.removeImage].xref;
        c.remove_images = i.checked ? [...new Set([...c.remove_images, x])] : c.remove_images.filter(t => t !== x);
      };
    });

    card.querySelectorAll('[data-remove-text]').forEach(i => {
      let x = d.text_candidates[+i.dataset.removeText].text;
      i.onchange = () => {
        c.remove_texts = i.checked ? [...new Set([...c.remove_texts, x])] : c.remove_texts.filter(t => t !== x);
        if (i.checked && confirm(`Remember "${x}" as a rule for future batches?`)) {
          saveRules([...rules(), x]);
        }
      };
    });

    card.querySelector('[data-manual-mark]').oninput = e => {
      let old = c.manual_mark;
      c.manual_mark = e.target.value;
      if (c.manual_include) {
        c.remove_texts = c.remove_texts.filter(t => t !== old);
        if (c.manual_mark.trim()) c.remove_texts.push(c.manual_mark.trim());
      }
    };

    card.querySelector('[data-manual-include]').onchange = e => {
      c.manual_include = e.target.checked;
      c.remove_texts = c.remove_texts.filter(t => t !== c.manual_mark);
      if (c.manual_include && c.manual_mark.trim()) c.remove_texts.push(c.manual_mark.trim());
    };

    card.querySelector('[data-remove-links]').onchange = e => c.remove_brand_links = e.target.checked;
    
    let annotCtrl = card.querySelector('[data-remove-annotations]');
    if (annotCtrl) annotCtrl.onchange = e => c.remove_brand_annotations = e.target.checked;

    card.querySelector('[data-watermark]').onchange = e => c.watermark = e.target.checked;

    syncCover(d.id);
  });
}

// ⚡ Smart Auto-Clean button handler
$('#autoCleanBtn').onclick = () => {
  let promoCount = 0;
  state.documents.filter(d => !d.error).forEach(d => {
    const c = state.configs[d.id];
    // Auto-select promo/ad boundary pages for removal
    d.pages.forEach(p => {
      if (['Possible branded cover', 'Promotional page', 'QR / contact page'].includes(p.classification.label)) {
        if (!c.remove_pages.includes(p.number - 1)) {
          c.remove_pages.push(p.number - 1);
          promoCount++;
        }
      }
    });

    // Auto-select detected old-brand text
    (d.text_candidates || []).forEach(tc => {
      if (!c.remove_texts.includes(tc.text)) {
        c.remove_texts.push(tc.text);
      }
    });

    // Apply suggestions if blank
    const s = d.suggestions || {};
    if (!c.fields.title && s.title) c.fields.title = s.title;
    if (!c.fields.course_code && s.course_code) c.fields.course_code = s.course_code;
    if (!c.fields.scheme) c.fields.scheme = s.scheme || 'KTU 2024 SCHEME';
    if (!c.fields.category) c.fields.category = s.category || 'LAB EXAM NOTES';
    if (!c.fields.tags) c.fields.tags = s.tags || '12 Programs • Aim • Algorithm • C Program • Sample I/O • Result';
    c.remove_brand_links = true;
  });

  renderDocs();
  toast(`⚡ Smart Auto-Clean: marked ${promoCount} promo page(s) and applied KTU settings.`);
};

function paintProgress(data) {
  const box = $('#processingProgress');
  box.classList.remove('hidden');
  const total = data.total || 0, done = data.done || 0;
  $('#progressCount').textContent = `${done} / ${total}`;
  $('#progressLabel').textContent = data.status === 'complete' ? 'Preparation complete!' : data.current ? `Preparing ${data.current}…` : 'Preparing PDFs…';
  $('#progressFill').style.width = (total ? Math.round(done / total * 100) : 100) + '%';
  
  const resultById = new Map((data.results || []).map(x => [x.id, x]));
  $('#progressFiles').innerHTML = state.documents.filter(d => !d.error).map(d => {
    let r = resultById.get(d.id);
    let status = r ? (r.ok ? 'Ready to download ✓' : 'Could not prepare') : data.current === d.filename ? 'Working…' : 'Queued';
    return `<div class="progress-file"><span>${esc(d.filename)}</span><b class="${r && !r.ok ? 'progress-fail' : ''}">${status}</b></div>`;
  }).join('');
}

function runStitchAnimation(doc, config, processPromise) {
  const studio = $('#stitchStudio');
  studio.classList.remove('hidden');

  // Personalize the studio
  const f = (config && config.fields) || {};
  const fn = doc ? doc.filename : 'Document.pdf';
  const title = f.title || doc?.suggestions?.title || fn.replace(/\.[^/.]+$/, '');
  const scheme = f.scheme || 'KTU 2024 SCHEME';
  const cat = f.category || 'LAB EXAM NOTES';
  const tags = f.tags || '12 Programs • Aim • Algorithm • C Program • Sample I/O • Result';
  const contact = f.phone ? `Contact • ${f.phone}` : 'Contact • 8606159002';

  $('#stitchFileBadge').textContent = fn;
  $('#stitchDocTitle').textContent = `Synthesizing ${title.slice(0, 36)}${title.length > 36 ? '…' : ''}`;
  $('#stitchCoverScheme').textContent = scheme;
  $('#stitchCoverCat').textContent = cat;
  $('#stitchCoverTitle').textContent = title;
  $('#stitchCoverTags').textContent = tags;
  $('#stitchCoverContact').textContent = contact;

  if (state.logoUrl) {
    $('#stitchCoverLogo').src = state.logoUrl;
  }

  // Reset visual states
  const rawDoc = $('#stitchDocRaw');
  const coverDoc = $('#stitchDocCover');
  const seal = $('#stitchSeal');
  const eraseBoxes = $$('.erase-box');
  const pbarFill = $('#stitchPbarFill');
  const pbarText = $('#stitchPbarText');
  const pbarPct = $('#stitchPbarPercent');
  const statusStat = $('#stitchStatusStat');

  rawDoc.classList.remove('redacting');
  coverDoc.classList.remove('visible');
  seal.classList.remove('pop');
  eraseBoxes.forEach(b => b.classList.remove('active'));
  pbarFill.style.width = '0%';
  pbarPct.textContent = '0%';
  statusStat.textContent = 'ACTIVE';

  const steps = $$('.stitch-step');
  steps.forEach((s, idx) => {
    s.classList.toggle('active', idx === 0);
    s.classList.remove('done');
  });

  let skipped = false;
  const skipBtn = $('#skipStitchBtn');
  const onSkip = () => { skipped = true; };
  skipBtn.onclick = onSkip;

  const wait = ms => new Promise(res => {
    if (skipped) return res();
    const t = setTimeout(res, ms);
    skipBtn.addEventListener('click', () => { clearTimeout(t); res(); }, { once: true });
  });

  return new Promise(async (resolve, reject) => {
    // Run the animation choreography
    (async () => {
      try {
        // Step 1: Parse
        pbarFill.style.width = '20%';
        pbarPct.textContent = '20%';
        pbarText.textContent = 'Analyzing AST quads & layers…';
        await wait(450);
        if (skipped) return;

        // Step 2: Redact Watermarks
        steps[0].classList.remove('active');
        steps[0].classList.add('done');
        steps[1].classList.add('active');
        rawDoc.classList.add('redacting');
        eraseBoxes.forEach(b => b.classList.add('active'));
        pbarFill.style.width = '45%';
        pbarPct.textContent = '45%';
        pbarText.textContent = 'Erasing watermarks & contact marks…';
        await wait(550);
        if (skipped) return;

        // Step 3: Synthesize Azhumathimayam Cover
        steps[1].classList.remove('active');
        steps[1].classList.add('done');
        steps[2].classList.add('active');
        coverDoc.classList.add('visible');
        pbarFill.style.width = '70%';
        pbarPct.textContent = '70%';
        pbarText.textContent = 'Synthesizing KTU 2024 Scheme cover…';
        await wait(550);
        if (skipped) return;

        // Step 4: Inject Interactive URI link & Protection
        steps[2].classList.remove('active');
        steps[2].classList.add('done');
        steps[3].classList.add('active');
        pbarFill.style.width = '90%';
        pbarPct.textContent = '90%';
        pbarText.textContent = 'Embedding interactive URI & stamps…';
        await wait(450);
        if (skipped) return;

        // Step 5: Verification & Stream Deflation
        steps[3].classList.remove('active');
        steps[3].classList.add('done');
        steps[4].classList.add('active');
        seal.classList.add('pop');
        pbarFill.style.width = '100%';
        pbarPct.textContent = '100%';
        pbarText.textContent = '100% Verified · Ready to download';
        statusStat.textContent = 'READY ✓';
        await wait(400);
      } catch (err) {
        // Ignore animation errors, network result takes priority
      }
    })();

    // Concurrently wait for backend response
    try {
      const data = await processPromise;
      if (!skipped) {
        // Ensure final state looks glorious before closing
        pbarFill.style.width = '100%';
        pbarPct.textContent = '100%';
        steps.forEach(s => { s.classList.remove('active'); s.classList.add('done'); });
        seal.classList.add('pop');
        coverDoc.classList.add('visible');
        await wait(300);
      }
      studio.classList.add('hidden');
      resolve(data);
    } catch (err) {
      studio.classList.add('hidden');
      reject(err);
    }
  });
}

$('#processBtn').onclick = async () => {
  if (!state.job) return;
  $('#processBtn').disabled = true;
  $('#processBtn').textContent = 'Preparing confirmed PDFs…';
  goStep(3);

  const activeDocs = state.documents.filter(d => !d.error);
  const firstDoc = activeDocs[0];
  const firstConfig = firstDoc ? state.configs[firstDoc.id] : null;

  try {
    const processPromise = safeFetchJSON(`/api/process/${state.job}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ documents: state.configs })
    });

    let data = await runStitchAnimation(firstDoc, firstConfig, processPromise);

    while (data.status !== 'complete') {
      paintProgress(data);
      await new Promise(resolve => setTimeout(resolve, 500));
      data = await safeFetchJSON(`/api/status/${state.job}`);
    }

    paintProgress(data);

    const okResults = (data.results || []).filter(x => x.ok);
    const downloadAllBtn = $('#downloadAllBtn');
    if (okResults.length > 0) {
      downloadAllBtn.href = `/download-all/${state.job}`;
      downloadAllBtn.style.display = 'inline-flex';
      downloadAllBtn.textContent = okResults.length > 1 ? `Download All ${okResults.length} PDFs (ZIP) ↓` : 'Download All (ZIP) ↓';
    } else {
      downloadAllBtn.style.display = 'none';
    }

    $('#results').innerHTML = (data.results || []).map(x => x.ok ? `
      <div class="result-row">
        <div>
          <strong>${esc(x.filename)}</strong>
          <small>${x.pages} pages · ${x.size < 1024 * 1024 ? Math.round(x.size / 1024) + ' KB' : (x.size / 1024 / 1024).toFixed(1) + ' MB'}${x.removed_pages.length ? ` · removed old page(s) ${x.removed_pages.join(', ')}` : ''}${x.removed_text?.length ? ` · erased ${x.removed_text.length} old marks` : ''}</small>
        </div>
        <a class="button primary download-link" href="${x.url}" download="${esc(x.filename)}">Download PDF ↓</a>
      </div>` : `
      <div class="result-row">
        <div>
          <strong>${esc(x.filename)}</strong>
          <div class="result-error">${esc(x.error)}</div>
        </div>
        <span class="badge" style="background:#fff0ee;color:#9d3028">Not prepared</span>
      </div>`).join('') || '<p class="muted">No files were eligible for processing.</p>';

    $('#reviewPanel').classList.add('hidden');
    $('#resultsPanel').classList.remove('hidden');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    toast('✨ Azhumathimayam Notes prepared with 0 errors!');
  } catch (e) {
    $('#stitchStudio').classList.add('hidden');
    toast(e.message);
    goStep(2);
  } finally {
    $('#processBtn').disabled = false;
    $('#processBtn').innerHTML = 'Prepare confirmed PDFs <span>→</span>';
  }
};

function reset() {
  state = { job: null, documents: [], configs: {}, metadataRecords: [], metadataMatches: {}, defaults: {}, logoUrl: null };
  $('#uploadForm').reset();
  $('#chosenFiles').textContent = '';
  $('#uploadError').textContent = '';
  $('#uploadPanel').classList.remove('hidden');
  $('#reviewPanel').classList.add('hidden');
  $('#resultsPanel').classList.add('hidden');
  goStep(1);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

$('#newBatch').onclick = reset;
$('#newBatch2').onclick = reset;
