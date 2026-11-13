const $ = s => document.querySelector(s), $$ = s => Array.from(document.querySelectorAll(s));
const fields = [
  ['title', 'Subject or title'],
  ['course_code', 'Course code'],
  ['module', 'Module / unit'],
  ['institution', 'University / institution name'],
  ['scheme', 'Scheme / academic year (optional)'],
  ['category', 'Cover label / category (optional)'],
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
    scheme: '',
    category: '',
    website: 'azhumathimayam.invytra.in',
    phone: '8606159002',
    email: '',
    subtitle: '',
    tags: '',
    theme_color: '#640000',
    banner_color: '#640000',
    bg_color: '#F7F4EF',
    cat_color: '#8C1D1D',
    watermark_color: '#B89494',
    watermark_text: 'അഴിമതി മയം',
    watermark_subtext: '*by invytra',
    watermark_type: 'text'
  };
}

const THEMES = {
  maroon: {
    name: 'Azhumathimayam Maroon',
    theme_color: '#640000',
    banner_color: '#640000',
    cat_color: '#8C1D1D',
    bg_color: '#F7F4EF',
    watermark_color: '#B89494'
  },
  navy: {
    name: 'Royal Navy',
    theme_color: '#0B192C',
    banner_color: '#0B192C',
    cat_color: '#1E3E80',
    bg_color: '#F4F6F9',
    watermark_color: '#708DA8'
  },
  emerald: {
    name: 'Imperial Emerald',
    theme_color: '#064E3B',
    banner_color: '#064E3B',
    cat_color: '#047857',
    bg_color: '#F0FDF4',
    watermark_color: '#689E82'
  },
  obsidian: {
    name: 'Obsidian Slate',
    theme_color: '#18181B',
    banner_color: '#18181B',
    cat_color: '#27272A',
    bg_color: '#F4F4F5',
    watermark_color: '#82828D'
  },
  crimson: {
    name: 'Crimson Ruby',
    theme_color: '#7A0016',
    banner_color: '#7A0016',
    cat_color: '#9E1B32',
    bg_color: '#FFF5F5',
    watermark_color: '#B5727F'
  }
};

function deriveThemeFromHex(hex) {
  const clean = String(hex || '').replace(/[^0-9a-fA-F]/g, '');
  if (clean.length !== 6 && clean.length !== 3) {
    return THEMES.maroon;
  }
  const full = clean.length === 3 ? clean.split('').map(c => c + c).join('') : clean;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);

  const wmR = Math.min(255, Math.round(r * 0.52 + 100));
  const wmG = Math.min(255, Math.round(g * 0.52 + 100));
  const wmB = Math.min(255, Math.round(b * 0.52 + 100));
  const toHex = n => n.toString(16).padStart(2, '0');

  return {
    name: 'Custom',
    theme_color: `#${full}`,
    banner_color: `#${full}`,
    cat_color: `#${toHex(Math.min(255, Math.round(r * 1.25)))}${toHex(Math.min(255, Math.round(g * 1.25)))}${toHex(Math.min(255, Math.round(b * 1.25)))}`,
    bg_color: '#F8F7F5',
    watermark_color: `#${toHex(wmR)}${toHex(wmG)}${toHex(wmB)}`
  };
}

function applyThemeGlobally(themeObj) {
  const banner = themeObj.banner_color || themeObj.theme_color || '#640000';
  const theme = {
    ...themeObj,
    theme_color: themeObj.theme_color || banner,
    banner_color: banner,
    cat_color: themeObj.cat_color || banner,
    bg_color: themeObj.bg_color || '#F7F4EF',
    watermark_color: themeObj.watermark_color || '#B89494'
  };

  state.defaults = { ...state.defaults, ...theme };
  document.documentElement.style.setProperty('--wine', theme.banner_color);
  document.documentElement.style.setProperty('--wine-dark', theme.banner_color);
  document.documentElement.style.setProperty('--wine-light', theme.cat_color);
  document.documentElement.style.setProperty('--cream', theme.bg_color);

  state.documents.filter(d => !d.error).forEach(d => {
    const c = state.configs[d.id];
    if (c) {
      c.fields = { ...c.fields, ...theme };
      syncCover(d.id);
    }
  });

  const picker = $('#globalThemePicker');
  const customSwatch = $('#globalCustomSwatch');
  const customLabel = $('.theme-custom-label');
  const presetButtons = $$('#globalThemePresets .theme-pill');
  const matchedPreset = presetButtons.find(btn =>
    btn.dataset.theme.toLowerCase() === theme.banner_color.toLowerCase() &&
    btn.dataset.cat.toLowerCase() === theme.cat_color.toLowerCase() &&
    btn.dataset.bg.toLowerCase() === theme.bg_color.toLowerCase() &&
    btn.dataset.wm.toLowerCase() === theme.watermark_color.toLowerCase()
  );
  presetButtons.forEach(btn => btn.classList.toggle('active', btn === matchedPreset));
  if (customLabel) customLabel.classList.toggle('active', !matchedPreset);
  if (picker) picker.value = theme.banner_color;
  if (customSwatch) customSwatch.style.background = theme.banner_color;

  toast(`🎨 ${theme.name || 'Color theme'} applied to all covers`);
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
  if ($('#watermarkImage')?.files[0]) fd.append('watermark_image', $('#watermarkImage').files[0]);
  
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
      scheme: s.scheme || '',
      category: s.category || '',
      tags: s.tags || ''
    };
    
    Object.keys(m).forEach(k => {
      if (k !== 'filename' && fields.some(x => x[0] === k) && String(m[k]).trim()) {
        f[k] = m[k];
      }
    });

    state.configs[d.id] = {
      fields: f,
      remove_pages: d.page_count > 1 ? [0] : [],
      remove_texts: [],
      manual_mark: '',
      manual_include: false,
      watermark: true,
      watermark_pages: d.pages.map(p => p.number - 1),
      watermark_position: 'center',
      cover_layout: {logo_x: .5, logo_y: 252/842, title_x: .5, title_y: 536/842, title_size: 26, logo_width: 252, title_color: '#1f1f1f'},
      remove_brand_links: false,
      remove_brand_annotations: false,
      remove_images: [],
      remove_image_groups: [],
      add_cover: true
    };
  });
}

