export type Role = "admin" | "viewer" | "guest";

export interface BuildingRef {
  id: string;
  name: string;
}

export interface User {
  id: string;
  login: string;
  full_name: string;
  role: Role;
  buildings: BuildingRef[];
  blocked: boolean;
  locked_until: string | null;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
  version: number;
}

export interface Me extends User {
  role_title: string;
  expires_at?: string | null; // гость по ссылке: до какого времени действует ссылка
}

export interface JournalEntry {
  id: number;
  at: string;
  actor_id: string | null;
  actor_name: string;
  action: string;
  summary: string;
  entity: string;
  refs: string[];
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface Page<T> {
  items: T[];
  next_before_id?: number | null;
}
