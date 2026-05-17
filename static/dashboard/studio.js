/*
 * Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>
 *
 * AISBF - AI Service Broker Framework || AI Should Be Free
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

// ─────────────────────────────────────────────────────────────────
//  State
// ─────────────────────────────────────────────────────────────────
let models = [], activeModel = null, chatHistory = [], chatBusy = false, attachedImage = null;
let _localCapSet = new Set();  // capabilities available from locally downloaded (not necessarily configured) models
let _imgPollTimer = null;
let _vidPollTimer = null;
let _audPollTimer = null;
let functionBindingDefs = [];
let functionBindings = {};
let bindingSearchState = {};
let selectedBindingId = 'chat';
let _pendingBindingFocusKey = null;

function _startVidPoll(prefix) {
  if (_vidPollTimer) { clearInterval(_vidPollTimer); _vidPollTimer = null; }
  const wrap = $(prefix+'-pbar-wrap'), fill = $(prefix+'-pbar-fill'), lbl = $(prefix+'-pbar-label');
  if (!wrap) return;
  wrap.classList.add('active'); fill.style.width='0%'; lbl.textContent='';
  _vidPollTimer = setInterval(async () => {
    try {
      const p = await (await dashboardFetch(buildStudioUrl('/video/progress'))).json();
      if (p.total > 0) {
        fill.style.width = p.pct + '%';
        const spd = p.it_per_s > 0 ? ` · ${p.it_per_s} it/s` : (p.elapsed > 0 ? ` · ${p.elapsed}s` : '');
        lbl.textContent = `${p.current} / ${p.total} steps${spd}`;
      } else if (p.elapsed > 0) {
        lbl.textContent = `${p.elapsed}s`;
      }
      if (!p.active) { clearInterval(_vidPollTimer); _vidPollTimer = null; }
    } catch(_) {}
  }, 500);
}

function _stopVidPoll(prefix, done) {
  if (_vidPollTimer) { clearInterval(_vidPollTimer); _vidPollTimer = null; }
  const wrap = $(prefix+'-pbar-wrap'), fill = $(prefix+'-pbar-fill'), lbl = $(prefix+'-pbar-label');
  if (!wrap) return;
  if (done) { fill.style.width='100%'; lbl.textContent='Done'; setTimeout(() => wrap.classList.remove('active'), 2000); }
  else { wrap.classList.remove('active'); }
}

function _startAudPoll(prefix) {
  if (_audPollTimer) { clearInterval(_audPollTimer); _audPollTimer = null; }
  const wrap = $(prefix+'-pbar-wrap'), fill = $(prefix+'-pbar-fill'), lbl = $(prefix+'-pbar-label');
  if (!wrap) return;
  wrap.classList.add('active'); fill.style.width='0%'; lbl.textContent='';
  _audPollTimer = setInterval(async () => {
    try {
      const p = await (await dashboardFetch(buildStudioUrl('/audio/progress'))).json();
      if (p.total > 0) {
        fill.style.width = p.pct + '%';
        const unit = p.unit || 'it';
        const spd = p.it_per_s > 0 ? ` · ${p.it_per_s} ${unit}/s` : (p.elapsed > 0 ? ` · ${p.elapsed}s` : '');
        lbl.textContent = `${p.current} / ${p.total} steps${spd}`;
      } else if (p.elapsed > 0) {
        lbl.textContent = `Elapsed: ${p.elapsed}s`;
      }
      if (!p.active) { clearInterval(_audPollTimer); _audPollTimer = null; }
    } catch(_) {}
  }, 500);
}

function _stopAudPoll(prefix, done) {
  if (_audPollTimer) { clearInterval(_audPollTimer); _audPollTimer = null; }
  const wrap = $(prefix+'-pbar-wrap'), fill = $(prefix+'-pbar-fill'), lbl = $(prefix+'-pbar-label');
  if (!wrap) return;
  if (done) { fill.style.width='100%'; lbl.textContent='Done'; setTimeout(() => wrap.classList.remove('active'), 2000); }
  else { wrap.classList.remove('active'); }
}
let apiToken = null;
let charSlots = {};        // prefix → [{name:'', images:[b64...]}]
let _charProfiles = [];    // cached list from /v1/characters
let artifactHistory = [];
const ARTIFACT_HISTORY_LIMIT = 12;

const $ = id => document.getElementById(id);
const studioBootstrapEl = $('studio-bootstrap');
let studioBootstrap = {};
try { studioBootstrap = studioBootstrapEl ? JSON.parse(studioBootstrapEl.textContent || '{}') : {}; } catch (_) { studioBootstrap = {}; }
const studioScope = studioBootstrap.scope || 'admin';
const studioOwnerId = studioBootstrap.owner_id || null;
const studioEntries = Array.isArray(studioBootstrap.entries) ? studioBootstrap.entries : [];
const STUDIO_API_BASE = window.__studioApiBase || '/dashboard/api/studio';
const STUDIO_USERNAME = window.__studioUsername || '';
const STUDIO_IS_GLOBAL_ADMIN = !!window.__studioIsGlobalAdmin;
const STUDIO_SYSTEM_PROMPT = typeof window.__studioSystemPrompt === 'string' ? window.__studioSystemPrompt : '';
const STUDIO_UNSUPPORTED_ENDPOINTS = new Set([
  '/v1/characters',
  '/v1/pipelines/audio-dub',
  '/v1/pipelines/audio-understand',
  '/v1/pipelines/audio-music-dub',
  '/v1/pipelines/image-to-video',
  '/v1/pipelines/video-dub',
  '/v1/pipelines/story'
]);

function buildStudioUrl(path) {
  return `${STUDIO_API_BASE}${path}`;
}

function buildBindingApiUrl(bindingId) {
  return buildStudioUrl(`/function-bindings/${encodeURIComponent(bindingId)}`);
}

function scopeApiPath(path) {
  if (!path) return path;
  if (path.startsWith('/api/v1/')) return buildStudioUrl(path.slice('/api/v1'.length));
  if (path.startsWith('/v1/')) return buildStudioUrl(path.slice('/v1'.length));
  return buildStudioUrl(path);
}

function buildAdminApiUrl(path) {
  return `${STUDIO_API_BASE}${path}`;
}

function buildCharacterAdminUrl(name) {
  return STUDIO_IS_GLOBAL_ADMIN ? buildAdminApiUrl(`/characters/${encodeURIComponent(name)}`) : buildStudioUrl(`/characters/${encodeURIComponent(name)}`);
}

function buildCharacterThumbUrl(name) {
  return `${buildCharacterAdminUrl(name)}/thumbnail`;
}

function buildEnvironmentAdminUrl(name) {
  return STUDIO_IS_GLOBAL_ADMIN ? buildAdminApiUrl(`/environments/${encodeURIComponent(name)}`) : buildStudioUrl(`/environments/${encodeURIComponent(name)}`);
}

function buildEnvironmentThumbUrl(name) {
  return `${buildEnvironmentAdminUrl(name)}/thumbnail`;
}

function buildVoiceDeleteUrl(name) {
  return STUDIO_IS_GLOBAL_ADMIN ? buildAdminApiUrl(`/voices/${encodeURIComponent(name)}`) : buildStudioUrl(`/audio/voices/${encodeURIComponent(name)}`);
}

function buildVoiceListUrl() {
  return STUDIO_IS_GLOBAL_ADMIN ? buildAdminApiUrl('/audio/voices') : buildStudioUrl('/audio/voices');
}

function buildCharacterListUrl() {
  return STUDIO_IS_GLOBAL_ADMIN ? buildAdminApiUrl('/characters') : buildStudioUrl('/characters');
}

function buildEnvironmentListUrl() {
  return STUDIO_IS_GLOBAL_ADMIN ? buildAdminApiUrl('/environments') : buildStudioUrl('/environments');
}

function studioFetch(input, init) {
  return fetch(input, init);
}

function isUnsupportedStudioPath(path) {
  return Array.from(STUDIO_UNSUPPORTED_ENDPOINTS).some(prefix => path.startsWith(prefix));
}

function unsupportedError(path, label) {
  const suffix = label ? ` (${label})` : '';
  return new Error(`Unsupported in AISBF Studio: ${path}${suffix}`);
}

const val = id => ($(id) ? $(id).value : '');
const ival = id => parseInt(val(id)) || 0;
const fval = id => parseFloat(val(id)) || 0;
const chk = id => ($(id) ? $(id).checked : false);

// Capability → which level-1 tab
const CAP_CAT = {
  text_generation:'chat', image_to_text:'chat',
  image_generation:'image', image_to_image:'image', inpainting:'image',
  image_upscaling:'image', depth_estimation:'image', image_segmentation:'image',
  video_generation:'video', image_to_video:'video', video_to_video:'video',
  video_interpolation:'video', video_upscaling:'video',
  text_to_speech:'audio', speech_to_text:'audio', subtitle_generation:'video',
  audio_generation:'audio',
  embeddings:'embed',
};
// Capability → which level-2 sub-tab
const CAP_SUB = {
  image_generation:'img-gen', image_to_image:'img-edit', inpainting:'img-inpaint',
  image_upscaling:'img-upscale', depth_estimation:'img-depth', image_segmentation:'img-seg',
  video_generation:'vid-t2v', image_to_video:'vid-i2v', video_to_video:'vid-v2v',
  video_interpolation:'vid-interp', video_upscaling:'vid-up',
  subtitle_generation:'vid-sub',
  text_to_speech:'aud-tts', speech_to_text:'aud-stt',
  audio_generation:'aud-gen',
  model_3d_generation:'3d-generate', image_to_3d:'3d-img-to3d',
  video_to_3d:'3d-vid-to3d', model_3d_to_image:'3d-from3d',
};
// Sub-tab → parent category
const SUB_CAT = {
  'img-gen':'image','img-edit':'image','img-inpaint':'image','img-upscale':'image','img-depth':'image','img-seg':'image','img-faceswap':'image','img-deblur':'image','img-unpix':'image','img-outfit':'image','img-outfit':'image',
  'img-to3d':'image','img-from3d':'image',
  'vid-t2v':'video','vid-i2v':'video','vid-v2v':'video','vid-ti2v':'video','vid-interp':'video',
  'vid-sub':'video','vid-dub':'video','vid-up':'video','vid-faceswap':'video','vid-outfit':'video',
  'vid-to3d':'video','vid-from3d':'video',
  'aud-gen':'audio','aud-music-dub':'audio','aud-tts':'audio','aud-stt':'audio','aud-clone':'audio','aud-convert':'audio','aud-understand':'audio','aud-stems':'audio','aud-clean':'audio',
  '3d-generate':'3d','3d-img-to3d':'3d','3d-vid-to3d':'3d','3d-from3d':'3d',
  'prof-char':'profiles','prof-env':'profiles','prof-voice':'profiles',
};
// Sub-tabs that share a panel with an image sub-tab (vid-X → panel-img-Y)
const SUB_PANEL_ALIAS = {
  'vid-faceswap': 'panel-img-faceswap',
  'vid-outfit':   'panel-img-outfit',
};
// Video models also enable all video sub-tabs
const VIDEO_EXTRA_SUBS = ['vid-ti2v', 'vid-dub', 'vid-v2v', 'vid-sub', 'vid-interp', 'vid-up', 'vid-faceswap', 'vid-outfit'];
const TAB_STATE = {
  available: { label:'Ready', className:'state-ready' },
  partial: { label:'Partial', className:'state-partial' },
  unavailable: { label:'Unavailable', className:'state-unavailable' },
  none: {},
};
// Subs whose features are served by any available dedicated model, not only activeModel.
const CROSS_MODEL_SUBS = new Set(['aud-stt', 'aud-tts', 'aud-gen', 'embed']);
const STUDIO_CAPABILITIES = {
  'vid-dub': {
    category:'video',
    label:'Video dubbing',
    summary:'Translate spoken dialogue in a source video into another language and optionally burn subtitles into the result.',
    requires:['speech_to_text','text_to_speech'],
    optional:['subtitle_generation','video_to_video'],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/video/dub` or `/api/u/{username}/video/dub`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/video/dub` request and its multi-model payload.'
    ],
    backendPath: scopeApiPath('/v1/video/dub'),
    io:'Input: source video. Output: dubbed video with optional subtitle burn-in.'
  },
  'aud-gen': {
    category:'audio',
    label:'Music / SFX generation',
    summary:'Generate music beds, ambience, or sound effects through a provider-backed audio generation route.',
    requires:['audio_generation'],
    optional:['speech_to_text'],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/audio/generate` or `/api/u/{username}/audio/generate`.',
      'Actual support still depends on the selected provider/model accepting the forwarded `v1/audio/generations` request.'
    ],
    backendPath: scopeApiPath('/v1/audio/generate'),
    io:'Input: prompt and optional melody reference. Output: generated audio clip via proxied provider route.'
  },
  'aud-music-dub': {
    category:'audio',
    label:'Music dubbing',
    summary:'Assess song and lyric-localization workflows only when AISBF exposes a provider-backed multi-stage route.',
    requires:['speech_to_text','text_to_speech'],
    optional:['audio_generation'],
    notes:[
      'AISBF does not currently expose `/api/v1/pipelines/audio-music-dub` or a user-scoped equivalent.',
      'No local remix, stem isolation, or fallback pipeline should be implied.'
    ],
    backendPath: scopeApiPath('/v1/pipelines/audio-music-dub'),
    io:'Input: source song plus language goals. Output: proxied music dubbing artifacts when supported.'
  },
  'aud-understand': {
    category:'audio',
    label:'Audio understanding',
    summary:'Surface semantic audio analysis only when AISBF exposes a dedicated proxied route for it.',
    requires:['speech_to_text'],
    optional:['text_generation'],
    notes:[
      'AISBF does not currently expose `/api/v1/pipelines/audio-understand` or a user-scoped equivalent.',
      'Transcript + chat remains a manual workflow, not an integrated Studio backend path.'
    ],
    backendPath: scopeApiPath('/v1/pipelines/audio-understand'),
    io:'Input: source audio or video. Output: proxied audio reasoning response when supported.'
  },
  'aud-stems': {
    category:'audio',
    label:'Stem separation',
    summary:'Separate stems through a provider-backed audio utility route when the selected backend supports source separation.',
    requires:[],
    optional:['audio_generation','speech_to_text'],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/audio/stems` or `/api/u/{username}/audio/stems`.',
      'The proxied provider must support the forwarded `v1/audio/split` request shape for this to succeed.'
    ],
    backendPath: buildStudioUrl('/audio/stems'),
    io:'Input: mixed audio. Output: separated stems via proxied provider route.'
  },
  'aud-clean': {
    category:'audio',
    label:'Audio cleanup',
    summary:'Clean up audio through a provider-backed restoration route when the selected backend supports denoise or repair operations.',
    requires:[],
    optional:['speech_to_text'],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/audio/cleanup` or `/api/u/{username}/audio/cleanup`.',
      'The proxied provider must support the forwarded `v1/audio/denoise` request shape for this to succeed.'
    ],
    backendPath: buildStudioUrl('/audio/cleanup'),
    io:'Input: noisy audio. Output: restored audio via proxied provider route.'
  },
  'aud-clone': {
    category:'audio',
    label:'Voice cloning',
    summary:'Clone a voice through a provider-backed route when the selected backend supports voice synthesis from references.',
    requires:['text_to_speech'],
    optional:['audio_generation'],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/audio/clone` or `/api/u/{username}/audio/clone`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/audio/clone` request.'
    ],
    backendPath: scopeApiPath('/v1/audio/clone'),
    io:'Input: text plus either a saved voice profile or reference audio/text. Output: synthesized cloned voice audio.'
  },
  'aud-convert': {
    category:'audio',
    label:'Voice conversion',
    summary:'Convert one voice into another through a provider-backed route when the selected backend supports conversion.',
    requires:['speech_to_text'],
    optional:['text_to_speech','audio_generation'],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/audio/convert` or `/api/u/{username}/audio/convert`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/audio/convert` request.'
    ],
    backendPath: scopeApiPath('/v1/audio/convert'),
    io:'Input: source audio plus a target voice or voice profile. Output: converted audio via proxied provider route.'
  },
  'embed': {
    category:'embed',
    label:'Embeddings',
    summary:'Generate dense text embedding vectors for semantic search, similarity scoring, and RAG pipelines.',
    requires:['embeddings'],
    optional:[],
    notes:[
      'Requires a model with <b>embedding</b> capability configured in the Models page.',
      'GGUF text models with embedding support work, as do dedicated sentence-transformer models.',
    ],
    backendPath: buildStudioUrl('/embeddings'),
    io:'Input: one or more text strings. Output: floating-point embedding vectors.'
  },
  'img-faceswap': {
    category:'image',
    label:'Face Swap',
    summary:'Replace faces through a provider-backed face-swap route when the selected backend supports it.',
    requires:[],
    optional:[],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/images/faceswap` or `/api/u/{username}/images/faceswap`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/images/faceswap` request.'
    ],
    backendPath: buildStudioUrl('/images/faceswap'),
    io:'Input: source face image + target image or video. Output: face-swapped result via proxied provider route.'
  },
  'vid-faceswap': {
    category:'video',
    label:'Face Swap (Video)',
    summary:'Replace faces in video through a provider-backed face-swap route when the selected backend supports it.',
    requires:[],
    optional:[],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/images/faceswap` or `/api/u/{username}/images/faceswap`.',
      'Actual success depends on the selected provider/model accepting the forwarded face-swap payload for video targets.'
    ],
    backendPath: buildStudioUrl('/images/faceswap'),
    io:'Input: source face image + target video. Output: face-swapped video via proxied provider route.'
  },
  'img-deblur': {
    category:'image',
    label:'Deblur',
    summary:'Deblur images through a provider-backed restoration route when the selected backend supports it.',
    requires:[],
    optional:[],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/images/deblur` or `/api/u/{username}/images/deblur`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/images/deblur` request.'
    ],
    backendPath: buildStudioUrl('/images/deblur'),
    io:'Input: blurred image. Output: restored image via proxied provider route.'
  },
  'img-unpix': {
    category:'image',
    label:'Unpixelate / Upscale',
    summary:'Restore low-resolution images through a provider-backed super-resolution route when the selected backend supports it.',
    requires:[],
    optional:[],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/images/unpixelate` or `/api/u/{username}/images/unpixelate`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/images/unpixelate` request.'
    ],
    backendPath: buildStudioUrl('/images/unpixelate'),
    io:'Input: low-resolution or pixelated image. Output: upscaled image via proxied provider route.'
  },
  'img-outfit': {
    category:'image',
    label:'Outfit transfer',
    summary:'Apply outfit or wardrobe changes through a provider-backed image route when the selected backend supports it.',
    requires:['image_to_image'],
    optional:['inpainting'],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/images/outfit` or `/api/u/{username}/images/outfit`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/images/outfit` request.'
    ],
    backendPath: scopeApiPath('/v1/images/outfit'),
    io:'Input: source image or video plus outfit prompt. Output: transformed media via proxied provider route.'
  },
  'img-depth': {
    category:'image',
    label:'Depth estimation',
    summary:'Estimate image depth through a provider-backed route when the selected backend supports it.',
    requires:['depth_estimation'],
    optional:[],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/images/depth` or `/api/u/{username}/images/depth`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/images/depth` request.'
    ],
    backendPath: scopeApiPath('/v1/images/depth'),
    io:'Input: image. Output: depth map.'
  },
  'vid-interp': {
    category:'video',
    label:'Frame interpolation',
    summary:'Interpolate frames through a provider-backed video utility route when the selected backend supports it.',
    requires:['video_interpolation'],
    optional:[],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/video/interpolate` or `/api/u/{username}/video/interpolate`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/video/interpolate` request.'
    ],
    backendPath: scopeApiPath('/v1/video/interpolate'),
    io:'Input: video or keyframes. Output: interpolated video.'
  },
  'vid-sub': {
    category:'video',
    label:'Subtitle generation',
    summary:'Generate subtitles through a provider-backed video utility route when the selected backend supports it.',
    requires:['subtitle_generation'],
    optional:['speech_to_text'],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/video/subtitle` or `/api/u/{username}/video/subtitle`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/video/subtitle` request.'
    ],
    backendPath: scopeApiPath('/v1/video/subtitle'),
    io:'Input: video. Output: subtitle text or burned video.'
  },
  '3d-img-to3d': {
    category:'3d',
    label:'Image to 3D',
    summary:'Convert images to 3D through a provider-backed route when the selected backend supports it.',
    requires:['image_to_3d'],
    optional:['depth_estimation'],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/images/to3d` or `/api/u/{username}/images/to3d`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/images/to3d` request.'
    ],
    backendPath: scopeApiPath('/v1/images/to3d'),
    io:'Input: image. Output: stereo image or mesh artifact.'
  },
  '3d-vid-to3d': {
    category:'3d',
    label:'Video to 3D',
    summary:'Convert video to 3D through a provider-backed route when the selected backend supports it.',
    requires:['video_to_3d'],
    optional:['depth_estimation'],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/video/to3d` or `/api/u/{username}/video/to3d`.',
      'Actual success depends on the selected provider/model accepting the forwarded `v1/video/to3d` request.'
    ],
    backendPath: scopeApiPath('/v1/video/to3d'),
    io:'Input: video. Output: stereoscopic video or 3D artifact.'
  },
  '3d-from3d': {
    category:'3d',
    label:'Render from 3D',
    summary:'Render images or turntable video from 3D assets through provider-backed routes when supported.',
    requires:['model_3d_to_image'],
    optional:[],
    notes:[
      'AISBF now proxies this Studio panel through `/api/v1/images/from3d`, `/api/v1/video/from3d`, and user-scoped equivalents.',
      'Actual success depends on the selected provider/model accepting the forwarded 3D render request.'
    ],
    backendPath: scopeApiPath('/v1/images/from3d'),
    io:'Input: 3D asset. Output: rendered image or turntable video.'
  }
};
function capMissingHtml(caps, label) {
  if (!caps.length) return '';
  const chips = caps.map(cap => `<span class="cap-chip dim">${cap.replace(/_/g,' ')}</span>`).join(' ');
  return `<div class="cap-missing"><strong>${label}:</strong> ${chips}</div>`;
}

const SUB_CAPABILITY_RULES = {
  'img-gen': { category:'image', requiresAny:['image_generation'] },
  'img-edit': { category:'image', requiresAny:['image_to_image'] },
  'img-inpaint': { category:'image', requiresAny:['inpainting'] },
  'img-upscale': { category:'image', requiresAny:['image_upscaling'] },
  'img-depth': { category:'image', requiresAny:['depth_estimation'] },
  'img-seg': { category:'image', requiresAny:['image_segmentation'] },
  'img-faceswap': { category:'image' },
  'img-deblur': { category:'image' },
  'img-unpix': { category:'image' },
  'img-outfit': { category:'image', requiresAny:['image_to_image','inpainting'] },
  'vid-t2v': { category:'video', requiresAny:['video_generation'] },
  'vid-i2v': { category:'video', requiresAny:['image_to_video'] },
  'vid-v2v': { category:'video', optional:['video_to_video'], fallbackTypes:['video'] },
  'vid-ti2v': { category:'video', optional:['video_generation','image_to_video'], fallbackTypes:['video'] },
  'vid-interp': { category:'video', optional:['video_interpolation'], fallbackTypes:['video'] },
  'vid-sub': { category:'video', optional:['subtitle_generation'], fallbackTypes:['video'] },
  'vid-dub': { category:'video', optional:['subtitle_generation','speech_to_text','text_to_speech'], fallbackTypes:['video'] },
  'vid-up': { category:'video', requiresAny:['video_upscaling'], fallbackTypes:['video'] },
  'vid-faceswap': { category:'video' },
  'vid-outfit': { category:'video', requiresAny:['inpainting','image_to_image'], fallbackTypes:['video'] },
  'img-to3d': { category:'image', optional:['depth_estimation','image_to_3d'], fallbackTypes:['image'] },
  'img-from3d': { category:'image', optional:['model_3d_to_image'], fallbackTypes:['image'] },
  'vid-to3d': { category:'video', optional:['depth_estimation','video_to_3d'], fallbackTypes:['video'] },
  'vid-from3d': { category:'video', optional:['model_3d_to_image'], fallbackTypes:['video'] },
  '3d-generate': { category:'3d', optional:['model_3d_generation','image_to_3d'], fallbackTypes:['image'] },
  '3d-img-to3d': { category:'3d', optional:['depth_estimation','image_to_3d'], fallbackTypes:['image'] },
  '3d-vid-to3d': { category:'3d', optional:['depth_estimation','video_to_3d'], fallbackTypes:['video'] },
  '3d-from3d': { category:'3d', optional:['model_3d_to_image'], fallbackTypes:['image'] },
  'aud-gen': { category:'audio', requiresAny:['audio_generation'] },
  'aud-music-dub': { category:'audio', optional:['speech_to_text','text_to_speech','audio_generation'] },
  'aud-tts': { category:'audio', requiresAny:['text_to_speech'] },
  'aud-clone': { category:'audio', requiresAny:['text_to_speech','audio_generation'] },
  'aud-convert': { category:'audio', requiresAny:['speech_to_text','text_to_speech','audio_generation'] },
  'aud-stt': { category:'audio', requiresAny:['speech_to_text'] },
  'aud-understand': { category:'audio', optional:['speech_to_text','text_generation'], fallbackTypes:['audio','text','vision'] },
  'aud-stems': { category:'audio', optional:['audio_generation'], fallbackTypes:['audio'] },
  'aud-clean': { category:'audio', optional:['speech_to_text'], fallbackTypes:['audio'] },
  'embed': { requiresAny:['embeddings'] },
};
const CATEGORY_TABS = ['chat', 'image', 'video', 'audio', '3d', 'profiles', 'pipe', 'embed', 'archive'];
const DASHBOARD_CAPABILITY_MAP = {
  chat: 'text_generation',
  vision: 'image_to_text',
  image_generation: 'image_generation',
  image_edit: 'image_to_image',
  video_generation: 'video_generation',
  video_understanding: 'video_to_video',
  audio_input: 'speech_to_text',
  transcription: 'speech_to_text',
  speech_generation: 'text_to_speech',
  audio_generation: 'audio_generation',
  embeddings: 'embeddings',
  tool_use: 'text_generation',
  reasoning: 'text_generation',
  code_generation: 'text_generation',
  code_completion: 'text_generation',
  translation: 'text_generation',
  summarization: 'text_generation',
  object_detection: 'object_detection',
  segmentation: 'image_segmentation',
  image_captioning: 'image_to_text',
  '3d_generation': 'model_3d_generation'
};
const CATEGORY_SUBS = {
  image: Object.keys(SUB_CAPABILITY_RULES).filter(sub => SUB_CAT[sub] === 'image'),
  video: Object.keys(SUB_CAPABILITY_RULES).filter(sub => SUB_CAT[sub] === 'video'),
  audio: Object.keys(SUB_CAPABILITY_RULES).filter(sub => SUB_CAT[sub] === 'audio'),
  '3d': Object.keys(SUB_CAPABILITY_RULES).filter(sub => SUB_CAT[sub] === '3d'),
};
let currentTabState = { categories:{}, subs:{} };
let audioBackendHealth = {
  separation: { available:false, engine:null, model:null },
  restoration: { available:false, engine:null, model:null },
  musicDub: { available:false, stages:[] },
};

function refreshAudioBackendHealth() {
  audioBackendHealth = {
    separation: {
      available: false,
      engine: null,
      model: null,
    },
    restoration: {
      available: false,
      engine: null,
      model: null,
    },
    musicDub: {
      available: false,
      stages: [],
    },
  };
}

function capabilitySetForModel(m) {
  return new Set((m?.capabilities || []).filter(Boolean));
}

function boundModelForRole(bindingId, roleKey, fallbackModel = activeModel) {
  const assignedId = bindingModelId(bindingId, roleKey);
  if (assignedId) {
    const model = models.find(item => item.id === assignedId);
    if (model) return model;
  }
  return fallbackModel || null;
}

function boundModelId(bindingId, roleKey, fallbackModel = activeModel) {
  return boundModelForRole(bindingId, roleKey, fallbackModel)?.id || '';
}

function studioModelMetadataForRole(bindingId, roleKey, fallbackModel = activeModel) {
  const model = boundModelForRole(bindingId, roleKey, fallbackModel);
  if (!model) return null;
  return {
    id: model.id,
    name: model.name,
    capabilities: model.capabilities || [],
    studio_adapter: model.metadata?.studio_adapter || null,
    studio_adapter_override: model.metadata?.studio_adapter_override || null,
    studio_adapter_profile: model.metadata?.studio_adapter_profile || null,
    studio_adapter_profile_override: model.metadata?.studio_adapter_profile_override || null,
    provider_type: model.metadata?.provider_type || null,
    provider_endpoint: model.metadata?.provider_endpoint || null,
    provider_id: model.id.includes('/') ? model.id.split('/')[0] : null,
    studio_kind: model.studioKind || null,
  };
}

function crossModelCaps() {
  const s = new Set();
  models.forEach(m => (m.capabilities || []).forEach(c => s.add(c)));
  return s;
}

function bestModelForCap(cap) {
  const preferredBinding = functionBindingDefs.find(def => (def.roles || []).some(role => (role.capabilities || []).includes(cap)));
  if (preferredBinding) {
    const preferredRole = preferredBinding.roles.find(role => (role.capabilities || []).includes(cap));
    const bound = preferredRole ? boundModelForRole(preferredBinding.id, preferredRole.key, null) : null;
    if (bound) return bound;
  }
  return models.find(m => (m.capabilities || []).includes(cap)) || null;
}

function updatePipelineBadges() {
  const allCaps = crossModelCaps();
  document.querySelectorAll('.pipe-card[data-requires]').forEach(card => {
    let reqs, opts;
    try { reqs = JSON.parse(card.dataset.requires || '[]'); } catch(e) { reqs = []; }
    try { opts = JSON.parse(card.dataset.optional || '[]'); } catch(e) { opts = []; }
    const hasAll = reqs.every(c => allCaps.has(c));
    const hasSome = reqs.some(c => allCaps.has(c));
    const state = hasAll ? 'ready' : (hasSome || (!reqs.length && opts.some(c => allCaps.has(c)))) ? 'partial' : 'unavailable';
    const label = state === 'ready' ? 'Ready' : state === 'partial' ? 'Partial' : 'Unavailable';
    const head = card.querySelector('.pipe-head');
    if (!head) return;
    let badge = head.querySelector('.pipe-badge');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'pipe-badge';
      const title = head.querySelector('.pipe-title');
      if (title) title.insertAdjacentElement('afterend', badge);
      else head.insertBefore(badge, head.firstChild);
    }
    badge.className = `pipe-badge ${state}`;
    badge.textContent = label;
    // Capability chips in the card body
    const body = card.querySelector('.pipe-card-body');
    if (body) {
      let capsDiv = body.querySelector('.pipe-caps');
      if (!capsDiv) {
        capsDiv = document.createElement('div');
        capsDiv.className = 'pipe-caps';
        body.insertBefore(capsDiv, body.firstChild);
      }
      const fmt = c => c.replace(/_/g, ' ');
      const reqChips = reqs.map(c =>
        `<span class="pipe-cap-chip${allCaps.has(c) ? ' ok' : ' missing'}" title="${c}">${fmt(c)}</span>`
      ).join('');
      const optChips = opts.map(c =>
        `<span class="pipe-cap-chip optional${allCaps.has(c) ? ' ok' : ''}" title="${c}">${fmt(c)}</span>`
      ).join('');
      const parts = [];
      if (reqChips) parts.push(`<span class="pipe-caps-label">Requires</span>${reqChips}`);
      if (optChips) parts.push(`<span class="pipe-caps-label">Optional</span>${optChips}`);
      capsDiv.innerHTML = parts.join('');
    }
  });
  autoPopulatePipelineInputs();
}

function hasTypeFallback(rule, typeOrTypes) {
  if (!Array.isArray(rule.fallbackTypes)) return false;
  if (typeOrTypes instanceof Set) return rule.fallbackTypes.some(t => typeOrTypes.has(t));
  return rule.fallbackTypes.includes(typeOrTypes);
}

function evaluateSubCapability(rule, caps, typeOrTypes) {
  const required = rule.requiresAny || [];
  const optional = rule.optional || [];
  const hasRequired = required.some(cap => caps.has(cap));
  const hasOptional = optional.some(cap => caps.has(cap));
  const fallback = hasTypeFallback(rule, typeOrTypes);

  if (hasRequired) return 'available';
  if (!required.length && (hasOptional || fallback)) return 'partial';
  if (required.length && (hasOptional || fallback)) return 'partial';
  if (!required.length) return 'partial';
  return 'unavailable';
}

function evaluateCategoryState(cat, subStates, caps, type) {
  if (cat === 'chat') {
    return (caps.has('text_generation') || caps.has('image_to_text') || type === 'text' || type === 'vision')
      ? 'available'
      : 'partial';
  }
  if (cat === 'pipe') return 'none';
  if (cat === 'archive') return 'none';
  if (cat === 'profiles') return 'none';
  if (cat === 'embed') return caps.has('embeddings') || type === 'embedding' ? 'available' : 'unavailable';
  if (cat === '3d') return 'none';  // always show 3D tab (no required capability)
  const states = (CATEGORY_SUBS[cat] || []).map(sub => subStates[sub]).filter(Boolean);
  if (states.includes('available')) return 'available';
  if (states.includes('partial')) return 'partial';
  return 'unavailable';
}

function setTabVisualState(btn, state) {
  if (!btn) return;
  btn.classList.remove('state-ready', 'state-partial', 'state-unavailable');
  const def = TAB_STATE[state] || TAB_STATE.unavailable;
  if (def.className) btn.classList.add(def.className);
  const badge = btn.querySelector('.tab-status');
  if (!badge) return;
  if (def.label) {
    badge.textContent = def.label;
    badge.hidden = false;
  } else {
    badge.textContent = '';
    badge.hidden = true;
  }
}

function isSubVisibleForCategory(sub, cat) {
  return SUB_CAT[sub] === cat;
}

function getFirstVisibleSub(cat) {
  return document.querySelector(`.t2btn[data-sub][data-cat-visible="${cat}"]:not(.state-hidden)`);
}

function getSubtabState(sub) {
  return currentTabState.subs[sub] || 'unavailable';
}

function getCapabilityDetails(sub) {
  const def = STUDIO_CAPABILITIES[sub];
  if (!def) return null;
  const caps = crossModelCaps();
  const required = def.requires || [];
  const optional = def.optional || [];
  const missingRequired = required.filter(cap => !caps.has(cap));
  const missingOptional = optional.filter(cap => !caps.has(cap));
  const availability = getSubtabState(sub);
  return {
    ...def,
    availability,
    missingRequired,
    missingOptional,
  };
}

function renderCapabilityCard(sub) {
  const shell = $(`cap-${sub}`);
  if (!shell) return;
  const details = getCapabilityDetails(sub);
  if (!details) {
    shell.style.display = 'none';
    shell.innerHTML = '';
    return;
  }
  shell.style.display = '';
  shell.classList.remove('state-partial', 'state-unavailable');
  if (details.availability === 'partial') shell.classList.add('state-partial');
  if (details.availability === 'unavailable') shell.classList.add('state-unavailable');
  const availabilityLabel = details.availability === 'available' ? 'Ready' : details.availability === 'partial' ? 'Partial' : 'Unavailable';
  const availabilityClass = details.availability === 'available' ? ' ok' : details.availability === 'partial' ? ' warn' : ' dim';
  const missingBits = [];
  if (details.missingRequired.length) missingBits.push(capMissingHtml(details.missingRequired, 'Missing required'));
  if (details.missingOptional.length) missingBits.push(capMissingHtml(details.missingOptional, 'Limited without'));
  const notes = (details.notes || []).map(note => `<div class="cap-note">${note}</div>`).join('');
  shell.innerHTML = `
    <div class="cap-card-top">
      <div>
        <div class="cap-card-title">${details.label}</div>
        <div class="cap-card-summary">${details.summary}</div>
      </div>
      <span class="cap-chip${availabilityClass}">${availabilityLabel}</span>
    </div>
    <div class="cap-meta">
      <span class="cap-chip">${details.category}</span>
      <span class="cap-chip">${details.backendPath}</span>
      <span class="cap-chip">${details.io}</span>
    </div>
    ${missingBits.join('')}
    ${notes}
    ${renderSubModelPicker(sub)}
  `;
}

function renderCapabilityCards() {
  Object.keys(STUDIO_CAPABILITIES).forEach(renderCapabilityCard);
  // Render availability cards for all subs using SUB_CAPABILITY_RULES
  Object.keys(SUB_CAPABILITY_RULES).forEach(sub => {
    if (STUDIO_CAPABILITIES[sub]) return; // already handled above
    const shell = $(`cap-${sub}`);
    if (!shell) return;
    const state = currentTabState.subs[sub] || 'unavailable';
    const picker = renderSubModelPicker(sub);
    if (state === 'available') {
      if (picker) {
        shell.style.display = '';
        shell.classList.remove('state-partial', 'state-unavailable');
        shell.innerHTML = picker;
      } else {
        shell.style.display = 'none';
        shell.innerHTML = '';
      }
      return;
    }
    shell.style.display = '';
    shell.classList.remove('state-partial', 'state-unavailable');
    shell.classList.add(state === 'partial' ? 'state-partial' : 'state-unavailable');
    const rule = SUB_CAPABILITY_RULES[sub];
    const allCaps = crossModelCaps();
    const missingRequired = (rule.requiresAny || []).filter(c => !allCaps.has(c));
    const missingOptional = (rule.optional || []).filter(c => !allCaps.has(c));
    const label = document.querySelector(`.t2btn[data-sub="${sub}"]`)?.childNodes[0]?.textContent?.trim() || sub;
    const missingBits = [];
    if (missingRequired.length) missingBits.push(capMissingHtml(missingRequired, 'Missing required'));
    if (missingOptional.length) missingBits.push(capMissingHtml(missingOptional, 'Limited without'));
    const availabilityLabel = state === 'partial' ? 'Partial' : 'Unavailable';
    const availabilityClass = state === 'partial' ? ' warn' : ' dim';
    shell.innerHTML = `
      <div class="cap-card-top">
        <div class="cap-card-title">${escapeHtml(label)}</div>
        <span class="cap-chip${availabilityClass}">${availabilityLabel}</span>
      </div>
      ${missingBits.join('')}
      ${picker}
    `;
  });
  renderAudioBackendHealth();
}

function renderCapabilityOutputNote(sub) {
  const details = getCapabilityDetails(sub);
  const noteId = `cap-output-note-${sub}`;
  const panelId = SUB_PANEL_ALIAS[sub] || (`panel-${sub}`);
  const panel = $(panelId);
  if (!panel) return;
  panel.querySelector(`#${noteId}`)?.remove();
  if (!details || details.availability === 'available') return;
  const missingItems = [];
  details.missingRequired.forEach(cap => {
    const label = cap.replace(/_/g,' ');
    missingItems.push(`<strong>Required:</strong> ${label}`);
  });
  details.missingOptional.forEach(cap => {
    const label = cap.replace(/_/g,' ');
    missingItems.push(`<strong>Optional:</strong> ${label}`);
  });
  if (!missingItems.length && Array.isArray(details.notes)) missingItems.push(...details.notes);
  const title = details.availability === 'unavailable' ? '⚠ Feature unavailable' : '⚠ Feature partially available';
  const detailHtml = missingItems.length
    ? `<ul>${missingItems.map(item => `<li>${item}</li>`).join('')}</ul>`
    : '<div>Some required pieces are missing for this surface.</div>';
  const target = panel.querySelector('.gen-out') || panel.querySelector('.gen-wrap') || panel;
  target.insertAdjacentHTML('afterbegin', `
    <div class="cap-output-note ${details.availability === 'unavailable' ? 'unavailable' : ''}" id="${noteId}">
      <strong>${title}</strong>
      ${detailHtml}
    </div>
  `);
}

function renderOutputCapabilityNotes() {
  Object.keys(STUDIO_CAPABILITIES).forEach(sub => renderCapabilityOutputNote(sub));
}

function summarizeDiagnostics() {
  const subStates = currentTabState.subs || {};
  const details = Object.entries(SUB_CAPABILITY_RULES).map(([sub, rule]) => {
    const def = STUDIO_CAPABILITIES[sub];
    const state = subStates[sub] || 'unavailable';
    const label = def?.label || document.querySelector(`.t2btn[data-sub="${sub}"]`)?.childNodes[0]?.textContent?.trim() || sub;
    const fallbackOnly = state !== 'available' && !((rule.requiresAny || []).some(cap => capabilitySetForModel(activeModel).has(cap))) && hasTypeFallback(rule, activeModel?.type || 'text');
    return { sub, state, label, fallbackOnly };
  });
  return {
    available: details.filter(item => item.state === 'available'),
    limited: details.filter(item => item.state === 'partial' && !item.fallbackOnly),
    unavailable: details.filter(item => item.state === 'unavailable'),
    fallbackOnly: details.filter(item => item.fallbackOnly),
  };
}

function renderAudioBackendHealth() {
  const targets = {
    'aud-music-dub': audioBackendHealth.musicDub,
    'aud-stems': audioBackendHealth.separation,
    'aud-clean': audioBackendHealth.restoration,
  };
  Object.entries(targets).forEach(([sub, info]) => {
    const shell = $(`cap-${sub}`);
    if (!shell) return;
    const extra = [];
    if (info?.engine) extra.push(`<div class="cap-note"><strong>Runtime engine:</strong> ${escapeHtml(info.engine)}</div>`);
    if (info?.model) extra.push(`<div class="cap-note"><strong>Runtime model:</strong> ${escapeHtml(info.model)}</div>`);
    if (Array.isArray(info?.stages) && info.stages.length) extra.push(`<div class="cap-note"><strong>Stages:</strong> ${info.stages.map(escapeHtml).join(' → ')}</div>`);
    if (extra.length) shell.insertAdjacentHTML('beforeend', extra.join(''));
  });
}

function renderDiagnostics() {
  const shell = $('diag-groups');
  if (!shell) return;
  if (!activeModel) {
    shell.innerHTML = '<div class="diag-empty">Select a model to inspect Studio surfaces.</div>';
    return;
  }
  const groups = summarizeDiagnostics();
  const defs = [
    { key:'available', label:'Available surfaces' },
    { key:'limited', label:'Limited surfaces' },
    { key:'unavailable', label:'Unavailable surfaces' },
    { key:'fallbackOnly', label:'Fallback / pipeline-only' },
  ];
  shell.innerHTML = defs.map(def => {
    const items = groups[def.key] || [];
    return `
      <div class="diag-group">
        <div class="diag-group-head">
          <div class="diag-group-label">${escapeHtml(def.label)}</div>
          <span class="cap-chip">${items.length}</span>
        </div>
        ${items.length ? `<div class="diag-items">${items.map(item => `<span class="cap-chip">${escapeHtml(item.label)}</span>`).join('')}</div>` : '<div class="diag-empty">None</div>'}
      </div>
    `;
  }).join('');
}

function compactSummary(value, max=140) {
  const text = previewText(value, '').replace(/\s+/g, ' ').trim();
  if (!text) return '—';
  return text.length > max ? text.slice(0, max - 1) + '…' : text;
}

function pushArtifactHistory(entry) {
  artifactHistory.unshift({
    timestamp: new Date(),
    ...entry,
  });
  artifactHistory = artifactHistory.slice(0, ARTIFACT_HISTORY_LIMIT);
  renderArtifactHistory();
}

function renderArtifactHistory() {
  const shell = $('artifact-history-list');
  if (!shell) return;
  if (!artifactHistory.length) {
    shell.innerHTML = '<div class="hist-empty">Successful outputs from this session will appear here.</div>';
    return;
  }
  shell.innerHTML = artifactHistory.map(item => {
    const links = (item.links || []).filter(link => link?.href).map(link => `<a class="btn btn-ghost btn-sm hist-link" href="${escapeHtml(link.href)}" target="_blank" rel="noopener">${escapeHtml(link.label || 'Open')}</a>`).join('');
    const chips = [item.family, item.model].filter(Boolean).map(value => `<span class="cap-chip">${escapeHtml(value)}</span>`).join('');
    return `
      <div class="hist-item">
        <div class="hist-top">
          <div>
            <div class="hist-name">${escapeHtml(item.task)}</div>
            <div class="hist-meta">${escapeHtml(item.timestamp.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}))}</div>
          </div>
          <div class="hist-links">${links}</div>
        </div>
        <div class="hist-chips">${chips}</div>
        <div class="hist-summary">${escapeHtml(compactSummary(item.summary))}</div>
      </div>
    `;
  }).join('');
}

function buildDubHistorySummary(preview) {
  const source = preview?.source_lang || 'auto';
  const target = preview?.target_lang || 'unspecified';
  return `Dub ${source} → ${target}${preview?.burn_subtitles ? ' with burned subtitles' : ''}`;
}

function buildImageHistorySummary(urls) {
  return `${urls.length} image${urls.length === 1 ? '' : 's'} generated`;
}

function buildAudioHistorySummary(prompt, duration) {
  const promptText = compactSummary(prompt, 90);
  return `${duration || '—'}s clip · ${promptText}`;
}

function buildTTSHistorySummary(input, voice) {
  return `${voice || 'default voice'} · ${compactSummary(input, 100)}`;
}

function buildSTTHistorySummary(text, fileName) {
  return `${fileName || 'uploaded file'} · ${compactSummary(text, 100)}`;
}

function buildStemHistorySummary(mode, count, backend) {
  const engine = backend?.engine || 'unknown';
  const model = backend?.model ? ` · ${backend.model}` : '';
  return `${mode} · ${count} artifact${count === 1 ? '' : 's'} · ${engine}${model}`;
}

function buildCleanupHistorySummary(applied, fileName, backend) {
  const engine = backend?.engine || 'unknown';
  const model = backend?.model ? ` · ${backend.model}` : '';
  return `${fileName || 'uploaded file'} · ${(applied || []).join(', ') || 'no ops'} · ${engine}${model}`;
}

function buildMusicDubHistorySummary(transcript, translatedLyrics, backend) {
  const engine = backend?.engine || 'pipeline';
  const model = backend?.model ? ` · ${backend.model}` : '';
  return `${compactSummary(transcript, 50)} · ${compactSummary(translatedLyrics, 50)} · ${engine}${model}`;
}

function buildDubFamilyLabel() {
  return val('vd-track-mode') === 'localized-mix' ? 'video dub / localized mix' : 'video dub / speech-only';
}

function buildDubLinks(item) {
  const src = vidSrc(item);
  return src ? [{ label:'Open', href:src }] : [];
}

function buildAudioLinks(item) {
  const src = audSrc(item);
  return src ? [{ label:'Open', href:src }] : [];
}

function buildImageLinks(urls) {
  return (urls || []).filter(Boolean).slice(0, 2).map((href, index) => ({ label:index === 0 ? 'Open' : `Open ${index + 1}`, href }));
}

function buildDubPreferencePreview() {
  return {
    source_lang: val('vd-slang') || undefined,
    target_lang: val('vd-tlang') || undefined,
    burn_subtitles: chk('vd-burn'),
    preserve_voice: chk('vd-preserve-voice'),
    preserve_tone: chk('vd-preserve-tone'),
    preserve_timing: chk('vd-preserve-timing'),
    preserve_singing: chk('vd-preserve-singing'),
    translate_lyrics: chk('vd-lyrics'),
    track_mode: val('vd-track-mode') || 'speech-only',
  };
}

function previewText(value, fallback='—') {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function previewFileName(id) {
  const file = fileOrNull(id);
  return file ? file.name : 'none';
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#39;');
}

function previewExportBody(endpoint, body) {
  const safe = Object.fromEntries(Object.entries(body).filter(([, value]) => value !== undefined));
  return {
    endpoint,
    body: safe,
    json: JSON.stringify(safe, null, 2),
  };
}

function buildAudioPreviewData() {
  return previewExportBody(buildStudioUrl('/audio/generate'), {
    model: activeModel?.id || '',
    prompt: val('ag-prompt'),
    duration: fval('ag-dur') || 10,
    temperature: fval('ag-temp') || 1.0,
    top_k: ival('ag-topk') || 250,
    cfg_coef: fval('ag-cfg') || 3.0,
    seed: val('ag-seed') ? ival('ag-seed') : undefined,
    melody: fileOrNull('ag-melody') ? '<audio file data>' : undefined,
    response_format: 'url',
  });
}

function buildTTSPreviewData() {
  return previewExportBody(buildStudioUrl('/audio/speech'), {
    model: activeModel?.id || '',
    input: val('at-text'),
    voice: val('at-voice') || undefined,
    speed: fval('at-speed') || 1.0,
    response_format: 'mp3',
  });
}

function buildSTTPreviewData() {
  const sttModel = bestModelForCap('speech_to_text') || activeModel;
  return previewExportBody(buildStudioUrl('/audio/transcriptions'), {
    model: sttModel?.id || '',
    file: fileOrNull('as-file') ? '<multipart audio/video file>' : undefined,
    language: val('as-lang') || undefined,
    prompt: val('as-prompt') || undefined,
    response_format: 'json',
  });
}

function buildImageGenPreviewData() {
  return previewExportBody(buildStudioUrl('/images/generations'), {
    model: activeModel?.id || '',
    prompt: val('ig-prompt'),
    negative_prompt: val('ig-neg') || undefined,
    size: `${ival('ig-w') || 1024}x${ival('ig-h') || 1024}`,
    steps: ival('ig-steps') || 30,
    guidance_scale: fval('ig-cfg') || 7.5,
    seed: val('ig-seed') ? ival('ig-seed') : undefined,
    n: ival('ig-n') || 1,
    response_format: 'url',
    safety_checker: chk('ig-nosafe') ? false : undefined,
  });
}

function buildEmbeddingsPreviewData() {
  const lines = val('em-text').split('\n').filter(l => l.trim());
  const input = lines.length <= 1 ? (lines[0] || '') : lines;
  return previewExportBody(buildStudioUrl('/embeddings'), {
    model: activeModel?.id || '',
    input,
    encoding_format: val('em-enc') || 'float',
    dimensions: val('em-dims') ? ival('em-dims') : undefined,
  });
}

function buildAudioUnderstandPreviewData() {
  return previewExportBody(buildStudioUrl('/pipelines/audio-understand'), {
    audio: fileOrNull('au-file') ? '<audio/video file data>' : undefined,
    audio_model: activeModel?.id || '',
    text_model: val('au-text-model') || undefined,
    input: val('au-goal') || undefined,
    language: val('as-lang') || undefined,
  });
}

function buildMusicDubPreviewData() {
  return previewExportBody(buildStudioUrl('/pipelines/audio-music-dub'), {
    audio: fileOrNull('amd-file') ? '<audio/video file data>' : undefined,
    stt_model: getAssignedModelId('aud-music-dub', 'speech_to_text'),
    tts_model: getAssignedModelId('aud-music-dub', 'text_to_speech'),
    source_lang: val('amd-slang') || undefined,
    target_lang: val('amd-tlang') || undefined,
    notes: val('amd-notes') || undefined,
  });
}

function buildStemPreviewData() {
  return previewExportBody(buildStudioUrl('/audio/stems'), {
    audio: fileOrNull('ast-file') ? '<audio/video file data>' : undefined,
    stem_mode: val('ast-mode') || 'vocals-instrumental',
    response_format: 'url',
  });
}

function buildCleanupPreviewData() {
  return previewExportBody(buildStudioUrl('/audio/cleanup'), {
    audio: fileOrNull('ac-file') ? '<audio/video file data>' : undefined,
    noise_reduction: chk('ac-noise'),
    normalize: chk('ac-level'),
    remove_hum: chk('ac-hum'),
    repair_clicks: chk('ac-click'),
    response_format: 'url',
  });
}

function buildDubPreviewData() {
  const preview = buildDubPreferencePreview();
  return previewExportBody(buildStudioUrl('/video/dub'), {
    stt_model: getAssignedModelId('vid-dub', 'speech_to_text'),
    tts_model: getAssignedModelId('vid-dub', 'text_to_speech'),
    video: fileOrNull('vd-src') ? '<video file data>' : undefined,
    source_lang: preview.source_lang,
    target_lang: preview.target_lang,
    burn_subtitles: preview.burn_subtitles,
  });
}

function buildCodeSnippet(kind, preview) {
  const origin = window.location.hostname === '0.0.0.0'
    ? window.location.origin.replace('0.0.0.0', '127.0.0.1')
    : window.location.origin;
  const token = apiToken || 'YOUR_API_KEY';
  if (kind === 'curl') {
    return `curl -X POST ${origin}${preview.endpoint} \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${token}" \\
  -d '${preview.json.replace(/'/g, "'\\''")}'`;
  }
  if (kind === 'python') {
    return `import requests\n\npayload = ${preview.json}\nresponse = requests.post(\n    "${origin}${preview.endpoint}",\n    headers={"Authorization": "Bearer ${token}"},\n    json=payload,\n    timeout=300,\n)\nprint(response.json())`;
  }
  return `const payload = ${preview.json};\nconst response = await dashboardFetch("${origin}${preview.endpoint}", {\n  method: "POST",\n  headers: { "Content-Type": "application/json", "Authorization": "Bearer ${token}" },\n  body: JSON.stringify(payload),\n});\nconst data = await response.json();\nconsole.log(data);`;
}

function renderRequestPreview(panel, config) {
  const shell = $(config.containerId);
  if (!shell) return;
  const preview = config.build();
  const fields = config.fields.map(field => `
    <div class="req-preview-field">
      <div class="req-preview-label">${escapeHtml(field.label)}</div>
      <div class="req-preview-value">${escapeHtml(previewText(field.value(preview)))}</div>
    </div>
  `).join('');
  const snippet = buildCodeSnippet(config.snippet || 'curl', preview);
  shell.innerHTML = `
    <div class="req-preview-top">
      <div>
        <div class="req-preview-title">Request preview</div>
        <div class="req-preview-sub">Read-only export derived from current form values.</div>
      </div>
      <div class="req-preview-endpoint">POST ${escapeHtml(preview.endpoint)}</div>
    </div>
    <div class="req-preview-grid">${fields}</div>
    <div class="req-preview-actions">
      <button type="button" class="btn btn-ghost btn-sm" data-preview-kind="curl">cURL</button>
      <button type="button" class="btn btn-ghost btn-sm" data-preview-kind="python">Python</button>
      <button type="button" class="btn btn-ghost btn-sm" data-preview-kind="javascript">JavaScript</button>
      <button type="button" class="btn btn-ghost btn-sm" data-preview-copy>Copy</button>
    </div>
    <textarea class="fi req-preview-code" readonly>${escapeHtml(snippet)}</textarea>
    <div class="req-preview-status"></div>
  `;
  const codeEl = shell.querySelector('.req-preview-code');
  const statusEl = shell.querySelector('.req-preview-status');
  shell.querySelectorAll('[data-preview-kind]').forEach(btn => {
    btn.classList.toggle('btn-primary', btn.dataset.previewKind === (config.snippet || 'curl'));
    btn.classList.toggle('btn-ghost', btn.dataset.previewKind !== (config.snippet || 'curl'));
    btn.addEventListener('click', () => {
      config.snippet = btn.dataset.previewKind;
      renderRequestPreview(panel, config);
    });
  });
  shell.querySelector('[data-preview-copy]')?.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(codeEl.value);
      statusEl.textContent = 'Copied ✓';
    } catch (e) {
      statusEl.textContent = 'Copy failed';
    }
  });
}

const REQUEST_PREVIEW_CONFIG = {
  'aud-gen': {
    containerId:'ag-preview',
    snippet:'curl',
    build:buildAudioPreviewData,
    fields:[
      { label:'Model', value:preview => preview.body.model || 'none selected' },
      { label:'Prompt', value:preview => preview.body.prompt || 'empty' },
      { label:'Duration', value:preview => preview.body.duration },
      { label:'Temperature', value:preview => preview.body.temperature },
      { label:'Melody ref', value:() => previewFileName('ag-melody') },
      { label:'Seed', value:preview => preview.body.seed ?? 'random' },
    ],
  },
  'aud-tts': {
    containerId:'at-preview',
    snippet:'curl',
    build:buildTTSPreviewData,
    fields:[
      { label:'Model', value:preview => preview.body.model || 'none selected' },
      { label:'Voice', value:preview => preview.body.voice || 'default' },
      { label:'Speed', value:preview => preview.body.speed },
      { label:'Text', value:preview => preview.body.input || 'empty' },
    ],
  },
  'aud-stt': {
    containerId:'as-preview',
    snippet:'curl',
    build:buildSTTPreviewData,
    fields:[
      { label:'Model', value:preview => preview.body.model || 'none selected' },
      { label:'File', value:() => previewFileName('as-file') },
      { label:'Language', value:preview => preview.body.language || 'auto' },
      { label:'Hint', value:preview => preview.body.prompt || 'none' },
    ],
  },
  'img-gen': {
    containerId:'ig-preview',
    snippet:'curl',
    build:buildImageGenPreviewData,
    fields:[
      { label:'Model', value:preview => preview.body.model || 'none selected' },
      { label:'Prompt', value:preview => preview.body.prompt || 'empty' },
      { label:'Size', value:preview => preview.body.size },
      { label:'Steps', value:preview => preview.body.steps },
      { label:'CFG', value:preview => preview.body.guidance_scale },
      { label:'Count', value:preview => preview.body.n },
    ],
  },
  'embed': {
    containerId:'em-preview',
    snippet:'curl',
    build:buildEmbeddingsPreviewData,
    fields:[
      { label:'Model', value:preview => preview.body.model || 'none selected' },
      { label:'Items', value:preview => Array.isArray(preview.body.input) ? preview.body.input.length : (preview.body.input ? 1 : 0) },
      { label:'Encoding', value:preview => preview.body.encoding_format },
      { label:'Dimensions', value:preview => preview.body.dimensions ?? 'full' },
    ],
  },
  'aud-understand': {
    containerId:'au-preview',
    snippet:'curl',
    build:buildAudioUnderstandPreviewData,
    fields:[
      { label:'Audio model', value:preview => preview.body.audio_model || 'none selected' },
      { label:'Reasoning model', value:preview => preview.body.text_model || 'transcript only' },
      { label:'File', value:() => previewFileName('au-file') },
      { label:'Goal', value:preview => preview.body.input || 'general understanding' },
    ],
  },
  'aud-music-dub': {
    containerId:'amd-preview',
    snippet:'curl',
    build:buildMusicDubPreviewData,
    fields:[
      { label:'STT model', value:preview => preview.body.stt_model || 'none selected' },
      { label:'TTS model', value:preview => preview.body.tts_model || 'none selected' },
      { label:'File', value:() => previewFileName('amd-file') },
      { label:'Source lang', value:preview => preview.body.source_lang || 'auto' },
      { label:'Target lang', value:preview => preview.body.target_lang || 'none' },
    ],
  },
  'vid-dub': {
    containerId:'vd-preview',
    snippet:'curl',
    build:buildDubPreviewData,
    fields:[
      { label:'STT model', value:preview => preview.body.stt_model || 'none selected' },
      { label:'TTS model', value:preview => preview.body.tts_model || 'none selected' },
      { label:'Video file', value:() => previewFileName('vd-src') },
      { label:'Source lang', value:preview => preview.body.source_lang || 'auto' },
      { label:'Target lang', value:preview => preview.body.target_lang || 'required at run time' },
      { label:'Burn subtitles', value:preview => preview.body.burn_subtitles },
      { label:'Track mode', value:() => val('vd-track-mode') || 'speech-only' },
    ],
  },
};

function updateRequestPreview(panel) {
  const config = REQUEST_PREVIEW_CONFIG[panel];
  if (!config) return;
  renderRequestPreview(panel, config);
}

function initRequestPreviews() {
  ['ag-prompt','ag-dur','ag-temp','ag-topk','ag-cfg','ag-melody','ag-seed','at-text','at-voice','at-speed','as-file','as-lang','as-prompt','ig-prompt','ig-neg','ig-w','ig-h','ig-steps','ig-cfg','ig-seed','ig-n','ig-nosafe','em-text','em-enc','em-dims','au-file','au-goal','au-text-model','amd-file','amd-slang','amd-tlang','amd-notes','vd-src','vd-slang','vd-tlang','vd-track-mode','vd-burn','vd-preserve-voice','vd-preserve-tone','vd-preserve-timing','vd-preserve-singing','vd-lyrics']
    .forEach(id => {
      const el = $(id);
      if (!el) return;
      el.addEventListener('input', () => {
        if (id.startsWith('ag-')) updateRequestPreview('aud-gen');
        if (id.startsWith('at-')) updateRequestPreview('aud-tts');
        if (id.startsWith('as-')) updateRequestPreview('aud-stt');
        if (id.startsWith('ig-')) updateRequestPreview('img-gen');
        if (id.startsWith('em-')) updateRequestPreview('embed');
        if (id.startsWith('au-')) updateRequestPreview('aud-understand');
        if (id.startsWith('amd-')) updateRequestPreview('aud-music-dub');
        if (id.startsWith('ast-')) updateRequestPreview('aud-stems');
        if (id.startsWith('ac-')) updateRequestPreview('aud-clean');
        if (id.startsWith('vd-')) updateRequestPreview('vid-dub');
      });
      el.addEventListener('change', () => {
        if (id.startsWith('ag-')) updateRequestPreview('aud-gen');
        if (id.startsWith('at-')) updateRequestPreview('aud-tts');
        if (id.startsWith('as-')) updateRequestPreview('aud-stt');
        if (id.startsWith('ig-')) updateRequestPreview('img-gen');
        if (id.startsWith('em-')) updateRequestPreview('embed');
        if (id.startsWith('au-')) updateRequestPreview('aud-understand');
        if (id.startsWith('amd-')) updateRequestPreview('aud-music-dub');
        if (id.startsWith('ast-')) updateRequestPreview('aud-stems');
        if (id.startsWith('ac-')) updateRequestPreview('aud-clean');
        if (id.startsWith('vd-')) updateRequestPreview('vid-dub');
      });
    });
  updateRequestPreview('aud-gen');
  updateRequestPreview('aud-tts');
  updateRequestPreview('aud-stt');
  updateRequestPreview('img-gen');
  updateRequestPreview('embed');
  updateRequestPreview('aud-understand');
  updateRequestPreview('aud-music-dub');
  updateRequestPreview('aud-stems');
  updateRequestPreview('aud-clean');
  updateRequestPreview('vid-dub');
  renderDiagnostics();
  renderArtifactHistory();
}

// ─────────────────────────────────────────────────────────────────
//  Boot
// ─────────────────────────────────────────────────────────────────
function deduplicateModels(raw) {
  const TYPE_PREFIXES = /^(audio|tts|image|vision|video|audio_gen|embedding):/;

  // Group entries sharing the same alias → keep only the entry whose id === alias
  const aliasGroups = {};
  const noAlias = [];
  for (const m of raw) {
    if (m.alias) (aliasGroups[m.alias] = aliasGroups[m.alias] || []).push(m);
    else noAlias.push(m);
  }
  const result = [];
  for (const alias in aliasGroups) {
    const g = aliasGroups[alias];
    result.push(g.find(m => m.id === alias) || g[0]);
  }
  // For alias-less entries, skip bare basenames that are short forms of a full path
  const fullIds = new Set(noAlias.map(m => m.id));
  for (const m of noAlias) {
    if (m.id.includes('/')) {
      result.push(m);
    } else if (![...fullIds].some(id => id.endsWith('/' + m.id))) {
      result.push(m);
    }
  }
  // Drop "type:modelname" entries when "modelname" already appears in the result
  const resultIds = new Set(result.map(m => m.id));
  return result.filter(m => {
    const match = m.id.match(TYPE_PREFIXES);
    return !match || !resultIds.has(m.id.slice(match[0].length));
  });
}

function normalizeDashboardCaps(caps) {
  const out = [];
  (caps || []).forEach(cap => {
    const mapped = DASHBOARD_CAPABILITY_MAP[cap] || cap;
    if (mapped && !out.includes(mapped)) out.push(mapped);
  });
  return out;
}

function dashboardFetch(input, init) {
  return studioFetch(input, init);
}

function inferModelTypeFromCapabilities(caps) {
  if (caps.includes('video_generation') || caps.includes('image_to_video') || caps.includes('video_to_video')) return 'video';
  if (caps.includes('audio_generation') || caps.includes('speech_to_text')) return 'audio';
  if (caps.includes('text_to_speech')) return 'tts';
  if (caps.includes('image_generation') || caps.includes('image_to_image')) return 'image';
  if (caps.includes('image_to_text')) return 'vision';
  if (caps.includes('embeddings')) return 'embedding';
  if (caps.includes('model_3d_generation') || caps.includes('image_to_3d') || caps.includes('video_to_3d')) return 'spatial';
  return 'text';
}

function bootstrapModelsFromCatalog() {
  return studioEntries.map(entry => {
    const caps = normalizeDashboardCaps([...(entry.capabilities || []), ...(entry.partial_capabilities || [])]);
    return {
      id: entry.id,
      name: entry.label || entry.target_id || entry.id,
      capabilities: caps,
      type: inferModelTypeFromCapabilities(caps),
      description: entry.description || '',
      studioAvailability: entry.availability_state || ((entry.partial_capabilities || []).length ? 'partial' : 'ready'),
      studioKind: entry.kind,
      studioPartial: entry.partial_capabilities || [],
      sourceId: entry.source_id || '',
      targetId: entry.target_id || '',
      metadata: entry.metadata || {},
    };
  });
}

function displayNameForModel(model) {
  if (!model) return '';
  return model.name || model.label || model.id?.split('/').pop() || model.id || '';
}

function providerLabelForModel(model) {
  if (!model) return '';
  return model.sourceId || model.id?.split('/')[1] || '';
}

function modelMatchesQuery(model, query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return true;
  const haystack = [
    model.id,
    displayNameForModel(model),
    providerLabelForModel(model),
    model.studioKind,
    ...(model.capabilities || []),
  ].filter(Boolean).join(' ').toLowerCase();
  return haystack.includes(q);
}

function getBindingDefinition(bindingId) {
  return functionBindingDefs.find(def => def.id === bindingId) || null;
}

function bindingRoles(bindingId) {
  return functionBindings[bindingId] || {};
}

function bindingModelId(bindingId, roleKey) {
  return bindingRoles(bindingId)[roleKey] || '';
}

function modelsForRole(role) {
  const caps = role?.capabilities || [];
  if (!caps.length) return models.slice();
  return models.filter(model => caps.some(cap => capabilitySetForModel(model).has(cap)));
}

function ensureBindingSelection(bindingId) {
  const def = getBindingDefinition(bindingId);
  if (!def) return;
  const next = { ...(functionBindings[bindingId] || {}) };
  let changed = false;
  (def.roles || []).forEach(role => {
    if (next[role.key]) return;
    const first = modelsForRole(role)[0];
    if (first) {
      next[role.key] = first.id;
      changed = true;
    }
  });
  if (changed) functionBindings[bindingId] = next;
}

function ensureDefaultBindingSelections() {
  functionBindingDefs.forEach(def => ensureBindingSelection(def.id));
}

async function loadFunctionBindings() {
  try {
    const res = await dashboardFetch(buildStudioUrl('/function-bindings'));
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    functionBindingDefs = Array.isArray(data.definitions) ? data.definitions : [];
    functionBindings = data.bindings && typeof data.bindings === 'object' ? data.bindings : {};
    ensureDefaultBindingSelections();
  } catch (_) {
    functionBindingDefs = [];
    functionBindings = {};
  }
}

async function loadModels() {
  models = deduplicateModels(bootstrapModelsFromCatalog());
  await loadFunctionBindings();
  renderSidebar();
  if (models.length) selectModel(models[0]);
  else $('model-list').innerHTML = '<div class="muted small" style="padding:.5rem .6rem">No Studio targets available</div>';
}

async function loadLocalCapabilities() {
  try {
    const r = await dashboardFetch(buildAdminApiUrl('/cached-models'));
    if (!r.ok) return;
    const d = await r.json();
    _localCapSet.clear();
    [...(d.hf||[]), ...(d.gguf||[])].forEach(m => {
      (m.capabilities||[]).forEach(cap => _localCapSet.add(cap));
    });
    // Re-render capability cards now that local data is available
    renderCapabilityCards();
  } catch(e) {}
}

const BADGE = {text:'mb-text',vision:'mb-vision',image:'mb-image',video:'mb-video',
               audio:'mb-audio',tts:'mb-tts',audio_gen:'mb-audiogen',embedding:'mb-embed',
               spatial:'mb-image'};
const BLABEL = {text:'LLM',vision:'VLM',image:'IMG',video:'VID',audio:'STT',
                tts:'TTS',audio_gen:'MUS',embedding:'EMB',spatial:'SPA'};

function renderSidebar() {
  const el = $('model-list');
  const activeEl = document.activeElement;
  const activeIsBindingSearch = activeEl && activeEl.classList && activeEl.classList.contains('binding-role-search');
  const activeValue = activeIsBindingSearch ? activeEl.value : '';
  const activeSelectionStart = activeIsBindingSearch && typeof activeEl.selectionStart === 'number' ? activeEl.selectionStart : null;
  const activeSelectionEnd = activeIsBindingSearch && typeof activeEl.selectionEnd === 'number' ? activeEl.selectionEnd : null;
  const restoreKey = activeIsBindingSearch ? activeEl.getAttribute('data-search-key') : null;
  if (!functionBindingDefs.length) { el.innerHTML='<div class="muted small" style="padding:.5rem .6rem">No Studio bindings</div>'; return; }
  el.innerHTML = `<div class="binding-list">${functionBindingDefs.map(renderBindingCard).join('')}</div>`;
  if (_pendingBindingFocusKey) {
    const pendingEl = el.querySelector(`.binding-role-search[data-search-key="${CSS.escape(_pendingBindingFocusKey)}"]`);
    if (pendingEl) {
      pendingEl.focus();
      pendingEl.setSelectionRange(pendingEl.value.length, pendingEl.value.length);
    }
    _pendingBindingFocusKey = null;
  } else if (restoreKey) {
    const nextEl = el.querySelector(`.binding-role-search[data-search-key="${CSS.escape(restoreKey)}"]`);
    if (nextEl) {
      nextEl.focus();
      if (nextEl.value !== activeValue) nextEl.value = activeValue;
      if (activeSelectionStart !== null && activeSelectionEnd !== null && typeof nextEl.setSelectionRange === 'function') {
        nextEl.setSelectionRange(activeSelectionStart, activeSelectionEnd);
      }
    }
  }
}

function renderBindingCard(def) {
  const roles = def.roles || [];
  const assignedCount = roles.filter(role => !!bindingModelId(def.id, role.key)).length;
  const active = selectedBindingId === def.id ? ' active' : '';
  const body = selectedBindingId === def.id ? `<div class="binding-card-body">${roles.map(role => renderBindingRole(def, role)).join('')}</div>` : '';
  return `<div class="binding-card${active}" data-binding-id="${def.id}">
    <div class="binding-card-head" onclick="selectBindingCard('${def.id}')">
      <div>
        <div class="binding-card-title">${escapeHtml(def.label)}</div>
        <div class="binding-card-meta">${escapeHtml(def.category || 'studio')} · ${escapeHtml(def.endpoint || '')}</div>
      </div>
      <div class="binding-card-count">${assignedCount}/${roles.length}</div>
    </div>
    ${body}
  </div>`;
}

function _providerSuggestionsForRole(role, queryLower) {
  const capable = modelsForRole(role);
  const map = new Map();
  for (const model of capable) {
    if (model.studioKind !== 'provider_model') continue;
    const pid = model.sourceId || model.id?.split('/')[1] || '';
    if (!pid) continue;
    map.set(pid, (map.get(pid) || 0) + 1);
  }
  let providers = [...map.entries()].map(([id, count]) => ({ id, count }));
  if (queryLower) {
    providers = providers.filter(p => p.id.toLowerCase().includes(queryLower));
    providers.sort((a, b) => {
      const aPrefix = a.id.toLowerCase().startsWith(queryLower) ? 0 : 1;
      const bPrefix = b.id.toLowerCase().startsWith(queryLower) ? 0 : 1;
      if (aPrefix !== bPrefix) return aPrefix - bPrefix;
      return a.id.localeCompare(b.id);
    });
  } else {
    providers.sort((a, b) => a.id.localeCompare(b.id));
  }
  return providers;
}

function _renderBindingModelResult(def, role, model, assignedId) {
  const isActive = model.id === assignedId;
  return `<button class="binding-role-result${isActive ? ' active' : ''}" onclick="saveBindingRole('${def.id}','${role.key}','${encodeURIComponent(model.id)}');return false;">
    <span>
      <div class="binding-role-result-name">${escapeHtml(displayNameForModel(model))}</div>
      <div class="binding-role-result-meta">${escapeHtml(model.id)} · ${escapeHtml(model.studioKind || model.type || 'model')}</div>
    </span>
    <span class="binding-role-result-meta">${escapeHtml((model.capabilities || []).slice(0, 3).join(', ') || 'capability')}</span>
  </button>`;
}

function setBindingSearch(bindingId, roleKey, value) {
  const key = `${bindingId}:${roleKey}`;
  bindingSearchState[key] = value;
  _pendingBindingFocusKey = key;
  renderSidebar();
}

function renderBindingRole(def, role) {
  const searchKey = `${def.id}:${role.key}`;
  const query = bindingSearchState[searchKey] || '';
  const assignedId = bindingModelId(def.id, role.key);
  const assignedModel = models.find(model => model.id === assignedId) || null;

  let resultsHtml;
  const slashIdx = query.indexOf('/');

  if (slashIdx !== -1) {
    // Provider-scoped: "providerid/" or "providerid/modelpart"
    const providerPart = query.slice(0, slashIdx).toLowerCase();
    const modelPart = query.slice(slashIdx + 1).toLowerCase();
    const capable = modelsForRole(role);
    const candidates = capable.filter(model => {
      const pid = (model.sourceId || model.id?.split('/')[1] || '').toLowerCase();
      if (pid !== providerPart) return false;
      if (!modelPart) return true;
      const tgt = (model.targetId || '').toLowerCase();
      const name = displayNameForModel(model).toLowerCase();
      return tgt.includes(modelPart) || name.includes(modelPart);
    });
    const breadcrumb = `<div class="binding-provider-breadcrumb"><span class="binding-provider-crumb-name">${escapeHtml(query.slice(0, slashIdx))}/</span><span class="binding-provider-crumb-hint">type to filter models</span></div>`;
    resultsHtml = breadcrumb + (candidates.length
      ? candidates.slice(0, 50).map(model => _renderBindingModelResult(def, role, model, assignedId)).join('')
      : `<div class="binding-empty">No matching model for "${escapeHtml(providerPart)}" with the required capability.</div>`);
  } else {
    const q = query.trim().toLowerCase();
    const capable = modelsForRole(role);
    const providers = _providerSuggestionsForRole(role, q);
    const providerHtml = providers.length
      ? `<div class="binding-provider-chips">${providers.slice(0, 8).map(p =>
          `<button class="binding-provider-chip" onclick="setBindingSearch('${escapeHtml(def.id)}','${escapeHtml(role.key)}','${escapeHtml(p.id)}/');return false;">${escapeHtml(p.id)}<span class="binding-chip-count">${p.count}</span></button>`
        ).join('')}</div>`
      : '';
    const modelCandidates = q ? capable.filter(model => modelMatchesQuery(model, q)) : capable;
    const modelHtml = modelCandidates.length
      ? modelCandidates.slice(0, q ? 50 : 20).map(model => _renderBindingModelResult(def, role, model, assignedId)).join('')
      : '';
    const emptyHtml = !providerHtml && !modelHtml
      ? `<div class="binding-empty">${q ? 'No matching provider/model, rotation, or autoselect with the required capability.' : 'No models available with the required capability.'}</div>`
      : '';
    resultsHtml = providerHtml + modelHtml + emptyHtml;
  }

  const currentMeta = assignedModel
    ? `${escapeHtml(assignedModel.id)} · ${escapeHtml((role.capabilities || []).join(' or '))}`
    : `Needs ${escapeHtml((role.capabilities || []).join(' or '))}`;
  return `<div class="binding-role">
    <div class="binding-role-top">
      <div class="binding-role-label">${escapeHtml(role.label)}</div>
      <div class="binding-role-state">${assignedModel ? 'Bound' : (role.optional ? 'Optional' : 'Missing')}</div>
    </div>
    <div class="binding-role-meta">${currentMeta}</div>
    <input class="fi binding-role-search" type="search" data-search-key="${escapeHtml(searchKey)}" value="${escapeHtml(query)}" placeholder="Search provider/model, rotation, autoselect" oninput="updateBindingSearch('${def.id}','${role.key}', this.value)">
    <div class="binding-role-results">${resultsHtml}</div>
    ${assignedModel ? `<button class="btn btn-ghost btn-sm binding-role-clear" onclick="clearBindingRole('${def.id}','${role.key}');return false;">Clear</button>` : ''}
  </div>`;
}

function selectBindingCard(bindingId) {
  selectedBindingId = bindingId;
  renderSidebar();
}

function updateBindingSearch(bindingId, roleKey, value) {
  bindingSearchState[`${bindingId}:${roleKey}`] = value || '';
  renderSidebar();
}

async function saveBindingRole(bindingId, roleKey, encodedModelId) {
  const modelId = decodeURIComponent(encodedModelId || '');
  const roles = { ...(functionBindings[bindingId] || {}) };
  roles[roleKey] = modelId;
  const res = await dashboardFetch(buildBindingApiUrl(bindingId), {
    method:'PUT',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ roles }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  functionBindings = data.bindings || functionBindings;
  const model = models.find(item => item.id === modelId);
  if (model && (!activeModel || bindingId === 'chat' || selectedBindingId === bindingId)) {
    activeModel = model;
  }
  renderSidebar();
  renderCapabilityCards();
}

async function clearBindingRole(bindingId, roleKey) {
  const roles = { ...(functionBindings[bindingId] || {}) };
  delete roles[roleKey];
  const res = await dashboardFetch(buildBindingApiUrl(bindingId), {
    method:'PUT',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({ roles }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  functionBindings = data.bindings || functionBindings;
  ensureBindingSelection(bindingId);
  renderSidebar();
  renderCapabilityCards();
}

function selectModel(m) {
  activeModel = m;
  chatHistory = []; attachedImage = null; updateAttachBar();
  $('chat-msgs').innerHTML = `<div class=\"chat-empty\"><h3>${escapeHtml(m.name || m.id.split('/').pop())}</h3><p>${escapeHtml(m.description || 'Start below')}</p></div>`;
  updateRequestPreview('aud-gen');
  updateRequestPreview('aud-tts');
  updateRequestPreview('aud-stt');
  updateRequestPreview('img-gen');
  updateRequestPreview('embed');
  updateRequestPreview('aud-understand');
  updateRequestPreview('aud-music-dub');
  updateRequestPreview('aud-stems');
  updateRequestPreview('aud-clean');
  updateRequestPreview('vid-dub');
  // Update chat input placeholder to hint at routing for non-text models
  const PLACEHOLDER = {
    image: 'Describe an image to generate…',
    tts: 'Type text to speak…',
    audio: 'Use Audio → Transcribe to upload audio',
    video: 'Describe a video to generate…',
    audio_gen: 'Describe music or audio to generate…',
    embedding: 'Use the Embeddings tab',
  };
  $('chat-in').placeholder = PLACEHOLDER[m.type] || 'Send a message…';
  updateTabs(m);
}

function updateTabs(m) {
  const allCaps = crossModelCaps();
  const allTypes = new Set(models.map(mdl => mdl.type || 'text'));
  const type = m.type || 'text';
  refreshAudioBackendHealth();
  const subStates = {};
  Object.entries(SUB_CAPABILITY_RULES).forEach(([sub, rule]) => {
    if (VIDEO_EXTRA_SUBS.includes(sub) && allTypes.has('video') && !rule.fallbackTypes) {
      rule = Object.assign({}, rule, { fallbackTypes:['video'] });
    }
    subStates[sub] = evaluateSubCapability(rule, allCaps, allTypes);
  });
  // Profile subs are always available; route-limited backends stay partial unless wired server-side.
  ['prof-char', 'prof-env', 'prof-voice'].forEach(sub => { subStates[sub] = 'available'; });
  updatePipelineBadges();
  const categoryStates = {};
  CATEGORY_TABS.forEach(cat => {
    categoryStates[cat] = evaluateCategoryState(cat, subStates, allCaps, type);
  });
  currentTabState = { categories:categoryStates, subs:subStates };

  document.querySelectorAll('.t1btn').forEach(btn => {
    setTabVisualState(btn, categoryStates[btn.dataset.cat] || 'unavailable');
  });
  document.querySelectorAll('.t2btn').forEach(btn => {
    setTabVisualState(btn, subStates[btn.dataset.sub] || 'unavailable');
  });
  $('attach-btn').style.display = capabilitySetForModel(m).has('image_to_text') ? '' : 'none';
  renderCapabilityCards();
  renderDiagnostics();
  renderOutputCapabilityNotes();
  const activeCatBtn = document.querySelector('.t1btn.active');
  const nextCat = activeCatBtn?.dataset.cat || 'chat';
  selectCat(nextCat);
}

function selectCat(cat) {
  document.querySelectorAll('.t1btn').forEach(b => b.classList.toggle('active', b.dataset.cat === cat));
  const hasL2 = ['image','video','audio','3d','profiles'].includes(cat);
  $('tabbar2').classList.toggle('visible', hasL2);
  if (!hasL2) {
    clearSidebarHighlights();
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    const panel = $('panel-' + cat);
    if (panel) panel.classList.add('active');
    if (cat === 'archive') loadArchive();
    return;
  }
  document.querySelectorAll('.t2btn').forEach(btn => {
    const belongsHere = SUB_CAT[btn.dataset.sub] === cat;
    btn.dataset.catVisible = belongsHere ? cat : '';
    btn.classList.toggle('state-hidden', !belongsHere);
  });
  if (cat === 'profiles') { profCharLoad(); profEnvLoad(); profVoiceLoad(); }
  const activeSub = document.querySelector('.t2btn.active');
  const activeSubFits = activeSub && isSubVisibleForCategory(activeSub.dataset.sub, cat);
  const nextSub = activeSubFits ? activeSub.dataset.sub : getFirstVisibleSub(cat)?.dataset.sub;
  if (nextSub) selectSub(nextSub);
}

// Legacy transient per-capability model assignments retained for compatibility.
const capModelAssignments = {};

function modelsForCap(cap) {
  return models.filter(m => capabilitySetForModel(m).has(cap));
}

function modelsForSub(sub) {
  const rule = SUB_CAPABILITY_RULES[sub];
  if (!rule) return [];
  return models.map(m => {
    const caps = capabilitySetForModel(m);
    let state = evaluateSubCapability(rule, caps, m.type || 'text');
    if (state === 'unavailable' && rule.category === (m.type || 'text')) state = 'partial';
    return { model: m, state };
  }).filter(item => item.state !== 'unavailable');
}

function subNeedsMultiModel(sub) {
  const studioRule = STUDIO_CAPABILITIES[sub];
  if (!studioRule) return false;
  return (studioRule.requires || []).length > 1;
}

function renderCapRow(sub, cap, isOptional) {
  const capable = modelsForCap(cap);
  if (!capable.length) {
    if (isOptional) return '';
    return `<div class="cap-assign-row">
      <span class="cap-assign-label">${cap.replace(/_/g,' ')}</span>
      <span class="cap-chip dim">No model available</span>
    </div>`;
  }
  const assigned = capModelAssignments[sub]?.[cap];
  const chips = capable.map(m => {
    const isSelected = m.id === assigned;
    const label = escapeHtml(m.id.split('/').pop());
    const safe = JSON.stringify(m).replace(/"/g, '&quot;');
    return `<button class="cap-model-chip ok${isSelected ? ' active' : ''}" onclick="assignModelToCap('${sub}','${cap}',${safe})" title="${m.id}">${label}</button>`;
  }).join('');
  return `<div class="cap-assign-row${isOptional ? ' opt' : ''}">
    <span class="cap-assign-label">${cap.replace(/_/g,' ')}</span>
    <div class="cap-model-chips">${chips}</div>
  </div>`;
}

function renderMultiCapPicker(sub) {
  const studioRule = STUDIO_CAPABILITIES[sub];
  const required = studioRule?.requires || [];
  const optional  = studioRule?.optional  || [];
  const reqRows = required.map(c => renderCapRow(sub, c, false)).join('');
  const optRows = optional.map(c => renderCapRow(sub, c, true)).join('');
  const optSection = optRows
    ? `<div class="cap-assign-sep">Optional</div>${optRows}`
    : '';
  return `<div class="cap-model-picker multi">
    <span class="cap-model-picker-label">Models per role</span>
    <div class="cap-assign-rows">${reqRows}${optSection}</div>
  </div>`;
}

function renderSubModelPicker(sub) {
  const def = getBindingDefinition(sub);
  if (!def) return '';
  const summary = (def.roles || []).map(role => {
    const model = boundModelForRole(sub, role.key, null);
    const label = model ? displayNameForModel(model) : (role.optional ? 'optional' : 'missing');
    return `<span class="cap-model-chip ${model ? 'ok' : 'warn'}">${escapeHtml(role.label)}: ${escapeHtml(label)}</span>`;
  }).join('');
  return `<div class="cap-model-picker"><span class="cap-model-picker-label">Bindings</span><div class="cap-model-chips">${summary}</div></div>`;
}

function assignModelToCap(sub, cap, model) {
  if (!capModelAssignments[sub]) capModelAssignments[sub] = {};
  capModelAssignments[sub][cap] = model.id;
  // Sync left-panel selection only for single-cap subs; multi-cap subs have
  // independent per-role assignments that shouldn't overwrite the global model.
  if (!subNeedsMultiModel(sub)) {
    activeModel = model;
    document.querySelectorAll('.model-item').forEach(el =>
      el.classList.toggle('active', el.dataset.id === model.id));
  }
  renderCapabilityCards();
  if (SUB_CAT[sub]) highlightSidebarForSub(sub);
}

// Returns the user-assigned model ID for a capability, or falls back to activeModel.
function getAssignedModelId(sub, cap) {
  if (capModelAssignments[sub]?.[cap]) return capModelAssignments[sub][cap];
  const def = getBindingDefinition(sub);
  if (def) {
    const role = (def.roles || []).find(item => (item.capabilities || []).includes(cap)) || def.roles?.[0];
    if (role) return boundModelId(sub, role.key, activeModel);
  }
  return activeModel?.id || '';
}

// Returns the ModelInfo object for the best model to use for a single capability.
// Prefers models with load_mode:'load' (already resident), then smallest used_vram_gb.
function bestModelForCap(cap) {
  return modelsForCap(cap).slice().sort((a, b) => {
    const al = a.load_mode === 'load' ? 0 : 1;
    const bl = b.load_mode === 'load' ? 0 : 1;
    if (al !== bl) return al - bl;
    return (a.used_vram_gb || 99) - (b.used_vram_gb || 99);
  })[0] || null;
}

// Primary capability per sub-tab — used for single-cap model assignment and API calls.
const SUB_API_CAP = {
  'img-gen':      'image_generation',
  'img-edit':     'image_to_image',
  'img-inpaint':  'inpainting',
  'img-upscale':  'image_upscaling',
  'img-depth':    'depth_estimation',
  'img-seg':      'image_segmentation',
  'img-outfit':   'image_to_image',
  'vid-t2v':      'video_generation',
  'vid-i2v':      'image_to_video',
  'vid-v2v':      'video_to_video',
  'vid-ti2v':     'video_generation',
  'vid-interp':   'video_interpolation',
  'vid-sub':      'subtitle_generation',
  'vid-up':       'video_upscaling',
  'aud-gen':      'audio_generation',
  'aud-tts':      'text_to_speech',
  'aud-clone':    'text_to_speech',
  'aud-convert':  'speech_to_text',
  'aud-stt':      'speech_to_text',
  'aud-understand':'speech_to_text',
  'aud-music-dub':'speech_to_text',
  'embed':        'embeddings',
};

// Returns the model ID to use for a sub-tab operation.
// Prefers the user-assigned model, falls back to activeModel.
function modelForSub(sub) {
  const def = getBindingDefinition(sub);
  if (def?.roles?.length) return boundModelId(sub, def.roles[0].key, activeModel);
  const cap = SUB_API_CAP[sub];
  if (cap && capModelAssignments[sub]?.[cap]) return capModelAssignments[sub][cap];
  return activeModel?.id || '';
}

// Assigns a model to a single-cap sub without changing the global activeModel.
function selectSubModel(sub, model) {
  const cap = SUB_API_CAP[sub]
    || (STUDIO_CAPABILITIES[sub]?.requires || SUB_CAPABILITY_RULES[sub]?.requiresAny || [])[0]
    || '__default__';
  assignModelToCap(sub, cap, model);
}

// Auto-assigns the best VRAM-fitting model to each capability for any sub.
// Existing manual assignments are never overwritten.
function autoAssignModels(sub) {
  const studioRule = STUDIO_CAPABILITIES[sub];
  if (subNeedsMultiModel(sub)) {
    const caps = [...(studioRule?.requires || []), ...(studioRule?.optional || [])];
    caps.forEach(cap => {
      if (capModelAssignments[sub]?.[cap]) return;
      const best = bestModelForCap(cap);
      if (best) { if (!capModelAssignments[sub]) capModelAssignments[sub] = {}; capModelAssignments[sub][cap] = best.id; }
    });
  } else {
    const cap = SUB_API_CAP[sub];
    if (cap && !capModelAssignments[sub]?.[cap]) {
      const best = bestModelForCap(cap);
      if (best) { if (!capModelAssignments[sub]) capModelAssignments[sub] = {}; capModelAssignments[sub][cap] = best.id; }
    }
  }
}

// Auto-populates empty pipeline form inputs with the best available model for each role.
const PIPELINE_INPUT_CAP = {
  'pp1-imodel': 'image_generation',
  'pp1-vmodel': 'image_to_video',
  'pp2-model':  'speech_to_text',
  'pp3-amodel': 'text_to_speech',
};
function autoPopulatePipelineInputs() {
  Object.entries(PIPELINE_INPUT_CAP).forEach(([inputId, cap]) => {
    const el = $(inputId);
    if (!el || el.value) return; // don't overwrite user input
    const best = bestModelForCap(cap);
    if (best) el.value = best.id;
  });
}

function highlightSidebarForSub(sub) {
  if (subNeedsMultiModel(sub)) {
    // Highlight every model that covers any required capability
    const required = (STUDIO_CAPABILITIES[sub]?.requires || []);
    const capable = new Set();
    required.forEach(cap => modelsForCap(cap).forEach(m => capable.add(m.id)));
    document.querySelectorAll('.model-item').forEach(el => {
      el.classList.remove('cap-ok', 'cap-partial');
      if (capable.has(el.dataset.id)) el.classList.add('cap-ok');
    });
    return;
  }
  const compatible = new Map(modelsForSub(sub).map(({ model, state }) => [model.id, state]));
  document.querySelectorAll('.model-item').forEach(el => {
    el.classList.remove('cap-ok', 'cap-partial');
    const state = compatible.get(el.dataset.id);
    if (state === 'available') el.classList.add('cap-ok');
    else if (state === 'partial') el.classList.add('cap-partial');
  });
}

function clearSidebarHighlights() {
  document.querySelectorAll('.model-item').forEach(el => el.classList.remove('cap-ok', 'cap-partial'));
}

function selectSub(sub) {
  if (SUB_CAT[sub] && currentTabState.subs[sub] === undefined) return;
  if (SUB_CAT[sub]) {
    const parentCat = SUB_CAT[sub];
    const belongsToActiveCat = document.querySelector(`.t1btn.active`)?.dataset.cat === parentCat;
    const btn = document.querySelector(`.t2btn[data-sub="${sub}"]`);
    if (!belongsToActiveCat || !btn || btn.classList.contains('state-hidden')) return;
  }
  document.querySelectorAll('.t2btn').forEach(b => b.classList.toggle('active', b.dataset.sub === sub));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  const panelId = SUB_PANEL_ALIAS[sub] || ('panel-' + sub);
  const panel = $(panelId);
  if (panel) panel.classList.add('active');
  renderCapabilityOutputNote(sub);
  // When switching to vid-faceswap, pre-select video mode
  if (sub === 'vid-faceswap') { const t = $('fs-type'); if (t) { t.value='video'; fsFaceSwapTypeChange(); } }
  if (sub === 'vid-outfit')   { const t = $('ot-type'); if (t) { t.value='video'; otOutfitTypeChange(); } }
  // Toggle shared cap-cards on faceswap and outfit panels
  if (sub === 'vid-faceswap' || sub === 'img-faceswap') {
    const isVid = sub === 'vid-faceswap';
    const ic = $('cap-img-faceswap'), vc = $('cap-vid-faceswap');
    if (ic) ic.style.display = isVid ? 'none' : '';
    if (vc) vc.style.display = isVid ? '' : 'none';
  }
  if (sub === 'vid-outfit' || sub === 'img-outfit') {
    const isVid = sub === 'vid-outfit';
    const ic = $('cap-img-outfit'), vc = $('cap-vid-outfit');
    if (ic) ic.style.display = isVid ? 'none' : '';
    if (vc) vc.style.display = isVid ? '' : 'none';
  }
  if (getBindingDefinition(sub)) {
    selectedBindingId = sub;
    renderSidebar();
  }
  if (SUB_CAT[sub]) { autoAssignModels(sub); highlightSidebarForSub(sub); }
}

// ─────────────────────────────────────────────────────────────────
//  Chat
// ─────────────────────────────────────────────────────────────────
function addMsg(role, text, imgSrc) {
  const wrap = $('chat-msgs');
  wrap.querySelector('.chat-empty')?.remove();
  const t = new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  const name = role === 'user' ? 'You' : (activeModel?.id?.split('/').pop() || 'AI');
  d.innerHTML = `<div class="av ${role==='user'?'user':'ai'}">${role==='user'?'YOU':'AI'}</div>
    <div class="msg-body">
      <div class="msg-meta">${name} · ${t}</div>
      ${imgSrc ? `<img src="${imgSrc}" class="msg-img" onclick="window.open(this.src)">` : ''}
      <div class="msg-text">${String(text).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>')}</div>
    </div>`;
  wrap.appendChild(d);
  wrap.scrollTop = wrap.scrollHeight;
}

function attachImg(input) {
  const f = input.files[0]; if (!f) return;
  const r = new FileReader();
  r.onload = e => {
    attachedImage = e.target.result;
    $('attach-thumb').src = attachedImage;
    $('attach-name').textContent = f.name;
    updateAttachBar();
  };
  r.readAsDataURL(f);
}
function clearAttach() { attachedImage = null; updateAttachBar(); }
function updateAttachBar() { $('attach-bar').style.display = attachedImage ? 'flex' : 'none'; }

async function sendChat() {
  const chatModel = boundModelForRole('chat', 'model', activeModel);
  if (chatBusy || !chatModel) return;
  const input = $('chat-in');
  const text = input.value.trim(); if (!text) return;

  // Route non-text models to the correct endpoint instead of /v1/chat/completions
  const mtype = chatModel.type || 'text';
  if (mtype === 'image') {
    input.value = '';
    // Switch to image-gen tab and pre-fill prompt
    $('ig-prompt').value = text;
    document.querySelector('.t1btn[data-cat="image"]')?.click();
    document.querySelector('.t2btn[data-sub="img-gen"]')?.click();
    await genImage();
    return;
  }
  if (mtype === 'tts') {
    input.value = '';
    $('at-text').value = text;
    document.querySelector('.t1btn[data-cat="audio"]')?.click();
    document.querySelector('.t2btn[data-sub="aud-tts"]')?.click();
    await genTTS();
    return;
  }
  if (mtype === 'audio') {
    addMsg('assistant', 'This is a speech-to-text model. Use the Audio → Transcribe tab to upload audio.');
    return;
  }
  if (mtype === 'video') {
    input.value = '';
    $('vt-prompt').value = text;
    document.querySelector('.t1btn[data-cat="video"]')?.click();
    document.querySelector('.t2btn[data-sub="vid-t2v"]')?.click();
    await genVideoT2V();
    return;
  }
  if (mtype === 'audio_gen') {
    input.value = '';
    $('ag-prompt').value = text;
    document.querySelector('.t1btn[data-cat="audio"]')?.click();
    document.querySelector('.t2btn[data-sub="aud-gen"]')?.click();
    await genAudio();
    return;
  }
  if (mtype === 'embedding') {
    addMsg('assistant', 'This is an embedding model. Use the Embeddings tab.');
    return;
  }

  addMsg('user', text, attachedImage);
  let content = text;
  if (attachedImage && (chatModel.capabilities||[]).includes('image_to_text')) {
    content = [{type:'image_url',image_url:{url:attachedImage}},{type:'text',text}];
  }
  chatHistory.push({role:'user',content});
  input.value = ''; input.style.height = 'auto';
  attachedImage = null; updateAttachBar();
  chatBusy = true; $('send-btn').disabled = true;
  $('typing').textContent = 'Thinking…';
  const _chatT0 = Date.now();
  try {
    const messages = STUDIO_SYSTEM_PROMPT
      ? [{role:'system', content:STUDIO_SYSTEM_PROMPT}, ...chatHistory]
      : chatHistory;
    const r = await dashboardFetch(buildStudioUrl('/chat/completions'),{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({model:chatModel.id,messages,stream:false})
    });
    if (!r.ok) throw new Error('HTTP '+r.status+': '+await r.text());
    const d = await r.json();
    const reply = d.choices[0].message.content;
    const elapsed = (Date.now() - _chatT0) / 1000;
    const toks = d.usage?.completion_tokens;
    if (toks && elapsed > 0) {
      $('typing').textContent = `${toks} tok · ${(toks/elapsed).toFixed(1)} tok/s`;
    }
    addMsg('assistant',reply);
    chatHistory.push({role:'assistant',content:reply});
  } catch(e) { addMsg('assistant','Error: '+e.message); }
  finally { chatBusy=false; $('send-btn').disabled=false; setTimeout(()=>{ $('typing').textContent=''; }, 3000); }
}

$('chat-in').addEventListener('keydown', e => { if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat();} });
$('chat-in').addEventListener('input', function(){ this.style.height='auto'; this.style.height=Math.min(this.scrollHeight,140)+'px'; });

// ─────────────────────────────────────────────────────────────────
//  Utilities
// ─────────────────────────────────────────────────────────────────
function fileToB64(file) {
  return new Promise((res,rej) => {
    const r = new FileReader();
    r.onload = e => res(e.target.result);
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}
function fileOrNull(id) { const f=$(id); return f&&f.files[0] ? f.files[0] : null; }
async function b64OrNull(id) { const f=fileOrNull(id); return f ? await fileToB64(f) : null; }

function showImg(outId, src, prog) {
  $(outId).innerHTML = `<div class="gen-out-inner">
    <img class="out-img" src="${src}" onclick="window.open(this.src)">
    <a href="${src}" download class="btn btn-ghost btn-sm dl">Download</a>
  </div>`;
  if(prog) $(prog).textContent='Done ✓';
}
function showVideo(outId, src, prog) {
  $(outId).innerHTML = `<div class="gen-out-inner">
    <video class="out-video" controls src="${src}"></video>
    <a href="${src}" download class="btn btn-ghost btn-sm dl">Download</a>
  </div>`;
  if(prog) $(prog).textContent='Done ✓';
}
function showAudio(outId, src, prog, ext) {
  $(outId).innerHTML = `<div class="gen-out-inner" style="width:100%">
    <audio class="out-audio" controls src="${src}"></audio>
    <a href="${src}" download="audio.${ext||'wav'}" class="btn btn-ghost btn-sm dl">Download</a>
  </div>`;
  if(prog) $(prog).textContent='Done ✓';
}
function imgSrc(d) { return d.url || (d.b64_json ? 'data:image/png;base64,'+d.b64_json : null); }
function vidSrc(d) { return d.url || (d.b64_mp4 ? 'data:video/mp4;base64,'+d.b64_mp4 : null); }
function audSrc(d) {
  if (d.url) return d.url;
  for (const k of Object.keys(d)) { if(k.startsWith('b64_')) return 'data:audio/'+k.slice(4)+';base64,'+d[k]; }
  return null;
}

async function post(path, body) {
  if (isUnsupportedStudioPath(path)) throw unsupportedError(path);
  const r = await dashboardFetch(buildStudioUrl(path), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function postForm(path, fd) {
  if (isUnsupportedStudioPath(path)) throw unsupportedError(path);
  const r = await dashboardFetch(buildStudioUrl(path), {method:'POST', body:fd});
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// Character reference helpers
// ─────────────────────────────────────────────────────────────────
//  Character consistency — named multi-slot system
// ─────────────────────────────────────────────────────────────────
async function loadCharProfileList() {
  try {
    const d = await dashboardFetch(buildStudioUrl('/characters')).then(r => r.json());
    _charProfiles = d.characters || [];
  } catch(e) { _charProfiles = []; }
}

function _profileOptions(selectedName) {
  const base = `<option value="">Load profile…</option>`;
  return base + _charProfiles.map(p =>
    `<option value="${p.name}" ${p.name===selectedName?'selected':''}>${p.name}</option>`
  ).join('');
}

function renderCharSlots(prefix) {
  const container = $(prefix+'-char-slots');
  if (!container) return;
  if (!charSlots[prefix]) charSlots[prefix] = [];
  if (!charSlots[prefix].length) { container.innerHTML = ''; return; }
  container.innerHTML = charSlots[prefix].map((slot, idx) => `
    <div class="char-slot" id="${prefix}-slot-${idx}">
      <div class="char-slot-header">
        <input type="text" class="fi" style="flex:1;font-size:12px" placeholder="Character name (e.g. Alice)"
          value="${slot.name||''}" onchange="charSlots['${prefix}'][${idx}].name=this.value">
        <button class="btn btn-ghost btn-sm" style="color:var(--red);padding:.1rem .35rem" onclick="removeCharSlot('${prefix}',${idx})">✕</button>
      </div>
      <div class="char-slot-actions">
        <input type="file" accept="image/*" multiple class="fi" style="flex:1;font-size:11px"
          onchange="addCharSlotImages('${prefix}',${idx},this)">
        <select class="fselect" style="font-size:11px;max-width:130px"
          onchange="if(this.value)loadCharProfileIntoSlot('${prefix}',${idx},this.value);this.value=''">
          ${_profileOptions('')}
        </select>
        <button class="btn btn-ghost btn-sm" style="font-size:11px" onclick="saveCharSlotAsProfile('${prefix}',${idx})">Save</button>
      </div>
      <div class="char-refs" id="${prefix}-slot-thumbs-${idx}">
        ${slot.images.map((src,i)=>`<img class="char-thumb" src="${src}" title="Click to remove" onclick="removeCharSlotImage('${prefix}',${idx},${i})">`).join('')}
      </div>
    </div>`).join('');
}

function addCharSlot(prefix) {
  if (!charSlots[prefix]) charSlots[prefix] = [];
  charSlots[prefix].push({name:'', images:[]});
  renderCharSlots(prefix);
}

function removeCharSlot(prefix, idx) {
  charSlots[prefix].splice(idx, 1);
  renderCharSlots(prefix);
}

function addCharSlotImages(prefix, idx, input) {
  if (!charSlots[prefix]?.[idx]) return;
  Array.from(input.files).forEach(f => {
    const reader = new FileReader();
    reader.onload = e => {
      charSlots[prefix][idx].images.push(e.target.result);
      renderCharSlots(prefix);
    };
    reader.readAsDataURL(f);
  });
}

function removeCharSlotImage(prefix, idx, imgIdx) {
  charSlots[prefix]?.[idx]?.images.splice(imgIdx, 1);
  renderCharSlots(prefix);
}

async function loadCharProfileIntoSlot(prefix, idx, name) {
  try {
    const d = await dashboardFetch(buildStudioUrl(`/characters/${encodeURIComponent(name)}`)).then(r => r.json());
    if (!charSlots[prefix]?.[idx]) return;
    charSlots[prefix][idx].name = charSlots[prefix][idx].name || d.name;
    charSlots[prefix][idx].images = (d.images||[]).map(img => img.data);
    renderCharSlots(prefix);
  } catch(e) { alert('Failed to load profile: '+e.message); }
}

async function saveCharSlotAsProfile(prefix, idx) {
  const slot = charSlots[prefix]?.[idx];
  if (!slot || !slot.images.length) { alert('Add at least one image first.'); return; }
  const name = slot.name || prompt('Profile name:');
  if (!name) return;
  try {
    const r = await dashboardFetch(buildStudioUrl('/characters/extract'), {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
      name,
      description: '',
      images: slot.images,
      })
    });
    if (!r.ok) throw new Error(await r.text());
    charSlots[prefix][idx].name = name;
    await loadCharProfileList();
    renderCharSlots(prefix);
    alert(`Saved profile "${name}"`);
  } catch(e) { alert('Save failed: '+e.message); }
}

// ─────────────────────────────────────────────────────────────────
//  Saved character profile multi-slot system (up to 6 per panel)
// ─────────────────────────────────────────────────────────────────
const MAX_CHAR_PROFILES = 6;

function _charProfileOpts() {
  return '<option value="">— select profile —</option>' +
    _charProfiles.map(p =>
      `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}${p.description ? ' — ' + escapeHtml(p.description) : ''}</option>`
    ).join('');
}

function addCharProfileSlot(prefix) {
  const container = $(`${prefix}-char-profile-slots`);
  if (!container) return;
  const rows = container.querySelectorAll('.char-prof-row');
  if (rows.length >= MAX_CHAR_PROFILES) return;
  const row = document.createElement('div');
  row.className = 'frow char-prof-row';
  row.style.cssText = 'gap:.3rem;margin:.1rem 0';
  row.innerHTML =
    `<select class="fi char-prof-sel" data-prefix="${prefix}" style="flex:1">${_charProfileOpts()}</select>` +
    `<button class="btn btn-ghost btn-sm" onclick="removeCharProfileSlot('${prefix}',this)" ` +
    `style="padding:.15rem .45rem;font-size:12px;flex-shrink:0">✕</button>`;
  container.appendChild(row);
  _updateAddCharBtn(prefix);
}

function removeCharProfileSlot(prefix, btn) {
  btn.closest('.char-prof-row')?.remove();
  _updateAddCharBtn(prefix);
}

function _updateAddCharBtn(prefix) {
  const container = $(`${prefix}-char-profile-slots`);
  const btn = $(`${prefix}-add-char-btn`);
  if (!container || !btn) return;
  btn.disabled = container.querySelectorAll('.char-prof-row').length >= MAX_CHAR_PROFILES;
}

function getCharProfilesList(prefix) {
  const container = $(`${prefix}-char-profile-slots`);
  if (!container) return [];
  return Array.from(container.querySelectorAll('.char-prof-sel'))
    .map(s => s.value).filter(Boolean);
}

function initCharProfileSlots() {
  ['ig','vt','vi','vv','ti'].forEach(prefix => {
    const container = $(`${prefix}-char-profile-slots`);
    if (container && container.querySelectorAll('.char-prof-row').length === 0) {
      addCharProfileSlot(prefix);
    }
  });
}

// ─────────────────────────────────────────────────────────────────
//  Environment profile multi-slot system (up to 6 per panel)
// ─────────────────────────────────────────────────────────────────
let _envProfiles = [];   // cached list from /v1/environments

function _envProfileOpts() {
  return '<option value="">— select environment —</option>' +
    _envProfiles.map(p =>
      `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}${p.description ? ' — ' + escapeHtml(p.description) : ''}</option>`
    ).join('');
}

function addEnvProfileSlot(prefix) {
  const container = $(`${prefix}-env-profile-slots`);
  if (!container) return;
  const rows = container.querySelectorAll('.env-prof-row');
  if (rows.length >= MAX_CHAR_PROFILES) return;
  const row = document.createElement('div');
  row.className = 'frow env-prof-row';
  row.style.cssText = 'gap:.3rem;margin:.1rem 0';
  row.innerHTML =
    `<select class="fi env-prof-sel" data-prefix="${prefix}" style="flex:1">${_envProfileOpts()}</select>` +
    `<button class="btn btn-ghost btn-sm" onclick="removeEnvProfileSlot('${prefix}',this)" ` +
    `style="padding:.15rem .45rem;font-size:12px;flex-shrink:0">✕</button>`;
  container.appendChild(row);
  _updateAddEnvBtn(prefix);
}

function removeEnvProfileSlot(prefix, btn) {
  btn.closest('.env-prof-row')?.remove();
  _updateAddEnvBtn(prefix);
}

function _updateAddEnvBtn(prefix) {
  const container = $(`${prefix}-env-profile-slots`);
  const btn = $(`${prefix}-add-env-btn`);
  if (!container || !btn) return;
  btn.disabled = container.querySelectorAll('.env-prof-row').length >= MAX_CHAR_PROFILES;
}

function getEnvProfilesList(prefix) {
  const container = $(`${prefix}-env-profile-slots`);
  if (!container) return [];
  return Array.from(container.querySelectorAll('.env-prof-sel'))
    .map(s => s.value).filter(Boolean);
}

function refreshEnvSelectors() {
  const opts = _envProfileOpts();
  document.querySelectorAll('.env-prof-sel').forEach(sel => {
    const cur = sel.value;
    sel.innerHTML = opts;
    if (cur) sel.value = cur;
  });
}

function initEnvProfileSlots() {
  ['ig','vt','vi','vv','ti'].forEach(prefix => {
    const container = $(`${prefix}-env-profile-slots`);
    if (container && container.querySelectorAll('.env-prof-row').length === 0) {
      addEnvProfileSlot(prefix);
    }
  });
}

function buildCharactersPayload(prefix) {
  const slots = charSlots[prefix] || [];
  const valid = slots.filter(s => s.images.length > 0);
  if (!valid.length) return undefined;
  return valid.map(s => ({name: s.name || undefined, images: s.images}));
}

// ─────────────────────────────────────────────────────────────────
//  Character Dialog
// ─────────────────────────────────────────────────────────────────
const MAX_DIALOG_LINES = 6;

function _dialogCharOpts() {
  return '<option value="">— No character —</option>' +
    (_charProfiles||[]).map(p=>`<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join('');
}

function _dialogVoiceOpts() {
  return '<option value="">— TTS voice ID below —</option>' +
    (_voiceProfiles||[]).map(v=>`<option value="${escapeHtml(v.name)}">${escapeHtml(v.name)}${v.description?' — '+escapeHtml(v.description):''}</option>`).join('');
}

function _dialogSectionHtml(prefix) {
  return `<details style="margin-top:.25rem">
  <summary style="font-size:12px;font-weight:600;cursor:pointer;color:var(--text-2)">Character Dialog</summary>
  <div style="margin-top:.5rem;display:flex;flex-direction:column;gap:.5rem">
    <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap;font-size:12px">
      <label style="display:flex;align-items:center;gap:.3rem">Timing:
        <select id="${prefix}-dlg-timing" class="fselect" style="font-size:12px" onchange="refreshDialogTiming('${prefix}')">
          <option value="sequential">Sequential</option>
          <option value="manual">Manual</option>
        </select>
      </label>
      <label style="display:flex;align-items:center;gap:.3rem">Lip sync:
        <select id="${prefix}-dlg-method" class="fselect" style="font-size:12px">
          <option value="wav2lip">Wav2Lip</option>
          <option value="sadtalker">SadTalker</option>
          <option value="">Disabled</option>
        </select>
      </label>
    </div>
    <div id="${prefix}-dialog-slots" style="display:flex;flex-direction:column;gap:.4rem"></div>
    <button class="btn btn-ghost btn-sm" id="${prefix}-add-dlg-btn" onclick="addDialogLine('${prefix}')" style="align-self:flex-start;font-size:11px">+ Add line</button>
  </div>
</details>`;
}

function addDialogLine(prefix) {
  const container = document.getElementById(`${prefix}-dialog-slots`);
  if (!container) return;
  if (container.querySelectorAll('.dlg-row').length >= MAX_DIALOG_LINES) return;
  const row = document.createElement('div');
  row.className = 'dlg-row';
  row.style.cssText = 'background:var(--surface-2);border-radius:6px;padding:.5rem;display:flex;flex-direction:column;gap:.3rem';
  const timing = (document.getElementById(`${prefix}-dlg-timing`)||{}).value||'sequential';
  row.innerHTML = `
    <div style="display:flex;gap:.3rem;align-items:center">
      <select class="fi dlg-char" style="flex:1;font-size:12px" title="Character profile (for lip sync)">${_dialogCharOpts()}</select>
      <select class="fi dlg-voice" style="flex:1;font-size:12px" title="Voice profile">${_dialogVoiceOpts()}</select>
      <button class="btn btn-ghost btn-sm" onclick="removeDialogLine('${prefix}',this)" style="flex-shrink:0;padding:0 .4rem;font-size:13px" title="Remove line">✕</button>
    </div>
    <textarea class="fs dlg-text" rows="2" placeholder="Spoken text for this character…" style="font-size:12px;resize:vertical"></textarea>
    <div style="display:flex;gap:.8rem;align-items:center;flex-wrap:wrap;font-size:12px">
      <input class="fi dlg-voice-id" placeholder="TTS voice ID (if no profile)" style="flex:1;min-width:6rem;font-size:12px">
      <label style="display:flex;align-items:center;gap:.3rem;white-space:nowrap"><input type="checkbox" class="dlg-lipsync" checked> Lip sync</label>
      <label class="dlg-starttime-wrap" style="display:${timing==='manual'?'flex':'none'};align-items:center;gap:.3rem;white-space:nowrap">
        Start (s): <input type="number" class="fi dlg-starttime" style="width:5rem;font-size:12px" min="0" step="0.1" placeholder="auto">
      </label>
    </div>`;
  container.appendChild(row);
  const addBtn = document.getElementById(`${prefix}-add-dlg-btn`);
  if (addBtn) addBtn.disabled = container.querySelectorAll('.dlg-row').length >= MAX_DIALOG_LINES;
}

function removeDialogLine(prefix, btn) {
  const row = btn.closest('.dlg-row');
  if (row) row.remove();
  const addBtn = document.getElementById(`${prefix}-add-dlg-btn`);
  if (addBtn) addBtn.disabled = false;
}

function refreshDialogTiming(prefix) {
  const timing = (document.getElementById(`${prefix}-dlg-timing`)||{}).value||'sequential';
  const container = document.getElementById(`${prefix}-dialog-slots`);
  if (!container) return;
  container.querySelectorAll('.dlg-starttime-wrap').forEach(el => {
    el.style.display = timing === 'manual' ? 'flex' : 'none';
  });
}

function getDialogLines(prefix) {
  const container = document.getElementById(`${prefix}-dialog-slots`);
  if (!container) return [];
  const lines = [];
  container.querySelectorAll('.dlg-row').forEach(row => {
    const text = (row.querySelector('.dlg-text')||{}).value||'';
    if (!text.trim()) return;
    const charSel = row.querySelector('.dlg-char');
    const voiceSel = row.querySelector('.dlg-voice');
    const voiceId = (row.querySelector('.dlg-voice-id')||{}).value||'';
    const lipsync = (row.querySelector('.dlg-lipsync')||{}).checked !== false;
    const startEl = row.querySelector('.dlg-starttime');
    const startVal = startEl && startEl.value !== '' ? parseFloat(startEl.value) : null;
    lines.push({
      text,
      character: (charSel && charSel.value) || undefined,
      voice: (voiceSel && voiceSel.value) || voiceId || undefined,
      lip_sync: lipsync,
      start_time: startVal,
    });
  });
  return lines;
}

function refreshDialogSelects() {
  const charOpts = _dialogCharOpts();
  const voiceOpts = _dialogVoiceOpts();
  document.querySelectorAll('.dlg-char').forEach(sel => {
    const cur = sel.value; sel.innerHTML = charOpts; if (cur) sel.value = cur;
  });
  document.querySelectorAll('.dlg-voice').forEach(sel => {
    const cur = sel.value; sel.innerHTML = voiceOpts; if (cur) sel.value = cur;
  });
}

// ─────────────────────────────────────────────────────────────────
//  Image Generation
// ─────────────────────────────────────────────────────────────────
async function genImage() {
  if (!activeModel) return;
  // Cancel any previous orphaned poll timer
  if (_imgPollTimer) { clearInterval(_imgPollTimer); _imgPollTimer = null; }
  $('ig-prog').textContent='Generating…';
  const wrap=$('ig-pbar-wrap'), fill=$('ig-pbar-fill'), lbl=$('ig-pbar-label');
  wrap.classList.add('active'); fill.style.width='0%'; lbl.textContent='';
  $('ig-prog').scrollIntoView({behavior:'smooth', block:'nearest'});
  _imgPollTimer = setInterval(async()=>{
    try{
      const p=await (await dashboardFetch(buildStudioUrl('/images/progress'))).json();
      if(p.total>0){
        fill.style.width=p.pct+'%';
        const spd = p.it_per_s>0 ? ` · ${p.it_per_s} it/s` : (p.elapsed>0 ? ` · ${p.elapsed}s` : '');
        lbl.textContent=`${p.current} / ${p.total} steps${spd}`;
      }
      if(!p.active){ clearInterval(_imgPollTimer); _imgPollTimer=null; }
    }catch(_){}
  },400);
  try {
    const igCharProfiles = getCharProfilesList('ig');
    const igEnvProfiles = getEnvProfilesList('ig');
    const d = await post('/v1/images/generations', {
      model:modelForSub('img-gen'), prompt:val('ig-prompt'),
      size:val('ig-w')+'x'+val('ig-h'),
      steps:ival('ig-steps'), guidance_scale:fval('ig-cfg'),
      n:ival('ig-n')||1,
      ...(val('ig-seed') ? {seed:ival('ig-seed')} : {}),
      ...(val('ig-neg') ? {negative_prompt:val('ig-neg')} : {}),
      disable_safety_checker: chk('ig-nosafe'),
      response_format:'url',
      ...(igCharProfiles.length ? {character_profiles:igCharProfiles, character_strength:fval('ig-char-str')||0.6} : {}),
      ...(igEnvProfiles.length ? {environment_profiles:igEnvProfiles, environment_strength:fval('ig-env-str')||0.6} : {}),
    });
    clearInterval(_imgPollTimer); _imgPollTimer=null;
    fill.style.width='100%'; lbl.textContent='Done';
    const imgs = d.data.map(imgSrc).filter(Boolean);
    $('ig-out').innerHTML = `<div class="gen-out-inner">${
      imgs.map(s=>`<img class="out-img" src="${s}" onclick="window.open(this.src)">`).join('')
    }<a href="${imgs[0]}" download class="btn btn-ghost btn-sm dl">Download first</a></div>`;
    pushArtifactHistory({
      task:'Image generate',
      family:'image generation',
      model:modelForSub('img-gen'),
      summary:buildImageHistorySummary(imgs),
      links:buildImageLinks(imgs),
    });
    $('ig-prog').textContent='Done ✓';
    setTimeout(()=>{ wrap.classList.remove('active'); },2000);
  } catch(e) {
    clearInterval(_imgPollTimer); _imgPollTimer=null;
    wrap.classList.remove('active');
    $('ig-prog').textContent='Error: '+e.message;
  }
}

// ─────────────────────────────────────────────────────────────────
//  Image Edit (i2i)
// ─────────────────────────────────────────────────────────────────
async function genEdit() {
  if (!activeModel) return;
  const img = await b64OrNull('ie-src');
  if (!img) { $('ie-prog').textContent='Select a source image.'; return; }
  $('ie-prog').textContent='Editing…';
  try {
    const d = await post('/v1/images/edits', {
      model:modelForSub('img-edit'), prompt:val('ie-prompt'), image:img,
      strength:fval('ie-str'), steps:ival('ie-steps'), guidance_scale:fval('ie-cfg'),
      ...(val('ie-seed') ? {seed:ival('ie-seed')} : {}), response_format:'url',
    });
    showImg('ie-out', imgSrc(d.data[0]), 'ie-prog');
  } catch(e) { $('ie-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Inpaint
// ─────────────────────────────────────────────────────────────────
async function genInpaint() {
  if (!activeModel) return;
  const [img, mask] = await Promise.all([b64OrNull('ip-src'), b64OrNull('ip-mask')]);
  if (!img||!mask) { $('ip-prog').textContent='Select source image and mask.'; return; }
  $('ip-prog').textContent='Inpainting…';
  try {
    const d = await post('/v1/images/inpaint', {
      model:modelForSub('img-inpaint'), prompt:val('ip-prompt'), image:img, mask,
      strength:fval('ip-str'), steps:ival('ip-steps'), guidance_scale:fval('ip-cfg'),
      ...(val('ip-seed') ? {seed:ival('ip-seed')} : {}), response_format:'url',
    });
    showImg('ip-out', imgSrc(d.data[0]), 'ip-prog');
  } catch(e) { $('ip-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Image Upscale
// ─────────────────────────────────────────────────────────────────
async function genImgUpscale() {
  if (!activeModel) return;
  const img = await b64OrNull('iu-src');
  if (!img) { $('iu-prog').textContent='Select an image.'; return; }
  $('iu-prog').textContent='Upscaling…';
  try {
    const d = await post('/v1/images/upscale', {model:modelForSub('img-upscale'), image:img, scale:ival('iu-scale'), response_format:'url'});
    showImg('iu-out', imgSrc(d.data[0]), 'iu-prog');
  } catch(e) { $('iu-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Depth
// ─────────────────────────────────────────────────────────────────
async function genDepth() {
  if (!activeModel) return;
  const img = await b64OrNull('id-src');
  if (!img) { $('id-prog').textContent='Select an image.'; return; }
  $('id-prog').textContent='Estimating depth…';
  try {
    const d = await post('/v1/images/depth', {model:modelForSub('img-depth'), image:img, response_format:'url'});
    showImg('id-out', imgSrc(d.data[0]), 'id-prog');
  } catch(e) { $('id-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Segment
// ─────────────────────────────────────────────────────────────────
async function genSegment() {
  if (!activeModel) return;
  const img = await b64OrNull('is-src');
  if (!img) { $('is-prog').textContent='Select an image.'; return; }
  $('is-prog').textContent='Segmenting…';
  const pts = val('is-pts') ? JSON.parse(val('is-pts')) : null;
  const boxes = val('is-boxes') ? JSON.parse(val('is-boxes')) : null;
  try {
    const d = await post('/v1/images/segment', {model:modelForSub('img-seg'), image:img, points:pts, boxes, response_format:'url'});
    showImg('is-out', imgSrc(d.data[0]), 'is-prog');
  } catch(e) { $('is-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Video Generation (t2v / i2v / v2v)
// ─────────────────────────────────────────────────────────────────
async function genVideo(mode) {
  if (!activeModel) return;
  const progMap   = {t2v:'vt-prog',  i2v:'vi-prog',  v2v:'vv-prog'};
  const outMap    = {t2v:'vt-out',   i2v:'vi-out',   v2v:'vv-out'};
  const prefixMap = {t2v:'vt',       i2v:'vi',        v2v:'vv'};
  const prog = progMap[mode], outId = outMap[mode], prefix = prefixMap[mode];
  $(prog).textContent='Generating… (this may take several minutes)';
  _startVidPoll(prefix);
  const subId = {t2v:'vid-t2v', i2v:'vid-i2v', v2v:'vid-v2v'}[mode];
  const body = {model:modelForSub(subId), mode};
  if (mode==='t2v') {
    body.prompt=val('vt-prompt'); body.negative_prompt=val('vt-neg');
    body.width=ival('vt-w')||512; body.height=ival('vt-h')||512;
    body.num_frames=ival('vt-frames')||16; body.fps=ival('vt-fps')||8;
    body.num_inference_steps=ival('vt-steps')||25; body.guidance_scale=fval('vt-cfg')||7.5;
    if (val('vt-seed')) body.seed=ival('vt-seed');
    if (val('vt-cam')) body.camera_motion=val('vt-cam');
    body.disable_safety_checker=chk('vt-nosafe');
    const vtProfiles = getCharProfilesList('vt');
    if (vtProfiles.length) { body.character_profiles=vtProfiles; body.character_strength=fval('vt-char-str')||0.8; }
    const vtEnvProfiles = getEnvProfilesList('vt');
    if (vtEnvProfiles.length) { body.environment_profiles=vtEnvProfiles; body.environment_strength=fval('vt-env-str')||0.6; }
    const vtDialogs = getDialogLines('vt');
    if (vtDialogs.length) { body.dialogs=vtDialogs; body.lip_sync_method=val('vt-dlg-method')||'wav2lip'; }
  } else if (mode==='i2v') {
    const img = await b64OrNull('vi-src');
    if (!img) { $(prog).textContent='Select a source image.'; return; }
    body.init_image=img; body.prompt=val('vi-prompt')||'animate this image';
    body.num_frames=ival('vi-frames')||16; body.fps=ival('vi-fps')||8;
    body.num_inference_steps=ival('vi-steps')||25; body.guidance_scale=fval('vi-cfg')||7.5;
    if (val('vi-seed')) body.seed=ival('vi-seed');
    if (val('vi-cam')) body.camera_motion=val('vi-cam');
    body.disable_safety_checker=chk('vt-nosafe');
    const viProfiles = getCharProfilesList('vi');
    if (viProfiles.length) { body.character_profiles=viProfiles; body.character_strength=fval('vi-cstr')||0.8; }
    const viChars = buildCharactersPayload('vi');
    if (viChars) { body.characters=viChars; body.character_strength=fval('vi-cstr')||0.8; }
    const viEnvProfiles = getEnvProfilesList('vi');
    if (viEnvProfiles.length) { body.environment_profiles=viEnvProfiles; body.environment_strength=fval('vi-estr')||0.6; }
    const viDialogs = getDialogLines('vi');
    if (viDialogs.length) { body.dialogs=viDialogs; body.lip_sync_method=val('vi-dlg-method')||'wav2lip'; }
  } else {
    const vid = await b64OrNull('vv-src');
    if (!vid) { $(prog).textContent='Select a source video.'; return; }
    body.video=vid; body.prompt=val('vv-prompt'); body.strength=fval('vv-str');
    body.num_inference_steps=ival('vv-steps')||25; body.guidance_scale=fval('vv-cfg')||7.5;
    if (val('vv-seed')) body.seed=ival('vv-seed');
    if (val('vv-cam')) body.camera_motion=val('vv-cam');
    body.disable_safety_checker=chk('vt-nosafe');
    const vvProfiles = getCharProfilesList('vv');
    if (vvProfiles.length) { body.character_profiles=vvProfiles; body.character_strength=fval('vv-cstr')||0.8; }
    const vvChars = buildCharactersPayload('vv');
    if (vvChars) { body.characters=vvChars; body.character_strength=fval('vv-cstr')||0.8; }
    const vvEnvProfiles = getEnvProfilesList('vv');
    if (vvEnvProfiles.length) { body.environment_profiles=vvEnvProfiles; body.environment_strength=fval('vv-estr')||0.6; }
    const vvDialogs = getDialogLines('vv');
    if (vvDialogs.length) { body.dialogs=vvDialogs; body.lip_sync_method=val('vv-dlg-method')||'wav2lip'; }
  }
  try {
    const d = await post('/v1/video/generations', body);
    _stopVidPoll(prefix, true);
    showVideo(outId, vidSrc(d.data[0]), prog);
  } catch(e) { _stopVidPoll(prefix, false); $(prog).textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Ti2V  (text + init image + end image)
// ─────────────────────────────────────────────────────────────────
async function genTi2V() {
  if (!activeModel) return;
  $('ti-prog').textContent='Generating… (may take several minutes)';
  const [initImg, endImg, srcVid] = await Promise.all([b64OrNull('ti-init'), b64OrNull('ti-end'), b64OrNull('ti-vid')]);
  if (!srcVid && !initImg) { $('ti-prog').textContent='Select an initial image or source video.'; return; }
  _startVidPoll('ti');

  const body = {
    model:modelForSub('vid-ti2v'),
    mode: srcVid ? 'v2v' : endImg ? 'interp' : (val('ti-prompt') ? 'ti2v' : 'i2v'),
    prompt:val('ti-prompt'), negative_prompt:val('ti-neg'),
    init_image:initImg||undefined, end_image:endImg||undefined,
    video:srcVid||undefined,
    ...(srcVid ? {strength:fval('ti-vstr')||0.7} : {}),
    width:ival('ti-w')||512, height:ival('ti-h')||512,
    num_frames:ival('ti-frames')||16, fps:ival('ti-fps')||8,
    num_inference_steps:ival('ti-steps')||25, guidance_scale:fval('ti-cfg')||7.5,
    camera_motion:val('ti-cam')||undefined,
    ...(val('ti-seed') ? {seed:ival('ti-seed')} : {}),
    // Character
    ...(getCharProfilesList('ti').length ? {character_profiles:getCharProfilesList('ti')} : {}),
    characters: buildCharactersPayload('ti'),
    character_strength:fval('ti-cstr')||0.8,
    // Environment
    ...(getEnvProfilesList('ti').length ? {environment_profiles:getEnvProfilesList('ti'), environment_strength:fval('ti-estr')||0.6} : {}),
    // Audio
    add_audio:!!val('ti-atype'),
    audio_type:val('ti-atype')||undefined,
    audio_prompt:val('ti-aprompt')||undefined,
    tts_text:val('ti-ttstext')||undefined,
    tts_voice:val('ti-voice')||undefined,
    tts_speed:fval('ti-speed')||1.0,
    lip_sync:chk('ti-lipsync'),
    // Character dialog
    ...(getDialogLines('ti').length ? {dialogs:getDialogLines('ti'), lip_sync_method:val('ti-dlg-method')||'wav2lip'} : {}),
    // Subtitles
    generate_subtitles:chk('ti-gensub'),
    burn_subtitles:chk('ti-burnsub'),
    translate_subtitles:chk('ti-transsub'),
    subtitle_target_lang:val('ti-sublang')||undefined,
    // Post
    upscale_output:chk('ti-upscale'),
    upscale_factor:ival('ti-upfact')||2,
    interpolate_output:chk('ti-interp'),
    fps_multiplier:ival('ti-fmult')||2,
    // Safety
    disable_safety_checker:chk('ti-nosafe'),
  };

  try {
    const d = await post('/v1/video/generations', body);
    _stopVidPoll('ti', true);
    showVideo('ti-out', vidSrc(d.data[0]), 'ti-prog');
  } catch(e) { _stopVidPoll('ti', false); $('ti-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Frame Interpolation
// ─────────────────────────────────────────────────────────────────
async function genInterp() {
  if (!activeModel) return;
  $('vc-prog').textContent='Interpolating…';
  const [vid, init, end] = await Promise.all([b64OrNull('vc-src'), b64OrNull('vc-init'), b64OrNull('vc-end')]);
  const body = {model:modelForSub('vid-interp'), fps_multiplier:ival('vc-mult')||2};
  if (vid) body.video=vid;
  else if (init && end) { body.init_image=init; body.end_image=end; }
  else { $('vc-prog').textContent='Provide a video or both frame images.'; return; }
  try {
    const d = await post('/v1/video/interpolate', body);
    showVideo('vc-out', vidSrc(d.data[0]), 'vc-prog');
  } catch(e) { $('vc-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Subtitles
// ─────────────────────────────────────────────────────────────────
async function genSubtitles() {
  if (!activeModel) return;
  const vid = await b64OrNull('vs-src');
  if (!vid) { $('vs-prog').textContent='Select a video.'; return; }
  $('vs-prog').textContent='Generating subtitles…';
  const burn = val('vs-fmt') === 'burned_video';
  const body = {
    model:modelForSub('vid-sub'), video:vid,
    language:val('vs-lang')||undefined,
    burn, format:val('vs-fmt'),
    translate:chk('vs-translate'),
    target_lang:val('vs-tlang')||undefined,
  };
  try {
    const d = await post('/v1/video/subtitle', body);
    const item = d.data[0];
    if (item.url || item.b64_mp4) showVideo('vs-out', vidSrc(item), 'vs-prog');
    else if (item.text) {
      $('vs-out').innerHTML = `<div class="gen-out-inner" style="width:100%;text-align:left">
        <pre style="white-space:pre-wrap;font-size:12px;background:var(--surface-2);padding:.75rem;border-radius:6px;width:100%;box-sizing:border-box">${item.text}</pre>
        <button class="btn btn-ghost btn-sm" onclick="navigator.clipboard.writeText(${JSON.stringify(item.text)})">Copy</button>
      </div>`;
      $('vs-prog').textContent='Done ✓';
    }
  } catch(e) { $('vs-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Dub
// ─────────────────────────────────────────────────────────────────
async function genDub() {
  if (!activeModel) return;
  const vid = await b64OrNull('vd-src');
  if (!vid) { $('vd-prog').textContent='Select a video.'; return; }
  const preview = buildDubPreferencePreview();
  $('vd-prog').textContent='Dubbing…';
  try {
    const d = await post('/v1/video/dub', {
      stt_model: getAssignedModelId('vid-dub', 'speech_to_text'),
      tts_model: getAssignedModelId('vid-dub', 'text_to_speech'),
      video_model: boundModelId('vid-dub', 'video_model', null),
      _studio_model_metadata: studioModelMetadataForRole('vid-dub', 'video_model') || studioModelMetadataForRole('vid-dub', 'stt_model'),
      video:vid,
      source_lang:preview.source_lang, target_lang:preview.target_lang,
      burn_subtitles:preview.burn_subtitles,
    });
    if (d && typeof d === 'object') d._studioPreview = preview;
    const item = d.data[0];
    showVideo('vd-out', vidSrc(item), 'vd-prog');
    pushArtifactHistory({
      task:'Video dub',
      family:buildDubFamilyLabel(),
      model:getAssignedModelId('vid-dub', 'speech_to_text') || activeModel?.id,
      summary:buildDubHistorySummary(preview),
      links:buildDubLinks(item),
    });
  } catch(e) { $('vd-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Video upscale
// ─────────────────────────────────────────────────────────────────
async function genVidUpscale() {
  if (!activeModel) return;
  const vid = await b64OrNull('vu-src');
  if (!vid) { $('vu-prog').textContent='Select a video.'; return; }
  $('vu-prog').textContent='Upscaling…';
  try {
    const d = await post('/v1/video/upscale', {model:modelForSub('vid-up'), video:vid, upscale_factor:ival('vu-scale')||2});
    showVideo('vu-out', vidSrc(d.data[0]), 'vu-prog');
  } catch(e) { $('vu-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  2D ↔ 3D  &  3D model generation
// ─────────────────────────────────────────────────────────────────

async function _readFileB64(inputId) {
  const el = $(inputId);
  if (!el || !el.files || !el.files[0]) return null;
  return new Promise(resolve => {
    const fr = new FileReader();
    fr.onload = e => resolve(e.target.result.split(',')[1]);
    fr.readAsDataURL(el.files[0]);
  });
}

async function genImageTo3D() {
  const img = await b64OrNull('i3-src');
  if (!img) { $('i3-prog').textContent='Select a source image.'; return; }
  const method = val('i3-method') || 'stereo';
  $('i3-prog').textContent='Converting…';
  try {
    const d = await post('/v1/images/to3d', {
      _studio_model_metadata: studioModelMetadataForRole('img-to3d', 'model'),
      model: modelForSub('img-to3d'),
      image: img,
      method,
      max_shift: ival('i3-shift') || 20,
      response_format: 'url',
    });
    const item = d.data[0];
    if (method === 'mesh') {
      const url = item.url || ('#data:model/gltf-binary;base64,' + item.b64_glb);
      const link = `<a class="btn btn-ghost btn-sm dl" href="${item.url || ''}" download="model.glb">Download GLB</a>`;
      $('i3-out').innerHTML = `<div class="gen-empty" style="padding:1rem">${link}<p style="font-size:12px;color:var(--text-3);margin-top:.5rem">GLB file ready</p></div>`;
      $('i3-prog').textContent = 'Done ✓';
    } else {
      showImg('i3-out', imgSrc(item), 'i3-prog');
    }
  } catch(e) { $('i3-prog').textContent='Error: '+e.message; }
}

async function genImageFrom3D() {
  const raw = await _readFileB64('f3-src');
  if (!raw) { $('f3-prog').textContent='Select a 3D model file.'; return; }
  $('f3-prog').textContent='Rendering…';
  try {
    const d = await post('/v1/images/from3d', {
      _studio_model_metadata: studioModelMetadataForRole('img-from3d', 'model'),
      model: modelForSub('img-from3d'),
      model_data: raw,
      format: val('f3-fmt') || 'glb',
      camera_distance: fval('f3-dist') || 2.0,
      camera_elevation: fval('f3-elev') || 30,
      camera_azimuth: fval('f3-azim') || 45,
      width: ival('f3-w') || 512,
      height: ival('f3-h') || 512,
      response_format: 'url',
    });
    showImg('f3-out', imgSrc(d.data[0]), 'f3-prog');
  } catch(e) { $('f3-prog').textContent='Error: '+e.message; }
}

async function genVideoTo3D() {
  const vid = await b64OrNull('v3-src');
  if (!vid) { $('v3-prog').textContent='Select a source video.'; return; }
  $('v3-prog').textContent='Converting frames… (may take a while)';
  try {
    const d = await post('/v1/video/to3d', {
      _studio_model_metadata: studioModelMetadataForRole('vid-to3d', 'model'),
      model: modelForSub('vid-to3d'),
      video: vid,
      method: val('v3-method') || 'anaglyph',
      max_shift: ival('v3-shift') || 15,
      response_format: 'url',
    });
    showVideo('v3-out', vidSrc(d.data[0]), 'v3-prog');
  } catch(e) { $('v3-prog').textContent='Error: '+e.message; }
}

async function genVideoFrom3D() {
  const raw = await _readFileB64('vf3-src');
  if (!raw) { $('vf3-prog').textContent='Select a 3D model file.'; return; }
  $('vf3-prog').textContent='Rendering turntable…';
  try {
    const d = await post('/v1/video/from3d', {
      _studio_model_metadata: studioModelMetadataForRole('vid-from3d', 'model'),
      model: modelForSub('vid-from3d'),
      model_data: raw,
      format: val('vf3-fmt') || 'glb',
      frames: ival('vf3-frames') || 36,
      fps: ival('vf3-fps') || 12,
      camera_elevation: fval('vf3-elev') || 20,
      camera_distance: fval('vf3-dist') || 2.5,
      width: ival('vf3-w') || 512,
      height: ival('vf3-h') || 512,
      response_format: 'url',
    });
    showVideo('vf3-out', vidSrc(d.data[0]), 'vf3-prog');
  } catch(e) { $('vf3-prog').textContent='Error: '+e.message; }
}

async function gen3DModel() {
  const prompt = val('g3-prompt');
  const img = await b64OrNull('g3-img');
  if (!prompt && !img) { $('g3-prog').textContent='Enter a prompt or select an image.'; return; }
  $('g3-prog').textContent='Generating 3D model… (may take several minutes)';
  try {
    const body = { model: modelForSub('3d-generate'), _studio_model_metadata: studioModelMetadataForRole('3d-generate', 'model'), response_format: 'url' };
    if (prompt) body.prompt = prompt;
    if (img) body.image = img;
    if (ival('g3-steps')) body.steps = ival('g3-steps');
    if (val('g3-seed')) body.seed = ival('g3-seed');
    const d = await post('/v1/3d/generate', body);
    const item = d.data[0];
    const backend = d.backend || 'unknown';
    const dlUrl = item.url;
    const dlHref = dlUrl ? `<a class="btn btn-primary btn-sm dl" href="${dlUrl}" download="model.glb">Download GLB</a>` : '';
    $('g3-out').innerHTML = `<div style="text-align:center;padding:1.5rem;display:flex;flex-direction:column;align-items:center;gap:.6rem">
      <div style="font-size:13px;color:var(--text-2)">3D model generated (backend: <strong>${escapeHtml(backend)}</strong>)</div>
      ${dlHref}
      <div style="font-size:11px;color:var(--text-3)">Open the GLB in any 3D viewer (e.g. Blender, model-viewer, Windows 3D Viewer)</div>
    </div>`;
    $('g3-prog').textContent = 'Done ✓';
  } catch(e) { $('g3-prog').textContent='Error: '+e.message; }
}

// 3D tab aliases (same logic, different input IDs)
async function gen3DImgTo3D() {
  const img = await b64OrNull('t3i-src');
  if (!img) { $('t3i-prog').textContent='Select a source image.'; return; }
  const method = val('t3i-method') || 'stereo';
  $('t3i-prog').textContent='Converting…';
  try {
    const d = await post('/v1/images/to3d', {
      _studio_model_metadata: studioModelMetadataForRole('3d-img-to3d', 'model'),
      model: modelForSub('3d-img-to3d'),
      image: img, method,
      max_shift: ival('t3i-shift') || 20,
      response_format: 'url',
    });
    const item = d.data[0];
    if (method === 'mesh') {
      $('t3i-out').innerHTML = `<div class="gen-empty" style="padding:1rem"><a class="btn btn-primary btn-sm dl" href="${item.url || ''}" download="model.glb">Download GLB</a></div>`;
      $('t3i-prog').textContent = 'Done ✓';
    } else {
      showImg('t3i-out', imgSrc(item), 't3i-prog');
    }
  } catch(e) { $('t3i-prog').textContent='Error: '+e.message; }
}

async function gen3DVidTo3D() {
  const vid = await b64OrNull('t3v-src');
  if (!vid) { $('t3v-prog').textContent='Select a source video.'; return; }
  $('t3v-prog').textContent='Converting frames… (may take a while)';
  try {
    const d = await post('/v1/video/to3d', {
      _studio_model_metadata: studioModelMetadataForRole('3d-vid-to3d', 'model'),
      model: modelForSub('3d-vid-to3d'),
      video: vid,
      method: val('t3v-method') || 'anaglyph',
      max_shift: ival('t3v-shift') || 15,
      response_format: 'url',
    });
    showVideo('t3v-out', vidSrc(d.data[0]), 't3v-prog');
  } catch(e) { $('t3v-prog').textContent='Error: '+e.message; }
}

function r3TypeChange() {
  const isVideo = val('r3-type') === 'video';
  $('r3-img-opts').style.display = isVideo ? 'none' : '';
  $('r3-vid-opts').style.display = isVideo ? '' : 'none';
}

async function gen3DRender() {
  const raw = await _readFileB64('r3-src');
  if (!raw) { $('r3-prog').textContent='Select a 3D model file.'; return; }
  const isVideo = val('r3-type') === 'video';
  $('r3-prog').textContent = isVideo ? 'Rendering turntable…' : 'Rendering…';
  try {
    if (isVideo) {
      const d = await post('/v1/video/from3d', {
        _studio_model_metadata: studioModelMetadataForRole('3d-from3d', 'model'),
        model: modelForSub('3d-from3d'),
        model_data: raw,
        format: val('r3-fmt') || 'glb',
        frames: ival('r3-frames') || 36,
        fps: ival('r3-fps') || 12,
        camera_elevation: fval('r3-velev') || 20,
        camera_distance: fval('r3-vdist') || 2.5,
        width: ival('r3-w') || 512,
        height: ival('r3-h') || 512,
        response_format: 'url',
      });
      showVideo('r3-out', vidSrc(d.data[0]), 'r3-prog');
    } else {
      const d = await post('/v1/images/from3d', {
        _studio_model_metadata: studioModelMetadataForRole('3d-from3d', 'model'),
        model: modelForSub('3d-from3d'),
        model_data: raw,
        format: val('r3-fmt') || 'glb',
        camera_distance: fval('r3-dist') || 2.0,
        camera_elevation: fval('r3-elev') || 30,
        camera_azimuth: fval('r3-azim') || 45,
        width: ival('r3-w') || 512,
        height: ival('r3-h') || 512,
        response_format: 'url',
      });
      showImg('r3-out', imgSrc(d.data[0]), 'r3-prog');
    }
  } catch(e) { $('r3-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Webcam / Microphone capture utility
//  openWebcam(boxId, fileInputId, previewId, mode)
//  mode: 'photo' | 'audio'
// ─────────────────────────────────────────────────────────────────
const _webcamState = {};  // boxId → { stream, recorder, chunks }

async function openWebcam(boxId, fileInputId, previewId, mode) {
  const box = $(boxId);
  if (!box) return;
  // Toggle off if already open
  if (box.style.display !== 'none') {
    _stopWebcam(boxId);
    box.style.display = 'none';
    return;
  }
  box.style.display = 'flex';
  box.innerHTML = '<div style="color:var(--text-3);font-size:12px">Requesting permission…</div>';

  try {
    const constraints = mode === 'audio'
      ? { audio: true }
      : { video: { facingMode: 'user' }, audio: false };
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    _webcamState[boxId] = { stream, recorder: null, chunks: [] };

    if (mode === 'photo') {
      const video = document.createElement('video');
      video.srcObject = stream; video.autoplay = true; video.muted = true;
      video.style.cssText = 'width:100%;max-height:200px;border-radius:6px;background:#000';
      const canvas = document.createElement('canvas');
      canvas.style.display = 'none';
      const snapBtn = document.createElement('button');
      snapBtn.className = 'btn btn-primary btn-sm'; snapBtn.textContent = '📸 Capture';
      const closeBtn = document.createElement('button');
      closeBtn.className = 'btn btn-ghost btn-sm'; closeBtn.textContent = '✕ Close';
      const ctrl = document.createElement('div');
      ctrl.className = 'webcam-controls';
      ctrl.append(snapBtn, closeBtn);
      box.innerHTML = ''; box.append(video, canvas, ctrl);

      snapBtn.onclick = () => {
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0);
        canvas.toBlob(blob => {
          const file = new File([blob], 'webcam.png', { type: 'image/png' });
          _setFileInput(fileInputId, file);
          if (previewId) previewMediaInput(fileInputId, previewId);
          _stopWebcam(boxId);
          box.style.display = 'none';
        }, 'image/png');
      };
      closeBtn.onclick = () => { _stopWebcam(boxId); box.style.display = 'none'; };

    } else {
      // Audio recording
      const recorder = new MediaRecorder(stream);
      _webcamState[boxId].recorder = recorder;
      _webcamState[boxId].chunks = [];
      recorder.ondataavailable = e => { if (e.data.size) _webcamState[boxId].chunks.push(e.data); };
      recorder.onstop = () => {
        const blob = new Blob(_webcamState[boxId].chunks, { type: 'audio/webm' });
        const file = new File([blob], 'recording.webm', { type: 'audio/webm' });
        _setFileInput(fileInputId, file);
        _stopWebcam(boxId);
        box.style.display = 'none';
        // Show confirmation
        const fi = $(fileInputId);
        if (fi) fi.title = 'Recorded audio ready';
      };

      const recBtn = document.createElement('button');
      recBtn.className = 'btn btn-primary btn-sm'; recBtn.textContent = '⏺ Start Recording';
      const stopBtn = document.createElement('button');
      stopBtn.className = 'btn btn-ghost btn-sm'; stopBtn.textContent = '⏹ Stop & Use';
      stopBtn.disabled = true;
      const closeBtn = document.createElement('button');
      closeBtn.className = 'btn btn-ghost btn-sm'; closeBtn.textContent = '✕ Cancel';
      const timer = document.createElement('span');
      timer.style.cssText = 'font-size:12px;color:var(--text-3);min-width:3rem';
      const ctrl = document.createElement('div');
      ctrl.className = 'webcam-controls'; ctrl.append(recBtn, stopBtn, closeBtn, timer);
      box.innerHTML = ''; box.append(ctrl);

      let _timerInterval;
      recBtn.onclick = () => {
        recorder.start();
        recBtn.disabled = true; stopBtn.disabled = false;
        recBtn.textContent = '🔴 Recording…';
        let secs = 0;
        _timerInterval = setInterval(() => { secs++; timer.textContent = secs + 's'; }, 1000);
      };
      stopBtn.onclick = () => {
        clearInterval(_timerInterval);
        recorder.stop();
      };
      closeBtn.onclick = () => { clearInterval(_timerInterval); _stopWebcam(boxId); box.style.display = 'none'; };
    }
  } catch(e) {
    box.innerHTML = `<div style="color:var(--error);font-size:12px">Permission denied: ${e.message}</div>`;
  }
}

function _stopWebcam(boxId) {
  const state = _webcamState[boxId];
  if (!state) return;
  if (state.stream) state.stream.getTracks().forEach(t => t.stop());
  delete _webcamState[boxId];
}

function _setFileInput(fileInputId, file) {
  const fi = $(fileInputId);
  if (!fi) return;
  const dt = new DataTransfer();
  dt.items.add(file);
  fi.files = dt.files;
  fi.dispatchEvent(new Event('change'));
}

function previewMediaInput(fileInputId, previewId) {
  const fi = $(fileInputId), prev = $(previewId);
  if (!fi || !prev || !fi.files[0]) return;
  const f = fi.files[0];
  const url = URL.createObjectURL(f);
  if (f.type.startsWith('image/'))
    prev.innerHTML = `<img src="${url}" style="max-width:100%;max-height:120px;border-radius:6px">`;
  else if (f.type.startsWith('video/'))
    prev.innerHTML = `<video src="${url}" controls style="max-width:100%;max-height:120px;border-radius:6px"></video>`;
  else if (f.type.startsWith('audio/'))
    prev.innerHTML = `<audio src="${url}" controls style="width:100%"></audio>`;
}

// ─────────────────────────────────────────────────────────────────
//  Deblur
// ─────────────────────────────────────────────────────────────────
async function genDeblur() {
  const f = fileOrNull('db-src');
  if (!f) { $('db-prog').textContent='Select an image.'; return; }
  $('db-prog').textContent='Deblurring…';
  try {
    const d = await post('/v1/images/deblur', {_studio_model_metadata: studioModelMetadataForRole('img-deblur', 'model'), model:modelForSub('img-deblur'), image: await fileToB64(f), strength: fval('db-str')||0.5, response_format:'url'});
    showImg('db-out', imgSrc(d.data[0]), 'db-prog');
  } catch(e) { $('db-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Unpixelate
// ─────────────────────────────────────────────────────────────────
async function genUnpixelate() {
  const f = fileOrNull('up-src');
  if (!f) { $('up-prog').textContent='Select an image.'; return; }
  $('up-prog').textContent='Restoring…';
  try {
    const d = await post('/v1/images/unpixelate', {_studio_model_metadata: studioModelMetadataForRole('img-unpix', 'model'), model:modelForSub('img-unpix'), image: await fileToB64(f), scale: ival('up-scale')||4, response_format:'url'});
    showImg('up-out', imgSrc(d.data[0]), 'up-prog');
  } catch(e) { $('up-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Outfit Change
// ─────────────────────────────────────────────────────────────────
function fsFaceSwapTypeChange() {
  const isVideo = val('fs-type') === 'video';
  const tgtInput = $('fs-tgt');
  if (tgtInput) tgtInput.accept = isVideo ? 'video/*' : 'image/*,video/*';
  const camBtn = $('fs-tgt-cam-btn');
  if (camBtn) camBtn.style.display = isVideo ? 'none' : '';
  const wrap = $('fs-tgt-wrap');
  if (wrap) wrap.querySelector('.fl').textContent = isVideo ? 'Target video' : 'Target image';
}

function otOutfitTypeChange() {
  const isVideo = val('ot-type') === 'video';
  $('ot-img-wrap').style.display = isVideo ? 'none' : '';
  $('ot-vid-wrap').style.display = isVideo ? '' : 'none';
}

async function genOutfit() {
  if (!activeModel) return;
  const isVideo = val('ot-type') === 'video';
  if (!val('ot-prompt')) { $('ot-prog').textContent='Enter an outfit prompt.'; return; }
  $('ot-prog').textContent = isVideo ? 'Changing outfit on video…' : 'Changing outfit…';
  const body = {
    _studio_model_metadata: studioModelMetadataForRole('img-outfit', 'model'),
    model: modelForSub('img-outfit'),
    prompt: val('ot-prompt'),
    steps: ival('ot-steps')||30,
    guidance_scale: fval('ot-cfg')||7.5,
    response_format: 'url',
  };
  if (val('ot-neg')) body.negative_prompt = val('ot-neg');
  if (val('ot-seed')) body.seed = ival('ot-seed');
  const maskFile = fileOrNull('ot-mask');
  if (maskFile) body.mask = await fileToB64(maskFile);
  if (isVideo) {
    const f = fileOrNull('ot-vid');
    if (!f) { $('ot-prog').textContent='Select a source video.'; return; }
    body.video = await fileToB64(f);
  } else {
    const f = fileOrNull('ot-src');
    if (!f) { $('ot-prog').textContent='Select a source image.'; return; }
    body.image = await fileToB64(f);
  }
  try {
    const d = await post('/v1/images/outfit', body);
    if (isVideo) showVideo('ot-out', vidSrc(d.data[0]), 'ot-prog');
    else showImg('ot-out', imgSrc(d.data[0]), 'ot-prog');
  } catch(e) { $('ot-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Face Swap
// ─────────────────────────────────────────────────────────────────
async function genFaceSwap() {
  const srcFile = fileOrNull('fs-src'), tgtFile = fileOrNull('fs-tgt');
  if (!srcFile || !tgtFile) { $('fs-prog').textContent='Select source face and target.'; return; }
  $('fs-prog').textContent='Swapping face…';
  const [src, tgt] = await Promise.all([fileToB64(srcFile), fileToB64(tgtFile)]);
  const ttype = val('fs-type') || 'image';
  try {
    const bindingId = ttype === 'video' ? 'vid-faceswap' : 'img-faceswap';
    const d = await post('/v1/images/faceswap', { _studio_model_metadata: studioModelMetadataForRole(bindingId, 'model'), model:modelForSub(bindingId), source_face:src, target:tgt, target_type:ttype, response_format:'url' });
    const item = d.data[0];
    if (ttype === 'video') showVideo('fs-out', vidSrc(item) || 'data:video/mp4;base64,'+item.b64_mp4, 'fs-prog');
    else showImg('fs-out', imgSrc(item), 'fs-prog');
  } catch(e) { $('fs-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Pipeline 5: Face Swap  (server-side)
// ─────────────────────────────────────────────────────────────────
async function runPipeline5() {
  const srcFile = fileOrNull('pp5-src'), tgtFile = fileOrNull('pp5-tgt');
  if (!srcFile || !tgtFile) { $('pp5-prog').textContent='Select source face and target.'; return; }
  $('pp5-prog').textContent='Swapping face…';
  const [src, tgt] = await Promise.all([fileToB64(srcFile), fileToB64(tgtFile)]);
  const ttype = val('pp5-type') || 'image';
  try {
    const d = await post('/v1/images/faceswap', { source_face:src, target:tgt, target_type:ttype, response_format:'url' });
    const item = d.data[0];
    if (ttype === 'video') showVideo('pp5-out', vidSrc(item) || 'data:video/mp4;base64,'+item.b64_mp4, 'pp5-prog');
    else showImg('pp5-out', imgSrc(item), 'pp5-prog');
  } catch(e) { $('pp5-prog').textContent='Error: '+e.message; }
}
let _voiceProfiles = [];

async function loadVoiceProfiles() {
  try {
    const d = await dashboardFetch(buildStudioUrl('/audio/voices')).then(r => r.json());
    _voiceProfiles = d.voices || [];
    ['vc-voice', 'pp4-voice', 'cv-voice', 'pvc-voice', 'psvc-voice'].forEach(id => {
      const sel = $(id); if (!sel) return;
      const cur = sel.value;
      sel.innerHTML = '<option value="">— Or upload reference audio below —</option>' +
        _voiceProfiles.map(v => `<option value="${v.name}">${v.name}${v.description ? ' — '+v.description : ''}</option>`).join('');
      if (cur) sel.value = cur;
    });
    refreshDialogSelects();
  } catch(e) {}
}

async function saveVoiceProfile() {
  const name = val('vc-savename'), transcript = val('vc-savetxt');
  const f = fileOrNull('vc-saveref');
  if (!name || !transcript || !f) { $('vc-saveprog').textContent='Fill in name, transcript and audio file.'; return; }
  $('vc-saveprog').textContent='Saving…';
  const fd = new FormData();
  fd.append('name', name); fd.append('transcript', transcript);
  fd.append('description', val('vc-savedesc'));
  fd.append('audio', f);
  try {
    const r = await dashboardFetch(buildStudioUrl('/audio/voices'), {method:'POST', body:fd});
    if (!r.ok) throw new Error(await r.text());
    $('vc-saveprog').textContent='Saved ✓';
    await loadVoiceProfiles();
  } catch(e) { $('vc-saveprog').textContent='Error: '+e.message; }
}

async function genVoiceClone() {
  const text = val('vc-text');
  if (!text) { $('vc-prog').textContent='Enter text to synthesize.'; return; }
  const voiceName = val('vc-voice');
  const refFile = fileOrNull('vc-ref');
  const refTxt = val('vc-reftxt');
  if (!voiceName && (!refFile || !refTxt)) {
    $('vc-prog').textContent='Select a voice profile or upload reference audio + transcript.'; return;
  }
  $('vc-prog').textContent='Cloning voice…';
  const body = {
    _studio_model_metadata: studioModelMetadataForRole('aud-clone', 'model'),
    text,
    speed: fval('vc-speed') || 1.0,
    ...(val('vc-seed') ? {seed: ival('vc-seed')} : {}),
    response_format: 'url',
  };
  body.model = modelForSub('aud-clone');
  if (voiceName) {
    body.voice_name = voiceName;
  } else {
    body.ref_audio = await fileToB64(refFile);
    body.ref_text = refTxt;
  }
  try {
    const d = await post('/v1/audio/clone', body);
    const src = audSrc(d.data[0]);
    showAudio('vc-out', src, 'vc-prog', 'wav');
  } catch(e) { $('vc-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Voice Convert (SVC — preserves pitch/melody)
// ─────────────────────────────────────────────────────────────────
async function genVoiceConvert() {
  const srcFile = fileOrNull('cv-src');
  if (!srcFile) { $('cv-prog').textContent='Select source audio.'; return; }
  const voiceName = val('cv-voice');
  const refFile = fileOrNull('cv-ref');
  if (!voiceName && !refFile) { $('cv-prog').textContent='Select a voice profile or upload reference audio.'; return; }
  const singing = val('cv-mode') === 'singing';
  $('cv-prog').textContent = singing ? 'Converting (singing mode)…' : 'Converting…';
  const src = await fileToB64(srcFile);
  const body = {
    _studio_model_metadata: studioModelMetadataForRole('aud-convert', 'model'),
    model: modelForSub('aud-convert'),
    source_audio: src,
    f0_condition: singing,
    pitch_shift: ival('cv-pitch') || 0,
    diffusion_steps: ival('cv-steps') || 10,
    response_format: 'url',
  };
  if (voiceName) body.voice_name = voiceName;
  else body.target_voice = await fileToB64(refFile);
  try {
    const d = await post('/v1/audio/convert', body);
    const src2 = audSrc(d.data[0]);
    showAudio('cv-out', src2, 'cv-prog', 'wav');
  } catch(e) { $('cv-prog').textContent='Error: '+e.message; }
}

// Also populate cv-voice dropdown when voice profiles load

// ─────────────────────────────────────────────────────────────────
//  Pipeline VC: Voice Clone
// ─────────────────────────────────────────────────────────────────
async function runPipelineVC() {
  const text = val('pvc-text');
  if (!text) { $('pvc-prog').textContent='Enter text to synthesize.'; return; }
  const voiceName = val('pvc-voice'), refFile = fileOrNull('pvc-ref'), refTxt = val('pvc-reftxt');
  if (!voiceName && (!refFile || !refTxt)) { $('pvc-prog').textContent='Select a voice profile or upload reference audio + transcript.'; return; }
  $('pvc-prog').textContent='Cloning voice…';
  const body = { text, speed: fval('pvc-speed')||1.0, response_format:'url' };
  if (val('pvc-seed')) body.seed = ival('pvc-seed');
  if (voiceName) body.voice_name = voiceName;
  else { body.ref_audio = await fileToB64(refFile); body.ref_text = refTxt; }
  try {
    const d = await post('/v1/audio/clone', body);
    showAudio('pvc-out', audSrc(d.data[0]), 'pvc-prog', 'wav');
  } catch(e) { $('pvc-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Pipeline SVC: Voice Convert
// ─────────────────────────────────────────────────────────────────
async function runPipelineSVC() {
  const srcFile = fileOrNull('psvc-src');
  if (!srcFile) { $('psvc-prog').textContent='Select source audio.'; return; }
  const voiceName = val('psvc-voice'), refFile = fileOrNull('psvc-ref');
  if (!voiceName && !refFile) { $('psvc-prog').textContent='Select a voice profile or upload reference audio.'; return; }
  const singing = val('psvc-mode') === 'singing';
  $('psvc-prog').textContent = singing ? 'Converting (singing mode)…' : 'Converting…';
  const body = {
    source_audio: await fileToB64(srcFile),
    f0_condition: singing,
    pitch_shift: ival('psvc-pitch')||0,
    diffusion_steps: ival('psvc-steps')||10,
    response_format: 'url',
  };
  if (voiceName) body.voice_name = voiceName;
  else body.target_voice = await fileToB64(refFile);
  try {
    const d = await post('/v1/audio/convert', body);
    showAudio('psvc-out', audSrc(d.data[0]), 'psvc-prog', 'wav');
  } catch(e) { $('psvc-prog').textContent='Error: '+e.message; }
}

async function runPipeline4() {
  const f = fileOrNull('pp4-src');
  if (!f) { $('pp4-prog').textContent='Select a source file.'; return; }
  const voiceName = val('pp4-voice');
  const refFile = fileOrNull('pp4-ref');
  const refTxt = val('pp4-reftxt');
  if (!voiceName && (!refFile || !refTxt)) {
    $('pp4-prog').textContent='Select a voice profile or upload reference audio + transcript.'; return;
  }
  $('pp4-prog').textContent='Running audio dub pipeline…';
  const isVideo = f.type.startsWith('video/');
  const b64 = await fileToB64(f);
  const body = {
    speed: fval('pp4-speed') || 1.0,
    source_lang: val('pp4-slang') || undefined,
    target_lang: val('pp4-tlang') || undefined,
    whisper_model: val('pp4-whisper') || undefined,
    burn_subtitles: chk('pp4-burn'),
    response_format: 'url',
  };
  if (isVideo) body.video = b64; else body.audio = b64;
  if (voiceName) {
    body.voice_name = voiceName;
  } else {
    body.ref_audio = await fileToB64(refFile);
    body.ref_text = refTxt;
  }
  try {
    const d = await post('/v1/pipelines/audio-dub', body);
    const item = d.data[0];
    if (item.b64_mp4 || item.url) showVideo('pp4-out', vidSrc(item) || 'data:video/mp4;base64,'+item.b64_mp4, 'pp4-prog');
    else if (item.b64_wav) showAudio('pp4-out', 'data:audio/wav;base64,'+item.b64_wav, 'pp4-prog', 'wav');
    else $('pp4-prog').textContent='Done ✓';
  } catch(e) { $('pp4-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Audio Gen
// ─────────────────────────────────────────────────────────────────
async function genAudio() {
  if (!activeModel) return;
  $('ag-prog').textContent='Generating audio…';
  _startAudPoll('ag');
  const melody = await b64OrNull('ag-melody');
  const body = {
    model:modelForSub('aud-gen'), prompt:val('ag-prompt'),
    duration:fval('ag-dur')||10, temperature:fval('ag-temp')||1.0,
    top_k:ival('ag-topk')||250, cfg_coef:fval('ag-cfg')||3.0,
    ...(val('ag-seed') ? {seed:ival('ag-seed')} : {}),
    ...(melody ? {melody} : {}),
    response_format:'url',
  };
  try {
    const d = await post('/v1/audio/generate', body);
    _stopAudPoll('ag', true);
    const item = d.data[0];
    const src = audSrc(item);
    showAudio('ag-out', src, 'ag-prog', 'wav');
    pushArtifactHistory({
      task:'Audio generate',
      family:'audio generation',
      model:modelForSub('aud-gen'),
      summary:buildAudioHistorySummary(val('ag-prompt'), body.duration),
      links:buildAudioLinks(item),
    });
  } catch(e) { _stopAudPoll('ag', false); $('ag-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  TTS
// ─────────────────────────────────────────────────────────────────
async function genTTS() {
  if (!activeModel) return;
  $('at-prog').textContent='Synthesizing…';
  try {
    const ttsVoiceProfile = val('tts-voice-profile');
    const r = await dashboardFetch(buildStudioUrl('/audio/speech'), {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({_studio_model_metadata: studioModelMetadataForRole('aud-tts', 'model'), model:modelForSub('aud-tts'), input:val('at-text'),
        speed:fval('at-speed')||1.0, voice:val('at-voice')||undefined, response_format:'mp3',
        ...(ttsVoiceProfile ? {voice_profile:ttsVoiceProfile} : {}),
      })
    });
    if (!r.ok) throw new Error(await r.text());
    const blob = await r.blob();
    const src = URL.createObjectURL(blob);
    showAudio('at-out', src, 'at-prog', 'mp3');
    pushArtifactHistory({
      task:'Text to speech',
      family:'tts',
      model:modelForSub('aud-tts'),
      summary:buildTTSHistorySummary(val('at-text'), val('at-voice')),
      links: src ? [{ label:'Open', href:src }] : [],
    });
  } catch(e) { $('at-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  STT
// ─────────────────────────────────────────────────────────────────
async function genSTT() {
  const sttModelId = modelForSub('aud-stt');
  if (!sttModelId) return;
  const f = fileOrNull('as-file');
  if (!f) { $('as-prog').textContent='Select an audio file.'; return; }
  $('as-prog').textContent='Transcribing…';
  const fd = new FormData();
  fd.append('file', f); fd.append('model', sttModelId);
  if (val('as-lang')) fd.append('language', val('as-lang'));
  if (val('as-prompt')) fd.append('prompt', val('as-prompt'));
  try {
    const d = await postForm('/audio/transcriptions', fd);
    $('as-out').innerHTML = `<div class="gen-out-inner" style="width:100%;text-align:left">
      <pre style="white-space:pre-wrap;font-size:13px;line-height:1.6;background:var(--surface-2);padding:.75rem;border-radius:6px;width:100%;box-sizing:border-box">${d.text || JSON.stringify(d,null,2)}</pre>
      <button class="btn btn-ghost btn-sm" onclick="navigator.clipboard.writeText(${JSON.stringify(d.text||'')})">Copy</button>
    </div>`;
    pushArtifactHistory({
      task:'Transcription',
      family:'speech to text',
      model:sttModelId,
      summary:buildSTTHistorySummary(d.text || JSON.stringify(d), f.name),
      links:[],
    });
    $('as-prog').textContent='Done ✓';
  } catch(e) { $('as-prog').textContent='Error: '+e.message; }
}

async function genStems() {
  const f = fileOrNull('ast-file');
  if (!f) { $('ast-prog').textContent='Select a source mix.'; return; }
  $('ast-prog').textContent='Separating stems…';
  try {
    const body = {
      _studio_model_metadata: studioModelMetadataForRole('aud-stems', 'model'),
      model: modelForSub('aud-stems'),
      audio: await fileToB64(f),
      stem_mode: val('ast-mode') || 'vocals-instrumental',
      response_format: 'url',
    };
    const d = await post('/v1/audio/stems', body);
    const items = d.data || [];
    $('ast-out').innerHTML = `<div class="gen-out-inner" style="width:100%;text-align:left">${items.map(item => {
      const src = audSrc(item);
      return `<div style="width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:.75rem;margin-bottom:.6rem;box-sizing:border-box">
        <div style="font-size:12px;font-weight:600;margin-bottom:.35rem">${escapeHtml(item.name || 'stem')} · ${escapeHtml(item.role || 'artifact')}</div>
        <audio class="out-audio" controls src="${src}"></audio>
        <div style="font-size:11px;color:var(--text-3);margin-top:.35rem">${escapeHtml((d.limitations || []).join(' · '))}</div>
        <a href="${src}" download="${escapeHtml(item.name || 'stem')}.wav" class="btn btn-ghost btn-sm dl">Download</a>
      </div>`;
    }).join('')}</div>`;
    pushArtifactHistory({
      task:'Stem separation',
      family:'audio stems',
      model:d.backend?.model || activeModel?.id || 'proxy-route',
      summary:buildStemHistorySummary(d.stem_mode, items.length, d.backend),
      links:buildMultiArtifactLinks(items),
    });
    $('ast-prog').textContent=`Done ✓ ${d.backend?.quality || 'provider route'}`;
  } catch(e) { $('ast-prog').textContent='Error: '+e.message; }
}

async function genAudioCleanup() {
  const f = fileOrNull('ac-file');
  if (!f) { $('ac-prog').textContent='Select a source recording.'; return; }
  $('ac-prog').textContent='Cleaning audio…';
  try {
    const body = {
      _studio_model_metadata: studioModelMetadataForRole('aud-clean', 'model'),
      model: modelForSub('aud-clean'),
      audio: await fileToB64(f),
      noise_reduction: chk('ac-noise'),
      normalize: chk('ac-level'),
      remove_hum: chk('ac-hum'),
      repair_clicks: chk('ac-click'),
      response_format: 'url',
    };
    const d = await post('/v1/audio/cleanup', body);
    const item = d.data?.[0];
    const src = item ? audSrc(item) : null;
    $('ac-out').innerHTML = `<div class="gen-out-inner" style="width:100%;text-align:left">
      <audio class="out-audio" controls src="${src}"></audio>
      <div style="font-size:12px;color:var(--text-2);width:100%;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;padding:.7rem;box-sizing:border-box">
        <strong>Applied:</strong> ${escapeHtml((d.applied || []).join(', ') || 'none')}<br>
        <strong>Backend:</strong> ${escapeHtml(d.backend?.model || d.backend?.engine || 'provider route')} · ${escapeHtml(d.backend?.quality || 'provider-defined')}<br>
        <strong>Limitations:</strong> ${escapeHtml((d.limitations || []).join(' · '))}
      </div>
      <a href="${src}" download="cleaned.wav" class="btn btn-ghost btn-sm dl">Download</a>
    </div>`;
    pushArtifactHistory({
      task:'Audio cleanup',
      family:'audio cleanup',
      model:d.backend?.model || activeModel?.id || 'proxy-route',
      summary:buildCleanupHistorySummary(d.applied, f.name, d.backend),
      links: src ? [{ label:'Open', href:src }] : [],
    });
    $('ac-prog').textContent=`Done ✓ ${d.backend?.quality || 'provider route'}`;
  } catch(e) { $('ac-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Embeddings
// ─────────────────────────────────────────────────────────────────
async function genEmbeddings() {
  if (!activeModel) return;
  $('em-prog').textContent='Embedding…';
  const lines = val('em-text').split('\n').filter(l => l.trim());
  if (!lines.length) { $('em-prog').textContent='Enter some text.'; return; }
  const input = lines.length === 1 ? lines[0] : lines;
  try {
    const d = await post('/v1/embeddings', {
      model:modelForSub('embed'), input,
      encoding_format:val('em-enc'),
      ...(val('em-dims') ? {dimensions:ival('em-dims')} : {}),
    });
    const preview = d.data.map((e,i) => {
      const vec = Array.isArray(e.embedding)
        ? '[' + e.embedding.slice(0,8).map(v=>v.toFixed(4)).join(', ') + ', …] dim=' + e.embedding.length
        : e.embedding.substring(0,60)+'…';
      return `<div style="margin-bottom:.4rem"><strong>${lines[i]?.substring(0,40)||i}</strong><br><code style="font-size:11px">${vec}</code></div>`;
    }).join('');
    $('em-out').innerHTML = `<div class="gen-out-inner" style="width:100%;text-align:left">${preview}</div>`;
    $('em-prog').textContent='Done ✓';
  } catch(e) { $('em-prog').textContent='Error: '+e.message; }
}

async function genAudioUnderstand() {
  if (!activeModel) return;
  const f = fileOrNull('au-file');
  if (!f) { $('au-prog').textContent='Select an audio or video file.'; return; }
  $('au-prog').textContent='Analyzing audio…';
  try {
    const d = await post('/v1/pipelines/audio-understand', {
      audio: await fileToB64(f),
      audio_model: boundModelId('aud-understand', 'audio_model', activeModel),
      _studio_model_metadata: studioModelMetadataForRole('aud-understand', 'audio_model'),
      ...(boundModelId('aud-understand', 'text_model', null) ? {text_model: boundModelId('aud-understand', 'text_model', null)} : {}),
      ...(val('au-text-model') ? {text_model: val('au-text-model')} : {}),
      ...(val('au-goal') ? {input: val('au-goal')} : {}),
    });
    $('au-out').innerHTML = `<div class="gen-out-inner" style="width:100%;text-align:left;gap:.75rem">
      <div style="width:100%"><strong>Transcript</strong><pre style="white-space:pre-wrap;font-size:13px;line-height:1.6;background:var(--surface-2);padding:.75rem;border-radius:6px;width:100%;box-sizing:border-box">${escapeHtml(d.transcript || 'No transcript returned.')}</pre></div>
      ${d.summary ? `<div style="width:100%"><strong>Summary</strong><pre style="white-space:pre-wrap;font-size:13px;line-height:1.6;background:var(--surface-2);padding:.75rem;border-radius:6px;width:100%;box-sizing:border-box">${escapeHtml(d.summary)}</pre></div>` : ''}
    </div>`;
    $('au-prog').textContent = d.summary ? 'Done ✓ transcript + reasoning' : 'Done ✓ transcript only';
  } catch(e) { $('au-prog').textContent='Error: '+e.message; }
}

async function genMusicDubPlan() {
  if (!activeModel) return;
  const f = fileOrNull('amd-file');
  if (!f) { $('amd-prog').textContent='Select a source song or vocal mix.'; return; }
  $('amd-prog').textContent='Inspecting music dub path…';
  try {
    const d = await post('/v1/pipelines/audio-music-dub', {
      audio: await fileToB64(f),
      stt_model: getAssignedModelId('aud-music-dub', 'speech_to_text'),
      tts_model: getAssignedModelId('aud-music-dub', 'text_to_speech'),
      audio_model: boundModelId('aud-music-dub', 'audio_model', null),
      _studio_model_metadata: studioModelMetadataForRole('aud-music-dub', 'audio_model') || studioModelMetadataForRole('aud-music-dub', 'stt_model'),
      ...(val('amd-slang') ? {source_lang: val('amd-slang')} : {}),
      ...(val('amd-tlang') ? {target_lang: val('amd-tlang')} : {}),
      ...(val('amd-notes') ? {notes: val('amd-notes')} : {}),
    });
    $('amd-out').innerHTML = `<div class="gen-out-inner" style="width:100%;text-align:left;gap:.75rem">
      <div style="width:100%"><strong>Transcript</strong><pre style="white-space:pre-wrap;font-size:13px;line-height:1.6;background:var(--surface-2);padding:.75rem;border-radius:6px;width:100%;box-sizing:border-box">${escapeHtml(d.transcript || 'No transcript returned.')}</pre></div>
      <div style="width:100%"><strong>Translated lyrics</strong><pre style="white-space:pre-wrap;font-size:13px;line-height:1.6;background:var(--surface-2);padding:.75rem;border-radius:6px;width:100%;box-sizing:border-box">${escapeHtml(d.translated_lyrics || 'No translated lyrics returned.')}</pre></div>
      <div style="width:100%"><strong>Final mix</strong><pre style="white-space:pre-wrap;font-size:13px;line-height:1.6;background:var(--surface-2);padding:.75rem;border-radius:6px;width:100%;box-sizing:border-box">${escapeHtml(d.final_mix?.path || 'No final mix path returned.')}</pre></div>
    </div>`;
    pushArtifactHistory({
      task:'Music dub',
      family:'audio music dub',
      model:d.backend?.model || activeModel.id,
      summary:buildMusicDubHistorySummary(d.transcript, d.translated_lyrics, d.backend),
      links:d.final_mix?.path ? [{ label:'Final mix', href:d.final_mix.path }] : [],
    });
    $('amd-prog').textContent='Done ✓ full-stage pipeline';
  } catch(e) { $('amd-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Pipeline 1: Image → Video  (server-side)
// ─────────────────────────────────────────────────────────────────
async function runPipeline1() {
  const prompt=val('pp1-prompt'), imodel=val('pp1-imodel'), vmodel=val('pp1-vmodel');
  if (!prompt||!imodel||!vmodel) { $('pp1-prog').textContent='Fill in prompt + both model IDs.'; return; }
  $('pp1-prog').textContent='Running pipeline… (image → video)';
  const body = {
    prompt, image_model:imodel, video_model:vmodel,
    image_size: val('pp1-isize')||'1024x1024',
    num_frames:ival('pp1-frames')||16, fps:ival('pp1-fps')||8,
    num_inference_steps:ival('pp1-vsteps')||25, guidance_scale:fval('pp1-vcfg')||7.5,
    ...(val('pp1-neg')   ? {negative_prompt:val('pp1-neg')} : {}),
    ...(val('pp1-isteps')? {image_steps:ival('pp1-isteps')} : {}),
    ...(val('pp1-icfg')  ? {image_cfg:fval('pp1-icfg')} : {}),
    ...(val('pp1-iseed') ? {image_seed:ival('pp1-iseed')} : {}),
    ...(val('pp1-vseed') ? {video_seed:ival('pp1-vseed')} : {}),
    ...(val('pp1-cam')   ? {camera_motion:val('pp1-cam')} : {}),
    ...(val('pp1-atype') ? {add_audio:true, audio_type:val('pp1-atype'), audio_prompt:val('pp1-aprompt')} : {}),
    response_format:'url',
  };
  try {
    const d = await post('/v1/pipelines/image-to-video', body);
    const item = d.data[0];
    if (item.image_url) $('pp1-out').innerHTML=`<img class="out-img" src="${item.image_url}" style="max-width:200px;border-radius:6px">`;
    if (item.url) showVideo('pp1-out', item.url, 'pp1-prog');
    else $('pp1-prog').textContent='Done ✓';
  } catch(e) { $('pp1-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Pipeline 2: Video → Dub + Subtitle  (server-side)
// ─────────────────────────────────────────────────────────────────
async function runPipeline2() {
  const f = fileOrNull('pp2-src');
  if (!f) { $('pp2-prog').textContent='Select a video.'; return; }
  const tlang = val('pp2-tlang');
  if (!tlang) { $('pp2-prog').textContent='Enter a target language.'; return; }
  const model = val('pp2-model') || (activeModel ? activeModel.id : '');
  $('pp2-prog').textContent='Dubbing + subtitling…';
  try {
    const vid = await fileToB64(f);
    const d = await post('/v1/pipelines/video-dub', {
      model, video:vid,
      source_lang:val('pp2-slang')||undefined,
      target_lang:tlang,
      voice_clone:chk('pp2-clone'),
      burn_subtitles:chk('pp2-burn'),
    });
    showVideo('pp2-out', vidSrc(d.data[0]), 'pp2-prog');
  } catch(e) { $('pp2-prog').textContent='Error: '+e.message; }
}

// ─────────────────────────────────────────────────────────────────
//  Pipeline 3: Full Story  (server-side)
// ─────────────────────────────────────────────────────────────────
async function runPipeline3() {
  const story=val('pp3-story'), tmodel=val('pp3-tmodel'), imodel=val('pp3-imodel'), vmodel=val('pp3-vmodel');
  if (!story||!tmodel||!imodel||!vmodel) { $('pp3-prog').textContent='Fill in story and text/image/video model IDs.'; return; }
  $('pp3-prog').textContent='Running full story pipeline…';
  try {
    const d = await post('/v1/pipelines/story', {
      story, text_model:tmodel, image_model:imodel, video_model:vmodel,
      tts_model:val('pp3-amodel')||undefined,
      tts_voice:val('pp3-voice')||'af_sarah',
      num_scenes:ival('pp3-scenes')||3,
      num_frames:ival('pp3-frames')||16,
      response_format:'url',
    });
    const item = d.data[0];
    const imgs = (item.image_urls||[]).map(s=>`<img src="${s}" style="max-width:120px;border-radius:4px">`).join('');
    if (imgs) $('pp3-out').innerHTML=`<div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:.5rem">${imgs}</div>`;
    if (item.video_url) showVideo('pp3-out', item.video_url, 'pp3-prog');
    if (item.audio_url) {
      const ext = item.audio_url.includes('mp3') ? 'mp3' : 'wav';
      showAudio('pp3-out', item.audio_url, null, ext);
    }
    if (!item.video_url) $('pp3-prog').textContent='Done ✓';
  } catch(e) { $('pp3-prog').textContent='Error: '+e.message; }
}

// The T2V panel (vid-t2v) needs its own controls inlined since Jinja
// fragment includes aren't available. Add them now:
document.getElementById('panel-vid-t2v').innerHTML = `<div class="gen-wrap">
  <div class="gen-ctrl">
    <div class="cap-card" id="cap-vid-t2v" style="display:none"></div>
    <div class="frow"><label class="fl">Prompt</label><textarea id="vt-prompt" class="fs" rows="4" placeholder="Describe the video…"></textarea></div>
    <div class="frow"><label class="fl">Negative prompt</label><textarea id="vt-neg" class="fs" rows="2" placeholder="Things to avoid…"></textarea></div>
    <div class="g2">
      <div class="frow"><label class="fl">Width</label><input type="number" id="vt-w" class="fi" value="512" step="64"></div>
      <div class="frow"><label class="fl">Height</label><input type="number" id="vt-h" class="fi" value="512" step="64"></div>
    </div>
    <div class="g2">
      <div class="frow"><label class="fl">Frames</label><input type="number" id="vt-frames" class="fi" value="16"></div>
      <div class="frow"><label class="fl">FPS</label><input type="number" id="vt-fps" class="fi" value="8"></div>
    </div>
    <div class="g2">
      <div class="frow"><label class="fl">Steps</label><input type="number" id="vt-steps" class="fi" value="25"></div>
      <div class="frow"><label class="fl">Guidance</label><input type="number" id="vt-cfg" class="fi" value="7.5" step="0.5"></div>
    </div>
    <div class="frow"><label class="fl">Seed</label><input type="number" id="vt-seed" class="fi" placeholder="random"></div>
    <div class="frow"><label class="fl" title="Removes the model's built-in safety checker. Only use with uncensored/NSFW fine-tunes.">Disable safety filter</label><input type="checkbox" id="vt-nosafe"></div>
    <div class="frow"><label class="fl">Camera motion</label>
      <select id="vt-cam" class="fselect">
        <option value="">None</option>
        <option value="zoom-in">Zoom in</option><option value="zoom-out">Zoom out</option>
        <option value="pan-left">Pan left</option><option value="pan-right">Pan right</option>
        <option value="tilt-up">Tilt up</option><option value="tilt-down">Tilt down</option>
        <option value="rotate">Rotate</option>
      </select>
    </div>
    <div class="frow" style="align-items:flex-start">
      <label class="fl" style="padding-top:.3rem">Characters</label>
      <div style="flex:1;display:flex;flex-direction:column;gap:.3rem">
        <div id="vt-char-profile-slots"></div>
        <button class="btn btn-ghost btn-sm" id="vt-add-char-btn" onclick="addCharProfileSlot('vt')" style="align-self:flex-start;font-size:11px">+ Add character</button>
      </div>
    </div>
    <div class="frow"><label class="fl">Character strength <span id="vt-char-sv">0.80</span></label>
      <input type="range" id="vt-char-str" min="0" max="1" step="0.05" value="0.8" oninput="document.getElementById('vt-char-sv').textContent=(+this.value).toFixed(2)" style="width:100%">
    </div>
    <div class="frow" style="align-items:flex-start">
      <label class="fl" style="padding-top:.3rem">Environments</label>
      <div style="flex:1;display:flex;flex-direction:column;gap:.3rem">
        <div id="vt-env-profile-slots"></div>
        <button class="btn btn-ghost btn-sm" id="vt-add-env-btn" onclick="addEnvProfileSlot('vt')" style="align-self:flex-start;font-size:11px">+ Add environment</button>
      </div>
    </div>
    <div class="frow"><label class="fl">Environment strength <span id="vt-env-sv">0.60</span></label>
      <input type="range" id="vt-env-str" min="0" max="1" step="0.05" value="0.6" oninput="document.getElementById('vt-env-sv').textContent=(+this.value).toFixed(2)" style="width:100%">
    </div>
    <div id="vt-dialog-section"></div>
    <button class="btn btn-primary" onclick="genVideo('t2v')">Generate Video</button>
    <div class="progress" id="vt-prog"></div>
    <div class="gen-progress-wrap" id="vt-pbar-wrap">
      <div class="gen-progress-bar-bg"><div class="gen-progress-bar-fill" id="vt-pbar-fill"></div></div>
      <div class="gen-progress-label" id="vt-pbar-label"></div>
    </div>
  </div>
  <div class="gen-out" id="vt-out"><div class="gen-empty">Video will appear here</div></div>
</div>`;

// Inject dialog sections into all video panels
['vt','vi','vv','ti'].forEach(p => {
  const el = document.getElementById(p+'-dialog-section');
  if (el) el.innerHTML = _dialogSectionHtml(p);
});

// ─────────────────────────────────────────────────────────────────
//  Character Profile Manager
// ─────────────────────────────────────────────────────────────────
let _pcImagesB64 = [];   // images staged for create

function profCharShowCreate() {
  _pcImagesB64 = [];
  $('pc-name').value = ''; $('pc-desc').value = ''; $('pc-max').value = '5';
  $('pc-img-previews').innerHTML = '';
  $('pc-form-status').textContent = '';
  $('pc-gen-prompt').value = '';
  $('pc-gen-n').value = '3';
  $('pc-gen-steps').value = '';
  $('pc-gen-w').value = '512'; $('pc-gen-h').value = '512';
  document.querySelectorAll('input[name="pc-mode"]').forEach(r => r.checked = r.value === 'extract');
  pcModeChange();
  pcPopulateModelSelect();
}
function profCharHideForm() { profCharShowCreate(); }

function pcModeChange() {
  const mode = (document.querySelector('input[name="pc-mode"]:checked') || {}).value || 'extract';
  $('pc-extract-fields').style.display = mode === 'extract' ? '' : 'none';
  $('pc-generate-fields').style.display = mode === 'generate' ? '' : 'none';
  $('pc-submit-btn').innerHTML = mode === 'generate' ? 'Generate &amp; Save' : 'Extract &amp; Save';
}

function profCharSubmit() {
  const mode = (document.querySelector('input[name="pc-mode"]:checked') || {}).value || 'extract';
  if (mode === 'generate') profCharGenerate(); else profCharSave();
}

function pcPopulateModelSelect() {
  const sel = $('pc-gen-model'); if (!sel) return;
  const cur = sel.value;
  // Collect image-capable models from the cached model list
  const opts = ['<option value="">Default image model</option>'];
  (models || []).forEach(m => {
    const caps = m.capabilities || [];
    if (caps.includes('image_generation') || caps.includes('image_to_image')) {
      opts.push(`<option value="${escapeHtml(m.id)}">${escapeHtml(m.id)}</option>`);
    }
  });
  sel.innerHTML = opts.join('');
  if (cur) sel.value = cur;
}

function pcImgFilesChanged() {
  _pcImagesB64 = [];
  $('pc-img-previews').innerHTML = '';
  const files = $('pc-img-files').files;
  for (const f of files) {
    const reader = new FileReader();
    reader.onload = e => {
      _pcImagesB64.push(e.target.result);
      const img = document.createElement('img');
      img.src = e.target.result;
      img.style.cssText = 'height:64px;border-radius:4px;object-fit:cover';
      $('pc-img-previews').appendChild(img);
    };
    reader.readAsDataURL(f);
  }
}

async function profCharSave() {
  const name = ($('pc-name').value||'').trim();
  if (!name) { $('pc-form-status').textContent = 'Name is required.'; return; }
  const hasImgs = _pcImagesB64.length > 0;
  const hasVids = $('pc-vid-files').files.length > 0;
  if (!hasImgs && !hasVids) { $('pc-form-status').textContent = 'Provide at least one image or video.'; return; }
  $('pc-form-status').textContent = 'Extracting…';
  try {
    const body = { name, description: $('pc-desc').value||'', max_images: parseInt($('pc-max').value)||5 };
    if (hasImgs) body.images = _pcImagesB64;
    if (hasVids) {
      body.videos = [];
      for (const f of $('pc-vid-files').files) {
        const b64 = await new Promise((res,rej)=>{const r=new FileReader();r.onload=e=>res(e.target.result);r.onerror=rej;r.readAsDataURL(f);});
        body.videos.push(b64);
      }
    }
    const r = await dashboardFetch(buildStudioUrl('/characters/extract'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if (!r.ok) throw new Error((await r.json()).detail || await r.text());
    const d = await r.json();
    $('pc-form-status').textContent = `Saved "${d.name}" (${d.image_count} reference images) ✓`;
    await profCharLoad();
    setTimeout(profCharHideForm, 1200);
  } catch(e) { $('pc-form-status').textContent = 'Error: ' + e.message; }
}

async function profCharGenerate() {
  const name = ($('pc-name').value||'').trim();
  if (!name) { $('pc-form-status').textContent = 'Name is required.'; return; }
  const prompt = ($('pc-gen-prompt').value||'').trim();
  if (!prompt) { $('pc-form-status').textContent = 'A visual prompt is required.'; return; }
  $('pc-form-status').textContent = 'Generating reference images… (this may take a while)';
  try {
    const body = {
      name,
      description: $('pc-desc').value||'',
      prompt,
      n: parseInt($('pc-gen-n').value)||3,
      width: parseInt($('pc-gen-w').value)||512,
      height: parseInt($('pc-gen-h').value)||512,
    };
    const mdl = $('pc-gen-model').value;
    if (mdl) body.model = mdl;
    const steps = parseInt($('pc-gen-steps').value);
    if (steps > 0) body.steps = steps;
    const r = await dashboardFetch(buildStudioUrl('/characters/generate'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if (!r.ok) throw new Error((await r.json()).detail || await r.text());
    const d = await r.json();
    $('pc-form-status').textContent = `Generated "${d.name}" (${d.image_count} reference images) ✓`;
    await profCharLoad();
    setTimeout(profCharHideForm, 1500);
  } catch(e) { $('pc-form-status').textContent = 'Error: ' + e.message; }
}

async function profCharLoad() {
  try {
    const d = await dashboardFetch(buildCharacterListUrl()).then(r=>r.json());
    _charProfiles = d.characters || [];
    renderCharList();
    // Ensure every panel has at least one slot, then refresh options
    initCharProfileSlots();
    refreshCharSelectors();
  } catch(e) { _charProfiles = []; }
}

function refreshCharSelectors() {
  const opts = _charProfileOpts();
  document.querySelectorAll('.char-prof-sel').forEach(sel => {
    const cur = sel.value;
    sel.innerHTML = opts;
    if (cur) sel.value = cur;
  });
  refreshDialogSelects();
}

function renderCharList() {
  const el = $('prof-char-list');
  if (!el) return;
  if (!_charProfiles.length) { el.innerHTML = '<div class="arch-empty">No character profiles yet.</div>'; return; }
  el.innerHTML = _charProfiles.map(p => {
    const n = escapeHtml(p.name);
    const thumb = p.image_count > 0
      ? `<img class="arch-thumb" src="${buildCharacterThumbUrl(p.name)}" loading="lazy" onerror="this.outerHTML='<div class=arch-thumb-ph>\u{1F464}</div>'" onclick="profCharView('${n}')">`
      : `<div class="arch-thumb-ph" onclick="profCharView('${n}')">\u{1F464}</div>`;
    const date = new Date(p.created_at * 1000).toLocaleDateString();
    return `
    <div class="arch-card">
      ${thumb}
      <div class="prof-card-info">
        <div class="prof-card-name">${n}</div>
        ${p.description ? `<div class="prof-card-desc">${escapeHtml(p.description)}</div>` : ''}
        <div class="prof-card-meta">${p.image_count} ref image${p.image_count!==1?'s':''} · ${date}</div>
        <div class="prof-card-actions">
          <button class="btn btn-ghost btn-sm" onclick="profCharView('${n}')">View</button>
          <button class="btn btn-danger btn-sm" onclick="profCharDelete('${n}')">Delete</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function profCharView(name) {
  const d = await dashboardFetch(buildCharacterAdminUrl(name)).then(r=>r.json());
  const imgs = (d.images||[]).map(img=>`<img src="${img.data}" style="height:80px;border-radius:4px;object-fit:cover" title="${escapeHtml(img.label||'')}">`).join('');
  alert(`Character: ${d.name}\nDescription: ${d.description||'—'}\nImages: ${d.image_count}\n\n(Images are shown in console; open DevTools to inspect)`);
  console.log('[profCharView]', d.name, d);
}

async function profCharDelete(name) {
  if (!confirm(`Delete character profile "${name}"?`)) return;
  const r = await dashboardFetch(buildCharacterAdminUrl(name), {method:'DELETE'});
  if (r.ok) await profCharLoad();
  else alert('Delete failed: ' + await r.text());
}


// ─────────────────────────────────────────────────────────────────
//  Voice Profile Manager
// ─────────────────────────────────────────────────────────────────

function profVoiceShowCreate() {
  $('pv-name').value=''; $('pv-desc').value=''; $('pv-transcript').value='';
  $('pv-form-status').textContent='';
}
function profVoiceHideForm() { profVoiceShowCreate(); }

async function profVoiceSave() {
  const name = ($('pv-name').value||'').trim();
  const f = $('pv-file').files[0];
  if (!name) { $('pv-form-status').textContent='Name is required.'; return; }
  if (!f) { $('pv-form-status').textContent='Select an audio or video file.'; return; }
  $('pv-form-status').textContent='Extracting voice profile…';
  try {
    const b64 = await new Promise((res,rej)=>{const r=new FileReader();r.onload=e=>res(e.target.result);r.onerror=rej;r.readAsDataURL(f);});
    const isVideo = f.type.startsWith('video/') || /\.(mp4|mov|mkv|avi|webm)$/i.test(f.name);
    const body = { name, description: $('pv-desc').value||'', transcript: $('pv-transcript').value||'' };
    if (isVideo) body.video = b64; else body.audio = b64;
    const r = await dashboardFetch(buildStudioUrl('/audio/voices/extract'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if (!r.ok) throw new Error((await r.json()).detail || await r.text());
    const d = await r.json();
    const transcript = d.voice?.transcript;
    $('pv-form-status').textContent = `Saved "${d.voice?.name}" ✓` + (transcript ? ` — transcript: "${transcript.slice(0,60)}…"` : '');
    await profVoiceLoad();
    setTimeout(profVoiceHideForm, 1800);
  } catch(e) { $('pv-form-status').textContent='Error: '+e.message; }
}

async function profVoiceLoad() {
  try {
    const d = await dashboardFetch(buildVoiceListUrl()).then(r=>r.json());
    const voices = d.voices || [];
    renderVoiceList(voices);
    // Refresh voice selectors (existing + new)
    ['vc-voice','pp4-voice','cv-voice','pvc-voice','psvc-voice','tts-voice-profile'].forEach(id => {
      const sel = $(id); if (!sel) return;
      const cur = sel.value;
      const placeholder = sel.dataset.placeholder || '— none —';
      sel.innerHTML = `<option value="">${placeholder}</option>` +
        voices.map(v=>`<option value="${escapeHtml(v.name)}">${escapeHtml(v.name)}${v.description?' — '+escapeHtml(v.description):''}</option>`).join('');
      if (cur) sel.value = cur;
    });
    _voiceProfiles = voices;
  } catch(e) {}
}

function renderVoiceList(voices) {
  const el = $('prof-voice-list');
  if (!el) return;
  if (!voices.length) { el.innerHTML = '<div class="arch-empty">No voice profiles yet.</div>'; return; }
  el.innerHTML = voices.map(v => {
    const n = escapeHtml(v.name);
    const date = new Date(v.created_at * 1000).toLocaleDateString();
    const quote = v.transcript ? `<div class="prof-voice-quote">&ldquo;${escapeHtml(v.transcript.slice(0,90))}${v.transcript.length>90?'&hellip;':''}&rdquo;</div>` : '';
    return `
    <div class="prof-voice-card">
      <div class="prof-voice-icon">&#127908;</div>
      <div class="prof-voice-info">
        <div class="prof-voice-name">${n}</div>
        ${v.description ? `<div class="prof-voice-meta">${escapeHtml(v.description)}</div>` : ''}
        ${quote}
        <div class="prof-voice-meta">${date}</div>
        <div class="prof-voice-actions">
          <button class="btn btn-danger btn-sm" onclick="profVoiceDelete('${n}')">Delete</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function profVoiceDelete(name) {
  if (!confirm(`Delete voice profile "${name}"?`)) return;
  const r = await dashboardFetch(buildVoiceDeleteUrl(name), {method:'DELETE'});
  if (r.ok) await profVoiceLoad();
  else alert('Delete failed: ' + await r.text());
}

// ─────────────────────────────────────────────────────────────────
//  Environment Profile Manager
// ─────────────────────────────────────────────────────────────────
let _peImagesB64 = [];

function profEnvShowCreate() {
  _peImagesB64 = [];
  $('pe-name').value = ''; $('pe-desc').value = ''; $('pe-max').value = '5';
  $('pe-img-previews').innerHTML = '';
  $('pe-form-status').textContent = '';
  $('pe-gen-prompt').value = '';
  $('pe-gen-n').value = '3'; $('pe-gen-steps').value = '';
  $('pe-gen-w').value = '512'; $('pe-gen-h').value = '512';
  document.querySelectorAll('input[name="pe-mode"]').forEach(r => r.checked = r.value === 'extract');
  peModeChange();
  pePopulateModelSelect();
}
function profEnvHideForm() { profEnvShowCreate(); }

function peModeChange() {
  const mode = (document.querySelector('input[name="pe-mode"]:checked') || {}).value || 'extract';
  $('pe-extract-fields').style.display = mode === 'extract' ? '' : 'none';
  $('pe-generate-fields').style.display = mode === 'generate' ? '' : 'none';
  $('pe-submit-btn').innerHTML = mode === 'generate' ? 'Generate &amp; Save' : 'Extract &amp; Save';
}

function profEnvSubmit() {
  const mode = (document.querySelector('input[name="pe-mode"]:checked') || {}).value || 'extract';
  if (mode === 'generate') profEnvGenerate(); else profEnvSave();
}

function pePopulateModelSelect() {
  const sel = $('pe-gen-model'); if (!sel) return;
  const cur = sel.value;
  const opts = ['<option value="">Default image model</option>'];
  (models || []).forEach(m => {
    const caps = m.capabilities || [];
    if (caps.includes('image_generation') || caps.includes('image_to_image')) {
      opts.push(`<option value="${escapeHtml(m.id)}">${escapeHtml(m.id)}</option>`);
    }
  });
  sel.innerHTML = opts.join('');
  if (cur) sel.value = cur;
}

function peImgFilesChanged() {
  _peImagesB64 = [];
  $('pe-img-previews').innerHTML = '';
  for (const f of $('pe-img-files').files) {
    const reader = new FileReader();
    reader.onload = e => {
      _peImagesB64.push(e.target.result);
      const img = document.createElement('img');
      img.src = e.target.result;
      img.style.cssText = 'height:64px;border-radius:4px;object-fit:cover';
      $('pe-img-previews').appendChild(img);
    };
    reader.readAsDataURL(f);
  }
}

async function profEnvSave() {
  const name = ($('pe-name').value||'').trim();
  if (!name) { $('pe-form-status').textContent = 'Name is required.'; return; }
  const hasImgs = _peImagesB64.length > 0;
  const hasVids = $('pe-vid-files').files.length > 0;
  if (!hasImgs && !hasVids) { $('pe-form-status').textContent = 'Provide at least one image or video.'; return; }
  $('pe-form-status').textContent = 'Extracting…';
  try {
    const body = { name, description: $('pe-desc').value||'', max_images: parseInt($('pe-max').value)||5 };
    if (hasImgs) body.images = _peImagesB64;
    if (hasVids) {
      body.videos = [];
      for (const f of $('pe-vid-files').files) {
        const b64 = await new Promise((res,rej)=>{const r=new FileReader();r.onload=e=>res(e.target.result);r.onerror=rej;r.readAsDataURL(f);});
        body.videos.push(b64);
      }
    }
    const r = await dashboardFetch(buildStudioUrl('/environments/extract'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if (!r.ok) throw new Error((await r.json()).detail || await r.text());
    const d = await r.json();
    $('pe-form-status').textContent = `Saved "${d.name}" (${d.image_count} reference images) ✓`;
    await profEnvLoad();
    setTimeout(profEnvHideForm, 1200);
  } catch(e) { $('pe-form-status').textContent = 'Error: ' + e.message; }
}

async function profEnvGenerate() {
  const name = ($('pe-name').value||'').trim();
  if (!name) { $('pe-form-status').textContent = 'Name is required.'; return; }
  const prompt = ($('pe-gen-prompt').value||'').trim();
  if (!prompt) { $('pe-form-status').textContent = 'A visual prompt is required.'; return; }
  $('pe-form-status').textContent = 'Generating reference images… (this may take a while)';
  try {
    const body = {
      name, description: $('pe-desc').value||'', prompt,
      n: parseInt($('pe-gen-n').value)||3,
      width: parseInt($('pe-gen-w').value)||512,
      height: parseInt($('pe-gen-h').value)||512,
    };
    const mdl = $('pe-gen-model').value;
    if (mdl) body.model = mdl;
    const steps = parseInt($('pe-gen-steps').value);
    if (steps > 0) body.steps = steps;
    const r = await dashboardFetch(buildStudioUrl('/environments/generate'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    if (!r.ok) throw new Error((await r.json()).detail || await r.text());
    const d = await r.json();
    $('pe-form-status').textContent = `Generated "${d.name}" (${d.image_count} reference images) ✓`;
    await profEnvLoad();
    setTimeout(profEnvHideForm, 1500);
  } catch(e) { $('pe-form-status').textContent = 'Error: ' + e.message; }
}

async function profEnvLoad() {
  try {
    const d = await dashboardFetch(buildEnvironmentListUrl()).then(r=>r.json());
    _envProfiles = d.environments || [];
    renderEnvList();
    initEnvProfileSlots();
    refreshEnvSelectors();
  } catch(e) { _envProfiles = []; }
}

function renderEnvList() {
  const el = $('prof-env-list');
  if (!el) return;
  if (!_envProfiles.length) { el.innerHTML = '<div class="arch-empty">No environment profiles yet.</div>'; return; }
  el.innerHTML = _envProfiles.map(p => {
    const n = escapeHtml(p.name);
    const thumb = p.image_count > 0
      ? `<img class="arch-thumb" src="${buildEnvironmentThumbUrl(p.name)}" loading="lazy" onerror="this.outerHTML='<div class=arch-thumb-ph>\u{1F304}</div>'" onclick="profEnvView('${n}')">`
      : `<div class="arch-thumb-ph" onclick="profEnvView('${n}')">\u{1F304}</div>`;
    const date = new Date(p.created_at * 1000).toLocaleDateString();
    return `
    <div class="arch-card">
      ${thumb}
      <div class="prof-card-info">
        <div class="prof-card-name">${n}</div>
        ${p.description ? `<div class="prof-card-desc">${escapeHtml(p.description)}</div>` : ''}
        <div class="prof-card-meta">${p.image_count} ref image${p.image_count!==1?'s':''} · ${date}</div>
        <div class="prof-card-actions">
          <button class="btn btn-ghost btn-sm" onclick="profEnvView('${n}')">View</button>
          <button class="btn btn-danger btn-sm" onclick="profEnvDelete('${n}')">Delete</button>
        </div>
      </div>
    </div>`;
  }).join('');
}

async function profEnvView(name) {
  const d = await dashboardFetch(buildEnvironmentAdminUrl(name)).then(r=>r.json());
  alert(`Environment: ${d.name}\nDescription: ${d.description||'—'}\nImages: ${d.image_count}\n\n(Images are shown in console; open DevTools to inspect)`);
  console.log('[profEnvView]', d.name, d);
}

async function profEnvDelete(name) {
  if (!confirm(`Delete environment profile "${name}"?`)) return;
  const r = await dashboardFetch(buildEnvironmentAdminUrl(name), {method:'DELETE'});
  if (r.ok) await profEnvLoad();
  else alert('Delete failed: ' + await r.text());
}

// ─────────────────────────────────────────────────────────────────
loadModels();
loadLocalCapabilities();
loadVoiceProfiles();
profCharLoad();
profEnvLoad();
profVoiceLoad();
initRequestPreviews();
initPipelineBuilder();
dashboardFetch(buildAdminApiUrl('/tokens')).then(r => r.json()).then(tokens => {
  if (Array.isArray(tokens) && tokens.length) apiToken = tokens[0].token;
}).catch(() => {});

// ── Pipeline accordion: opening one card closes all others ────────
document.querySelector('.pipe-panel').addEventListener('click', e => {
  const summary = e.target.closest('.pipe-card > summary');
  if (!summary) return;
  const card = summary.parentElement;
  // If it's currently closed, it's about to open — close siblings
  if (!card.open) {
    card.closest('.pipe-panel').querySelectorAll('details.pipe-card[open]').forEach(d => {
      if (d !== card) d.removeAttribute('open');
    });
  }
});
// ─────────────────────────────────────────────────────────────────
//  Pipeline Builder
// ─────────────────────────────────────────────────────────────────
let _stepTypes = [];       // [{type, label, params:[...]}]
let _pbSteps = [];         // current builder steps [{type, label, params:{}}]
let _customPipelines = []; // saved custom pipelines
let _editingPipelineId = null;

async function initPipelineBuilder() {
  try {
    const [typesRes, pipesRes] = await Promise.all([
      dashboardFetch(buildStudioUrl('/pipelines/step-types')).then(r => r.json()),
      dashboardFetch(buildStudioUrl('/pipelines/custom')).then(r => r.json()),
    ]);
    _stepTypes = typesRes.step_types || [];
    _customPipelines = pipesRes.pipelines || [];

    const sel = $('pb-add-type');
    if (sel) sel.innerHTML = _stepTypes.map(t =>
      `<option value="${t.type}">${t.label}</option>`).join('');

    renderCustomPipelineCards();
  } catch(e) {
    console.warn('Pipeline builder init failed:', e);
  }
}

function renderCustomPipelineCards() {
  const container = $('custom-pipe-cards');
  if (!container) return;
  container.innerHTML = _customPipelines.map(p => `
    <details class="pipe-card">
      <summary>
        <div class="pipe-head">
          <div class="pipe-title">${escapeHtml(p.name || p.id)}</div>
          <div class="pipe-summary">${escapeHtml(p.description || 'Custom multi-step pipeline for combining model and utility actions.')}</div>
          <div class="pipe-steps">
            ${(p.steps || []).map(s => `<span class="pipe-step">${escapeHtml(s.label || s.type)}</span>`).join('<span class="pipe-arrow">→</span>')}
          </div>
          <div class="pipe-tags"><span class="pipe-tag">custom</span><span class="pipe-tag">pipeline</span><span class="pipe-tag">${(p.steps || []).length} steps</span></div>
        </div>
      </summary>
      <div class="pipe-card-body">
        ${p.description ? `<p style="font-size:12px;color:var(--text-2);margin:0 0 .4rem">${escapeHtml(p.description)}</p>` : ''}
        <div class="frow"><label class="fl">Input</label><input id="cpr-input-${p.id}" class="fi" placeholder="{{ '{{' }}input{{ '}}' }} value"></div>
        <div style="display:flex;gap:.4rem;margin-top:.4rem;flex-wrap:wrap">
          <button class="btn btn-primary btn-sm" onclick="runCustomPipeline('${p.id}')">▶ Run</button>
          <button class="btn btn-ghost btn-sm" onclick="editCustomPipeline('${p.id}')">✎ Edit</button>
          <button class="btn btn-ghost btn-sm" style="color:var(--red)" onclick="deleteCustomPipeline('${p.id}')">✕ Delete</button>
        </div>
        <div class="progress" id="cpr-prog-${p.id}"></div>
        <div id="cpr-out-${p.id}"></div>
      </div>
    </details>`).join('');
}

function createPipeline() {
  _editingPipelineId = null;
  _pbSteps = [];
  $('pb-name').value = '';
  $('pb-desc').value = '';
  $('pb-input').value = '';
  $('pb-prog').textContent = 'Creating a new pipeline draft.';
  renderBuilderSteps();
  $('pipe-builder-card').open = true;
  $('pipe-builder-card').scrollIntoView({behavior:'smooth', block:'start'});
}

function pbAddStep() {
  const sel = $('pb-add-type');
  if (!sel) return;
  const type = sel.value;
  const typeDef = _stepTypes.find(t => t.type === type);
  if (!typeDef) return;
  const step = { type, label: typeDef.label, params: {} };
  // Set defaults from param schema
  (typeDef.params || []).forEach(([key, , , def]) => { if (def) step.params[key] = def; });
  _pbSteps.push(step);
  renderBuilderSteps();
}

function pbRemoveStep(idx) {
  _pbSteps.splice(idx, 1);
  renderBuilderSteps();
}

function pbMoveStep(idx, dir) {
  const to = idx + dir;
  if (to < 0 || to >= _pbSteps.length) return;
  [_pbSteps[idx], _pbSteps[to]] = [_pbSteps[to], _pbSteps[idx]];
  renderBuilderSteps();
}

function renderBuilderSteps() {
  const container = $('pb-steps');
  if (!container) return;
  container.innerHTML = _pbSteps.map((step, i) => {
    const typeDef = _stepTypes.find(t => t.type === step.type) || {params:[]};
    const paramFields = (typeDef.params || []).map(([key, inputType, label, def]) => {
      const v = step.params[key] ?? def ?? '';
      const hint = 'Use {{input}}, {{story}}, {{step' + i + '.output}}, {{step' + i + '.url}}, or other prior step fields.';
      if (inputType === 'textarea')
        return `<div class="pb-step-param"><label title="${hint}">${label}</label><textarea class="fi" rows="2" onchange="_pbSteps[${i}].params['${key}']=this.value">${v}</textarea></div>`;
      if (inputType === 'checkbox')
        return `<div class="pb-step-param"><label>${label}</label><input type="checkbox" ${v?'checked':''} onchange="_pbSteps[${i}].params['${key}']=this.checked"></div>`;
      if (inputType.startsWith('select:')) {
        const opts = inputType.slice(7).split('|').map(o => `<option value="${o}" ${o===v?'selected':''}>${o}</option>`).join('');
        return `<div class="pb-step-param"><label>${label}</label><select class="fselect" style="font-size:12px" onchange="_pbSteps[${i}].params['${key}']=this.value">${opts}</select></div>`;
      }
      if (inputType === 'ref')
        return `<div class="pb-step-param"><label title="Use {{ '{{' }}input{{ '}}' }}, {{ '{{' }}story{{ '}}' }}, or {{ '{{' }}stepN.url{{ '}}' }} / {{ '{{' }}stepN.output{{ '}}' }}">${label}</label><input class="fi" value="${v}" placeholder="{{ '{{' }}step${i>0?i-1:0}.url{{ '}}' }} or {{ '{{' }}input{{ '}}' }}" onchange="_pbSteps[${i}].params['${key}']=this.value"></div>`;
      return `<div class="pb-step-param"><label>${label}</label><input type="${inputType==='number'?'number':'text'}" class="fi" value="${v}" onchange="_pbSteps[${i}].params['${key}']=this.value"></div>`;
    }).join('');
    return `<div class="pb-step">
      <div class="pb-step-header">
        <span style="background:var(--accent-s);color:var(--accent);border-radius:4px;padding:.1rem .4rem;font-size:11px">${i}</span>
        <span style="flex:1">${step.label || step.type}</span>
        <button class="btn btn-ghost btn-sm" style="padding:.1rem .3rem" onclick="pbMoveStep(${i},-1)" ${i===0?'disabled':''}>↑</button>
        <button class="btn btn-ghost btn-sm" style="padding:.1rem .3rem" onclick="pbMoveStep(${i},1)" ${i===_pbSteps.length-1?'disabled':''}>↓</button>
        <button class="btn btn-ghost btn-sm" style="padding:.1rem .3rem;color:var(--red)" onclick="pbRemoveStep(${i})">✕</button>
      </div>
      <div class="frow" style="margin-bottom:.1rem"><label class="fl" style="font-size:11px">Label</label><input class="fi" style="font-size:12px" value="${step.label||''}" placeholder="${step.type}" onchange="_pbSteps[${i}].label=this.value"></div>
      <div class="pb-step-params">${paramFields}</div>
    </div>`;
  }).join('');
}

function _pbCollect() {
  return {
    id: _editingPipelineId || undefined,
    name: val('pb-name') || 'Untitled Pipeline',
    description: val('pb-desc') || '',
    steps: _pbSteps.map(s => ({ type: s.type, label: s.label, params: {...s.params} })),
    input: val('pb-input') || '',
  };
}

async function pbSave() {
  const def = _pbCollect();
  $('pb-prog').textContent = 'Saving…';
  try {
    let res;
    if (_editingPipelineId) {
      res = await dashboardFetch(buildStudioUrl(`/pipelines/custom/${_editingPipelineId}`), {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(def)}).then(r => r.json());
    } else {
      res = await dashboardFetch(buildStudioUrl('/pipelines/custom'), {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(def)}).then(r => r.json());
      _editingPipelineId = res.pipeline?.id;
    }
    _customPipelines = (await dashboardFetch(buildStudioUrl('/pipelines/custom')).then(r => r.json())).pipelines || [];
    renderCustomPipelineCards();
    $('pb-prog').textContent = 'Saved ✓';
  } catch(e) { $('pb-prog').textContent = 'Error: '+e.message; }
}

async function pbRun() {
  const def = _pbCollect();
  $('pb-prog').textContent = 'Running…';
  $('pb-out').innerHTML = '';
  try {
    const d = await post('/pipelines/run', {...def, input: val('pb-input')});
    _renderPipelineResult('pb-out', 'pb-prog', d);
  } catch(e) { $('pb-prog').textContent = 'Error: '+e.message; }
}

async function pbSaveAndRun() { await pbSave(); await pbRun(); }

async function runCustomPipeline(id) {
  const prog = $(`cpr-prog-${id}`), out = $(`cpr-out-${id}`);
  if (prog) prog.textContent = 'Running…';
  if (out) out.innerHTML = '';
  try {
    const input = val(`cpr-input-${id}`) || '';
    const d = await post(`/pipelines/custom/${id}/run`, {input});
    _renderPipelineResult(`cpr-out-${id}`, `cpr-prog-${id}`, d);
  } catch(e) { if (prog) prog.textContent = 'Error: '+e.message; }
}

function editCustomPipeline(id) {
  const p = _customPipelines.find(x => x.id === id);
  if (!p) return;
  _editingPipelineId = id;
  $('pb-name').value = p.name || '';
  $('pb-desc').value = p.description || '';
  _pbSteps = p.steps.map(s => ({...s, params:{...s.params}}));
  renderBuilderSteps();
  renderCustomPipelineCards();
  $('pipe-builder-card').open = true;
  $('pipe-builder-card').scrollIntoView({behavior:'smooth'});
  $('pb-prog').textContent = `Editing "${p.name}"`;
}

async function deleteCustomPipeline(id) {
  if (!confirm('Delete this pipeline?')) return;
  try {
    await dashboardFetch(buildStudioUrl(`/pipelines/custom/${id}`), {method:'DELETE'});
    _customPipelines = _customPipelines.filter(p => p.id !== id);
    if (_editingPipelineId === id) { _editingPipelineId = null; _pbSteps = []; renderBuilderSteps(); }
    renderCustomPipelineCards();
  } catch(e) { alert('Delete failed: '+e.message); }
}

function _renderPipelineResult(outId, progId, d) {
  const steps = d.steps || [];
  const last = steps[steps.length - 1] || {};
  // Show each step result
  const html = steps.map(s => {
    if (s.error) return `<div style="font-size:12px;color:var(--red);margin:.2rem 0">Step ${s.step} (${s.label}): ${s.error}</div>`;
    let media = '';
    if (s.url && s.url.match(/\.(mp4|webm)/i)) media = `<video controls src="${s.url}" style="max-width:100%;max-height:200px;border-radius:6px;margin-top:.3rem"></video>`;
    else if (s.url) media = `<img src="${s.url}" style="max-width:100%;max-height:200px;border-radius:6px;margin-top:.3rem">`;
    else if (s.b64_wav) media = `<audio controls src="data:audio/wav;base64,${s.b64_wav}" style="width:100%;margin-top:.3rem"></audio>`;
    else if (s.output) media = `<pre style="font-size:11px;white-space:pre-wrap;background:var(--surface-2);padding:.4rem;border-radius:4px;margin-top:.2rem">${s.output.substring(0,400)}${s.output.length>400?'…':''}</pre>`;
    return `<div style="font-size:12px;color:var(--text-2);margin:.2rem 0"><strong style="color:var(--text)">${s.label||s.type}</strong>${media}</div>`;
  }).join('');
  const out = $(outId);
  if (out) out.innerHTML = `<div style="display:flex;flex-direction:column;gap:.2rem;margin-top:.4rem">${html}</div>`;
  const prog = $(progId);
  if (prog) prog.textContent = steps.some(s => s.error) ? 'Completed with errors' : 'Done ✓';
}

// ─────────────────────────────────────────────────────────────────
//  Role picker (multi-cap sidebar assignment)
// ─────────────────────────────────────────────────────────────────
function showRolePicker(sub, model) {
  return;
}

function _rolePickerOutside(e) {
  const popup = $('role-picker-popup');
  if (popup && !popup.contains(e.target)) closeRolePicker();
  else if (popup) document.addEventListener('click', _rolePickerOutside, { once: true });
}

function closeRolePicker() {
  const popup = $('role-picker-popup');
  if (popup) popup.remove();
  document.removeEventListener('click', _rolePickerOutside);
}

// ─────────────────────────────────────────────────────────────────
//  Archive
// ─────────────────────────────────────────────────────────────────
let _archiveFilter = 'all';
let _archiveFiles = [];

async function loadArchive() {
  const grid = $('archive-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="arch-empty">Loading…</div>';
  try {
    const data = await (await dashboardFetch(buildStudioUrl('/archive'))).json();
    _archiveFiles = data.files || [];
    renderArchive();
  } catch(e) {
    grid.innerHTML = `<div class="arch-empty">Error loading archive: ${escapeHtml(e.message)}</div>`;
  }
}

function archiveSetFilter(type) {
  _archiveFilter = type;
  document.querySelectorAll('.arch-filter').forEach(b =>
    b.classList.toggle('active', b.dataset.type === type));
  renderArchive();
}

function renderArchive() {
  const grid = $('archive-grid');
  if (!grid) return;
  const files = _archiveFilter === 'all'
    ? _archiveFiles
    : _archiveFiles.filter(f => f.type === _archiveFilter);
  if (!files.length) {
    const msg = _archiveFiles.length
      ? 'No files match the filter.'
      : 'No generated files found. Set --file-path to save outputs to disk.';
    grid.innerHTML = `<div class="arch-empty">${msg}</div>`;
    return;
  }
  grid.innerHTML = files.map(f => {
    const date = new Date(f.created * 1000).toLocaleString([], {
      month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'
    });
    const size = f.size > 1048576
      ? (f.size / 1048576).toFixed(1) + ' MB'
      : Math.round(f.size / 1024) + ' KB';
    const thumb = f.type === 'image'
      ? `<img class="arch-thumb" src="${escapeHtml(f.url)}" onclick="window.open('${escapeHtml(f.url)}')" loading="lazy">`
      : `<div class="arch-thumb-ph">${f.type === 'video' ? '[video]' : '[audio]'}</div>`;
    const playBtn = f.type !== 'image'
      ? `<button class="arch-btn" onclick="archivePlay(${JSON.stringify(f).replace(/"/g,'&quot;')})">Play</button>`
      : '';
    const safeUrl = escapeHtml(f.url);
    const safeName = escapeHtml(f.filename);
    return `<div class="arch-card">
      ${thumb}
      <div class="arch-info">
        <div class="arch-name" title="${safeName}">${safeName}</div>
        <div class="arch-meta">${date} &middot; ${size}</div>
      </div>
      <div class="arch-actions">
        <a class="arch-btn" href="${safeUrl}" download="${safeName}">Download</a>
        ${playBtn}
        <button class="arch-btn del" onclick="archiveDelete('${safeName}')">Delete</button>
      </div>
    </div>`;
  }).join('');
}

async function archiveDelete(filename) {
  if (!confirm(`Delete ${filename}?`)) return;
  try {
    const r = await dashboardFetch(buildStudioUrl(`/archive/${encodeURIComponent(filename)}`), { method: 'DELETE' });
    if (!r.ok) throw new Error((await r.json()).detail || 'Delete failed');
    _archiveFiles = _archiveFiles.filter(f => f.filename !== filename);
    renderArchive();
  } catch(e) {
    alert('Delete failed: ' + e.message);
  }
}

function archivePlay(file) {
  const w = window.open('', '_blank', 'width=820,height=520');
  if (!w) return;
  const tag = file.type === 'video'
    ? `<video src="${escapeHtml(file.url)}" controls autoplay style="max-width:100%;max-height:100vh"></video>`
    : `<audio src="${escapeHtml(file.url)}" controls autoplay></audio>`;
  w.document.write(`<!doctype html><html><body style="margin:0;background:#000;display:flex;align-items:center;justify-content:center;height:100vh">${tag}</body></html>`);
}
