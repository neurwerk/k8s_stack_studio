import { apiGet } from "./client";

export interface VersionInfo {
  version: string;
}

export async function fetchVersion(): Promise<VersionInfo> {
  return apiGet<VersionInfo>("/version");
}
