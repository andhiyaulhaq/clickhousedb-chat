<script>
  import Chart from './Chart.svelte'

  let { res } = $props()

  const fmt = (v) =>
    v === null ? '—' : typeof v === 'number' ? v.toLocaleString('id-ID', { maximumFractionDigits: 2 }) : Array.isArray(v) ? JSON.stringify(v) : v
</script>

{#if res.interpretation}<p class="note">{res.interpretation}</p>{/if}

{#if res.error}<p class="error">{res.error}</p>{/if}

{#if res.chart?.type === 'stat'}
  <div class="stat">{fmt(res.rows[0][0])}<small>{res.columns[0]}</small></div>
{:else if res.chart}
  <Chart chart={res.chart} columns={res.columns} rows={res.rows} />
{/if}

{#if res.summary}<p>{res.summary}</p>{/if}

{#if res.rows.length}
  <div class="table">
    <table>
      <thead><tr>{#each res.columns as c}<th>{c}</th>{/each}</tr></thead>
      <tbody>
        {#each res.rows as row}
          <tr>{#each row as v}<td class:num={typeof v === 'number'}>{fmt(v)}</td>{/each}</tr>
        {/each}
      </tbody>
    </table>
  </div>
  <p class="meta">{res.rows.length} baris{res.rows.length >= 1000 ? ' (dibatasi 1000)' : ''}</p>
{:else if !res.error}
  <p class="meta">Tidak ada data yang cocok.</p>
{/if}

<!-- A wrong-but-plausible answer is the main product risk (docs/guide.md section 3): the SQL is always one click away -->
{#if res.sql}
  <details>
    <summary>SQL{res.attempts ? ` (diperbaiki ${res.attempts}×)` : ''}</summary>
    <pre>{res.sql}</pre>
  </details>
{/if}

<style>
  .note { color: #555; font-style: italic; }
  .error { color: #b3261e; background: #fdecea; padding: 0.5rem 0.75rem; border-radius: 6px; }
  .stat { font-size: 2.5rem; font-weight: 600; }
  .stat small { display: block; font-size: 0.9rem; font-weight: 400; color: #666; }
  .table { max-height: 360px; overflow: auto; border: 1px solid #ddd; border-radius: 6px; margin-top: 0.75rem; }
  table { border-collapse: collapse; width: 100%; font-size: 0.875rem; }
  th, td { padding: 0.35rem 0.6rem; text-align: left; white-space: nowrap; }
  th { position: sticky; top: 0; background: #f5f5f5; }
  tr:nth-child(even) td { background: #fafafa; }
  td.num { text-align: right; }
  .meta { color: #777; font-size: 0.8rem; margin: 0.4rem 0 0; }
  details { margin-top: 0.5rem; font-size: 0.85rem; }
  summary { cursor: pointer; color: #555; }
  pre { background: #f5f5f5; padding: 0.6rem; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; }
</style>
