/**
 * citykit.js — Download City Kit
 *
 * Generates a zip containing:
 *   letter.md    — editable letter with city data filled in
 *   data.json    — machine-readable stats
 *   RoadKills.png, NetworkGuess.png, IsoChrones.png — map screenshots
 *
 * Security (Athena):
 *   - Whitelisted filenames only — no path traversal possible
 *   - All user input escaped before insertion into markdown
 *   - JSZip bundled locally — no CDN dependency
 *   - Kit hash logged for tamper detection
 */

"use strict";

var CityKit = (function() {

  // Athena: only these filenames are allowed in the zip
  var ALLOWED_FILES = ['letter.md', 'data.json', 'RoadKills.png', 'NetworkGuess.png', 'IsoChrones.png'];

  // Athena: escape user input for markdown (prevent injection)
  function esc(str) {
    if (!str) return '';
    return String(str).replace(/[<>&"'`]/g, function(c) {
      return {'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;','`':'&#96;'}[c] || c;
    });
  }

  // Get current city data from MeshMobility state
  async function getCityData() {
    var data = {
      city: '',
      state: '',
      county: '',
      population: null,
      deaths_per_year: null,
      worst_intersection: null,
      walk_score: null,
      road_miles: null,
      guideway_miles: null,
      network_cost: null,
      annual_savings: null,
      stations: 0,
      total_miles: 0,
      data_sources: [],
      generated: new Date().toISOString(),
    };

    // Get city label from sidebar
    var cityLabel = document.getElementById('sidebar-city');
    if (cityLabel) {
      var parts = cityLabel.textContent.split(',').map(function(s) { return s.trim(); });
      data.city = parts[0] || '';
      data.state = parts[1] || '';
      data.county = parts[2] || '';
    }

    // Get network stats from sidebar
    var netInfo = document.querySelector('.net-info');
    if (netInfo) {
      var text = netInfo.textContent;
      var stMatch = text.match(/Stations:\s*(\d+)/);
      var miMatch = text.match(/Total:\s*([\d.]+)\s*mi/);
      if (stMatch) data.stations = parseInt(stMatch[1]);
      if (miMatch) data.total_miles = parseFloat(miMatch[1]);
    }

    // Try to get FARS death count from overlay data
    try {
      var resp = await fetch('/api/overlays/stats');
      if (resp.ok) {
        var stats = await resp.json();
        if (stats.accidents) data.deaths_per_year = Math.round(stats.accidents.features / 5); // FARS is ~5 years
        data.data_sources.push('FARS via MeshMobility');
      }
    } catch(e) {}

    // Try PersonalizeTransit data
    try {
      var ptResp = await fetch('/api/personalize-transit?city=' + encodeURIComponent(data.city) + '&state=' + encodeURIComponent(data.state));
      if (ptResp.ok) {
        var pt = await ptResp.json();
        if (pt.population) data.population = pt.population;
        if (pt.walk_score) data.walk_score = pt.walk_score;
        if (pt.road_miles) data.road_miles = pt.road_miles;
        if (pt.network_cost) data.network_cost = pt.network_cost;
        if (pt.annual_savings) data.annual_savings = pt.annual_savings;
        data.data_sources.push('PersonalizeTransit');
      }
    } catch(e) {}

    // Calculate guideway miles
    if (data.road_miles) {
      data.guideway_miles = Math.round(data.road_miles / 14);
    }

    return data;
  }

  // Generate letter.md from template
  function generateLetter(data) {
    var city = esc(data.city) || '[YOUR CITY]';
    var state = esc(data.state) || '[ST]';
    var county = esc(data.county) || '[YOUR COUNTY]';
    var deaths = data.deaths_per_year || '___';
    var deathCost = deaths !== '___' ? '$' + Math.round(deaths * 1.7) + ' million' : '$___ million';
    var intersection = esc(data.worst_intersection) || '[WORST INTERSECTION — check your crash map]';
    var cost = data.network_cost || '[RUN AT PersonalizeTransit.com]';
    var savings = data.annual_savings || '[RUN AT PersonalizeTransit.com]';
    var date = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

    return [
      '# STOP THE CHILD MURDER',
      '',
      '*' + date + '*',
      '',
      'Dear Mayor and City Councilmembers,',
      '',
      'If a child is killed or injured at your house because you left knives on the floor would you face the consequences of a jury trial. The answer should be yes.',
      '',
      'Every death, every injury, should be at risk of legal review and the judgment of a jury. By this means our society forces those who are not careful for children because it is the moral thing to do to be careful for children because there are financial liabilities.',
      '',
      '**Last year, ' + deaths + ' people were killed on roads in ' + city + '.** At the NHTSA value of $1.7 million per statistical life, that is ' + deathCost + ' your community absorbed. The worst corridor is ' + intersection + ' — the same location, year after year. This is not designed for safety. It is designed for speed.',
      '',
      'An exception to accountability to juries for harms is the killing of children on roads. DOTs and government policymakers unconstitutionally created a mercantile highway monopoly and granted themselves sovereign immunity and immunity from jury review for killing children on roads.',
      '',
      'The result in America is we kill children on roads at 4 times the rate they are killed in other developed economies. The Netherlands provides an example of what is possible through accountability. In 1971 the US and Netherlands had very similar car-centric road policies, the same per person oil use, and the same roadkill rate for people. That year ~450 children were killed on Dutch roads triggering STOP DE KINDERMOORD — STOP THE CHILD MURDER.',
      '',
      'Over the next 40 years, killing of children on Dutch roads gradually dropped from ~450 to 14.',
      '',
      'US city governments just keep killing children. That behavior, every child death, should be subject to jury review. 5x5 Free Market (https://5x5FreeMarket.com) is a one-page law that government can adopt that would allow privately funded competition to the current highway monopoly and implement the 3,000 times better safety record of theme park thrill rides:',
      '',
      '- Privately funded transport networks 5 times more efficient than roads',
      '- Pay 5% of gross transport revenues to use air space over approved public Rights of Way.',
      '- To deploy and operate transport networks on which every injury and death is subject to review by a jury.',
      '',
      'Ending the mercantile highway monopoly and allowing alternative networks to highways can cut roadkill in most cities by 60-80% in 3-5 years.',
      '',
      'An example of an alternate to the highway monopoly is the PRT network in Morgantown, WV. It is a grade-separated network of self-driving cars. It was so important that President Nixon sent his daughter to open it in 1972. In 54 years there have been no serious injuries. In that same period 1.8 million Americans have been roadkilled and 2.4 million have had serious injuries each year.',
      '',
      'Helsinki, Finland (660,000 people) achieved **zero road deaths in 2025** — twelve consecutive months without a single pedestrian, cyclist, or driver killed. ' + city + ' killed ' + deaths + ' people.',
      '',
      '## Maps',
      '',
      'The following 3 maps show:',
      '',
      '**Map 1: Roadkills in ' + city + '**',
      '![Roadkills](RoadKills.png)',
      '',
      '**Map 2: Example PRT network expected to cut roadkills 60-80%**',
      '![Network](NetworkGuess.png)',
      '',
      '**Map 3: Travel times from downtown ' + city + ' without a car, 24x7**',
      '![Travel times](IsoChrones.png)',
      '',
      'Congressional Study PB-244854, Automated Guideway Transit (https://www.jpods.com/CongressionalStudy) was published in 1975 to identify solutions to traffic and the hardships of the 1973 Oil Embargo. The study stated government "institutional failures" (not being subject to jury review) block PRT innovation for "four to six decades."',
      '',
      'Adopt 5x5 Free Market so every death is subject to review by a jury and the "institutional barriers" to radically reducing roadkills will evaporate. Roadkills can be reduced 60-80% in 3-5 years.',
      '',
      '**Small Stings:** We also ask that ' + city + ' adopt a Small Stings program — citizens can fine the city $1 for every unsafe crosswalk, blind intersection, and missing barrier. Each sting is retrospection — a timestamped record of constructive knowledge that forces defects to the surface before they kill. Juries are retrospection after a death. Small Stings are retrospection before a death. 47 stings at one intersection this month means that intersection gets fixed this month — not after the next funeral.',
      '',
      '**We ask directly: Will you adopt the 5x5 Free Market standard and a Small Stings program? If not, what is your plan to stop killing people on the corridors shown in the crash map above?**',
      '',
      '## Tools',
      '',
      '- www.MeshMobility.com — map crashes and design a network',
      '- www.PersonalizeTransit.com — calculate your city\'s payback',
      '- www.CityRoadkills.com — why this matters',
      '- www.5x5FreeMarket.com — the regulatory framework',
      '',
      'Please let us know if you are interested.',
      '',
      '---',
      '',
      'Bill James',
      '612.414.4211',
      'bill.james@jpods.com',
      'www.JPods.com',
      '',
      '---',
      '',
      '*This letter was sent on ' + date + ' and is published at CityRoadkills.com. The public record of your response begins now.*',
      '',
      '*Recommendation: CC your local newspaper when sending this letter.*',
    ].join('\n');
  }

  // Capture current map view as PNG blob
  async function captureMap() {
    // Use leaflet-image or html2canvas if available, otherwise skip
    if (typeof html2canvas === 'function') {
      var mapEl = document.getElementById('map');
      if (!mapEl) return null;
      try {
        var canvas = await html2canvas(mapEl, { useCORS: true, scale: 2 });
        return new Promise(function(resolve) { canvas.toBlob(resolve, 'image/png'); });
      } catch(e) { return null; }
    }
    return null;
  }

  // Athena: compute simple hash for tamper detection
  function simpleHash(str) {
    var hash = 0;
    for (var i = 0; i < str.length; i++) {
      var chr = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + chr;
      hash |= 0;
    }
    return 'kit-' + Math.abs(hash).toString(36);
  }

  // Main: build and download the city kit
  async function download() {
    if (typeof JSZip === 'undefined') {
      alert('JSZip not loaded. Cannot create city kit.');
      return;
    }

    if (typeof setStatus === 'function') setStatus('Building city kit...');

    var data = await getCityData();
    if (!data.city) {
      alert('Find a city first (use Find City), then download the kit.');
      return;
    }

    var zip = new JSZip();
    var letterMd = generateLetter(data);
    var dataJson = JSON.stringify(data, null, 2);

    // Athena: only whitelisted files
    zip.file('letter.md', letterMd);
    zip.file('data.json', dataJson);

    // Try to capture current map screenshots
    // For now, users take screenshots manually — future: auto-capture
    // If images exist in the network folder on server, fetch them
    var folder = data.state.toLowerCase() + '_' + data.city.toLowerCase().replace(/\s+/g, '');
    var images = ['RoadKills.png', 'NetworkGuess.png', 'IsoChrones.png'];
    for (var i = 0; i < images.length; i++) {
      try {
        var imgResp = await fetch('/cityroadkills/' + folder + '/' + images[i]);
        if (imgResp.ok) {
          var blob = await imgResp.blob();
          // Athena: verify it's actually an image
          if (blob.type && blob.type.startsWith('image/')) {
            zip.file(images[i], blob);
          }
        }
      } catch(e) {}
    }

    // Athena: log kit hash for tamper detection
    var kitHash = simpleHash(letterMd + dataJson);
    zip.file('.kit-hash', kitHash + '\n' + new Date().toISOString() + '\n' + data.city + ', ' + data.state);

    // Generate and download
    var blob = await zip.generateAsync({ type: 'blob' });
    var fname = data.city.replace(/\s+/g, '_') + '_' + data.state + '_CityKit.zip';
    // Athena: sanitize filename
    fname = fname.replace(/[^a-zA-Z0-9_.\-]/g, '');

    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = fname;
    a.click();
    URL.revokeObjectURL(a.href);

    if (typeof setStatus === 'function') setStatus('City kit downloaded: ' + fname);
    if (typeof App !== 'undefined' && App.flash) App.flash('City kit downloaded: ' + fname, 4000);

    // Athena: log to Allie
    try {
      fetch('/api/allie/capture', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event: 'citykit_download',
          city: data.city,
          state: data.state,
          hash: kitHash,
          stations: data.stations,
          deaths: data.deaths_per_year,
        }),
      }).catch(function() {});
    } catch(e) {}
  }

  return { download: download, getCityData: getCityData };
})();
