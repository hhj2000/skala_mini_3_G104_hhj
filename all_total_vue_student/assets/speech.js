/* Kharakteres audio UI. Original audio stays in memory until explicitly sent for STT. */
(() => {
  const { ref, computed, watch, onBeforeUnmount } = Vue;
  async function errorMessage(response) {
    try {
      const value = (await response.json()).detail;
      return typeof value === 'string' ? value : value?.message || '입력 내용을 확인해 주세요.';
    } catch { return '음성 요청을 처리하지 못했습니다.'; }
  }
  function release(url) { if (url) URL.revokeObjectURL(url); }
  const VoiceInput = {
    props: ['config', 'targets'], emits: ['apply'],
    setup(props, { emit }) {
      const recording = ref(false), requesting = ref(false), stopping = ref(false), busy = ref(false);
      const error = ref(''), elapsed = ref(0), transcript = ref(''), target = ref(props.targets?.[0]?.key || 'prompt');
      const language = ref('ko'), audioUrl = ref(''), hasAudio = ref(false);
      let recorder, stream, timer, audioBlob, abort, disposed = false;
      const enabled = computed(() => Boolean(props.config?.enabled));
      function stopTracks() { stream?.getTracks().forEach(track => track.stop()); stream = null; }
      function stop() {
        clearInterval(timer);
        if (recorder?.state === 'recording') { stopping.value = true; recorder.stop(); }
        recording.value = false;
        // Keep tracks alive until MediaRecorder has flushed its final data event.
        if (!stopping.value) stopTracks();
      }
      function setAudio(blob) {
        release(audioUrl.value);
        audioBlob = blob; hasAudio.value = !!blob;
        audioUrl.value = blob ? URL.createObjectURL(blob) : '';
        transcript.value = '';
      }
      async function start() {
        if (requesting.value || recording.value || stopping.value || busy.value) return;
        error.value = '';
        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
          error.value = '이 브라우저에서는 마이크 녹음을 지원하지 않습니다. localhost 또는 HTTPS에서 접속하거나 파일을 올려 주세요.'; return;
        }
        requesting.value = true;
        try {
          stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          if (disposed) { stopTracks(); return; }
          const mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm', 'audio/ogg'].find(type => MediaRecorder.isTypeSupported(type));
          recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
          const chunks = []; let size = 0;
          recorder.ondataavailable = event => { if (event.data.size) { chunks.push(event.data); size += event.data.size; if (size > 10 * 1024 * 1024) stop(); } };
          recorder.onstop = () => {
            stopping.value = false; stopTracks();
            if (!disposed) {
              const blob = new Blob(chunks, { type: recorder.mimeType || mime || 'audio/webm' });
              if (blob.size) setAudio(blob);
              else { setAudio(null); error.value = '녹음된 음성이 비어 있습니다. 잠시 말한 뒤 종료하거나 파일을 올려 주세요.'; }
            }
          };
          recorder.onerror = () => { error.value = '녹음 중 오류가 발생했습니다. 파일 업로드로 다시 시도해 주세요.'; stop(); };
          setAudio(null); elapsed.value = 0;
          recorder.start(250); recording.value = true;
          timer = setInterval(() => { elapsed.value++; if (elapsed.value >= 60) stop(); }, 1000);
        } catch (err) {
          stopTracks();
          error.value = err.name === 'NotAllowedError' ? '마이크 권한이 필요합니다. 브라우저의 사이트 설정에서 허용해 주세요.' : '마이크를 열지 못했습니다. 다른 앱의 사용 여부를 확인하거나 파일을 올려 주세요.';
        } finally { requesting.value = false; }
      }
      function upload(event) {
        const file = event.target.files?.[0]; event.target.value = '';
        if (!file) return;
        error.value = '';
        if (file.size > 10 * 1024 * 1024) { error.value = '음성 파일은 10MB 이하여야 합니다.'; return; }
        if (!file.size) { error.value = '비어 있는 파일입니다.'; return; }
        const ext = file.name.split('.').pop().toLowerCase();
        const mime = file.type || ({ wav: 'audio/wav', mp3: 'audio/mpeg', m4a: 'audio/mp4', mp4: 'video/mp4', ogg: 'audio/ogg', flac: 'audio/flac', webm: 'audio/webm' })[ext];
        if (!mime) { error.value = '지원하는 오디오 파일을 선택해 주세요.'; return; }
        setAudio(new Blob([file], { type: mime }));
      }
      async function transcribe() {
        if (!audioBlob || busy.value) return;
        busy.value = true; error.value = ''; abort = new AbortController();
        try {
          const response = await fetch('/api/audio/transcribe?language=' + encodeURIComponent(language.value), {
            method: 'POST', headers: { 'Content-Type': audioBlob.type }, body: audioBlob, signal: abort.signal,
          });
          if (!response.ok) throw new Error(await errorMessage(response));
          const data = await response.json();
          if (!disposed) transcript.value = data.text;
        } catch (err) { if (err.name !== 'AbortError') error.value = err.message; }
        finally { busy.value = false; }
      }
      function apply() { if (transcript.value.trim()) emit('apply', { target: target.value, text: transcript.value.trim() }); }
      watch(() => props.targets?.map(t => t.key).join('|'), () => {
        if (!props.targets?.some(t => t.key === target.value)) target.value = props.targets?.[0]?.key;
      });
      onBeforeUnmount(() => { disposed = true; abort?.abort(); clearInterval(timer); stop(); release(audioUrl.value); });
      return { enabled, recording, requesting, stopping, busy, error, elapsed, transcript, target, language, audioUrl, hasAudio, start, stop, upload, transcribe, apply };
    },
    template: `<details class="audio-tools voice-input">
      <summary>🎙 음성으로 입력하기 {{ recording ? '· 녹음 중 '+elapsed+'초' : '' }}</summary>
      <p class="hint">녹음 최대 60초 · 파일 10MB. 전사 실행 시 음성이 OpenAI로 전송되며 API 사용료가 발생합니다. 인공어·고전어 원음은 잘못 인식될 수 있으므로 결과를 확인하세요.</p>
      <p v-if="!enabled" class="hint">음성 기능은 OpenAI API 키가 있는 실제 실행 모드에서 사용할 수 있습니다.</p>
      <div class="audio-buttons">
        <button type="button" class="btn quiet small" @click="start" :disabled="!enabled || recording || requesting || stopping || busy">{{ requesting ? '마이크 여는 중…' : '마이크 녹음 시작' }}</button>
        <button v-if="recording" type="button" class="btn quiet small" @click="stop">녹음 종료 · {{ elapsed }}초</button>
        <label class="audio-upload">파일 올리기<input type="file" accept="audio/*,.m4a,.mp4,.webm,.ogg,.flac" @change="upload" :disabled="!enabled || recording || requesting || stopping || busy" aria-label="전사할 음성 파일" /></label>
      </div>
      <audio v-if="audioUrl" :src="audioUrl" controls aria-label="전사 전 녹음 확인"></audio>
      <div class="field"><label>말한 언어<select v-model="language" :disabled="busy"><option value="ko">한국어</option><option value="en">영어</option><option value="">자동 감지</option></select></label></div>
      <button type="button" class="btn quiet small" @click="transcribe" :disabled="!enabled || !hasAudio || busy || recording || stopping">{{ busy ? '음성 전사 중…' : '음성 전사 실행' }}</button>
      <div v-if="transcript" class="field"><label>전사 결과 · 수정 후 적용<textarea v-model="transcript" maxlength="14000" aria-label="음성 전사 결과"></textarea></label>
        <label>입력할 곳<select v-model="target" aria-label="음성 입력 대상"><option v-for="item in targets" :key="item.key" :value="item.key">{{ item.label }}</option></select></label>
        <button type="button" class="btn quiet small" @click="apply" :disabled="busy || !transcript.trim()">선택한 칸에 적용</button>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </details>`,
  };
  const SpellAudio = {
    props: ['spell', 'config'],
    setup(props) {
      const scope = ref('incantation'), text = ref(''), snippet = ref(''), voice = ref('coral'), speed = ref(1);
      const busy = ref(false), error = ref(''), audioUrl = ref(''), audioElement = ref(null), readingArea = ref(null);
      let abort, sequence = 0;
      const enabled = computed(() => Boolean(props.config?.enabled));
      const constructed = computed(() => props.spell?.language_kind === 'constructed');
      const spokenIncantation = computed(() => constructed.value ? props.spell?.hangul_pronunciation || '' : props.spell?.incantation || '');
      const content = computed(() => {
        const spell = props.spell || {};
        if (scope.value === 'incantation') return spokenIncantation.value;
        if (scope.value === 'pronunciation') return spell.hangul_pronunciation || spell.romanization || '';
        if (scope.value === 'meaning') return spell.literal_meaning || '';
        if (scope.value === 'effect') return spell.effect || '';
        return [['이름', spell.name], ['주문', spokenIncantation.value], ['의미', spell.literal_meaning], ['효과', spell.effect], ['대상', spell.target], ['제약', spell.limitations], ['메모', spell.notes]]
          .filter(([, value]) => value?.trim()).map(([label, value]) => label + '. ' + value).join('\n');
      });
      function resetAudio() { sequence++; abort?.abort(); busy.value = false; audioElement.value?.pause(); release(audioUrl.value); audioUrl.value = ''; }
      watch(content, value => { text.value = value; snippet.value = ''; error.value = ''; }, { immediate: true });
      watch([text, voice, speed], resetAudio);
      function select() { const area = readingArea.value; snippet.value = area ? area.value.slice(area.selectionStart, area.selectionEnd) : ''; }
      async function speak(selection) {
        const input = (selection ? snippet.value : text.value).trim();
        if (!input || busy.value || !enabled.value) return;
        resetAudio(); const current = sequence;
        abort = new AbortController(); busy.value = true; error.value = '';
        try {
          const response = await fetch('/api/audio/speech', { method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: input, voice: voice.value, speed: Number(speed.value) }), signal: abort.signal });
          if (!response.ok) throw new Error(await errorMessage(response));
          const blob = await response.blob();
          if (!blob.size) throw new Error('생성된 음성이 비어 있습니다. 다시 시도해 주세요.');
          if (current === sequence) audioUrl.value = URL.createObjectURL(blob);
        } catch (err) { if (err.name !== 'AbortError' && current === sequence) error.value = err.message; }
        finally { if (current === sequence) busy.value = false; }
      }
      onBeforeUnmount(resetAudio);
      return { enabled, constructed, scope, text, snippet, voice, speed, busy, error, audioUrl, audioElement, readingArea, select, speak, resetAudio };
    },
    template: `<details class="audio-tools spell-audio">
      <summary>🔊 주문과 기록을 음성으로 듣기</summary>
      <p class="hint">OpenAI TTS · API 사용료 발생 · AI가 생성한 음성입니다. 인공어는 작가가 지정한 발음을 읽으며, 고전어·IPA의 정확한 발음을 보장하지 않습니다.</p>
      <p v-if="!enabled" class="hint">음성 기능은 OpenAI API 키가 있는 실제 실행 모드에서 사용할 수 있습니다.</p>
      <div class="field"><label>읽을 범위<select v-model="scope" aria-label="음성 변환 범위"><option value="incantation">{{ constructed ? '주문 · 작가가 지정한 발음' : '주문 원문' }}</option><option value="pronunciation">한글 전사 · 지정 발음</option><option value="meaning">주문의 의미</option><option value="effect">마법의 효과</option><option value="full">전체 기록 · 이름·주문·의미·효과·제약·메모</option></select></label></div>
      <div class="field"><label>읽을 내용 · 원하는 부분을 드래그해 선택<textarea ref="readingArea" v-model="text" maxlength="14000" aria-label="음성으로 읽을 내용" @select="select" @keyup="select" @mouseup="select" @input="snippet=''" :disabled="busy"></textarea></label></div>
      <div class="form-grid"><div class="field"><label>음색<select v-model="voice" aria-label="TTS 음색" :disabled="busy"><option v-for="name in (config?.voices || ['coral'])" :value="name">{{ name }}</option></select></label></div><div class="field"><label>읽기 속도<select v-model="speed" aria-label="TTS 읽기 속도" :disabled="busy"><option :value="0.75">느리게 (0.75배)</option><option :value="1">보통 (1배)</option><option :value="1.25">빠르게 (1.25배)</option></select></label></div></div>
      <div class="audio-buttons"><button type="button" class="btn quiet small" @click="speak(true)" :disabled="!enabled || busy || !snippet.trim()">선택한 구절 변환</button><button type="button" class="btn quiet small" @click="speak(false)" :disabled="!enabled || busy || !text.trim()">{{ busy ? '음성 만드는 중…' : '읽을 내용 전체 변환' }}</button><button v-if="busy" type="button" class="btn quiet small" @click="resetAudio">대기 취소</button></div>
      <p class="hint">전체 기록을 고르면 선택한 기록 전체를 읽습니다. 긴 내용은 나눠 생성해 하나의 WAV로 제공합니다.</p>
      <audio v-if="audioUrl" ref="audioElement" :src="audioUrl" controls aria-label="AI 생성 주문 음성"></audio>
      <a v-if="audioUrl" :href="audioUrl" download="kharakteres-speech.wav" class="audio-download">음성 파일 내려받기</a>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
    </details>`,
  };
  window.KharakteresSpeechComponents = { VoiceInput, SpellAudio };
})();
