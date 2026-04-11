<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Memory } from '$lib/types';

  const TYPES = ['all', 'fact', 'decision', 'preference', 'procedure', 'entity', 'idea'];

  let memories = $state<Memory[]>([]);
  let typeFilter = $state('all');
  let search = $state('');
  let loading = $state(true);

  async function load() {
    loading = true;
    try {
      memories = await api.memories.list(typeFilter === 'all' ? undefined : typeFilter);
    } finally {
      loading = false;
    }
  }

  onMount(load);

  const filtered = $derived(
    search
      ? memories.filter((m) => m.content.toLowerCase().includes(search.toLowerCase()))
      : memories
  );
</script>

<svelte:head><title>Memories — Cortex</title></svelte:head>

<div class="shell">
  <nav>
    <a href="/" class="logo">🧠 Cortex</a>
    <span class="nav-item active">Memories</span>
    <input bind:value={search} placeholder="search..." />
  </nav>

  <div class="filters">
    {#each TYPES as t}
      <button class:active={typeFilter === t} onclick={() => { typeFilter = t; load(); }}>
        {t}
      </button>
    {/each}
  </div>

  {#if loading}
    <p class="muted">Loading…</p>
  {:else if filtered.length === 0}
    <p class="muted">No memories found.</p>
  {:else}
    <p class="count">{filtered.length} memories</p>
    <ul class="list">
      {#each filtered as mem (mem.id)}
        <li class="card">
          <div class="card-top">
            <span class="type type-{mem.type}">{mem.type}</span>
            {#if mem.source}
              <a href="/sessions/{mem.source}" class="source">from session →</a>
            {/if}
            <span class="date">{mem.created_at.slice(0, 10)}</span>
          </div>
          <div class="content">{mem.content}</div>
          {#if mem.tags && mem.tags.length > 0}
            <div class="tags">
              {#each mem.tags as tag}<span class="tag">{tag}</span>{/each}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .shell { max-width: 700px; margin: 0 auto; padding: 16px; font-family: system-ui, sans-serif; }
  nav { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
  .logo { font-size: 18px; font-weight: 700; text-decoration: none; color: inherit; }
  .nav-item { color: #6b7280; font-size: 13px; }
  .nav-item.active { color: #e2e8f0; }
  input { background: #1f2937; border: 1px solid #374151; border-radius: 4px;
          padding: 4px 10px; color: #e2e8f0; font-size: 12px; width: 140px; margin-left: auto; }
  .filters { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 16px; }
  button { background: #1f2937; border: 1px solid #374151; border-radius: 4px;
           padding: 3px 10px; color: #9ca3af; cursor: pointer; font-size: 11px; }
  button.active { background: #374151; color: #e2e8f0; }
  .count { color: #6b7280; font-size: 11px; margin: 0 0 10px; }
  .list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
  .card { background: #111827; border: 1px solid #1f2937; border-radius: 6px; padding: 10px 14px; }
  .card-top { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .type { border-radius: 3px; padding: 1px 7px; font-size: 10px; white-space: nowrap; }
  .type-fact      { background: #1e3a5f; color: #93c5fd; }
  .type-decision  { background: #3b1f5e; color: #c4b5fd; }
  .type-preference{ background: #1c3a1c; color: #86efac; }
  .type-procedure { background: #3a2a0a; color: #fcd34d; }
  .type-entity    { background: #1f3a3a; color: #5eead4; }
  .type-idea      { background: #3a1f1f; color: #fca5a5; }
  .source { color: #6b7280; font-size: 11px; text-decoration: none; }
  .source:hover { color: #9ca3af; }
  .date { color: #374151; font-size: 10px; margin-left: auto; }
  .content { color: #d1d5db; font-size: 12px; line-height: 1.6; }
  .tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 6px; }
  .tag { background: #064e3b; border: 1px solid #065f46; border-radius: 12px;
         padding: 1px 8px; color: #6ee7b7; font-size: 10px; }
  .muted { color: #6b7280; }
  :global(body) { background: #0d1117; margin: 0; }
</style>
