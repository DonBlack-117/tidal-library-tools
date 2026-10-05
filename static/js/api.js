// Cliente del servidor. Los errores llegan como {"error": {"code", "message"}}.

export class ApiError extends Error {
  constructor(message, code, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function errorFrom(response) {
  const body = await response.json().catch(() => null);
  return new ApiError(body?.error?.message || `Error del servidor (${response.status})`,
                      body?.error?.code || 'HTTP_ERROR', response.status);
}

async function request(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new ApiError('No hay conexión con el servidor', 'NETWORK_ERROR', 0);
  }
  if (!response.ok) throw await errorFrom(response);
  return response;
}

export async function getJSON(url) {
  return (await request(url)).json();
}

/** POST con JSON: el servidor rechaza cualquier otro tipo (protección contra otras páginas). */
export function postJSON(url, body = {}) {
  return request(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * Lee un stream SSE del servidor. Llama a onLine por cada línea y devuelve el
 * código de salida (null si el stream se cortó antes de terminar).
 */
export async function readEvents(response, onLine, onReader) {
  const reader = response.body.getReader();
  onReader?.(reader);
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) return null;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data: ')) continue;
      let data;
      try { data = JSON.parse(line.slice(6)); } catch { continue; }
      if (data.line !== undefined) onLine(data.line);
      if (data.done) return data.code;
    }
  }
}
