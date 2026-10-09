import { apiClient } from "../lib/apiClient";
import type {
  ResearchProvider,
  ResearchCapabilities,
  ResearchDetail,
  ResearchRun,
  ResearchSession,
} from "../types";

export async function capabilities(): Promise<ResearchCapabilities> {
  return (await apiClient.get<ResearchCapabilities>("/research/capabilities")).data;
}
export async function listSessions(offset = 0): Promise<ResearchSession[]> {
  return (
    await apiClient.get<ResearchSession[]>("/research/sessions", { params: { offset, limit: 50 } })
  ).data;
}
export async function createSession(): Promise<ResearchSession> {
  return (await apiClient.post<ResearchSession>("/research/sessions", {})).data;
}
export async function getSession(id: string): Promise<ResearchDetail> {
  return (await apiClient.get<ResearchDetail>(`/research/sessions/${id}`)).data;
}
export async function renameSession(id: string, title: string): Promise<ResearchSession> {
  return (await apiClient.patch<ResearchSession>(`/research/sessions/${id}`, { title })).data;
}
export async function deleteSession(id: string): Promise<void> {
  await apiClient.delete(`/research/sessions/${id}`);
}
export async function submitMessage(
  id: string,
  prompt: string,
  requestId: string,
  provider: ResearchProvider,
): Promise<ResearchRun> {
  return (
    await apiClient.post<ResearchRun>(`/research/sessions/${id}/messages`, {
      prompt,
      provider,
      request_id: requestId,
    })
  ).data;
}
export async function cancelRun(id: string): Promise<ResearchRun> {
  return (await apiClient.post<ResearchRun>(`/research/runs/${id}/cancel`)).data;
}