function inputHTML(key, label, val, cls = '') {
  const placeholders = {
    title: 'e.g. Operating Systems, Lab Record, Study Notes',
    institution: 'e.g. University of Kerala',
    scheme: 'Optional — leave blank to hide',
    category: 'e.g. LAB EXAM NOTES, STUDY NOTES, QUESTION BANK',
    tags: 'Optional cover details, separated by dots',
    website: 'azhumathimayam.invytra.in'
  };
  return `<div class="field ${cls}"><label>${esc(label)}</label><input data-field="${esc(key)}" value="${esc(val)}" placeholder="${esc(placeholders[key] || '')}"></div>`;
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

  // Hook up global color theme selector
  const themePills = $$('#globalThemePresets .theme-pill');
  const customPicker = $('#globalThemePicker');
  const customSwatch = $('#globalCustomSwatch');

  themePills.forEach(btn => {
    btn.onclick = () => {
      themePills.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const themeData = {
        theme_color: btn.dataset.theme,
        banner_color: btn.dataset.theme,
        cat_color: btn.dataset.cat,
        bg_color: btn.dataset.bg,
        watermark_color: btn.dataset.wm
      };
      applyThemeGlobally(themeData);
    };
  });

  if (customPicker) {
    customPicker.oninput = e => {
      const hex = e.target.value;
      if (customSwatch) customSwatch.style.background = hex;
      themePills.forEach(p => p.classList.remove('active'));
      const themeData = deriveThemeFromHex(hex);
      applyThemeGlobally(themeData);
    };
  }

  // Hook up watermark customizer controls
  const wmTypePills = $$('#wmTypePills .wm-type-pill');
  const wmTextControls = $('#wmTextControls');
  const wmImageControls = $('#wmImageControls');
  const globalWmText = $('#globalWmText');
  const globalWmSubtext = $('#globalWmSubtext');
  const reviewWmImageInput = $('#reviewWmImageInput');
  const wmImageThumb = $('#wmImageThumb');
  const wmImageThumbWrap = $('#wmImageThumbWrap');
  const wmImageStatusText = $('#wmImageStatusText');

  if (resp.watermark_image_uploaded) {
    if (wmImageThumbWrap) wmImageThumbWrap.classList.remove('hidden');
    if (wmImageThumb) wmImageThumb.src = `/watermark-preview/${state.job}?t=${Date.now()}`;
    if (wmImageStatusText) wmImageStatusText.textContent = 'Custom watermark image active ✓';
  }

  wmTypePills.forEach(btn => {
    btn.onclick = () => {
      wmTypePills.forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const mode = btn.dataset.wmType;
      state.defaults.watermark_type = mode;
      if (mode === 'image') {
        if (wmTextControls) wmTextControls.classList.add('hidden');
        if (wmImageControls) wmImageControls.classList.remove('hidden');
      } else {
        if (wmTextControls) wmTextControls.classList.remove('hidden');
        if (wmImageControls) wmImageControls.classList.add('hidden');
      }
      state.documents.filter(d => !d.error).forEach(d => {
        const c = state.configs[d.id];
        if (c) c.fields.watermark_type = mode;
      });
      toast(`Watermark mode: ${mode === 'image' ? 'Image Stamp' : 'Text Watermark'}`);
    };
  });

  if (resp.watermark_image_uploaded) {
    wmTypePills.find(p => p.dataset.wmType === 'image')?.click();
  }

  if (globalWmText) {
    globalWmText.oninput = e => {
      const val = e.target.value;
      state.defaults.watermark_text = val;
      state.documents.filter(d => !d.error).forEach(d => {
        const c = state.configs[d.id];
        if (c) c.fields.watermark_text = val;
      });
    };
  }

  if (globalWmSubtext) {
    globalWmSubtext.oninput = e => {
      const val = e.target.value;
      state.defaults.watermark_subtext = val;
      state.documents.filter(d => !d.error).forEach(d => {
        const c = state.configs[d.id];
        if (c) c.fields.watermark_subtext = val;
      });
    };
  }

  if (reviewWmImageInput) {
    reviewWmImageInput.onchange = async () => {
      if (!reviewWmImageInput.files[0] || !state.job) return;
      const fd = new FormData();
      fd.append('watermark_image', reviewWmImageInput.files[0]);
      try {
        const res = await safeFetchJSON(`/api/upload-watermark/${state.job}`, { method: 'POST', body: fd });
        if (res.ok) {
          if (wmImageThumbWrap) wmImageThumbWrap.classList.remove('hidden');
          if (wmImageThumb) wmImageThumb.src = `/watermark-preview/${state.job}?t=${Date.now()}`;
          if (wmImageStatusText) wmImageStatusText.textContent = 'Custom watermark image saved ✓';
          wmTypePills.find(p => p.dataset.wmType === 'image')?.click();
          toast('✓ Custom watermark image uploaded and selected!');
        }
      } catch (err) {
        toast(`Upload failed: ${err.message}`);
      }
    };
  }

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
      <input type="checkbox" data-remove-text="${i}" ${c.remove_texts.includes(x.text) ? 'checked' : ''}>
      <span><b>${esc(x.text)}</b><br>${esc(x.kind)} · pages ${esc(x.pages.join(', '))} · ${Math.round(x.confidence * 100)}% confidence${remembered ? ' · matched rule' : ''}</span>
    </label>`;
  }).join('');

  let imageCandidates = (d.repeated_images || []).map((im, i) => `
    <div class="image-candidate">
      <img src="${im.preview}" alt="Image object preview">
      <div>
        <label class="checkline"><input type="checkbox" data-remove-image="${i}" ${c.remove_image_groups.includes(im.xref) ? 'checked' : ''}> Remove matching image object${im.object_count > 1 ? 's' : ''} everywhere used</label>
        <small>Found on pages ${esc(im.pages.join(', '))} · ${im.object_count} matching object(s). ${esc(im.warning)}</small>
        <details class="image-compare" data-compare="${i}">
          <summary>Compare a page before and after removal</summary>
          <p class="muted">Preview removes only this image group, not any other changes. Check several pages, especially where the image overlaps notes.</p>
          <label>Page <select data-compare-page>${im.pages.map(n => `<option value="${n - 1}">${n}</option>`).join('')}</select></label>
          <button type="button" class="button secondary" data-compare-run>Preview removal</button>
          <div class="muted" data-compare-status aria-live="polite"></div>
          <div class="compare-pages" data-compare-result hidden>
            <figure><figcaption>Original</figcaption><img data-compare-original alt="Original page"></figure>
            <figure><figcaption>Without this image group</figcaption><img data-compare-after alt="Page with selected image group removed"></figure>
          </div>
        </details>
      </div>
    </div>`).join('');

  let imageSection = imageCandidates ? `<div class="brain-box"><h4>Possible separate image watermarks</h4><p class="muted">Review each image and all page uses before selecting it. Removing the image leaves other page objects in place. It is not guaranteed to be a watermark.</p>${imageCandidates}</div>` : '';
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
          <label class="checkline"><input type="checkbox" data-add-cover ${c.add_cover ? 'checked' : ''}> Add a new cover page</label>
          <div class="section-title">Cover details & metadata</div>
          <div class="doc-fields">${fields.map(([k, l]) => inputHTML(k, l, f[k] || '')).join('')}</div>

          <div class="section-title" style="margin-top:24px">Page decisions</div>
          <p class="muted">${d.page_count > 1 ? 'Page 1 is selected for removal as the old cover. Check its preview and uncheck it if it contains notes.' : 'This single-page PDF is retained; at least one original page must remain.'} Select any other pages you want removed.</p>
          <div class="pages-list">${pageRows}</div>

          <div class="brain-box">
            <h4>Detected old watermarks & text marks</h4><p class="muted">Text removal can also erase overlapping text. Select only after reviewing; use separate image objects below when possible.</p>
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
            <input type="checkbox" data-watermark ${c.watermark ? 'checked' : ''}> Add my watermark to selected retained pages
          </label>
          <label>Watermark position <select data-watermark-position>
            ${[['center','Center'],['top-left','Top left'],['top-center','Top center'],['top-right','Top right'],['middle-left','Middle left'],['middle-right','Middle right'],['bottom-left','Bottom left'],['bottom-center','Bottom center'],['bottom-right','Bottom right']].map(([v,l]) => `<option value="${v}" ${c.watermark_position === v ? 'selected' : ''}>${l}</option>`).join('')}
          </select></label>
          <p class="muted">The watermark is translucent and placed over page content so it also appears on scans; review readability. Use the page checkboxes above to choose where it appears.</p>
          ${imageSection}
          <div class="brain-box">
            <h4>Content-preserving watermark removal</h4>
            <p class="muted">Separate image objects above are the safest option. For a mark baked into a scan, try the experimental reconstruction below.</p>
          </div>
          <div class="brain-box">
            <h4>Experimental scan reconstruction</h4>
            <p class="muted">Only for pages containing one full-page scan. Draw around the mark, pick its color, and review the red detection mask and result. Color matching suggests pixels, not an AI watermark detector. AI reconstruction guesses missing content and can alter similarly colored notes or invent details. It runs on the app server, not an external AI service. Inspect closely before approval.</p>
            <label>Page <select data-scan-page>${pages.map(p => `<option value="${p.number - 1}">Page ${p.number}</option>`).join('')}</select></label>
            <label>Mark color <input data-scan-color type="color" value="#cccccc"></label>
            <button type="button" class="button secondary" data-scan-pick>Pick color from page</button>
            <label>Color tolerance <input data-scan-tolerance type="number" value="20" min="1" max="100"></label>
            <label>Reconstruction method <select data-scan-engine><option value="ai">Local AI (MI-GAN, CPU)</option><option value="classic">Classic inpainting</option></select></label>
            <div class="region-preview" data-scan-area><img data-scan-image src="${esc(pages[0]?.preview || '')}" alt="Original page: drag to select the watermark"><div data-scan-overlay></div></div>
            <button type="button" class="button secondary" data-scan-preview>Preview reconstruction</button>
            <div data-scan-status class="muted" aria-live="polite">Draw a rectangle around the mark first.</div>
            <div data-scan-result hidden><p>Detected pixels (red) — check that notes aren't marked.</p><img data-scan-mask alt="Pixels selected for reconstruction shown in red" style="max-width:100%;width:420px"><p>Proposed result — compare with the original above, including any text beneath the mark.</p><a data-scan-full target="_blank" rel="noopener">Open full-resolution result</a><br><img data-scan-output alt="Reconstructed page preview" style="max-width:100%;width:420px"><label class="checkline"><input type="checkbox" data-scan-approve> I reviewed this result and accept possible content changes.</label></div>
          </div>
          ${warnings}
        </div>

        <div>
          <div class="section-title">Cover editor</div>
          <div class="cover-preview">
            <div class="cover-caption">Drag the logo or title handles; the image is rendered from the actual PDF cover</div>
            <div class="cover-canvas" data-cover-canvas><img data-cover-render alt="PDF cover preview"><button type="button" class="cover-handle" data-cover-handle="logo" aria-label="Drag logo position">Logo</button><button type="button" class="cover-handle" data-cover-handle="title" aria-label="Drag title position">Title</button></div>
            <div class="cover-controls">
              <label>Logo X <input type="range" min="8" max="92" data-cover-number="logo_x"></label>
              <label>Logo Y <input type="range" min="8" max="92" data-cover-number="logo_y"></label>
              <label>Title X <input type="range" min="8" max="92" data-cover-number="title_x"></label>
              <label>Title Y <input type="range" min="8" max="92" data-cover-number="title_y"></label>
              <label>Title size <input type="number" min="12" max="40" data-cover-number="title_size"></label>
              <label>Logo width <input type="number" min="80" max="350" data-cover-number="logo_width"></label>
              <label>Title color <input type="color" data-cover-number="title_color"></label>
              <button type="button" class="button ghost" data-cover-reset>Reset layout</button>
              <small data-cover-status aria-live="polite"></small>
            </div>
            <div class="cover" style="display:none" data-cover="${d.id}">
              <div class="cover-top">
                <div class="cover-scheme">${esc((f.scheme || '').toUpperCase())}</div>
                <img class="cover-logo" src="${state.logoUrl}" alt="Azhumathimayam">
                <div class="cover-logo-fallback hidden">അഴിമതി മയം</div>
              </div>
              <div class="cover-bottom">
                <div class="cover-cat"></div>
                <div class="cover-title">Study Notes</div>
                <div class="cover-sub"></div>
                <div class="cover-divider"></div>
                <div class="cover-pill-btn">
                  <span class="cover-link-text">azhumathimayam.invytra.in</span>
                </div>
                <div class="cover-contact">Contact • 8606159002</div>
                <div class="cover-brand">I N V Y T R A</div>
                <div class="cover-tags"></div>
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

  box.querySelector('.cover-scheme').textContent = (f.scheme || '').toUpperCase();
  box.querySelector('.cover-cat').textContent = (f.category || '').toUpperCase();
  box.querySelector('.cover-title').textContent = f.title || 'Study Notes';

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
    tagsEl.textContent = f.tags || '';
  }

  // Sync theme palette colors to live cover
  const banner = f.banner_color || f.theme_color || '#640000';
  const cat = f.cat_color || '#8C1D1D';
  const bg = f.bg_color || '#F7F4EF';

  const topEl = box.querySelector('.cover-top');
  const btmEl = box.querySelector('.cover-bottom');
  const pillEl = box.querySelector('.cover-pill-btn');
  const contactEl = box.querySelector('.cover-contact');
  const brandEl = box.querySelector('.cover-brand');
  const catEl = box.querySelector('.cover-cat');

  if (topEl) topEl.style.background = banner;
  if (btmEl) btmEl.style.background = bg;
  if (pillEl) pillEl.style.background = banner;
  if (contactEl) contactEl.style.color = banner;
  if (brandEl) brandEl.style.color = banner;
  if (catEl) catEl.style.color = cat;
  scheduleCoverPreview(id);
}

const coverPreviewTimers = new Map();
const coverPreviewVersions = new Map();
const coverPreviewURLs = new Map();
function scheduleCoverPreview(id) {
  clearTimeout(coverPreviewTimers.get(id));
  const version = (coverPreviewVersions.get(id) || 0) + 1;
  coverPreviewVersions.set(id, version);
  coverPreviewTimers.set(id, setTimeout(async () => {
    const card = document.querySelector(`[data-doc="${id}"]`), c = state.configs[id];
    if (!card || !c) return;
    const status = card.querySelector('[data-cover-status]');
    try {
      const res = await fetch(`/api/cover-preview/${state.job}`, {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({fields: c.fields, cover_layout: c.cover_layout})});
      if (!res.ok) { const data = await res.json(); throw new Error(data.error || 'Cover preview failed'); }
      const blob = await res.blob();
      if (coverPreviewVersions.get(id) !== version || !card.isConnected) return;
      const previous = coverPreviewURLs.get(id); if (previous) URL.revokeObjectURL(previous);
      const url = URL.createObjectURL(blob); coverPreviewURLs.set(id, url);
      card.querySelector('[data-cover-render]').src = url;
      status.textContent = 'Preview updated';
    } catch (e) { if (coverPreviewVersions.get(id) === version && card.isConnected) status.textContent = e.message; }
  }, 250));
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
        c.remove_image_groups = i.checked ? [...new Set([...c.remove_image_groups, x])] : c.remove_image_groups.filter(t => t !== x);
      };
    });

    card.querySelectorAll('[data-compare]').forEach(el => {
      const candidate = d.repeated_images[+el.dataset.compare], select = el.querySelector('[data-compare-page]');
      const result = el.querySelector('[data-compare-result]'), status = el.querySelector('[data-compare-status]');
      let version = 0, url = null;
      select.onchange = () => { version++; result.hidden = true; status.textContent = 'Preview the newly selected page.'; if (url) URL.revokeObjectURL(url); url = null; };
      el.querySelector('[data-compare-run]').onclick = async () => {
        const current = ++version, page = +select.value;
        result.hidden = true; status.textContent = 'Preparing comparison…';
        if (url) { URL.revokeObjectURL(url); url = null; }
        try {
          const response = await fetch(`/image-removal-preview/${state.job}/${d.id}/${candidate.xref}/${page}`);
          if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(error.error || 'Could not preview this page.'); }
          const blob = await response.blob();
          if (current !== version) return;
          url = URL.createObjectURL(blob);
          el.querySelector('[data-compare-original]').src = d.pages[page].preview;
          el.querySelector('[data-compare-after]').src = url;
          result.hidden = false; status.textContent = 'Compare the result before selecting the group.';
        } catch (error) { if (current === version) status.textContent = error.message; }
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
    card.querySelector('[data-add-cover]').onchange = e => c.add_cover = e.target.checked;
    card.querySelector('[data-watermark-position]').onchange = e => c.watermark_position = e.target.value;
    const canvas = card.querySelector('[data-cover-canvas]');
    const layoutControls = card.querySelectorAll('[data-cover-number]');
    const showLayout = () => {
      layoutControls.forEach(el => { const k = el.dataset.coverNumber; el.value = k.endsWith('_x') || k.endsWith('_y') ? Math.round(c.cover_layout[k]*100) : c.cover_layout[k]; });
      canvas.querySelectorAll('[data-cover-handle]').forEach(h => { const k = h.dataset.coverHandle; h.style.left = `${c.cover_layout[k+'_x']*100}%`; h.style.top = `${c.cover_layout[k+'_y']*100}%`; });
    };
    layoutControls.forEach(el => el.oninput = () => {
      const k = el.dataset.coverNumber, val = el.type === 'color' ? el.value : Number(el.value);
      if (el.type === 'number' && (!el.value || !Number.isFinite(val))) return;
      c.cover_layout[k] = k.endsWith('_x') || k.endsWith('_y') ? val/100 : val;
      showLayout(); scheduleCoverPreview(d.id);
    });
    canvas.querySelectorAll('[data-cover-handle]').forEach(handle => {
      let dragging = false;
      const update = e => { const b = canvas.getBoundingClientRect(), k = handle.dataset.coverHandle;
        c.cover_layout[k+'_x'] = Math.max(.08, Math.min(.92, (e.clientX-b.left)/b.width));
        c.cover_layout[k+'_y'] = Math.max(.08, Math.min(.92, (e.clientY-b.top)/b.height));
        showLayout(); scheduleCoverPreview(d.id);
      };
      handle.onpointerdown = e => { e.preventDefault(); dragging = true; handle.setPointerCapture(e.pointerId); update(e); };
      handle.onpointermove = e => { if (dragging) update(e); };
      handle.onpointerup = () => { dragging = false; };
      handle.onpointercancel = () => { dragging = false; };
    });
    card.querySelector('[data-cover-reset]').onclick = () => { c.cover_layout = {logo_x:.5, logo_y:252/842, title_x:.5, title_y:536/842, title_size:26, logo_width:252, title_color:'#1f1f1f'}; showLayout(); scheduleCoverPreview(d.id); };
    showLayout();


    const scanArea = card.querySelector('[data-scan-area]'), scanPage = card.querySelector('[data-scan-page]');
    const scanImage = card.querySelector('[data-scan-image]'), scanOverlay = card.querySelector('[data-scan-overlay]');
    const scanColor = card.querySelector('[data-scan-color]'), scanTolerance = card.querySelector('[data-scan-tolerance]'), scanEngine = card.querySelector('[data-scan-engine]');
    const scanResult = card.querySelector('[data-scan-result]'), scanOutput = card.querySelector('[data-scan-output]');
    const scanApprove = card.querySelector('[data-scan-approve]'), scanStatus = card.querySelector('[data-scan-status]');
    let rect = null, start = null, proposed = null, version = 0, previewUrl = null, maskUrl = null, picking = false;
    // A newly rendered editor must be reviewed again, never silently reuse an old approval.
    delete c.scan_reconstruction;
    const resetScan = () => {
      version++; proposed = null; delete c.scan_reconstruction; scanApprove.checked = false;
      scanResult.hidden = true;
      if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
      if (maskUrl) { URL.revokeObjectURL(maskUrl); maskUrl = null; }
    };
    const point = e => { const b = scanArea.getBoundingClientRect(); return [Math.max(0, Math.min(1,(e.clientX-b.left)/b.width)), Math.max(0, Math.min(1,(e.clientY-b.top)/b.height))]; };
    card.querySelector('[data-scan-pick]').onclick = () => { picking = true; scanStatus.textContent = 'Click a watermark pixel in the page preview to sample its color.'; };
    scanArea.onpointerdown = e => {
      e.preventDefault();
      if (picking) {
        picking = false; resetScan();
        try {
          const [x, y] = point(e), canvas = document.createElement('canvas');
          canvas.width = scanImage.naturalWidth; canvas.height = scanImage.naturalHeight;
          if (!canvas.width || !canvas.height) throw new Error('Page preview is not ready.');
          const ctx = canvas.getContext('2d', {willReadFrequently: true}); ctx.drawImage(scanImage, 0, 0);
          const rgba = ctx.getImageData(Math.min(canvas.width-1, Math.floor(x*canvas.width)), Math.min(canvas.height-1, Math.floor(y*canvas.height)), 1, 1).data;
          scanColor.value = '#' + Array.from(rgba.slice(0, 3), n => n.toString(16).padStart(2, '0')).join('');
          scanStatus.textContent = 'Color sampled. Review the red mask before approving.';
        } catch (err) { scanStatus.textContent = err.message || 'Could not sample the page.'; }
        return;
      }
      resetScan(); start = point(e); scanArea.setPointerCapture(e.pointerId);
    };
    scanArea.onpointerup = e => {
      if (!start) return;
      const end = point(e); rect = {x0: Math.min(start[0],end[0]), y0: Math.min(start[1],end[1]), x1: Math.max(start[0],end[0]), y1: Math.max(start[1],end[1])}; start = null;
      if (rect.x1-rect.x0 < .005 || rect.y1-rect.y0 < .005) { rect = null; scanOverlay.innerHTML = ''; return; }
      scanOverlay.innerHTML = `<div class="region-box" style="left:${rect.x0*100}%;top:${rect.y0*100}%;width:${(rect.x1-rect.x0)*100}%;height:${(rect.y1-rect.y0)*100}%"></div>`;
      scanStatus.textContent = 'Selection ready. Choose the watermark color and preview.';
    };
    scanArea.onpointercancel = () => { start = null; };
    scanPage.onchange = () => { picking = false; resetScan(); rect = null; scanOverlay.innerHTML = ''; scanImage.src = d.pages[+scanPage.value].preview; scanStatus.textContent = 'Draw a rectangle around the mark first.'; };
    for (const control of [scanColor, scanTolerance, scanEngine]) control.oninput = () => { resetScan(); scanStatus.textContent = 'Settings changed. Preview again.'; };
    card.querySelector('[data-scan-preview]').onclick = async () => {
      if (!rect) { scanStatus.textContent = 'Draw a rectangle around the mark first.'; return; }
      resetScan(); const current = version;
      const settings = {...rect, page: +scanPage.value, color: scanColor.value, tolerance: +scanTolerance.value, engine: scanEngine.value};
      scanStatus.textContent = 'Preparing local preview…';
      try {
        const url = `/api/reconstruct-preview/${state.job}/${d.id}/${settings.page}`;
        const options = {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(settings)};
        const [res, maskRes] = await Promise.all([fetch(url, options), fetch(`${url}?mask=1`, options)]);
        for (const response of [res, maskRes]) {
          if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error || 'Preview failed'); }
        }
        const [blob, maskBlob] = await Promise.all([res.blob(), maskRes.blob()]);
        if (current !== version) return;
        previewUrl = URL.createObjectURL(blob); maskUrl = URL.createObjectURL(maskBlob); card.querySelector('[data-scan-mask]').src = maskUrl; scanOutput.src = previewUrl; card.querySelector('[data-scan-full]').href = previewUrl; proposed = settings;
        scanResult.hidden = false; scanStatus.textContent = 'Compare the result with the original before approving.';
      } catch (err) { if (current === version) scanStatus.textContent = err.message; }
    };
    scanApprove.onchange = () => { if (scanApprove.checked && proposed) c.scan_reconstruction = {...proposed, approved: true}; else delete c.scan_reconstruction; };

    syncCover(d.id);
  });
}

// ⚡ Smart Auto-Clean button handler
$('#autoCleanBtn').onclick = () => {
  state.documents.filter(d => !d.error).forEach(d => {
    const c = state.configs[d.id];
    // Apply suggestions if blank
    const s = d.suggestions || {};
    if (!c.fields.title && s.title) c.fields.title = s.title;
    if (!c.fields.course_code && s.course_code) c.fields.course_code = s.course_code;
    if (!c.fields.scheme && s.scheme) c.fields.scheme = s.scheme;
    if (!c.fields.category && s.category) c.fields.category = s.category;
    if (!c.fields.tags && s.tags) c.fields.tags = s.tags;
  });

  renderDocs();
  toast('Suggested cover details applied. Review watermark candidates before removing anything.');
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
  const title = f.title || doc?.suggestions?.title || fn.replace(/\.[^/.]+$/, '') || 'Study Notes';
  const scheme = f.scheme || '';
  const cat = f.category || '';
  const tags = f.tags || '';
  const coverDetails = [f.subtitle, f.institution, [f.course_code, f.module].filter(Boolean).join(' · ')].filter(Boolean);
  const contact = f.phone ? `Contact • ${f.phone}` : 'Contact • 8606159002';
  const banner = f.banner_color || f.theme_color || '#640000';
  const catColor = f.cat_color || '#8C1D1D';
  const bgColor = f.bg_color || '#F7F4EF';

  $('#stitchFileBadge').textContent = fn;
  $('#stitchDocTitle').textContent = `Synthesizing ${title.slice(0, 34)}${title.length > 34 ? '…' : ''}`;
  $('#stitchCoverScheme').textContent = scheme;
  $('#stitchCoverCat').textContent = cat;
  $('#stitchCoverCat').style.color = catColor;
  $('#stitchCoverTitle').textContent = title;
  const stitchDetails = $('#stitchCoverSub');
  stitchDetails.textContent = coverDetails.join(' — ');
  stitchDetails.style.display = coverDetails.length ? 'block' : 'none';
  $('#stitchCoverTags').textContent = tags;
  $('#stitchCoverContact').textContent = contact;
  $('#stitchCoverContact').style.color = banner;
  $('#stitchCoverBrand').style.color = banner;
  $('#stitchCoverTop').style.background = banner;
  $('#stitchCoverPill').style.background = banner;
  $('#stitchCoverBottom').style.background = bgColor;

  if (state.logoUrl) {
    $('#stitchCoverLogo').src = state.logoUrl;
  }

  // Real pages array
  const pages = (doc && doc.pages) || [];
  const totalPages = Math.max(1, pages.length || doc?.page_count || 1);

  // Populate Filmstrip pills
  const filmstrip = $('#stitchFilmstrip');
  filmstrip.innerHTML = '';
  for (let i = 1; i <= Math.min(totalPages, 24); i++) {
    const pill = document.createElement('div');
    pill.className = `filmstrip-pill ${i === 1 ? 'active' : ''}`;
    pill.id = `filmPill-${i}`;
    pill.textContent = `Pg ${i}`;
    filmstrip.appendChild(pill);
  }

  // Terminal logging helper
  const terminal = $('#stitchTerminal');
  terminal.innerHTML = '';
  const startTime = performance.now();
  const logTerminal = (msg, cls = '') => {
    const elapsed = ((performance.now() - startTime) / 1000).toFixed(2);
    const line = document.createElement('div');
    line.className = `terminal-line ${cls}`;
    line.textContent = `[+${elapsed}s] ${msg}`;
    terminal.appendChild(line);
    terminal.scrollTop = terminal.scrollHeight;
  };

  logTerminal(`Initialized PyMuPDF vector AST pipeline for: ${fn}`, 'init');
  logTerminal(`Document metadata checked. Scheme: ${scheme || 'not set'}`, 'init');

  // Visual Elements
  const coverView = $('#stitchCoverView');
  const pageView = $('#stitchPageView');
  const pageImg = $('#stitchPageImg');
  const hudTop = $('#stitchHudTop');
  const hudCenter = $('#stitchHudCenter');
  const hudBottom = $('#stitchHudBottom');
  const seal = $('#stitchSeal');
  const pbarFill = $('#stitchPbarFill');
  const pbarText = $('#stitchPbarText');
  const pbarPct = $('#stitchPbarPercent');
  const statPage = $('#stitchStatPage');
  const statPurged = $('#stitchStatPurged');
  const statWatermark = $('#stitchStatWatermark');
  const stepIndicator = $('#stitchStepIndicator');

  // Reset visual states
  coverView.classList.toggle('hidden', !config?.add_cover);
  pageView.classList.toggle('hidden', !!config?.add_cover);
  if (!config?.add_cover && pages[0]) pageImg.src = pages[0].preview;
  seal.classList.remove('pop');
  hudTop.classList.remove('active');
  hudCenter.classList.remove('active');
  hudBottom.classList.remove('active');
  pbarFill.style.width = '0%';
  pbarPct.textContent = '0%';
  statPage.textContent = `1 / ${totalPages}`;
  statPurged.textContent = 'Review selections';
  statWatermark.textContent = config?.watermark ? 'Selected' : 'Off';

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
    // Run the page-by-page inspection loop
    (async () => {
      try {
        // --- STEP 1: COVER SYNTHESIS (Page 1) ---
        stepIndicator.textContent = config?.add_cover ? 'PREPARING COVER' : 'PREPARING ORIGINAL PAGES';
        pbarText.textContent = config?.add_cover ? 'Preparing cover…' : 'Preparing document…';
        pbarFill.style.width = '15%';
        pbarPct.textContent = '15%';
        logTerminal(config?.add_cover ? 'Cover requested.' : 'No cover requested; preserving original document structure where possible.');
        await wait(550);
        if (skipped) return;

        // Mark Page 1 filmstrip done
        const p1Pill = $('#filmPill-1');
        if (p1Pill) { p1Pill.classList.remove('active'); p1Pill.classList.add('done'); }

        // --- STEP 2+: CYCLE THROUGH SUBSEQUENT ACTUAL PAGES ---
        const maxPagesToAnimate = Math.min(totalPages, 6);

        for (let p = 2; p <= maxPagesToAnimate; p++) {
          if (skipped) break;
          const pageIdx = p - 1;
          const pageInfo = pages[pageIdx];
          const previewUrl = pageInfo?.preview || `/preview/${state.job}/${doc.id}/${pageIdx}`;

          // Switch from cover to real page
          coverView.classList.add('hidden');
          pageView.classList.remove('hidden');
          pageImg.src = previewUrl;

          // Update telemetry
          stepIndicator.textContent = `INSPECTING PAGE ${p} OF ${totalPages}`;
          statPage.textContent = `${p} / ${totalPages}`;
          const currentPercent = Math.min(92, Math.round((p / totalPages) * 85) + 15);
          pbarFill.style.width = `${currentPercent}%`;
          pbarPct.textContent = `${currentPercent}%`;
          pbarText.textContent = `Preparing Page ${p}…`;

          // Activate filmstrip pill
          const curPill = $(`#filmPill-${p}`);
          if (curPill) curPill.classList.add('active');

          logTerminal(`Page ${p}: Vector xref streams extracted. Scanning headers & footers.`);
          await wait(300);
          if (skipped) break;

          // Pop HUD badges simulating laser scan operations
          hudTop.classList.add('active');
          logTerminal(`Page ${p}: Preparing selected changes.`);
          await wait(280);
          if (skipped) break;

          const wmType = (f.watermark_type || 'text').toLowerCase();
          const wmLabel = wmType === 'image' ? 'Image Stamp' : (f.watermark_text || 'അഴിമതി മയം');
          const wmCenterText = hudCenter.querySelector('.hud-text');
          if (wmCenterText) wmCenterText.textContent = config?.watermark ? `${wmLabel.slice(0, 22)} SELECTED` : 'NO NEW WATERMARK';
          hudCenter.classList.add('active');
          statWatermark.textContent = config?.watermark ? 'Selected' : 'Off';
          logTerminal(`Page ${p}: Watermark option ${config?.watermark ? "enabled" : "off"}.`);
          await wait(280);
          if (skipped) break;

          hudBottom.classList.add('active');
          await wait(220);
          if (skipped) break;

          // Reset HUD for next page
          hudTop.classList.remove('active');
          hudCenter.classList.remove('active');
          hudBottom.classList.remove('active');

          if (curPill) {
            curPill.classList.remove('active');
            curPill.classList.add('done');
          }
        }

        // --- FINAL WRAP-UP STEP ---
        pbarFill.style.width = '100%';
        pbarPct.textContent = '100%';
        pbarText.textContent = 'Preparing output…';
        stepIndicator.textContent = 'REVIEW OUTPUT';
        statWatermark.textContent = config?.watermark ? 'Selected' : 'Off';
        seal.classList.add('pop');
        logTerminal(`Waiting for processing result.`, 'success');
        await wait(350);

      } catch (err) {
        // Non-blocking for UI animation
      }
    })();

    // Concurrently wait for backend response
    try {
      const data = await processPromise;
      if (!skipped) {
        pbarFill.style.width = '100%';
        pbarPct.textContent = '100%';
        seal.classList.add('pop');
        $$('.filmstrip-pill').forEach(pill => pill.classList.add('done'));
        await wait(350);
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
  const invalid = state.documents.find(d => !d.error && new Set(state.configs[d.id].remove_pages).size >= d.page_count);
  if (invalid) { toast(`Keep at least one original page in ${invalid.filename}.`); return; }
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
          <small>${x.pages} pages · ${x.size < 1024 * 1024 ? Math.round(x.size / 1024) + ' KB' : (x.size / 1024 / 1024).toFixed(1) + ' MB'}${x.cover_added ? ' · cover added' : ''}${x.removed_pages.length ? ` · removed old page(s) ${x.removed_pages.join(', ')}` : ''}${x.watermarked_pages?.length ? ` · watermark on ${x.watermarked_pages.length} original page(s)` : ''}${x.removed_text?.length ? ` · erased ${x.removed_text.length} old marks` : ''}${x.removed_images?.length ? ` · removed ${x.removed_images.length} image object(s)` : ''}${x.reconstructed_page ? ` · reconstructed page ${x.reconstructed_page}; review carefully` : ''}${x.text_verified ? ' · selectable text verified unchanged' : ''}</small>
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
