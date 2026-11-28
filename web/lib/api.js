export class ApiError extends Error {
  constructor(message, payload = {}, status = null) {
    super(message);
    this.name = "ApiError";
    this.payload = payload;
    this.status = status;
  }
}

export async function fetchJson(url, options = {}) {
  const { timeoutMs = 120000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      signal: controller.signal,
    });
    const text = await response.text();
    let payload = {};

    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (_error) {
        throw new ApiError(
          response.ok
            ? "服务器返回了无法解析的数据。"
            : `请求失败 (${response.status})`,
          {},
          response.status,
        );
      }
    }

    if (!response.ok) {
      throw new ApiError(
        payload.error || `请求失败 (${response.status})`,
        payload,
        response.status,
      );
    }

    return payload;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("请求超时，请稍后重试。");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export const api = {
  config: () => fetchJson("/api/config/public"),
  knowledge: () => fetchJson("/api/kb/stats"),
  document: (id, offset = 0) =>
    fetchJson(
      "/api/kb/document/" + encodeURIComponent(id) + "?offset=" + offset,
    ),
};
