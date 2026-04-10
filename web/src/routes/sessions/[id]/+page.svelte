<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Session, Chunk } from '$lib/types';

  let session = $state<Session | null>(null);
  let loadError = $state(false);
  let showTranscript = $state(false);
  let transcriptChunks = $state<Chunk[]>([]);
  let transcriptError = $state(false);
  let vikunjaStatus = $state<'idle' | 'loading' | 'done' | 'error'>('idle');
  let copyStatus = $state<'idle' | 'copied' | 'error'>('idle');

  onMount(async () => {
    const id = $page.params.id;
    if (!id) return;
    try {
      session = await api.sessions.get(id);
    } catch {
      loadError = true;
    }
  });

  async function pushVikunja() {
    if (!session) return;
    vikunjaStatus = 'loading';
    try {
      await api.sessions.pushVikunja(session.id);
      vikunjaStatus = 'done';
    } catch {
      vikunjaStatus = 'error';
    }
  }

  function buildResumptionPrompt(s: Session): string {
    const chunks = (s.chunks ?? []).slice(-3);
    const excerpts = chunks.map((c) => c.content.slice(0, 300)).join('\n\n---\n\n');
    return `We were working on "${s.title ?? s.id}" on ${s.date}. Here's where we left off:\n\n${excerpts}\n\nPick up from here.`;
  }

  async function copyPrompt() {
    if (!session) return;
    try {
      await navigator.clipboard.writeText(buildResumptionPrompt(session));
      copyStatus = 'copied';
      setTimeout(() => (copyStatus = 'idle'), 2000);
    } catch {
      copyStatus = 'error';
      setTimeout(() => (copyStatus = 'idle'), 2000);
    }
  }

  async function loadTranscript() {
    if (!session) return;
    try {
      const result = await api.sessions.transcript(session.id);
      transcriptChunks = result.chunks;
      showTranscript = true;
    } catch {
      transcriptError = true;
    }
  }
</script>

<svelte:head>
  <title>{session ? (session.title ?? session.id) : 'Session'} — Cortex</title>
</svelte:head>

<div class="shell">
  <a href="/" class="back">← Back</a>

  {#if loadError}
    <p class="muted">Failed to load session.</p>
  {:else if !session}
    <p class="muted">Loading…</p>
  {:else}
    <div class="header" class:open={session.status === 'open'}>
      <span class="dot" class:dot-open={session.status === 'open'}></span>
      <div>
        <h1>{session.title ?? session.id}</h1>
        <p class="meta">
          {session.date} · {session.chunk_count} responses · {session.memory_count} memories
          {#if session.status === 'open'}<span class="open-badge">⚠ open</span>{/if}
        </p>
        {#if session.summary}<p class="summary">{session.summary}</p>{/if}
        <div class="tags">
          {#each (session.tags ?? []) as tag}<span class="tag">{tag}</span>{/each}
        </div>
      </div>
    </div>

    {#if session.chunks && session.chunks.length > 0}
      <section>
        <h2>Last responses</h2>
        {#each session.chunks.slice(-3) as chunk}
          <div class="chunk">{chunk.content}</div>
        {/each}
      </section>
    {/if}

    {#if session.memories && session.memories.length > 0}
      <section>
        <h2>Memories extracted</h2>
        {#each session.memories as mem}
          <div class="memory">
            <span class="mem-type">{mem.type}</span>
            <span>{mem.content}</span>
          </div>
        {/each}
      </section>
    {/if}

    <div class="actions">
      <button onclick={pushVikunja} disabled={vikunjaStatus === 'loading' || vikunjaStatus === 'done'}>
        {#if vikunjaStatus === 'done'}✓ Added to Vikunja
        {:else if vikunjaStatus === 'loading'}…
        {:else if vikunjaStatus === 'error'}⚠ Vikunja error
        {:else}📋 Push to Vikunja{/if}
      </button>
      <button onclick={copyPrompt}>
        {copyStatus === 'copied' ? '✓ Copied!' : copyStatus === 'error' ? '⚠ Copy failed' : '▶ Copy resumption prompt'}
      </button>
      <button onclick={loadTranscript}>👁 Full transcript</button>
    </div>

    {#if transcriptError}
      <p class="muted">Failed to load transcript.</p>
    {:else if showTranscript}
      <section>
        <h2>Full transcript</h2>
        {#each transcriptChunks as chunk}
          <div class="chunk">{chunk.content}</div>
        {/each}
      </section>
    {/if}
  {/if}
</div>

<style>
  .shell { max-width: 700px; margin: 0 auto; padding: 16px; font-family: system-ui, sans-serif; }
  .back { color: #6b7280; font-size: 13px; text-decoration: none; display: block; margin-bottom: 16px; }
  .header { display: flex; gap: 12px; align-items: flex-start; padding: 14px;
            background: #111827; border: 1px solid #1f2937; border-radius: 8px; margin-bottom: 16px; }
  .header.open { background: #1a0f0f; border-color: #7f1d1d; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #34d399;
         flex-shrink: 0; margin-top: 6px; }
  .dot.dot-open { background: #f87171; box-shadow: 0 0 6px #f87171; }
  h1 { color: #e2e8f0; font-size: 18px; margin: 0 0 4px; }
  .header.open h1 { color: #fecaca; }
  .meta { color: #6b7280; font-size: 12px; margin: 0 0 6px; }
  .open-badge { color: #f87171; margin-left: 6px; }
  .summary { color: #9ca3af; font-size: 13px; margin: 6px 0; }
  .tags { display: flex; gap: 4px; flex-wrap: wrap; }
  .tag { background: #064e3b; border: 1px solid #065f46; border-radius: 12px;
         padding: 1px 8px; color: #6ee7b7; font-size: 10px; }
  .header.open .tag { background: #431407; border-color: #7c2d12; color: #fdba74; }
  section { margin-bottom: 16px; }
  h2 { color: #6b7280; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
       margin: 0 0 8px; }
  .chunk { background: #1f2937; border-radius: 4px; padding: 10px; color: #d1d5db;
           font-size: 12px; line-height: 1.6; margin-bottom: 6px; white-space: pre-wrap; }
  .memory { display: flex; gap: 8px; align-items: flex-start; margin-bottom: 6px; }
  .mem-type { background: #1e3a5f; border-radius: 3px; padding: 1px 6px;
              color: #93c5fd; font-size: 10px; white-space: nowrap; }
  .memory span:last-child { color: #d1d5db; font-size: 12px; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
  .actions button { background: #1f2937; border: 1px solid #374151; border-radius: 5px;
                    padding: 8px 14px; color: #9ca3af; cursor: pointer; font-size: 12px; }
  .actions button:first-child { background: #1e3a5f; border-color: #2d5a8e; color: #93c5fd; }
  .actions button:nth-child(2) { background: #1c3a1c; border-color: #2d6a2d; color: #86efac; }
  .actions button:disabled { opacity: 0.6; cursor: default; }
  .muted { color: #6b7280; }
  :global(body) { background: #0d1117; margin: 0; }
</style>
