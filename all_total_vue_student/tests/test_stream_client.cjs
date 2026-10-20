// node --test tests/test_stream_client.cjs (Node 18+ built-in Web Streams)
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
global.window = {};
vm.runInThisContext(fs.readFileSync(path.join(__dirname, '../assets/generation-stream.js'), 'utf8'));
const client = window.KharakteresStream;

function response(text) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({
    start(controller) {
      // Split every UTF-8 byte, including within Korean syllables and CRLF separators.
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
      controller.close();
    },
  }), { headers: { 'Content-Type': 'text/event-stream' } });
}

test('UTF-8 fragments, comments and CRLF preserve event order and Korean text', async () => {
  global.fetch = async () => response(': heartbeat\r\n\r\nevent: token\r\ndata: {"text":"빛"}\r\n\r\nevent: done\r\ndata: {"draft":{"name":"빛의 서약"}}\r\n\r\n');
  const events = [];
  const result = await client.generate({}, undefined, (kind, data) => events.push([kind, data]));
  assert.equal(events[0][1].text, '빛');
  assert.deepEqual(events.map(x => x[0]), ['token', 'done']);
  assert.equal(result.draft.name, '빛의 서약');
});

test('transport EOF never becomes a completed draft and is not retried', async () => {
  let calls = 0;
  global.fetch = async () => { calls++; return response('event: token\ndata: {"text":"partial"}\n\n'); };
  await assert.rejects(client.generate({}, undefined, () => {}), /완료 전에 연결/);
  assert.equal(calls, 1);
});

test('provider error is surfaced without accepting a previous partial preview', async () => {
  global.fetch = async () => response('event: error\ndata: {"message":"검사 실패","clear_preview":true}\n\n');
  await assert.rejects(client.generate({}, undefined, () => {}), /검사 실패/);
});

test('partial structured fields decode escapes without needing complete JSON', () => {
  const output = client.fields('{"name":"빛\\n서약","incantation":"\\ube5b이여,');
  assert.equal(output[0].value, '빛\n서약');
  assert.equal(output[1].value, '빛이여,');
  assert.equal(client.fields('{"name":"\\uBE')[0], undefined);
});
