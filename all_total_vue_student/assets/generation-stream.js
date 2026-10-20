/* POST-based SSE client: preserves UTF-8 across network chunks, never auto-retries a paid request. */
(() => {
  async function generate(payload, signal, onEvent) {
    const response = await fetch('/api/generate/stream', {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(payload), signal,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const detail = body?.detail;
      throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail)
        ? detail.map(x => `${x.loc.at(-1)}: ${x.msg}`).join(' / ')
        : detail?.message || '주문 생성 요청을 처리하지 못했습니다.');
    }
    if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream'))
      throw new Error('실시간 연결을 열지 못했습니다. 서버를 재시작하고 다시 시도해 주세요.');
    const reader = response.body.getReader(), decoder = new TextDecoder();
    let buffer = '', result = null;
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
        let match;
        while ((match = /\r?\n\r?\n/.exec(buffer))) {
          const frame = buffer.slice(0, match.index);
          buffer = buffer.slice(match.index + match[0].length);
          let kind = 'message';
          const lines = [];
          for (const line of frame.split(/\r?\n/)) {
            if (line.startsWith('event:')) kind = line.slice(6).trim();
            if (line.startsWith('data:')) lines.push(line.slice(5).replace(/^ /, ''));
          }
          if (!lines.length) continue;
          const data = JSON.parse(lines.join('\n'));
          await onEvent(kind, data);
          if (kind === 'error') throw new Error(data.message || '주문 생성에 실패했습니다.');
          if (kind === 'done') { result = data; return result; }
        }
        if (buffer.length > 256000) throw new Error('실시간 응답이 너무 큽니다.');
        if (done) break;
      }
      throw new Error('완료 전에 연결이 끊어졌습니다. 저장하지 않았으니 다시 시도해 주세요.');
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  function fields(text) {
    const labels = { name: '주문 이름', incantation: '주문문', romanization: '로마자',
      hangul_pronunciation: '한글 전사', ipa: 'IPA', pronunciation_note: '발음 관례',
      literal_meaning: '의미', effect: '효과', limitations: '제약', notes: '메모' };
    const found = [];
    const re = /"(name|incantation|romanization|hangul_pronunciation|ipa|pronunciation_note|literal_meaning|effect|limitations|notes)"\s*:\s*"((?:\\.|[^"\\])*)/g;
    for (const match of text.matchAll(re)) {
      let raw = match[2], value;
      // Incomplete Unicode escapes are held until the following network delta.
      raw = raw.replace(/\\u[\da-fA-F]{0,3}$/, '');
      try { value = JSON.parse('"' + raw + '"'); } catch { continue; }
      if (value) found.push({ key: match[1], label: labels[match[1]], value });
    }
    return found;
  }
  window.KharakteresStream = { generate, fields };
})();
