<script>
  import Chart from 'chart.js/auto'

  // chart is the backend's {type: line|bar, x, y} (docs/guide.md rule 6); x and y name result columns
  // labels: the x axis names from the backend ("Jan 2025"); without them the raw column values are shown
  let { chart, columns, rows, labels } = $props()
  let canvas

  $effect(() => {
    const col = (name) => columns.indexOf(name)
    const c = new Chart(canvas, {
      type: chart.type,
      data: {
        labels: labels ?? rows.map((r) => r[col(chart.x)]),
        datasets: chart.y.map((name) => ({ label: name, data: rows.map((r) => r[col(name)]) })),
      },
      options: { maintainAspectRatio: false, plugins: { legend: { display: chart.y.length > 1 } } },
    })
    return () => c.destroy()
  })
</script>

<div class="chart"><canvas bind:this={canvas}></canvas></div>

<style>
  .chart { height: 280px; }
</style>
