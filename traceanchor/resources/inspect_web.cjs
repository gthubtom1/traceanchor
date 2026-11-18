'use strict';
// Owned helper: finite fixture dispatch, actual V8 inspector and loopback HTTP.
// No scenario-supplied code/eval, browser profile, external URL or shell command.
const fs = require('node:fs');
const crypto = require('node:crypto');
const http = require('node:http');
const inspector = require('node:inspector');
const {pathToFileURL} = require('node:url');

const trace = {schema_version: 1, status: 'failed', node_version: process.version,
  steps: [], network: [], inspector: {methods: [], pauses: [], function_coverage: [], source_verified: false},
  cleanup: {server: 'not-started', inspector: 'not-started'}};
const session = new inspector.Session();
const scripts = new Map();
let server, activeStep = null, activeProbe = null, baseUrl, targetUrl, sourceText = '';
let connected = false;

function bounded(value, cap = 65536) {
  const text = JSON.stringify(value, (key, item) => {
    if (typeof item === 'number' && !Number.isFinite(item)) throw new Error('Non-finite JSON observation');
    if (['undefined', 'function', 'symbol', 'bigint'].includes(typeof item)) throw new Error('Non-JSON observation');
    return item;
  });
  if (typeof text !== 'string' || Buffer.byteLength(text) > cap) throw new Error('JSON observation budget exceeded');
  return JSON.parse(text);
}
function errorData(error) {
  return {name: String(error?.name || 'Error'), message: String(error?.message || error).slice(0, 2000),
    ...(typeof error?.code === 'string' ? {code: error.code.slice(0, 100)} : {})};
}
function post(method, params = {}) {
  trace.inspector.methods.push(method);
  return new Promise((resolve, reject) => session.post(method, params, (err, result) => err ? reject(err) : resolve(result)));
}
function frameLocation(frame) {
  const location = frame.location || {};
  return {function: frame.functionName, url: scripts.get(location.scriptId)?.url || frame.url || '',
    script_id: location.scriptId, line: location.lineNumber + 1, column: location.columnNumber + 1};
}
session.on('Debugger.scriptParsed', ({params}) => scripts.set(params.scriptId, params));
session.on('Debugger.paused', ({params}) => {
  // Self-debugging callbacks must resume synchronously, never await in this event.
  const frames = params.callFrames.slice(0, 24).map(frameLocation);
  const targetFrames = frames.filter(frame => frame.url === targetUrl);
  if (trace.inspector.pauses.length < 160) {
    trace.inspector.pauses.push({step_id: activeStep, probe: activeProbe?.kind || 'dispatch-entry',
      network_id: activeProbe?.network_id || null, reason: params.reason, frames, target_frames: targetFrames});
  } else trace.inspector.pauses_truncated = true;
  if (activeProbe?.network_id) {
    const request = trace.network.find(item => item.id === activeProbe.network_id);
    if (request) request.request_stack = targetFrames;
  }
  session.post('Debugger.resume');
});
function probe(kind, networkId = null) {
  activeProbe = {kind, network_id: networkId};
  trace.inspector.methods.push('Debugger.pause');
  let failure;
  session.post('Debugger.pause', {}, err => {failure = err;});
  activeProbe = null;
  if (failure) throw failure;
}
async function bodyBytes(incoming) {
  const chunks = []; let count = 0;
  for await (const chunk of incoming) {
    count += chunk.length;
    if (count > 65536) throw new Error('HTTP request body exceeds 64 KiB');
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}
async function request(method, path, body = undefined) {
  if (!['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method) || typeof path !== 'string') throw new Error('Unsupported fixture request');
  const url = new URL(path, baseUrl);
  if (url.origin !== baseUrl || url.username || url.password || url.hash) throw new Error('Only owned loopback fixture origin is admitted');
  if (trace.network.length >= 36) throw new Error('Network observation count exceeded');
  const id = `request-${trace.network.length + 1}`;
  const entry = {id, step_id: activeStep, method, path: url.pathname + url.search,
    body: body === undefined ? null : bounded(body), request_stack: [], received: false};
  trace.network.push(entry);
  probe('http-request', id);
  const headers = {'x-traceanchor-request': id};
  const options = {method, headers, redirect: 'error', signal: AbortSignal.timeout(2000)};
  if (body !== undefined) {headers['content-type'] = 'application/json'; options.body = JSON.stringify(bounded(body));}
  const response = await fetch(url, options);
  const reader = response.body.getReader(); let count = 0; const chunks = [];
  try {
    for (;;) {
      const part = await reader.read(); if (part.done) break;
      count += part.value.byteLength;
      if (count > 65536) throw new Error('HTTP response body exceeds 64 KiB');
      chunks.push(Buffer.from(part.value));
    }
  } finally {await reader.cancel();}
  const text = Buffer.concat(chunks).toString('utf8');
  entry.response = {status: response.status, body: JSON.parse(text)};
  return bounded(entry.response);
}
function position(offset) {
  const prefix = sourceText.slice(0, offset); const line = prefix.split('\n').length;
  return {line, column: offset - prefix.lastIndexOf('\n')};
}
async function main() {
  const input = Buffer.alloc(131073); let length = 0;
  for (;;) {
    const count = fs.readSync(0, input, length, input.length - length, null);
    if (!count) break;
    length += count;
    if (length === input.length) throw new Error('Helper input exceeds 128 KiB');
  }
  const config = JSON.parse(input.subarray(0, length).toString('utf8'));
  if (typeof config.target !== 'string' || !Array.isArray(config.scenario?.steps) || config.scenario.steps.length > 12) throw new Error('Invalid finite scenario');
  const source = fs.readFileSync(config.target);
  if (source.length > 1048576) throw new Error('Target source exceeds 1 MiB');
  trace.source_sha256 = crypto.createHash('sha256').update(source).digest('hex');
  targetUrl = pathToFileURL(config.target).href;
  session.connect(); connected = true; trace.cleanup.inspector = 'pending';
  await post('Runtime.enable'); await post('Debugger.enable');
  await post('Debugger.setAsyncCallStackDepth', {maxDepth: 12});
  await post('Profiler.enable');
  await post('Profiler.startPreciseCoverage', {callCount: true, detailed: true});
  const module = await import(targetUrl);
  if (typeof module.createSession !== 'function' || typeof module.createService !== 'function') throw new Error('Target must export createSession and createService fixture factories');
  const script = [...scripts.values()].find(item => item.url === targetUrl);
  if (!script) throw new Error('Inspector did not observe target module');
  const inspected = await post('Debugger.getScriptSource', {scriptId: script.scriptId});
  sourceText = inspected.scriptSource;
  trace.inspector.source_sha256 = crypto.createHash('sha256').update(sourceText).digest('hex');
  trace.inspector.source_verified = trace.inspector.source_sha256 === trace.source_sha256;
  trace.inspector.target = {url: targetUrl, script_id: script.scriptId, source_length: sourceText.length};
  const service = await module.createService();
  if (typeof service.handle !== 'function' || typeof service.snapshot !== 'function') throw new Error('Invalid service fixture interface');
  server = http.createServer(async (incoming, outgoing) => {
    let entry;
    try {
      const id = incoming.headers['x-traceanchor-request'];
      entry = trace.network.find(item => item.id === id);
      const raw = await bodyBytes(incoming);
      const received = {method: incoming.method, path: incoming.url, body: raw ? JSON.parse(raw) : null};
      if (entry) {entry.received = true; entry.server_request = received; entry.service_before = bounded(await service.snapshot());}
      else trace.inspector.uncorrelated_request = true;
      const answer = bounded(await service.handle(received));
      if (!Number.isInteger(answer.status) || answer.status < 200 || answer.status > 599) throw new Error('Invalid fixture HTTP status');
      if (entry) {entry.service_after = bounded(await service.snapshot()); entry.server_response = answer;}
      outgoing.writeHead(answer.status, {'content-type': 'application/json', 'connection': 'close'});
      outgoing.end(JSON.stringify(answer.body));
    } catch (error) {
      if (entry) entry.server_error = errorData(error);
      outgoing.writeHead(500, {'content-type': 'application/json', 'connection': 'close'});
      outgoing.end(JSON.stringify({error: 'fixture-service-failed'}));
    }
  });
  await new Promise((resolve, reject) => {server.once('error', reject); server.listen(0, '127.0.0.1', resolve);});
  trace.cleanup.server = 'pending';
  baseUrl = `http://127.0.0.1:${server.address().port}`;
  trace.origin = baseUrl;
  const client = await module.createSession({request, baseUrl});
  if (typeof client.dispatch !== 'function' || typeof client.snapshot !== 'function') throw new Error('Invalid session fixture interface');
  // Fixed helper expression only: the scenario supplies data, never expressions.
  const slot = '__traceanchor_inspected_dispatch__';
  globalThis[slot] = client.dispatch;
  let breakpoint;
  try {
    const remote = await post('Runtime.evaluate', {expression: 'globalThis.__traceanchor_inspected_dispatch__', objectGroup: 'traceanchor'});
    if (!remote.result.objectId) throw new Error('Inspector could not resolve dispatch function');
    breakpoint = await post('Debugger.setBreakpointOnFunctionCall', {objectId: remote.result.objectId});
  } finally {delete globalThis[slot];}
  for (const step of config.scenario.steps) {
    activeStep = step.id;
    const before = bounded(await client.snapshot());
    let outcome, returned;
    try {returned = await client.dispatch(bounded(step.action));}
    catch (error) {outcome = {status: 'threw', error: errorData(error)};}
    // A serialization/collection failure is not a target business exception.
    if (!outcome) outcome = {status: 'returned', value: bounded(returned)};
    const after = bounded(await client.snapshot());
    trace.steps.push({id: step.id, action: bounded(step.action), before, outcome, after,
      network_ids: trace.network.filter(item => item.step_id === step.id).map(item => item.id)});
  }
  activeStep = null;
  await post('Debugger.removeBreakpoint', {breakpointId: breakpoint.breakpointId});
  const coverage = await post('Profiler.takePreciseCoverage');
  for (const scriptCoverage of coverage.result.filter(item => item.url === targetUrl)) {
    for (const fn of scriptCoverage.functions) {
      const range = fn.ranges[0];
      if (range && range.count > 0) trace.inspector.function_coverage.push({name: fn.functionName || '<module>',
        script_id: scriptCoverage.scriptId, url: targetUrl, start: position(range.startOffset),
        end: position(range.endOffset), calls: range.count,
        executed_ranges: fn.ranges.filter(item => item.count > 0).slice(0, 32).map(item => ({start: position(item.startOffset), end: position(item.endOffset), count: item.count}))});
    }
  }
  await post('Profiler.stopPreciseCoverage'); await post('Runtime.releaseObjectGroup', {objectGroup: 'traceanchor'});
  trace.final_service_state = bounded(await service.snapshot());
  if (trace.inspector.pauses_truncated || trace.inspector.uncorrelated_request) throw new Error('Runtime observation coverage incomplete');
  trace.status = 'completed';
}
(async () => {
  try {await main();}
  catch (error) {trace.error = errorData(error); process.exitCode = 1;}
  finally {
    if (server) {
      try {await new Promise(resolve => {server.close(resolve); server.closeAllConnections();}); trace.cleanup.server = 'complete';}
      catch (error) {trace.cleanup.server = 'failed'; trace.cleanup.error = errorData(error); process.exitCode = 1;}
    }
    if (connected) {session.disconnect(); trace.cleanup.inspector = 'complete';}
    const text = JSON.stringify(trace);
    if (Buffer.byteLength(text) > 4 * 1024 * 1024) {
      process.exitCode = 1;
      process.stdout.write(JSON.stringify({schema_version: 1, status: 'failed', error: {message: 'Trace output budget exceeded'}, cleanup: trace.cleanup}) + '\n');
    } else process.stdout.write(text + '\n');
  }
})();
