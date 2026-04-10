<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Session } from '$lib/types';

  let sessions = $state<Session[]>([]);
  let filter = $state<'all' | 'open' | 'closed'>('all');
  let search = $state('');
  let loading = $state(true);

  async function load() {
    loading = true;
    try {
      sessions = await api.sessions.list(filter);
    } finally {
      loading = false;
    }
  }

  onMount(load);

  const filtered = $derived(
    search
      ? sessions.filter(
          (s) =>
            s.title?.toLowerCase().includes(search.toLowerCase()) ||
            (s.tags ?? []).some((t) => t.includes(search.toLowerCase()))
        )
      : sessions
  );

  function openCount(ss: Session[]) {
    return ss.filter((s) => s.status === 'open').length;
  }
</script>

<svelte:head><title>Cortex</title></svelte:head>

<div class="shell">
  <nav>
    <span class="logo">🧠 Cortex</span>
    <div class="filters">
      <button class:active={filter === 'all'} onclick={() => { filter = 'all'; load(); }}>All</button>
      <button class:active={filter === 'open'} onclick={() => { filter = 'open'; load(); }}>
        ⚠ Open ({openCount(sessions)})
      </button>
      <button class:active={filter === 'closed'} onclick={() => { filter = 'closed'; load(); }}>
        ✓ Closed
      </button>
    </div>
    <input bind:value={search} placeholder="search..." />
  </nav>

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if filtered.length === 0}
    <p class="muted">No sessions found.</p>
  {:else}
    <ul class="timeline">
      {#each filtered as session (session.id)}
        <li>
          <a href="/sessions/{session.id}" class="card" class:open={session.status === 'open'}>
            <span class="dot" class:dot-open={session.status === 'open'}></span>
            <div class="card-body">
              <div class="card-title">{session.title ?? session.id}</div>
              <div class="card-meta">
                {session.date} · {session.chunk_count} responses · {session.memory_count} memories
                {#if session.status === 'open'}<span class="open-badge">⚠ open</span>{/if}
              </div>
              <div class="tags">
                {#each (session.tags ?? []) as tag}<span class="tag">{tag}</span>{/each}
              </div>
            </div>
          </a>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .shell { max-width: 700px; margin: 0 auto; padding: 16px; font-family: system-ui, sans-serif; }
  nav { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
  .logo { font-size: 18px; font-weight: 700; margin-right: auto; }
  .filters { display: flex; gap: 4px; }
  button { background: #1f2937; border: 1px solid #374151; border-radius: 4px;
           padding: 4px 10px; color: #9ca3af; cursor: pointer; font-size: 12px; }
  button.active { background: #374151; color: #e2e8f0; }
  input { background: #1f2937; border: 1px solid #374151; border-radius: 4px;
          padding: 4px 10px; color: #e2e8f0; font-size: 12px; width: 140px; }
  .timeline { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 4px; }
  .card { display: flex; gap: 10px; align-items: flex-start; padding: 10px 14px;
          background: #111827; border: 1px solid #1f2937; border-radius: 6px;
          text-decoration: none; color: inherit; }
  .card.open { background: #1a0f0f; border-color: #7f1d1d; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #34d399;
         flex-shrink: 0; margin-top: 4px; }
  .dot.dot-open { background: #f87171; box-shadow: 0 0 6px #f87171; }
  .card-body { flex: 1; }
  .card-title { color: #e2e8f0; font-size: 13px; font-weight: 500; }
  .card.open .card-title { color: #fecaca; }
  .card-meta { color: #6b7280; font-size: 11px; margin-top: 2px; }
  .open-badge { color: #f87171; margin-left: 6px; }
  .tags { display: flex; gap: 4px; margin-top: 5px; flex-wrap: wrap; }
  .tag { background: #064e3b; border: 1px solid #065f46; border-radius: 12px;
         padding: 1px 8px; color: #6ee7b7; font-size: 10px; }
  .card.open .tag { background: #431407; border-color: #7c2d12; color: #fdba74; }
  .muted { color: #6b7280; }
  :global(body) { background: #0d1117; margin: 0; }
</style>
