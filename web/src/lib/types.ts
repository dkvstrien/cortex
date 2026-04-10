export interface Memory {
  id: number;
  content: string;
  type: string;
  tags: string[];
  source: string | null;
  created_at: string;
}

export interface Chunk {
  id: number;
  content: string;
  created_at: string;
}

export interface Session {
  id: string;
  date: string;
  title: string | null;
  summary: string | null;
  status: 'open' | 'closed' | 'unprocessed';
  tags: string[];
  chunk_count: number;
  memory_count: number;
  classified_at: string | null;
  // only present in detail response
  chunks?: Chunk[];
  memories?: Memory[];
}
