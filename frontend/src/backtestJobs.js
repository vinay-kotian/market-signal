import { request } from './api.js';

export function waitForPoll(signal, delay = 1500) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException('Aborted', 'AbortError')); return; }
    const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, delay);
    signal?.addEventListener('abort', abort, { once: true });
  });
}

export async function followBacktestJob(id, { signal, onProgress = () => {}, send = request, wait = waitForPoll } = {}) {
  for (;;) {
    const job = await send(`/backtests/jobs/${id}`, { signal });
    onProgress(job.message);
    if (job.status === 'FAILED') {
      const error = new Error(job.error || 'Backtest failed.');
      error.terminal = true;
      throw error;
    }
    if (job.status === 'COMPLETED') return send(`/backtests/jobs/${id}/result`, { signal });
    if (!['QUEUED', 'RUNNING'].includes(job.status)) throw new Error('Invalid backtest job status.');
    await wait(signal);
  }
}

export async function startBacktestJob(config, { compare = false, signal, onAccepted = () => {}, ...options } = {}) {
  const send = options.send ?? request;
  const job = await send(`/backtests/jobs${compare ? '?compare=true' : ''}`, {
    method: 'POST', body: JSON.stringify(config), signal,
  });
  onAccepted(job);
  return followBacktestJob(job.id, { ...options, signal, send });
}
