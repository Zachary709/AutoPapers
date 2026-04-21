export async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("Content-Type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    const message = isJson && payload.error ? payload.error : response.statusText;
    const error = new Error(message);
    error.status = response.status;
    error.path = path;
    throw error;
  }
  return payload;
}

export function describeTaskApiError(error, prefix) {
  const path = typeof error?.path === "string" ? error.path : "";
  if (error?.status === 404 && path.startsWith("/api/tasks/")) {
    return `${prefix}：任务已不存在于服务端（404）。这通常表示 Web 服务刚刚重启，内存中的任务状态已经丢失。`;
  }
  return prefix ? `${prefix}：${error.message}` : error.message;
}
