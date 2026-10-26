<script>
  import { tick } from 'svelte'
  import Answer from './Answer.svelte'

  let question = $state('')
  let items = $state([]) // {question, pending, res, err}
  let bottom

  const busy = $derived(items.some((i) => i.pending))

  async function ask() {
    const q = question.trim()
    if (!q || busy) return
    question = ''
    items.push({ question: q, pending: true })
    const item = items[items.length - 1]
    tick().then(() => bottom.scrollIntoView({ behavior: 'smooth' }))
    try {
      const r = await fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      })
      const body = await r.json().catch(() => ({}))
      if (r.ok) item.res = body
      else item.err = typeof body.detail === 'string' ? body.detail : 'Permintaan ditolak (pertanyaan kosong atau terlalu panjang).'
    } catch {
      item.err = 'Server tidak terjangkau. Pastikan backend berjalan di port 8000.'
    }
    item.pending = false
    tick().then(() => bottom.scrollIntoView({ behavior: 'smooth' }))
  }
</script>

<main>
  <h1>ClickHouse Chat</h1>

  {#if !items.length}
    <p class="hint">Tanyakan data CRM dalam bahasa Indonesia, misalnya: <em>omset per bulan tahun lalu</em>, <em>jumlah pelanggan per segmen</em>.</p>
  {/if}

  {#each items as item}
    <section>
      <p class="q">{item.question}</p>
      {#if item.pending}
        <p class="meta">Menjawab… (sekitar 10 detik)</p>
      {:else if item.err}
        <p class="error">{item.err}</p>
      {:else}
        <Answer res={item.res} />
      {/if}
    </section>
  {/each}
  <div bind:this={bottom}></div>

  <form onsubmit={(e) => { e.preventDefault(); ask() }}>
    <input bind:value={question} maxlength="500" placeholder="Tulis pertanyaan…" autofocus />
    <button disabled={busy || !question.trim()}>Kirim</button>
  </form>
</main>

<style>
  :global(body) { margin: 0; font-family: system-ui, sans-serif; color: #222; background: #fff; }
  main { max-width: 860px; margin: 0 auto; padding: 1rem 1rem 6rem; }
  h1 { font-size: 1.25rem; }
  section { margin: 1.5rem 0; padding-bottom: 1.5rem; border-bottom: 1px solid #eee; }
  .q { font-weight: 600; background: #eef3ff; padding: 0.5rem 0.75rem; border-radius: 6px; }
  .hint, .meta { color: #777; }
  .error { color: #b3261e; background: #fdecea; padding: 0.5rem 0.75rem; border-radius: 6px; }
  form { position: fixed; bottom: 0; left: 0; right: 0; display: flex; gap: 0.5rem; max-width: 860px; margin: 0 auto; padding: 0.75rem 1rem; background: #fff; border-top: 1px solid #ddd; }
  input { flex: 1; padding: 0.6rem 0.75rem; font-size: 1rem; border: 1px solid #bbb; border-radius: 6px; }
  button { padding: 0.6rem 1.2rem; font-size: 1rem; border: 0; border-radius: 6px; background: #2457d6; color: #fff; cursor: pointer; }
  button:disabled { background: #9aa8c9; cursor: default; }
</style>
