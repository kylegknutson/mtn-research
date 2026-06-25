/* ──────────────────────────────────────────────────────────────────────────
   Heather GPX grab — run this in YOUR browser console (you're stable; the
   automation browser isn't). One-time pull of her non-ride tracks.

   STEPS:
   1. In a terminal, make sure the sink is running:
        cd <repo> && python3 scripts/strava_sink.py
      (it writes files to gpx/heather/ ; leave it running)
   2. Open her profile in Chrome, logged in:
        https://www.strava.com/athletes/41512178
   3. Open DevTools console (Cmd+Opt+J), paste this whole file, hit Enter.
   4. Watch the log. Files land in gpx/heather/. Re-running is safe (overwrites).
   ────────────────────────────────────────────────────────────────────────── */
(async () => {
  const ATHLETE = 41512178;
  const SINK = 'http://127.0.0.1:8731/save';
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const isRide = t => /cycl|ride|bike|velomobile|handcycle|e-?bike/i.test(t || '');

  // sink check
  try {
    const s = await fetch(SINK + '?fn=__ping.gpx', { method:'POST', body:'ping' });
    if (!s.ok) throw new Error('status ' + s.status);
  } catch (e) {
    console.error('❌ SINK NOT REACHABLE — is `python3 scripts/strava_sink.py` running?', e);
    return;
  }
  console.log('✓ sink reachable. Enumerating her activities by month…');

  // 1) enumerate every month 2020-01 .. now
  const noise = new Set(['19049098473','19035865689','19022236704','19023324303',
                         '18924408291','18924408245','18831472480','18831472720']);
  const ids = new Set();
  const now = new Date(), Y = now.getFullYear(), M = now.getMonth()+1;
  for (let y=2020; y<=Y; y++) for (let mo=1; mo<=12; mo++) {
    if (y===Y && mo>M) break;
    const ym = `${y}${String(mo).padStart(2,'0')}`;
    try {
      const h = await (await fetch(`/athletes/${ATHLETE}?interval=${ym}&interval_type=month&chart_type=miles`,
                                   {headers:{'Accept':'text/html'}})).text();
      for (const m of h.matchAll(/\/activities\/(\d+)/g)) if (!noise.has(m[1])) ids.add(m[1]);
    } catch(e) {}
    await sleep(120);
  }
  const list = [...ids];
  console.log(`✓ ${list.length} candidate activities. Downloading GPX (skipping rides)…`);

  // 2) download each: validate it's a real GPX, skip rides, POST to sink
  let saved=0, rides=0, fail=0, notgpx=0;
  for (let i=0; i<list.length; i++) {
    const id = list[i];
    try {
      const r = await fetch(`/activities/${id}/export_gpx`);
      if (!r.ok) { fail++; continue; }
      const g = await r.text();
      if (!g.startsWith('<?xml')) { notgpx++; continue; }   // private/others' → skip
      const typeM = g.match(/<type>([^<]+)<\/type>/i);
      const type = typeM ? typeM[1].trim() : 'unknown';
      const nameM = g.match(/<name>([^<]+)<\/name>/i);
      const slug = (nameM ? nameM[1] : '').toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,40);
      if (isRide(type)) { rides++; continue; }
      const fn = `${type.replace(/[^a-z0-9]+/gi,'_')}__${slug||'activity'}__${id}.gpx`;
      const sv = await fetch(`${SINK}?fn=${encodeURIComponent(fn)}`, {method:'POST', body:g});
      if (sv.ok) saved++; else fail++;
    } catch(e) { fail++; }
    if ((i+1) % 10 === 0 || i === list.length-1)
      console.log(`  …${i+1}/${list.length}  saved:${saved} rides-skipped:${rides} not-viewable:${notgpx} fail:${fail}`);
    await sleep(150);
  }
  console.log(`✅ DONE. saved ${saved} GPX to gpx/heather/  (skipped ${rides} rides, ${notgpx} not-viewable, ${fail} errors)`);
})();
